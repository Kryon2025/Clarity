"""账户云同步（v0.20）：把本机设置 / 空间 / 专注统计同步到深清商店服务器。

设计要点：

- 纯 urllib 实现（不新增依赖）；所有网络异常统一转成可读中文 CloudSyncError；
- 服务端接口（需先登录拿 token）：
    POST /api/auth/login {email,password}      → {token,user}
    GET  /api/sync                             → {revision, updated_at, payload, device_name}
    PUT  /api/sync {payload, revision, device} → 200 {revision, updated_at}
                                                 409 {detail, revision}
- payload 只带白名单设置 + 空间 + 专注统计，**不上传密码 / API Key / 本地文件路径 / 令牌**；
- 拉取写回前先把当前数据备份到 <数据目录>/backups/cloud-pre-pull-<时间戳>.json；
- 写回方式与「导入备份」一致：直接改数据目录里的 settings.json / spaces.json / stats.json，
  由 AppBridge 负责异步调度与写回后刷新内存；
- 本模块所有函数都是同步阻塞调用，异步由 AppBridge 的 QThreadPool 负责。
"""

from __future__ import annotations

import json
import logging
import os
import platform
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from ..consts import APP_VERSION
from ..paths import app_data_dir

logger = logging.getLogger("shenqing.cloud_sync")

#: 网络超时（秒）
TIMEOUT_SECONDS = 15.0
#: 请求 UA（服务端日志/风控能看出是桌面端）
USER_AGENT = f"ShenQing/{APP_VERSION} (Windows)"
#: 登录接口
LOGIN_PATH = "/api/auth/login"
#: 同步接口
SYNC_PATH = "/api/sync"
#: 设备名长度上限
DEVICE_NAME_LIMIT = 64
#: 备份目录（与 services/backup.py 一致：数据目录/backups）
BACKUP_DIR_NAME = "backups"
#: 拉取前备份文件名前缀
BACKUP_PREFIX = "cloud-pre-pull"
#: 服务端错误文案长度上限（避免把整页 HTML 塞进界面）
ERROR_TEXT_LIMIT = 200
#: 单次同步最多携带的专注记录数（只取最近的，防止 payload 无限膨胀）
MAX_SYNC_SESSIONS = 5000
#: 与 core/spaces.SCHEMA_VERSION 保持一致（避免为了一个常量在纯网络模块里 import PySide6）
SPACES_SCHEMA_VERSION = 6

#: 同步白名单：只同步这些设置键（刻意排除密码 / token / API Key / 本机路径 / 端口等）
SYNC_SETTINGS_KEYS: tuple[str, ...] = (
    "theme",
    "theme_mode",
    "custom_themes",
    "default_mode",
    "language",
    "autostart",
    "hardening",
    "keep_alive",
    "auto_update",
    "ai_enabled",
    "ai_provider",
    "ai_api_base",
    "ai_model",
    "ai_reasoning_enabled",
    "ai_web_search_enabled",
    "ai_reasoning_effort",
    "ui_font_family",
    "ui_font_scale",
    "nav_mode",
    "app_usage_heatmap_days",
    "volume_panel",
    "pomodoro_work_minutes",
    "pomodoro_break_minutes",
    "pomodoro_long_break_minutes",
    "pomodoro_rounds_before_long",
    "countdown_date",
    "default_minutes",
    "lock_level",
    "guard_interval_ms",
    "pause_limit",
    "cooldown_minutes",
    "site_block_enabled",
    "blocked_sites",
    "overlay_widget_order",
    "onboarding_done",
)

#: 明确不同步的敏感键（测试与文档都用它兜底）
SECRET_SETTINGS_KEYS: tuple[str, ...] = (
    "pin",
    "pin_enabled",
    "ai_api_key",
    "cloud_sync_token",
    "web_admin_token",
    "card_background",
)


class CloudSyncError(Exception):
    """账户同步错误：message 直接可以展示给用户。"""


# --------------------------------------------------------------------------- #
# 地址 / 设备名
# --------------------------------------------------------------------------- #
def normalize_url(url: object) -> str:
    """规范化服务器地址：补 https://、去掉末尾 /；空串返回空串，非法地址抛错。"""
    text = str(url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    try:
        parts = urllib.parse.urlsplit(text)
    except ValueError as exc:  # pragma: no cover - 极少数畸形地址
        raise CloudSyncError(f"服务器地址不正确：{exc}") from exc
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise CloudSyncError("服务器地址必须以 http:// 或 https:// 开头")
    if not parts.netloc:
        raise CloudSyncError("服务器地址缺少域名，例如 https://store.example.com")
    path = parts.path.rstrip("/")
    return urllib.parse.urlunsplit((scheme, parts.netloc, path, "", ""))


def api_url(url: object, path: str) -> str:
    """拼出接口地址：normalize_url(url) + path。"""
    base = normalize_url(url)
    if not base:
        raise CloudSyncError("请先填写商店服务器地址")
    return base + "/" + str(path or "").lstrip("/")


def default_device_name() -> str:
    """默认设备名：取电脑名（拿不到就退化成 Windows）。"""
    name = ""
    for getter in (platform.node, socket.gethostname):
        try:
            name = str(getter() or "").strip()
        except Exception:  # noqa: BLE001 - 极端环境下拿不到主机名
            name = ""
        if name:
            break
    return name[:DEVICE_NAME_LIMIT] or "Windows"


# --------------------------------------------------------------------------- #
# 底层请求
# --------------------------------------------------------------------------- #
def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _parse_json(raw: object) -> dict:
    """把响应体解析成 dict；解析不了就当空 dict（错误文案走 HTTP 状态兜底）。"""
    if isinstance(raw, dict):
        return raw
    text = ""
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8", errors="replace")
        except (UnicodeDecodeError, AttributeError):
            text = ""
    elif isinstance(raw, str):
        text = raw
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _detail(data: dict, fallback: str) -> str:
    """取服务端错误文案（detail / message / error），限长后返回。"""
    for key in ("detail", "message", "error"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:ERROR_TEXT_LIMIT]
        if isinstance(value, list) and value:
            return str(value[0])[:ERROR_TEXT_LIMIT]
    return fallback


def _timeout_seconds(timeout: float | None) -> float:
    try:
        value = float(TIMEOUT_SECONDS if timeout is None else timeout)
    except (TypeError, ValueError):
        value = TIMEOUT_SECONDS
    return max(0.05, value)


def _call(
    method: str,
    url: str,
    *,
    token: str = "",
    body: object | None = None,
    timeout: float | None = None,
) -> tuple[int, dict]:
    """发一个 JSON 请求，返回 (状态码, 解析后的响应 dict)；网络错误抛 CloudSyncError。"""
    seconds = _timeout_seconds(timeout)
    data: bytes | None = None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if body is not None:
        try:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise CloudSyncError(f"同步数据无法序列化：{exc}") from exc
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=seconds) as response:  # noqa: S310
            status = _as_int(getattr(response, "status", 200), 200) or 200
            return status, _parse_json(response.read())
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
        except (OSError, ValueError):
            raw = b""
        return _as_int(exc.code, 0), _parse_json(raw)
    except (TimeoutError, socket.timeout) as exc:
        raise CloudSyncError(
            f"连接服务器超时（{seconds:g} 秒），请检查网络或服务器地址"
        ) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise CloudSyncError(
                f"连接服务器超时（{seconds:g} 秒），请检查网络或服务器地址"
            ) from exc
        text = str(reason) or str(exc)
        raise CloudSyncError(f"无法连接服务器：{text[:ERROR_TEXT_LIMIT]}") from exc
    except (OSError, ValueError) as exc:
        raise CloudSyncError(f"网络请求失败：{exc}") from exc


# --------------------------------------------------------------------------- #
# 三个主要接口
# --------------------------------------------------------------------------- #
def login(
    url: object,
    email: object,
    password: object,
    *,
    timeout: float | None = None,
) -> str:
    """邮箱 + 密码登录商店账号，返回 token。

    :raises CloudSyncError: 地址 / 账号为空、密码错误、服务端报错、网络异常
    """
    base = normalize_url(url)
    if not base:
        raise CloudSyncError("请先填写商店服务器地址")
    email_text = str(email or "").strip()
    if not email_text or "@" not in email_text:
        raise CloudSyncError("请填写正确的邮箱")
    password_text = str(password or "")
    if not password_text:
        raise CloudSyncError("请填写密码")
    status, data = _call(
        "POST",
        api_url(base, LOGIN_PATH),
        body={"email": email_text, "password": password_text},
        timeout=timeout,
    )
    if status in (401, 403):
        raise CloudSyncError("邮箱或密码不正确")
    if status == 429:
        raise CloudSyncError("登录尝试太频繁，请稍后再试")
    if status >= 400:
        raise CloudSyncError(_detail(data, f"登录失败（HTTP {status}）"))
    token = str(data.get("token") or "").strip()
    if not token:
        raise CloudSyncError("登录响应里没有 token，请检查服务器版本")
    return token


def pull(url: object, token: object, *, timeout: float | None = None) -> dict:
    """拉取云端快照，返回 {revision, updated_at, payload, device_name}。

    云端还没有数据时（payload 为空 / revision 为 0）也会正常返回，由调用方判断。
    """
    base = normalize_url(url)
    if not base:
        raise CloudSyncError("请先填写商店服务器地址")
    token_text = str(token or "").strip()
    if not token_text:
        raise CloudSyncError("请先登录商店账号")
    status, data = _call(
        "GET", api_url(base, SYNC_PATH), token=token_text, timeout=timeout
    )
    if status in (401, 403):
        raise CloudSyncError("登录已失效，请重新登录")
    if status == 404:
        raise CloudSyncError("服务器没有账户同步接口（/api/sync），请升级商店服务端")
    if status >= 400:
        raise CloudSyncError(_detail(data, f"下载失败（HTTP {status}）"))
    payload = data.get("payload")
    return {
        "revision": max(0, _as_int(data.get("revision"), 0)),
        "updated_at": str(data.get("updated_at") or ""),
        "payload": payload if isinstance(payload, dict) else {},
        "device_name": str(data.get("device_name") or ""),
    }


def push(
    url: object,
    token: object,
    payload: object,
    revision: object,
    device: object,
    *,
    timeout: float | None = None,
) -> tuple[bool, int]:
    """上传本机快照。

    :return: (True, 新 revision) 成功；(False, 远端 revision) 版本冲突（HTTP 409）
    :raises CloudSyncError: 登录失效 / 服务端报错 / 网络异常
    """
    base = normalize_url(url)
    if not base:
        raise CloudSyncError("请先填写商店服务器地址")
    token_text = str(token or "").strip()
    if not token_text:
        raise CloudSyncError("请先登录商店账号")
    base_revision = max(0, _as_int(revision, 0))
    body = {
        "payload": payload if isinstance(payload, dict) else {},
        "revision": base_revision,
        "device": str(device or "").strip()[:DEVICE_NAME_LIMIT] or default_device_name(),
    }
    status, data = _call(
        "PUT",
        api_url(base, SYNC_PATH),
        token=token_text,
        body=body,
        timeout=timeout,
    )
    if status == 409:
        if "revision" not in data:
            raise CloudSyncError("服务端报告版本冲突，但没有返回 revision")
        return False, max(0, _as_int(data.get("revision"), 0))
    if status in (401, 403):
        raise CloudSyncError("登录已失效，请重新登录")
    if status >= 400:
        raise CloudSyncError(_detail(data, f"上传失败（HTTP {status}）"))
    return True, max(0, _as_int(data.get("revision"), base_revision + 1))


# --------------------------------------------------------------------------- #
# 快照导出 / 拉取前备份 / 写回
# --------------------------------------------------------------------------- #
def build_payload(settings: Any, spaces: Any, stats: Any) -> dict:
    """导出同步快照：{version, exported_at, settings:{白名单}, spaces:{...}, stats:{...}}。

    settings / spaces / stats 分别对应 Settings / SpaceManager / StatsStore。
    """
    settings_part: dict[str, Any] = {}
    for key in SYNC_SETTINGS_KEYS:
        try:
            value = settings.get(key) if settings is not None else None
        except Exception:  # noqa: BLE001 - 设置对象异常不影响其余字段
            value = None
        if value is not None:
            settings_part[key] = value
    items: list[dict] = []
    try:
        raw_spaces = spaces.all() if spaces is not None else []
    except Exception:  # noqa: BLE001
        raw_spaces = []
    for item in raw_spaces or []:
        if isinstance(item, dict):
            items.append(dict(item))
    try:
        raw_sessions = stats.sessions if stats is not None else []
    except Exception:  # noqa: BLE001
        raw_sessions = []
    sessions = [dict(item) for item in (raw_sessions or []) if isinstance(item, dict)]
    sessions = sessions[-MAX_SYNC_SESSIONS:]
    total_minutes = 0.0
    for item in sessions:
        try:
            total_minutes += float(item.get("minutes") or 0)
        except (TypeError, ValueError):
            continue
    return {
        "version": APP_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "settings": settings_part,
        "spaces": {"schemaVersion": SPACES_SCHEMA_VERSION, "items": items},
        "stats": {
            "total_sessions": len(sessions),
            "total_minutes": round(total_minutes, 1),
            "sessions": sessions,
        },
    }


def _data_root(data_dir: object = None) -> Path:
    if data_dir is None:
        return app_data_dir()
    root = Path(str(data_dir))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _read_json_file(path: Path) -> dict | None:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return None


def _write_json_file(path: Path, data: dict) -> None:
    """原子写：先写 .tmp 再 os.replace。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def backup_current(data_dir: object = None, now: datetime | None = None) -> Path:
    """拉取前备份当前数据到 <数据目录>/backups/cloud-pre-pull-<时间戳>.json。

    备份内容是给用户兜底用的纯 JSON（settings / spaces / stats 三个文件原样），
    :return: 备份文件路径；失败抛 CloudSyncError。
    """
    root = _data_root(data_dir)
    target_dir = root / BACKUP_DIR_NAME
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"{BACKUP_PREFIX}-{stamp}.json"
    snapshot = {
        "version": APP_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "settings": _read_json_file(root / "settings.json"),
        "spaces": _read_json_file(root / "spaces.json"),
        "stats": _read_json_file(root / "stats.json"),
    }
    try:
        _write_json_file(target, snapshot)
    except OSError as exc:
        raise CloudSyncError(f"备份当前数据失败：{exc}") from exc
    logger.info("拉取前备份完成：%s", target)
    return target


def apply_payload(payload: object, data_dir: object = None) -> dict:
    """把云端快照写回数据目录（与「导入备份」同一批文件）。

    - settings：只合并白名单里出现的键，其他本地设置保持不变；
    - spaces：整体覆盖 spaces.json；
    - stats：整体覆盖 stats.json。
    :return: {"settings": n, "spaces": n, "stats": n} 各项写入条数
    """
    data = payload if isinstance(payload, dict) else {}
    root = _data_root(data_dir)
    counts = {"settings": 0, "spaces": 0, "stats": 0}
    # ---- settings ----
    incoming_settings = data.get("settings")
    if isinstance(incoming_settings, dict) and incoming_settings:
        current = _read_json_file(root / "settings.json") or {}
        changed = False
        for key in SYNC_SETTINGS_KEYS:
            if key in incoming_settings:
                current[key] = incoming_settings[key]
                counts["settings"] += 1
                changed = True
        if changed:
            try:
                _write_json_file(root / "settings.json", current)
            except OSError as exc:
                raise CloudSyncError(f"写回设置失败：{exc}") from exc
    # ---- spaces ----
    spaces_block = data.get("spaces")
    raw_items = None
    if isinstance(spaces_block, dict):
        raw_items = spaces_block.get("items")
    elif isinstance(spaces_block, list):
        raw_items = spaces_block
    if isinstance(raw_items, list):
        items = [dict(item) for item in raw_items if isinstance(item, dict)]
        if items:
            version = SPACES_SCHEMA_VERSION
            if isinstance(spaces_block, dict):
                version = max(1, _as_int(spaces_block.get("schemaVersion"), version))
            try:
                _write_json_file(
                    root / "spaces.json",
                    {
                        "schemaVersion": version,
                        "spaces": items,
                        "updated": int(datetime.now().timestamp()),
                    },
                )
            except OSError as exc:
                raise CloudSyncError(f"写回空间失败：{exc}") from exc
            counts["spaces"] = len(items)
    # ---- stats ----
    stats_block = data.get("stats")
    raw_sessions = None
    if isinstance(stats_block, dict):
        raw_sessions = stats_block.get("sessions")
    elif isinstance(stats_block, list):
        raw_sessions = stats_block
    if isinstance(raw_sessions, list):
        sessions = [dict(item) for item in raw_sessions if isinstance(item, dict)]
        try:
            _write_json_file(root / "stats.json", {"sessions": sessions})
        except OSError as exc:
            raise CloudSyncError(f"写回统计失败：{exc}") from exc
        counts["stats"] = len(sessions)
    logger.info(
        "云端快照已写回：设置 %s 项 / 空间 %s 个 / 记录 %s 条",
        counts["settings"],
        counts["spaces"],
        counts["stats"],
    )
    return counts
