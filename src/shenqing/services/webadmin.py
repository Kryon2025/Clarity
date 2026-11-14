"""网页管理（v0.19）：在浏览器里管理深清。

设计要点（参考 Class Widgets 2 的网页端管理方式）：

- 线程化 HTTP 服务（ThreadingHTTPServer），只绑定 127.0.0.1，默认端口 8765
  （设置项 web_admin_port；被占用时自动 +1，最多尝试 20 个端口）；
- 所有 /api/* 都要 token（?token= 或 X-ShenQing-Token 头），否则 401；
  / 页面无 token 时给出一个粘贴框，把桌面端复制的完整地址粘进去即可；
- 页面是单文件 HTML（内嵌 CSS/JS、中文界面、海洋深色卡片风、浅色/移动端自适应），
  每 2 秒轮询 /api/state，任何操作后立即刷新；
- 与主程序解耦：所有读写都走 WebAdminHost。默认实现只依赖 Settings /
  SpaceManager / StatsStore，单元测试可以完全脱离 GUI；主程序在这里注入
  AppBridge 的动作（开始/停止专注、即时生效设置、商店安装等）。
"""

from __future__ import annotations

import json
import logging
import secrets
import shutil
import socket
import tempfile
import threading
import time
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from ..consts import (
    APP_NAME,
    APP_VERSION,
    CUSTOM_THEME_PREFIX,
    DEFAULT_THEME_SCHEME,
    DEFAULT_THEME_STYLE,
    MAX_MINUTES,
    MIN_MINUTES,
    MODE_LABELS,
    THEME_SCHEMES,
    THEMES,
)

logger = logging.getLogger("shenqing.webadmin")

#: 只监听本机回环地址（管理页不对外网开放）
BIND_HOST = "127.0.0.1"
#: 默认端口
DEFAULT_PORT = 8765
#: 端口被占用时最多尝试的端口数
MAX_PORT_ATTEMPTS = 20
#: token 随机字节数（secrets.token_urlsafe）
TOKEN_BYTES = 24
#: 鉴权头（也支持 ?token= 查询参数）
TOKEN_HEADER = "X-ShenQing-Token"
#: 请求体上限（字节）
MAX_BODY_BYTES = 64 * 1024
#: 商店快照后台刷新间隔（秒）——轮询不能等 6 秒的网络超时
STORE_REFRESH_SECONDS = 60.0
#: 热力图天数（简版）
HEATMAP_DAYS = 14

#: 空间档位（与 core.spaces.MODES 一致；这里不 import 以保持本模块不依赖 Qt）
MODES = ("light", "medium", "heavy")

#: POST /api/settings 白名单（不允许改 token / 端口）
SETTINGS_KEYS = (
    "theme_style",
    "theme_scheme",
    "language",
    "ui_font_scale",
    "ui_font_family",
    "nav_mode",
    "default_minutes",
    "auto_update",
    "site_block_enabled",
    "web_admin_enabled",
)

#: 导航模式（与 AppBridge.NAV_MODES 一致）
NAV_MODES = ("auto", "expanded", "icons", "custom")

#: 每个设置项在读取状态时的兜底值
_SETTING_FALLBACK: dict[str, Any] = {
    "language": "auto",
    "ui_font_scale": 1.0,
    "ui_font_family": "",
    "nav_mode": "expanded",
    "default_minutes": 25,
    "auto_update": True,
    "site_block_enabled": True,
    "web_admin_enabled": False,
}

#: 字号缩放范围 / 步进
FONT_SCALE_MIN = 0.8
FONT_SCALE_MAX = 1.4
FONT_SCALE_STEP = 0.05

__all__ = [
    "BIND_HOST",
    "DEFAULT_PORT",
    "MAX_PORT_ATTEMPTS",
    "MODES",
    "SETTINGS_KEYS",
    "TOKEN_HEADER",
    "WebAdminError",
    "WebAdminHost",
    "WebAdminNotFound",
    "WebAdminService",
    "normalize_setting",
    "legacy_theme_pair",
    "valid_theme_scheme",
    "valid_theme_style",
]


class WebAdminError(RuntimeError):
    """请求参数不合法（HTTP 400）。"""


class WebAdminNotFound(WebAdminError):
    """未知接口（HTTP 404）。"""


# ================= 参数归一化 =================


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value if value is not None else "").strip().lower()
    if text in ("1", "true", "yes", "on", "开"):
        return True
    if text in ("0", "false", "no", "off", "关", ""):
        return False
    raise WebAdminError("开关值不合法")


def _as_int(value: Any, *, minimum: int, maximum: int, name: str) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError) as exc:
        raise WebAdminError(f"{name}必须是数字") from exc
    return max(int(minimum), min(int(maximum), number))


def _as_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _clamp_scale(value: Any) -> float:
    try:
        scale = float(value)
    except (TypeError, ValueError) as exc:
        raise WebAdminError("字号必须是数字") from exc
    scale = max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, scale))
    steps = round((scale - FONT_SCALE_MIN) / FONT_SCALE_STEP)
    return round(FONT_SCALE_MIN + steps * FONT_SCALE_STEP, 2)


def _language_codes() -> set[str]:
    try:
        from ..i18n import supported_codes

        return set(supported_codes()) | {"auto"}
    except Exception:  # noqa: BLE001 - i18n 缺失时的兜底
        return {"auto", "zh_CN", "en_US"}


def valid_theme_style(settings: Any, style: Any) -> bool:
    """外观样式是否可用：内置样式（solid/glass/ocean）或已安装的 custom:<id>。"""
    value = str(style or "").strip()
    if not value:
        return False
    if value.startswith(CUSTOM_THEME_PREFIX):
        theme_id = value[len(CUSTOM_THEME_PREFIX) :]
        raw = settings.get("custom_themes", {})
        return isinstance(raw, dict) and bool(theme_id) and theme_id in raw
    return value in {item["value"] for item in THEMES}


#: 兼容旧名字（旧代码/测试可能还在导入）
valid_theme_mode = valid_theme_style


def valid_theme_scheme(scheme: Any) -> bool:
    """配色方案是否可用：auto / light / dark。"""
    return str(scheme or "").strip() in {item["value"] for item in THEME_SCHEMES}


def legacy_theme_pair(mode: Any) -> tuple[str, str] | None:
    """旧主题值 → (样式, 配色)；与桌面端 setThemeMode 的兼容映射一致。"""
    value = str(mode or "").strip()
    if value == "light":
        return (DEFAULT_THEME_STYLE, "light")
    if value == "solid":
        return (DEFAULT_THEME_STYLE, "dark")
    if value in ("glass", "ocean"):
        return (value, "dark")
    if value.startswith(CUSTOM_THEME_PREFIX):
        return (value, "auto")
    return None


def normalize_setting(settings: Any, key: str, value: Any) -> Any:
    """把网页传来的设置值归一化；不合法抛 WebAdminError。"""
    name = str(key or "").strip()
    if name not in SETTINGS_KEYS:
        raise WebAdminError(f"不支持的设置项：{name}")
    if name == "theme_style":
        style = str(value or "").strip()
        if not valid_theme_style(settings, style):
            raise WebAdminError("未知主题样式")
        return style
    if name == "theme_scheme":
        scheme = str(value or "").strip()
        if not valid_theme_scheme(scheme):
            raise WebAdminError("未知配色方案")
        return scheme
    if name == "language":
        code = str(value or "").strip()
        if code not in _language_codes():
            raise WebAdminError("不支持的语言")
        return code
    if name == "ui_font_scale":
        return _clamp_scale(value)
    if name == "ui_font_family":
        return str(value or "").strip()[:80]
    if name == "nav_mode":
        mode = str(value or "").strip()
        if mode not in NAV_MODES:
            raise WebAdminError("未知导航模式")
        return mode
    if name == "default_minutes":
        return _as_int(value, minimum=MIN_MINUTES, maximum=MAX_MINUTES, name="默认时长")
    if name == "auto_update":
        return _as_bool(value)
    if name == "site_block_enabled":
        return _as_bool(value)
    if name == "web_admin_enabled":
        return _as_bool(value)
    raise WebAdminError(f"不支持的设置项：{name}")


# ================= 主程序能力（可注入） =================


class WebAdminHost:
    """网页管理用到的主程序能力。

    默认实现只操作 Settings / SpaceManager / StatsStore（够单测用）；
    主程序创建时传入回调，把「开始专注」等动作接到 AppBridge 上。
    """

    def __init__(
        self,
        settings: Any,
        spaces: Any,
        stats: Any = None,
        *,
        store_service: Any = None,
        plugins_provider: Callable[[], list[dict]] | None = None,
        store_items_provider: Callable[[], list[dict]] | None = None,
        session_snapshot: Callable[[], dict] | None = None,
        session_start: Callable[[str, Any, str], tuple[bool, str]] | None = None,
        session_stop: Callable[[], tuple[bool, str]] | None = None,
        install_store_item: Callable[[str], tuple[bool, str]] | None = None,
        on_settings_changed: Callable[[str, Any], None] | None = None,
        on_spaces_changed: Callable[[], None] | None = None,
        version: str = APP_VERSION,
    ) -> None:
        self.settings = settings
        self.spaces = spaces
        self.stats = stats
        self.store_service = store_service
        self.version = str(version or APP_VERSION)
        self._plugins_provider = plugins_provider
        self._store_items_provider = store_items_provider
        self._session_snapshot = session_snapshot
        self._session_start = session_start
        self._session_stop = session_stop
        self._install_store_item = install_store_item
        self._on_settings_changed = on_settings_changed
        self._on_spaces_changed = on_spaces_changed

    # ---------- 读取 ----------
    def theme_style(self) -> str:
        """外观样式：solid / glass / ocean / custom:<id>。"""
        value = str(self.settings.get("theme_style", DEFAULT_THEME_STYLE) or "")
        return value if valid_theme_style(self.settings, value) else DEFAULT_THEME_STYLE

    def theme_scheme(self) -> str:
        """配色方案：auto / light / dark。"""
        value = str(self.settings.get("theme_scheme", DEFAULT_THEME_SCHEME) or "")
        return value if valid_theme_scheme(value) else DEFAULT_THEME_SCHEME

    def theme_mode(self) -> str:
        """兼容旧字段：等于样式（custom:<id> 原样）。"""
        return self.theme_style()

    def theme_schemes(self) -> list[dict]:
        """配色方案列表：[{value,label}]。"""
        return [
            {"value": str(item["value"]), "label": str(item["label"])}
            for item in THEME_SCHEMES
        ]

    def themes(self) -> list[dict]:
        result = [
            {
                "value": str(item["value"]),
                "label": str(item["label"]),
                "desc": str(item["desc"]),
                "experimental": bool(item.get("experimental")),
                "custom": False,
            }
            for item in THEMES
        ]
        raw = self.settings.get("custom_themes", {})
        if isinstance(raw, dict):
            for theme_id, item in raw.items():
                if not isinstance(item, dict):
                    continue
                key = str(theme_id or "").strip()
                if not key:
                    continue
                result.append(
                    {
                        "value": CUSTOM_THEME_PREFIX + key,
                        "label": str(item.get("name") or key),
                        "desc": str(item.get("description") or ""),
                        "experimental": False,
                        "custom": True,
                    }
                )
        return result

    @staticmethod
    def space_view(space: Any) -> dict:
        item = space if isinstance(space, dict) else {}
        try:
            minutes = int(item.get("minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0
        apps = item.get("allowed_apps")
        return {
            "id": str(item.get("id") or ""),
            "mode": str(item.get("mode") or ""),
            "name": str(item.get("name") or ""),
            "minutes": minutes,
            "allowedApps": [str(app) for app in apps] if isinstance(apps, list) else [],
        }

    def spaces_by_mode(self) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {mode: [] for mode in MODES}
        try:
            items = list(self.spaces.all())
        except Exception:  # noqa: BLE001 - 空间数据坏了不应该让管理页 500
            items = []
        for space in items:
            mode = str((space or {}).get("mode") or "")
            if mode in grouped:
                grouped[mode].append(self.space_view(space))
        return grouped

    def stats_summary(self) -> dict:
        empty = {
            "todayMinutes": 0.0,
            "todaySessions": 0,
            "weekMinutes": 0.0,
            "streakDays": 0,
            "totalSessions": 0,
            "heatmap": [],
        }
        if self.stats is None:
            return empty
        today = date.today()
        try:
            summary = {
                "todayMinutes": round(float(self.stats.today_minutes(today)), 1),
                "todaySessions": int(self.stats.today_sessions(today)),
                "weekMinutes": round(float(self.stats.week_minutes(today)), 1),
                "streakDays": int(self.stats.streak_days(today)),
                "totalSessions": int(self.stats.total_sessions()),
                "heatmap": [],
            }
        except Exception:  # noqa: BLE001
            return empty
        heatmap: list[dict] = []
        for offset in range(HEATMAP_DAYS - 1, -1, -1):
            day = today - timedelta(days=offset)
            try:
                minutes = round(float(self.stats.minutes_on(day)), 1)
            except Exception:  # noqa: BLE001
                minutes = 0.0
            heatmap.append({"date": day.isoformat(), "minutes": minutes})
        summary["heatmap"] = heatmap
        return summary

    def plugins_summary(self) -> list[dict]:
        if self._plugins_provider is None:
            return []
        try:
            items = list(self._plugins_provider() or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取插件列表失败：%s", exc)
            return []
        result: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            result.append(
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or item.get("id") or ""),
                    "version": str(item.get("version") or ""),
                    "description": str(item.get("description") or ""),
                    "enabled": bool(item.get("enabled", True)),
                    "error": str(item.get("error") or ""),
                }
            )
        return result

    def store_status(self) -> str:
        if self.store_service is None:
            return "builtin"
        try:
            return str(self.store_service.status or "builtin")
        except Exception:  # noqa: BLE001
            return "builtin"

    def store_items(self) -> list[dict]:
        provider = self._store_items_provider
        if provider is not None:
            try:
                return [item for item in (provider() or []) if isinstance(item, dict)]
            except Exception as exc:  # noqa: BLE001
                logger.warning("读取商店目录失败：%s", exc)
                return []
        if self.store_service is None:
            return []
        try:
            return [item for item in (self.store_service.items() or []) if isinstance(item, dict)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取商店目录失败：%s", exc)
            return []

    def session_snapshot(self) -> dict:
        if self._session_snapshot is not None:
            try:
                snapshot = self._session_snapshot()
                if isinstance(snapshot, dict):
                    return dict(snapshot)
            except Exception as exc:  # noqa: BLE001
                logger.warning("读取专注状态失败：%s", exc)
        return {"state": "idle", "remainingSeconds": 0, "spaceName": "", "level": ""}

    # ---------- 写入 ----------
    def notify_settings(self, key: str, value: Any) -> None:
        if self._on_settings_changed is None:
            return
        try:
            self._on_settings_changed(key, value)
        except Exception as exc:  # noqa: BLE001
            logger.warning("通知设置变更失败：%s", exc)

    def notify_spaces(self) -> None:
        if self._on_spaces_changed is None:
            return
        try:
            self._on_spaces_changed()
        except Exception as exc:  # noqa: BLE001
            logger.warning("通知空间变更失败：%s", exc)

    def apply_setting(self, key: str, value: Any) -> tuple[bool, str]:
        """写设置（白名单 + 归一化），成功后通知界面即时生效。"""
        name = str(key or "").strip()
        try:
            if name == "theme_style":
                return self.set_theme_style(str(value or ""))
            if name == "theme_scheme":
                return self.set_theme_scheme(str(value or ""))
            if name == "theme_mode":
                # 兼容旧网页管理页提交的单一主题值
                return self.set_theme(str(value or ""))
            normalized = normalize_setting(self.settings, name, value)
        except WebAdminError as exc:
            return False, str(exc)
        self.settings.set(name, normalized)
        self.notify_settings(name, normalized)
        return True, ""

    def set_theme_style(self, style: str) -> tuple[bool, str]:
        """切换外观样式（内置样式或已安装的 custom:<id>）。"""
        value = str(style or "").strip()
        if not valid_theme_style(self.settings, value):
            return False, "未知主题样式"
        self.settings.set("theme_style", value)
        self.notify_settings("theme_style", value)
        return True, ""

    def set_theme_scheme(self, scheme: str) -> tuple[bool, str]:
        """切换配色方案（auto / light / dark）。"""
        value = str(scheme or "").strip()
        if not valid_theme_scheme(value):
            return False, "未知配色方案"
        self.settings.set("theme_scheme", value)
        self.notify_settings("theme_scheme", value)
        return True, ""

    def set_theme(self, mode: str) -> tuple[bool, str]:
        """兼容旧接口：旧主题值映射成 样式 + 配色（light→solid+light 等）。"""
        pair = legacy_theme_pair(mode)
        if pair is None:
            return False, "未知主题"
        style, scheme = pair
        if not valid_theme_style(self.settings, style):
            return False, "未知主题"
        self.settings.set("theme_style", style)
        self.settings.set("theme_scheme", scheme)
        self.notify_settings("theme_style", style)
        self.notify_settings("theme_scheme", scheme)
        return True, ""

    def start_session(self, mode: str, minutes: Any, space_id: str) -> tuple[bool, str]:
        """默认实现：没有主程序时返回失败（主程序会注入真实动作）。"""
        return False, "当前环境无法开始专注"

    def stop_session(self) -> tuple[bool, str]:
        return False, "当前环境无法结束专注"

    def install_store_item(self, item_id: str) -> tuple[bool, str]:
        """安装商店条目（主题写到 settings，插件解压到用户插件目录）。"""
        wanted = str(item_id or "").strip()
        if not wanted:
            return False, "缺少条目 id"
        item = None
        if self.store_service is not None:
            try:
                item = self.store_service.get(wanted)
            except Exception:  # noqa: BLE001
                item = None
        if not item:
            return False, "商店里没有这个条目"
        try:
            from . import store as store_module
        except Exception:  # noqa: BLE001 - 商店模块缺失
            return False, "商店服务不可用"
        kind = str(item.get("kind") or "")
        name = str(item.get("name") or wanted)
        if kind == "theme":
            try:
                palette = store_module.normalize_palette(item.get("palette"))
                theme_id = store_module.normalize_theme_id(wanted)
            except store_module.StoreError as exc:
                return False, str(exc)
            raw = self.settings.get("custom_themes", {})
            stored = {
                str(key): value
                for key, value in (raw.items() if isinstance(raw, dict) else [])
                if isinstance(value, dict)
            }
            stored[theme_id] = {
                "name": name[:40],
                "description": str(item.get("summary") or "")[:200],
                "palette": palette,
            }
            self.settings.set("custom_themes", stored)
            self.settings.set("theme_style", CUSTOM_THEME_PREFIX + theme_id)
            self.notify_settings("theme_style", CUSTOM_THEME_PREFIX + theme_id)
            return True, f"已安装主题：{name}"
        if kind != "plugin":
            return False, "未知的商店条目类型"
        url = str(item.get("download_url") or "").strip()
        if not url:
            return False, "插件缺少下载地址"
        temp_dir: Path | None = None
        try:
            temp_dir = Path(tempfile.mkdtemp(prefix="shenqing-webadmin-"))
            zip_path = store_module.download_file(url, temp_dir / "plugin.zip")
            store_module.install_plugin_zip(zip_path, wanted)
        except store_module.StoreError as exc:
            return False, str(exc)
        except Exception as exc:  # noqa: BLE001 - 下载/解压异常都要给可读提示
            logger.warning("网页管理安装插件失败：%s", exc)
            return False, str(exc) or "插件安装失败"
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
        return True, f"已安装插件：{name}"


# ================= HTTP 层 =================


def _port_free(port: int) -> bool:
    """端口是否空闲：能连上说明已被别的进程占用（本机回环）。"""
    if port <= 0:
        return True
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.25)
    try:
        return probe.connect_ex((BIND_HOST, port)) != 0
    except OSError:
        return True
    finally:
        try:
            probe.close()
        except OSError:
            pass


class _AdminHTTPServer(ThreadingHTTPServer):
    """管理页服务端：daemon 线程，主程序退出不阻塞。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], service: "WebAdminService") -> None:
        self.service = service
        super().__init__(address, _AdminHandler)

    def handle_error(self, request: Any, client_address: Any) -> None:  # noqa: ANN401
        # 浏览器轮询断开连接很常见，不要把栈刷进日志
        logger.debug("网页管理连接异常：%s", client_address)


class _AdminHandler(BaseHTTPRequestHandler):
    """单文件管理页 + JSON API。"""

    server_version = "ShenQingWebAdmin/1.0"
    sys_version = ""

    @property
    def service(self) -> "WebAdminService":
        return self.server.service  # type: ignore[attr-defined]

    # ---- 路由入口 ----
    def do_GET(self) -> None:
        self._safe_handle("GET")

    def do_POST(self) -> None:
        self._safe_handle("POST")

    def do_HEAD(self) -> None:
        self._safe_handle("HEAD")

    def _safe_handle(self, method: str) -> None:
        try:
            self.service.handle(self, method)
        except Exception as exc:  # noqa: BLE001 - 单个请求出错不能拖垮服务
            logger.warning("网页管理请求处理失败：%s", exc)
            try:
                self.send_json(500, {"ok": False, "message": "内部错误"})
            except Exception:  # noqa: BLE001
                pass

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # 2 秒一次的轮询会把日志刷爆，这里静默
        return

    # ---- 响应 ----
    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def send_html(self, status: int, html: str) -> None:
        self._send_bytes(status, html.encode("utf-8"), "text/html; charset=utf-8")

    def send_empty(self, status: int) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _send_bytes(self, status: int, payload: bytes, content_type: str) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


# ================= 服务本体 =================


class WebAdminService:
    """本地网页管理服务：启停 / 鉴权 / 路由 / 页面。"""

    def __init__(
        self,
        settings: Any,
        host: WebAdminHost,
        *,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._host = host
        self._now = now or time.monotonic
        self._lock = threading.RLock()
        #: 串行化写操作：设置 / 空间都是「读-改-写」，并发请求会互相覆盖
        self._write_lock = threading.Lock()
        self._server: _AdminHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._port = 0
        self._token = ""
        self._error = ""
        # 商店快照：后台刷新，避免轮询被 6 秒网络超时拖住
        self._store_cache: list[dict] = []
        self._store_at = float("-inf")
        self._store_busy = False

    # ---------- 状态 ----------
    @property
    def settings(self) -> Any:
        return self._settings

    @property
    def host(self) -> WebAdminHost:
        return self._host

    @property
    def running(self) -> bool:
        with self._lock:
            return self._server is not None

    @property
    def port(self) -> int:
        with self._lock:
            return int(self._port)

    @property
    def token(self) -> str:
        with self._lock:
            if self._token:
                return self._token
        return self._read_token()

    @property
    def url(self) -> str:
        """带 token 的完整地址；未运行返回空字符串。"""
        if not self.running:
            return ""
        return f"http://{BIND_HOST}:{self.port}/?token={self.token}"

    def status(self) -> tuple[bool, str, str]:
        """(运行中, 带 token 的地址, 最近一次错误)。"""
        running = self.running
        return running, (self.url if running else ""), self._error

    # ---------- token ----------
    def _read_token(self) -> str:
        return str(self._settings.get("web_admin_token", "") or "").strip()

    def ensure_token(self) -> str:
        """确保存在 token：首次启用时生成 secrets.token_urlsafe(24) 并持久化。"""
        token = self._read_token()
        if not token:
            token = secrets.token_urlsafe(TOKEN_BYTES)
            self._settings.set("web_admin_token", token)
            logger.info("已生成网页管理 token")
        with self._lock:
            self._token = token
        return token

    def regenerate_token(self) -> str:
        """重新生成 token（旧地址立即失效）。"""
        token = secrets.token_urlsafe(TOKEN_BYTES)
        self._settings.set("web_admin_token", token)
        with self._lock:
            self._token = token
        return token

    # ---------- 启停 ----------
    def _base_port(self) -> int:
        try:
            port = int(self._settings.get("web_admin_port", DEFAULT_PORT))
        except (TypeError, ValueError):
            port = DEFAULT_PORT
        if port < 0 or port > 65535:
            port = DEFAULT_PORT
        return port

    @staticmethod
    def _port_candidates(base: int) -> list[int]:
        if base <= 0:
            return [0]  # 0 = 让系统分配（测试用）
        return [base + offset for offset in range(MAX_PORT_ATTEMPTS)]

    def start(self) -> bool:
        """启动服务；端口被占用时自动 +1（最多 20 次）。"""
        with self._lock:
            if self._server is not None:
                return True
            self._error = ""
        token = self.ensure_token()
        base = self._base_port()
        error = ""
        for port in self._port_candidates(base):
            if not _port_free(port):
                error = f"端口 {port} 已被占用"
                continue
            try:
                server = _AdminHTTPServer((BIND_HOST, port), self)
            except OSError as exc:
                error = f"端口 {port} 绑定失败：{exc}"
                logger.warning("网页管理端口 %s 绑定失败：%s", port, exc)
                continue
            actual = int(server.server_address[1])
            thread = threading.Thread(
                target=server.serve_forever,
                name="shenqing-webadmin",
                daemon=True,
            )
            thread.start()
            with self._lock:
                self._server = server
                self._thread = thread
                self._port = actual
                self._token = token
                self._error = ""
            logger.info("网页管理已启动：http://%s:%s/", BIND_HOST, actual)
            return True
        with self._lock:
            self._error = error or "无法启动网页管理服务"
        logger.warning("网页管理启动失败：%s", self._error)
        return False

    def stop(self) -> None:
        with self._lock:
            server, thread = self._server, self._thread
            self._server, self._thread, self._port = None, None, 0
        if server is None:
            return
        try:
            server.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            server.server_close()
        except Exception:  # noqa: BLE001
            pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        logger.info("网页管理已停止")

    def restart(self) -> bool:
        self.stop()
        return self.start()

    def set_enabled(self, enabled: bool) -> bool:
        """设置页开关：写设置并立即启停。"""
        self._settings.set("web_admin_enabled", bool(enabled))
        if enabled:
            return self.start()
        self.stop()
        return True

    # ---------- 路由 ----------
    def handle(self, handler: _AdminHandler, method: str) -> None:
        parsed = urlparse(handler.path or "/")
        path = parsed.path or "/"
        query = parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            self._serve_index(handler, query)
            return
        if path == "/favicon.ico":
            handler.send_empty(204)
            return
        if not path.startswith("/api/"):
            handler.send_json(404, {"ok": False, "message": "页面不存在"})
            return
        if not self._authorized(handler, query):
            handler.send_json(401, {"ok": False, "message": "token 无效或缺失"})
            return
        try:
            body = self._read_body(handler) if method in ("POST", "PUT") else {}
            status, payload = self._dispatch(method, path, body)
        except WebAdminNotFound as exc:
            status, payload = 404, {"ok": False, "message": str(exc)}
        except WebAdminError as exc:
            status, payload = 400, {"ok": False, "message": str(exc)}
        except Exception as exc:  # noqa: BLE001 - 接口异常统一转 500
            logger.warning("网页管理接口 %s 处理失败：%s", path, exc)
            status, payload = 500, {"ok": False, "message": f"内部错误：{exc}"}
        handler.send_json(status, payload)

    def _dispatch(self, method: str, path: str, body: dict) -> tuple[int, dict]:
        if path == "/api/state":
            if method not in ("GET", "HEAD"):
                raise WebAdminError("请用 GET 访问 /api/state")
            return 200, self.state()
        if path == "/api/settings":
            if method != "POST":
                raise WebAdminError("请用 POST 访问 /api/settings")
            with self._write_lock:
                return self._post_settings(body)
        if path == "/api/spaces":
            if method != "POST":
                raise WebAdminError("请用 POST 访问 /api/spaces")
            with self._write_lock:
                return self._post_spaces(body)
        if path == "/api/session":
            if method != "POST":
                raise WebAdminError("请用 POST 访问 /api/session")
            return self._post_session(body)
        if path == "/api/store/install":
            if method != "POST":
                raise WebAdminError("请用 POST 访问 /api/store/install")
            return self._post_store_install(body)
        if path == "/api/theme":
            if method != "POST":
                raise WebAdminError("请用 POST 访问 /api/theme")
            return self._post_theme(body)
        raise WebAdminNotFound(f"未知接口：{path}")

    # ---------- 鉴权 ----------
    def _authorized(self, handler: _AdminHandler, query: dict) -> bool:
        expected = self.token
        if not expected:
            return False
        supplied = ""
        values = query.get("token") or []
        if values:
            supplied = str(values[0] or "")
        if not supplied:
            supplied = str(handler.headers.get(TOKEN_HEADER, "") or "")
        if not supplied:
            return False
        return secrets.compare_digest(str(supplied), expected)

    def _read_body(self, handler: _AdminHandler) -> dict:
        try:
            length = int(handler.headers.get("Content-Length") or 0)
        except (TypeError, ValueError) as exc:
            raise WebAdminError("Content-Length 不合法") from exc
        if length <= 0:
            return {}
        raw = handler.rfile.read(min(length, MAX_BODY_BYTES))
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebAdminError("请求体不是合法 JSON") from exc
        if not isinstance(data, dict):
            raise WebAdminError("请求体必须是 JSON 对象")
        return data

    # ---------- 状态 ----------
    def _setting_value(self, key: str) -> Any:
        if key == "theme_style":
            return self._host.theme_style()
        if key == "theme_scheme":
            return self._host.theme_scheme()
        raw = self._host.settings.get(key, _SETTING_FALLBACK.get(key))
        try:
            return normalize_setting(self._host.settings, key, raw)
        except WebAdminError:
            return _SETTING_FALLBACK.get(key)

    def _settings_snapshot(self) -> dict[str, Any]:
        return {key: self._setting_value(key) for key in SETTINGS_KEYS}

    def _store_items_snapshot(self) -> list[dict]:
        self._maybe_refresh_store()
        installed_themes = self._installed_theme_ids()
        installed_plugins = {item["id"] for item in self._host.plugins_summary()}
        result: list[dict] = []
        for item in list(self._store_cache):
            item_id = str(item.get("id") or "")
            kind = str(item.get("kind") or "")
            if not item_id or kind not in ("theme", "plugin"):
                continue
            installed = (
                item_id in installed_themes if kind == "theme" else item_id in installed_plugins
            )
            result.append(
                {
                    "id": item_id,
                    "kind": kind,
                    "name": str(item.get("name") or item_id),
                    "author": str(item.get("author") or ""),
                    "summary": str(item.get("summary") or ""),
                    "version": str(item.get("version") or ""),
                    "rating": _as_float(item.get("rating")),
                    "downloads": int(_as_float(item.get("downloads"))),
                    "installed": installed,
                }
            )
        return result

    def _installed_theme_ids(self) -> set[str]:
        raw = self._host.settings.get("custom_themes", {})
        if not isinstance(raw, dict):
            return set()
        return {str(key) for key in raw.keys()}

    def _maybe_refresh_store(self) -> None:
        with self._lock:
            if self._store_busy:
                return
            if self._now() - self._store_at < STORE_REFRESH_SECONDS:
                return
            self._store_at = self._now()
            self._store_busy = True
        threading.Thread(
            target=self._refresh_store_worker,
            name="shenqing-webadmin-store",
            daemon=True,
        ).start()

    def _refresh_store_worker(self) -> None:
        try:
            self._store_cache = list(self._host.store_items() or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("刷新商店快照失败：%s", exc)
            self._store_cache = []
        finally:
            with self._lock:
                self._store_busy = False

    def state(self) -> dict:
        """GET /api/state 的完整内容。"""
        host = self._host
        return {
            "appName": APP_NAME,
            "version": host.version,
            "themeMode": host.theme_mode(),
            "themeStyle": host.theme_style(),
            "themeScheme": host.theme_scheme(),
            "themes": host.themes(),
            "themeSchemes": host.theme_schemes(),
            "modes": [
                {"value": mode, "label": MODE_LABELS.get(mode, mode)} for mode in MODES
            ],
            "spaces": host.spaces_by_mode(),
            "stats": host.stats_summary(),
            "settings": self._settings_snapshot(),
            "plugins": host.plugins_summary(),
            "storeStatus": host.store_status(),
            "storeItems": self._store_items_snapshot(),
            "session": host.session_snapshot(),
            "webAdmin": {"running": self.running, "port": self.port},
        }

    # ---------- 接口 ----------
    def _post_settings(self, body: dict) -> tuple[int, dict]:
        key = str(body.get("key") or "").strip()
        if not key:
            raise WebAdminError("缺少 key")
        if key not in SETTINGS_KEYS:
            raise WebAdminError(f"不允许修改的设置项：{key}")
        ok, message = self._host.apply_setting(key, body.get("value"))
        if not ok:
            return 400, {"ok": False, "message": message or "保存失败"}
        disabling = False
        if key == "web_admin_enabled":
            disabling = not bool(self._setting_value("web_admin_enabled"))
        if disabling:
            # 先把响应发出去，再关掉服务（否则浏览器拿不到结果）
            threading.Timer(0.3, self.stop).start()
        return 200, {
            "ok": True,
            "message": "已保存",
            "settings": self._settings_snapshot(),
        }

    def _post_spaces(self, body: dict) -> tuple[int, dict]:
        action = str(body.get("action") or "").strip().lower()
        spaces = self._host.spaces
        space_id = str(body.get("spaceId") or "").strip()
        if action == "add":
            mode = str(body.get("mode") or "").strip()
            space = spaces.add(mode)
            if space is None:
                return 400, {"ok": False, "message": "该档位不能新增空间"}
            self._host.notify_spaces()
            return 200, {
                "ok": True,
                "message": "已新增空间",
                "space": self._host.space_view(space),
                "spaces": self._host.spaces_by_mode(),
            }
        if action == "delete":
            if not space_id:
                raise WebAdminError("缺少 spaceId")
            if not spaces.delete(space_id):
                return 400, {"ok": False, "message": "无法删除该空间（该档位至少保留一个）"}
            self._host.notify_spaces()
            return 200, {
                "ok": True,
                "message": "已删除空间",
                "spaces": self._host.spaces_by_mode(),
            }
        if action == "rename":
            if not space_id:
                raise WebAdminError("缺少 spaceId")
            name = str(body.get("name") or "").strip()
            if not name:
                raise WebAdminError("空间名不能为空")
            if not spaces.set_name(space_id, name):
                return 400, {
                    "ok": False,
                    "message": "无法改名（空间不存在，或该档位名称固定）",
                }
            self._host.notify_spaces()
            return 200, {
                "ok": True,
                "message": "已改名",
                "spaces": self._host.spaces_by_mode(),
            }
        if action == "minutes":
            if not space_id:
                raise WebAdminError("缺少 spaceId")
            if body.get("minutes") in (None, ""):
                raise WebAdminError("缺少 minutes")
            space = spaces.set_minutes(space_id, body.get("minutes"))
            if space is None:
                return 400, {"ok": False, "message": "空间不存在"}
            self._host.notify_spaces()
            return 200, {
                "ok": True,
                "message": f"时长已改为 {space['minutes']} 分钟",
                "space": self._host.space_view(space),
                "spaces": self._host.spaces_by_mode(),
            }
        raise WebAdminError("未知的空间操作（add / delete / rename / minutes）")

    def _post_session(self, body: dict) -> tuple[int, dict]:
        action = str(body.get("action") or "").strip().lower()
        if action == "start":
            mode = str(body.get("mode") or "").strip()
            space_id = str(body.get("spaceId") or "").strip()
            minutes = body.get("minutes")
            if not space_id:
                if not mode:
                    raise WebAdminError("开始专注需要 mode + minutes，或 spaceId")
                if minutes in (None, ""):
                    raise WebAdminError("开始专注需要 mode + minutes，或 spaceId")
            ok, message = self._host.start_session(mode, minutes, space_id)
            if not ok:
                return 400, {"ok": False, "message": message or "无法开始专注"}
            return 200, {
                "ok": True,
                "message": message or "已开始专注",
                "session": self._host.session_snapshot(),
            }
        if action == "stop":
            ok, message = self._host.stop_session()
            if not ok:
                return 400, {"ok": False, "message": message or "无法结束专注"}
            return 200, {
                "ok": True,
                "message": message or "已结束专注",
                "session": self._host.session_snapshot(),
            }
        raise WebAdminError("未知的会话操作（start / stop）")

    def _post_theme(self, body: dict) -> tuple[int, dict]:
        """切换外观：新参数 {style, scheme}；兼容旧参数 {mode}。"""
        style = str(body.get("style") or "").strip()
        scheme = str(body.get("scheme") or "").strip()
        message = "已切换主题"
        if style:
            ok, message = self._host.set_theme_style(style)
            if not ok:
                return 400, {"ok": False, "message": message or "无法切换主题样式"}
        if scheme:
            ok, message = self._host.set_theme_scheme(scheme)
            if not ok:
                return 400, {"ok": False, "message": message or "无法切换配色方案"}
        if not style and not scheme:
            mode = str(body.get("mode") or "").strip()
            if not mode:
                raise WebAdminError("缺少 style / scheme / mode")
            ok, message = self._host.set_theme(mode)
            if not ok:
                return 400, {"ok": False, "message": message or "无法切换主题"}
        return 200, {
            "ok": True,
            "message": message or "已切换主题",
            "themeMode": self._host.theme_mode(),
            "themeStyle": self._host.theme_style(),
            "themeScheme": self._host.theme_scheme(),
            "themes": self._host.themes(),
            "themeSchemes": self._host.theme_schemes(),
        }

    def _post_store_install(self, body: dict) -> tuple[int, dict]:
        item_id = str(body.get("itemId") or "").strip()
        if not item_id:
            raise WebAdminError("缺少 itemId")
        ok, message = self._host.install_store_item(item_id)
        # 安装后让商店快照过期，下次轮询拿到最新安装状态
        with self._lock:
            self._store_at = float("-inf")
        if not ok:
            return 400, {"ok": False, "message": message or "安装失败"}
        return 200, {"ok": True, "message": message or "已安装"}

    # ---------- 页面 ----------
    def _serve_index(self, handler: _AdminHandler, query: dict) -> None:
        if self._authorized(handler, query):
            handler.send_html(200, _PAGE_HTML)
            return
        supplied = bool((query.get("token") or [""])[0])
        hint = "token 不正确，请重新从深清复制地址" if supplied else ""
        handler.send_html(200, _auth_page(hint))


# ================= 页面（单文件 HTML） =================


def _auth_page(hint: str) -> str:
    if hint:
        note = '<p class="hint error">' + hint + "</p>"
    else:
        note = '<p class="hint">在深清的设置 → 网页管理里复制「管理页地址」，粘贴到下面。</p>'
    return _AUTH_PAGE_TEMPLATE.replace("{{HINT}}", note)


_AUTH_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>深清 · 网页管理</title>
<style>
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
  background:radial-gradient(900px 500px at 20% -10%,rgba(79,155,255,.25),transparent 60%),
             radial-gradient(800px 420px at 85% 0%,rgba(53,224,200,.20),transparent 55%),
             linear-gradient(160deg,#04121a,#07232f);
  color:#eaf8fc;font-family:'Microsoft YaHei UI','Microsoft YaHei','PingFang SC',system-ui,sans-serif}
.card{width:min(92vw,420px);background:rgba(12,40,54,.92);border:1px solid rgba(86,206,224,.22);
  border-radius:18px;padding:26px 24px;box-shadow:0 18px 50px rgba(0,0,0,.45)}
h1{font-size:19px;margin:0 0 6px}
p.hint{color:#8fb6c4;font-size:13px;margin:0 0 16px;line-height:1.6}
p.hint.error{color:#ff9aa5}
label{display:block;font-size:12px;color:#8fb6c4;margin-bottom:6px}
input{width:100%;padding:11px 13px;border-radius:11px;border:1px solid rgba(86,206,224,.26);
  background:rgba(4,18,26,.75);color:#eaf8fc;font-size:13px;outline:none}
input:focus{border-color:#35e0c8;box-shadow:0 0 0 3px rgba(53,224,200,.14)}
button{margin-top:14px;width:100%;padding:11px 14px;border-radius:11px;border:0;cursor:pointer;
  background:linear-gradient(135deg,#35e0c8,#4f9bff);color:#04121a;font-weight:700;font-size:14px}
button:hover{filter:brightness(1.06)}
</style>
</head>
<body>
<div class="card">
  <h1>深清 · 网页管理</h1>
  {{HINT}}
  <label for="t">管理页地址中的 token</label>
  <input id="t" type="text" spellcheck="false" autocomplete="off" placeholder="粘贴完整地址或 token">
  <button id="go" type="button">进入管理页</button>
</div>
<script>
(function () {
  'use strict';
  var input = document.getElementById('t');
  var button = document.getElementById('go');
  function go() {
    var value = String(input.value || '').trim();
    if (!value) { input.focus(); return; }
    if (value.indexOf('token=') >= 0) {
      value = value.split('token=')[1].split('&')[0];
    }
    try { value = decodeURIComponent(value); } catch (err) { /* 原样使用 */ }
    location.href = '/?token=' + encodeURIComponent(value);
  }
  button.addEventListener('click', go);
  input.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') { go(); }
  });
  input.focus();
})();
</script>
</body>
</html>"""


_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>深清 · 网页管理</title>
<style>
*{box-sizing:border-box}
:root{
  --bg:#04121a;--bg2:#07232f;--card:rgba(12,40,54,.92);--card2:rgba(18,52,71,.92);
  --border:rgba(86,206,224,.20);--text:#eaf8fc;--muted:#8fb6c4;
  --accent:#35e0c8;--accent2:#4f9bff;--danger:#ff8f9b;--ok:#7ce7c0;
  --shadow:0 12px 34px rgba(0,0,0,.35);
}
@media (prefers-color-scheme: light){
  :root{--bg:#eef6f9;--bg2:#e1eff5;--card:rgba(255,255,255,.95);--card2:#f5fbfd;
    --border:rgba(16,90,110,.16);--text:#0e2733;--muted:#5c7c89;
    --accent:#0f9e93;--accent2:#2f6fdc;--danger:#d6455a;--ok:#128a6c;
    --shadow:0 10px 26px rgba(16,60,80,.12)}
}
html,body{margin:0;padding:0}
body{
  min-height:100vh;color:var(--text);
  background:radial-gradient(1200px 600px at 12% -10%,rgba(79,155,255,.20),transparent 60%),
             radial-gradient(900px 520px at 92% 0%,rgba(53,224,200,.16),transparent 55%),
             linear-gradient(160deg,var(--bg),var(--bg2));
  font-family:'Microsoft YaHei UI','Microsoft YaHei','PingFang SC',system-ui,sans-serif;
  font-size:14px;line-height:1.55;padding-bottom:44px;
}
.top{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;
  padding:18px clamp(14px,3vw,32px) 10px}
.brand{display:flex;align-items:center;gap:10px;min-width:0}
.brand h1{font-size:18px;margin:0;font-weight:700;letter-spacing:.5px;white-space:nowrap}
.dot{width:9px;height:9px;border-radius:50%;background:var(--muted);flex:none;
  box-shadow:0 0 0 4px rgba(143,182,196,.15)}
.dot.ok{background:var(--ok);box-shadow:0 0 0 4px rgba(124,231,192,.16)}
.dot.bad{background:var(--danger);box-shadow:0 0 0 4px rgba(255,143,155,.16)}
.meta{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.pill{padding:5px 11px;border-radius:999px;border:1px solid var(--border);background:var(--card2);
  font-size:12px;color:var(--muted);white-space:nowrap}
.pill.accent{color:var(--accent);border-color:rgba(53,224,200,.35)}
.pill.busy{color:var(--accent2);border-color:rgba(79,155,255,.35)}
.tabs{display:flex;gap:6px;padding:4px clamp(14px,3vw,32px) 0;overflow-x:auto;
  scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tab{appearance:none;border:0;background:transparent;color:var(--muted);font-size:14px;
  padding:9px 14px;border-radius:11px 11px 0 0;cursor:pointer;white-space:nowrap;
  border-bottom:2px solid transparent;font-family:inherit}
.tab:hover{color:var(--text)}
.tab.active{color:var(--accent);border-bottom-color:var(--accent);font-weight:700}
main{padding:0 clamp(14px,3vw,32px);display:grid;gap:14px;
  grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.pane{display:none;grid-column:1/-1}
.pane.active{display:contents}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;
  padding:16px 18px;box-shadow:var(--shadow)}
.card h2{font-size:14px;margin:0 0 12px;font-weight:700;letter-spacing:.3px}
.card-head{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;
  margin-bottom:12px}
.card-head h2{margin:0}
.muted{color:var(--muted);font-size:12px}
.big{font-size:26px;font-weight:700;letter-spacing:.5px}
.unit{font-size:12px;color:var(--muted);margin-left:4px}
.metrics{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(120px,1fr))}
.metric{padding:12px 14px;border-radius:13px;background:var(--card2);border:1px solid var(--border)}
.metric .label{font-size:12px;color:var(--muted);margin-bottom:6px}
.row{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end}
label.field{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--muted);
  min-width:130px;flex:1 1 130px}
label.inline{display:flex;gap:6px;align-items:center;font-size:12px;color:var(--muted)}
input,select{font-family:inherit;font-size:13px;color:var(--text);background:var(--card2);
  border:1px solid var(--border);border-radius:10px;padding:8px 10px;outline:none;
  min-width:0;width:100%}
input:focus,select:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(53,224,200,.14)}
input[type=range]{padding:0;height:26px;accent-color:var(--accent)}
input[type=checkbox]{width:18px;height:18px;accent-color:var(--accent)}
button{font-family:inherit;font-size:13px;border-radius:10px;padding:8px 14px;cursor:pointer;
  border:1px solid var(--border);background:var(--card2);color:var(--text)}
button:hover{filter:brightness(1.08)}
button.primary{background:linear-gradient(135deg,var(--accent),var(--accent2));
  color:#04121a;border:0;font-weight:700}
button.danger{color:var(--danger);border-color:rgba(255,143,155,.45)}
button.small{padding:6px 11px;font-size:12px}
.space-list{display:flex;flex-direction:column;gap:10px}
.space{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;
  padding:11px 13px;border-radius:12px;background:var(--card2);border:1px solid var(--border)}
.space-main{display:flex;flex-wrap:wrap;gap:10px;align-items:center;flex:1 1 240px;min-width:0}
.space-main .name{max-width:190px}
.space-actions{display:flex;gap:8px}
.heat{display:flex;gap:5px;align-items:flex-end;height:130px;padding-top:6px;overflow-x:auto}
.bar{flex:1 1 0;min-width:12px;height:100%;display:flex;flex-direction:column;
  justify-content:flex-end;align-items:center;gap:6px}
.bar-fill{width:100%;border-radius:6px 6px 3px 3px;
  background:linear-gradient(180deg,var(--accent),rgba(79,155,255,.55));min-height:4px}
.bar span{font-size:10px;color:var(--muted);white-space:nowrap}
.store-list{display:flex;flex-direction:column;gap:10px}
.store-item{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;
  padding:11px 13px;border-radius:12px;background:var(--card2);border:1px solid var(--border)}
.store-title{font-weight:700;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.tag{font-size:11px;padding:1px 8px;border-radius:999px;border:1px solid var(--border);
  color:var(--muted);font-weight:400}
.tag.ok{color:var(--ok);border-color:rgba(124,231,192,.4)}
.setting-row{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;
  padding:10px 0;border-bottom:1px dashed var(--border)}
.setting-row:last-child{border-bottom:0}
.setting-row .title{font-size:13px;flex:1 1 150px;min-width:120px}
.setting-row .control{flex:0 1 240px;display:flex;align-items:center;gap:8px;justify-content:flex-end}
.hint{color:var(--muted);font-size:12px;margin:10px 0 0}
.toast{position:fixed;left:50%;bottom:22px;transform:translate(-50%,18px);opacity:0;
  pointer-events:none;transition:all .22s ease;background:var(--card);
  border:1px solid var(--border);border-radius:12px;padding:10px 16px;font-size:13px;
  box-shadow:var(--shadow);max-width:min(90vw,520px);z-index:20}
.toast.show{opacity:1;transform:translate(-50%,0)}
.toast.error{color:var(--danger);border-color:rgba(255,143,155,.5)}
.unauthed{display:none}
@media (max-width:560px){
  .brand h1{font-size:16px}
  .metrics{grid-template-columns:repeat(2,minmax(0,1fr))}
  .space-actions{width:100%;justify-content:flex-end}
  .setting-row .control{flex:1 1 100%;justify-content:flex-start}
}
</style>
</head>
<body>
<header class="top">
  <div class="brand"><span class="dot" id="conn-dot"></span><h1 id="title">深清 · 网页管理</h1></div>
  <div class="meta">
    <span class="pill" id="pill-status">连接中…</span>
    <span class="pill accent" id="pill-theme">主题 —</span>
    <span class="pill" id="pill-version">v—</span>
    <button class="small" data-act="refresh">刷新</button>
  </div>
</header>
<nav class="tabs">
  <button class="tab active" data-tab="overview">概览</button>
  <button class="tab" data-tab="spaces">空间</button>
  <button class="tab" data-tab="settings">设置</button>
  <button class="tab" data-tab="stats">统计</button>
  <button class="tab" data-tab="store">商店</button>
</nav>
<main>
  <section class="pane active" data-pane="overview" id="pane-overview"></section>
  <section class="pane" data-pane="spaces" id="pane-spaces"></section>
  <section class="pane" data-pane="settings" id="pane-settings"></section>
  <section class="pane" data-pane="stats" id="pane-stats"></section>
  <section class="pane" data-pane="store" id="pane-store"></section>
</main>
<div class="toast" id="toast"></div>
<script>
(function () {
  'use strict';

  var TOKEN = new URLSearchParams(location.search).get('token') || '';
  var MODE_ORDER = ['light', 'medium', 'heavy'];
  var MODE_LABEL = { light: '浅清', medium: '覆清', heavy: '深清' };
  var STATUS_TEXT = { idle: '空闲', running: '专注中', paused: '已暂停' };
  var data = null;
  var busy = false;
  var editing = {};

  var SETTING_ROWS = [
    { key: 'theme_style', title: '主题样式', type: 'theme' },
    {
      key: 'theme_scheme', title: '主题配色', type: 'select', options: [
        { value: 'auto', label: '跟随系统' },
        { value: 'light', label: '浅色' },
        { value: 'dark', label: '深色' }
      ]
    },
    {
      key: 'language', title: '界面语言', type: 'select', options: [
        { value: 'auto', label: '跟随系统' },
        { value: 'zh_CN', label: '简体中文' },
        { value: 'en_US', label: 'English' }
      ]
    },
    {
      key: 'nav_mode', title: '导航模式', type: 'select', options: [
        { value: 'auto', label: '自动' },
        { value: 'expanded', label: '始终展开' },
        { value: 'icons', label: '仅图标' },
        { value: 'custom', label: '自定义' }
      ]
    },
    { key: 'ui_font_scale', title: '界面字号', type: 'range' },
    { key: 'ui_font_family', title: '界面字体', type: 'text' },
    { key: 'default_minutes', title: '默认时长（分钟）', type: 'number' },
    { key: 'auto_update', title: '自动检查更新', type: 'bool' },
    { key: 'site_block_enabled', title: '专注时屏蔽网站', type: 'bool' },
    { key: 'web_admin_enabled', title: '网页管理', type: 'bool' }
  ];

  function $(selector, root) { return (root || document).querySelector(selector); }
  function pane(name) { return $('#pane-' + name); }

  function esc(value) {
    return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function num(value, fallback) {
    var parsed = Number(value);
    return isFinite(parsed) ? parsed : fallback;
  }

  function toast(message, isError) {
    var el = $('#toast');
    if (!el) return;
    el.textContent = message;
    el.className = 'toast show' + (isError ? ' error' : '');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(function () { el.className = 'toast'; }, 2800);
  }

  function setConn(ok, text) {
    var dot = $('#conn-dot');
    var pill = $('#pill-status');
    if (dot) dot.className = 'dot ' + (ok ? 'ok' : 'bad');
    if (pill && !ok) pill.textContent = text || '连接失败';
  }

  function api(path, body) {
    var url = path + (path.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN);
    var options = {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'X-ShenQing-Token': TOKEN }
    };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    return fetch(url, options).then(function (response) {
      if (response.status === 401) {
        throw new Error('token 无效或已过期，请重新从深清复制地址');
      }
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok || (payload && payload.ok === false)) {
          throw new Error((payload && payload.message) || ('请求失败（' + response.status + '）'));
        }
        return payload;
      });
    });
  }

  function act(work) {
    if (busy) return;
    busy = true;
    Promise.resolve().then(work).then(function (message) {
      if (message) toast(message);
    }).catch(function (error) {
      toast(error && error.message ? error.message : String(error), true);
    }).then(function () {
      busy = false;
      return refresh();
    });
  }

  function refresh() {
    return api('/api/state').then(function (payload) {
      data = payload;
      setConn(true, '');
      render();
    }).catch(function (error) {
      setConn(false, error.message || '连接失败');
    });
  }

  function themeLabel() {
    var list = (data && data.themes) || [];
    var current = data ? data.themeStyle : '';
    for (var i = 0; i < list.length; i += 1) {
      if (list[i].value === current) return list[i].label;
    }
    return current || '—';
  }

  function schemeLabel() {
    var list = (data && data.themeSchemes) || [];
    var current = data ? data.themeScheme : '';
    for (var i = 0; i < list.length; i += 1) {
      if (list[i].value === current) return list[i].label;
    }
    return current || '—';
  }

  function schemeOptions(selected) {
    var list = (data && data.themeSchemes) || [];
    return list.map(function (item) {
      return '<option value="' + esc(item.value) + '"' +
        (item.value === selected ? ' selected' : '') + '>' + esc(item.label) + '</option>';
    }).join('');
  }

  function sessionText() {
    var session = (data && data.session) || {};
    var state = String(session.state || 'idle');
    var text = STATUS_TEXT[state] || state;
    if (state === 'running' || state === 'paused') {
      text += ' · ' + clock(session.remainingSeconds || 0);
      if (session.spaceName) text += ' · ' + session.spaceName;
    }
    return text;
  }

  function clock(seconds) {
    var total = Math.max(0, Math.round(num(seconds, 0)));
    var minutes = Math.floor(total / 60);
    var rest = total % 60;
    return (minutes < 10 ? '0' : '') + minutes + ':' + (rest < 10 ? '0' : '') + rest;
  }

  function renderTop() {
    var title = $('#title');
    if (title && data.appName) title.textContent = data.appName + ' · 网页管理';
    $('#pill-version').textContent = 'v' + String(data.version || '—');
    $('#pill-theme').textContent = '外观 ' + themeLabel() + ' · ' + schemeLabel();
    var pill = $('#pill-status');
    pill.textContent = sessionText();
    pill.className = 'pill' + (data.session && data.session.state === 'running' ? ' busy' : '');
  }

  function metric(label, value, unit) {
    return '<div class="metric"><div class="label">' + esc(label) + '</div><div>' +
      '<span class="big">' + esc(value) + '</span><span class="unit">' + esc(unit) + '</span></div></div>';
  }

  function themeOptions(selected) {
    var list = (data && data.themes) || [];
    return list.map(function (item) {
      return '<option value="' + esc(item.value) + '"' +
        (item.value === selected ? ' selected' : '') + '>' + esc(item.label) +
        (item.custom ? '（自定义）' : '') + '</option>';
    }).join('');
  }

  function renderOverview() {
    var stats = data.stats || {};
    var session = data.session || {};
    var running = session.state === 'running' || session.state === 'paused';
    var modes = data.modes || [];
    var options = modes.map(function (item) {
      return '<option value="' + esc(item.value) + '">' + esc(item.label) + '</option>';
    }).join('');
    var html = '';

    html += '<div class="card"><h2>今日专注</h2><div class="metrics">' +
      metric('专注时长', num(stats.todayMinutes, 0), '分钟') +
      metric('完成次数', num(stats.todaySessions, 0), '次') +
      '</div></div>';

    html += '<div class="card"><h2>本周</h2><div class="metrics">' +
      metric('累计时长', num(stats.weekMinutes, 0), '分钟') +
      metric('连续打卡', num(stats.streakDays, 0), '天') +
      metric('历史次数', num(stats.totalSessions, 0), '次') +
      '</div></div>';

    html += '<div class="card"><h2>专注</h2><div class="row">' +
      '<label class="field">档位<select id="start-mode">' + options + '</select></label>' +
      '<label class="field">时长（分钟）<input id="start-minutes" type="number" min="1" max="240" value="25"></label>' +
      '<button class="primary" data-act="session-start">开始专注</button>' +
      '<button class="danger" data-act="session-stop"' + (running ? '' : ' disabled') + '>结束</button>' +
      '</div><p class="hint">当前状态：' + esc(sessionText()) + '。覆清 / 深清开始后不可提前结束。</p></div>';

    html += '<div class="card"><h2>外观</h2><div class="row">' +
      '<label class="field">主题样式<select data-setting="theme_style">' + themeOptions(data.themeStyle) + '</select></label>' +
      '<label class="field">配色方案<select data-setting="theme_scheme">' + schemeOptions(data.themeScheme) + '</select></label>' +
      '</div><p class="hint">样式与配色互相独立；切换后桌面端立即生效。</p></div>';

    pane('overview').innerHTML = html;
  }

  function renderSpaces() {
    var groups = data.spaces || {};
    var html = '';
    MODE_ORDER.forEach(function (mode) {
      var list = groups[mode] || [];
      html += '<div class="card"><div class="card-head"><h2>' + MODE_LABEL[mode] + '</h2>' +
        '<span class="muted">' + list.length + ' 个空间</span>' +
        (mode === 'heavy' ? '' : '<button class="small" data-act="space-add" data-mode="' + mode + '">新增空间</button>') +
        '</div><div class="space-list">';
      if (!list.length) {
        html += '<p class="muted">暂无空间</p>';
      }
      list.forEach(function (space) {
        var fixed = mode === 'heavy';
        html += '<div class="space"><div class="space-main">' +
          (fixed
            ? '<strong>' + esc(space.name) + '</strong>'
            : '<input class="name" data-space-name="' + esc(space.id) + '" maxlength="20" value="' + esc(space.name) + '">') +
          '<label class="inline">时长 <input type="number" min="1" max="240" style="width:78px" ' +
          'data-space-minutes="' + esc(space.id) + '" value="' + num(space.minutes, 1) + '"> 分钟</label>' +
          '<span class="muted">白名单 ' + ((space.allowedApps || []).length) + ' 项</span>' +
          '</div><div class="space-actions">' +
          '<button class="primary small" data-act="space-save" data-id="' + esc(space.id) + '">保存</button>' +
          (fixed ? '' : '<button class="danger small" data-act="space-delete" data-id="' + esc(space.id) + '">删除</button>') +
          '</div></div>';
      });
      html += '</div></div>';
    });
    pane('spaces').innerHTML = html;
  }

  function settingControl(row) {
    var value = (data.settings || {})[row.key];
    if (row.type === 'theme') {
      return '<select data-setting="' + row.key + '">' + themeOptions(data.themeStyle) + '</select>';
    }
    if (row.type === 'select') {
      return '<select data-setting="' + row.key + '">' + row.options.map(function (item) {
        return '<option value="' + esc(item.value) + '"' +
          (String(item.value) === String(value) ? ' selected' : '') + '>' + esc(item.label) + '</option>';
      }).join('') + '</select>';
    }
    if (row.type === 'range') {
      return '<input type="range" min="0.8" max="1.4" step="0.05" data-setting="' + row.key +
        '" value="' + num(value, 1) + '"><span class="muted" data-scale-label>' + Math.round(num(value, 1) * 100) + '%</span>';
    }
    if (row.type === 'number') {
      return '<input type="number" min="1" max="240" data-setting="' + row.key + '" value="' + num(value, 25) + '">';
    }
    if (row.type === 'bool') {
      return '<input type="checkbox" data-setting="' + row.key + '"' + (value ? ' checked' : '') + '>';
    }
    return '<input type="text" data-setting="' + row.key + '" value="' + esc(value) + '">';
  }

  function renderSettings() {
    var rows = SETTING_ROWS.map(function (row) {
      return '<div class="setting-row"><div class="title">' + esc(row.title) + '</div>' +
        '<div class="control">' + settingControl(row) + '</div></div>';
    }).join('');
    var html = '<div class="card"><h2>设置</h2>' + rows +
      '<p class="hint">修改即时生效并写入本地设置；网页管理开关关闭后本页会立刻断开。</p></div>';
    var webadmin = data.webAdmin || {};
    html += '<div class="card"><h2>网页管理</h2><div class="metrics">' +
      metric('监听端口', num(webadmin.port, 0) || '—', '') +
      metric('状态', webadmin.running ? '运行中' : '已停止', '') +
      '</div><p class="hint">只有本机（127.0.0.1）可以访问；地址里的 token 相当于密码，请勿泄露。</p></div>';
    pane('settings').innerHTML = html;
  }

  function renderStats() {
    var stats = data.stats || {};
    var heat = stats.heatmap || [];
    var max = 1;
    heat.forEach(function (day) { if (num(day.minutes, 0) > max) max = num(day.minutes, 0); });
    var bars = heat.map(function (day) {
      var height = Math.max(5, Math.round((num(day.minutes, 0) / max) * 100));
      return '<div class="bar" title="' + esc(day.date) + ' · ' + esc(day.minutes) + ' 分钟">' +
        '<div class="bar-fill" style="height:' + height + '%"></div>' +
        '<span>' + esc(String(day.date || '').slice(5)) + '</span></div>';
    }).join('');
    var html = '<div class="card"><h2>专注数据</h2><div class="metrics">' +
      metric('今日', num(stats.todayMinutes, 0), '分钟') +
      metric('本周', num(stats.weekMinutes, 0), '分钟') +
      metric('连续打卡', num(stats.streakDays, 0), '天') +
      metric('历史次数', num(stats.totalSessions, 0), '次') +
      '</div></div>';
    html += '<div class="card"><h2>最近 14 天</h2><div class="heat">' + bars + '</div></div>';
    pane('stats').innerHTML = html;
  }

  function storeStatusLabel(status) {
    var text = String(status || '');
    if (text === 'online') return '在线目录';
    if (text === 'builtin') return '内置目录';
    if (text.indexOf('error:') === 0) return '在线目录失败，已回退内置（' + text.slice(6) + '）';
    return text || '未知';
  }

  function renderStore() {
    var items = data.storeItems || [];
    var plugins = data.plugins || [];
    var html = '<div class="card"><div class="card-head"><h2>商店</h2>' +
      '<span class="muted">目录：' + esc(storeStatusLabel(data.storeStatus)) + '</span></div>' +
      '<div class="store-list">';
    if (!items.length) {
      html += '<p class="muted">商店目录加载中…</p>';
    }
    items.forEach(function (item) {
      var kindText = item.kind === 'theme' ? '主题' : '插件';
      html += '<div class="store-item"><div><div class="store-title">' + esc(item.name) +
        '<span class="tag">' + kindText + '</span>' +
        (item.installed ? '<span class="tag ok">已安装</span>' : '') + '</div>' +
        '<p class="muted">' + esc(item.summary || item.author || '') + '</p></div>' +
        '<button class="primary small" data-act="store-install" data-id="' + esc(item.id) + '">' +
        (item.installed ? '重新安装' : '安装') + '</button></div>';
    });
    html += '</div></div>';

    html += '<div class="card"><h2>已安装插件</h2><div class="store-list">';
    if (!plugins.length) {
      html += '<p class="muted">暂无插件</p>';
    }
    plugins.forEach(function (plugin) {
      html += '<div class="store-item"><div><div class="store-title">' + esc(plugin.name) +
        '<span class="tag">' + (plugin.enabled ? '已启用' : '已停用') + '</span>' +
        (plugin.version ? '<span class="tag">v' + esc(plugin.version) + '</span>' : '') + '</div>' +
        '<p class="muted">' + esc(plugin.description || plugin.id) + '</p></div></div>';
    });
    html += '</div></div>';
    pane('store').innerHTML = html;
  }

  function render() {
    if (!data) return;
    renderTop();
    if (!editing.overview) renderOverview();
    if (!editing.spaces) renderSpaces();
    if (!editing.settings) renderSettings();
    if (!editing.stats) renderStats();
    if (!editing.store) renderStore();
  }

  // ---- 交互 ----
  document.addEventListener('focusin', function (event) {
    var host = event.target.closest ? event.target.closest('[data-pane]') : null;
    if (host) editing[host.getAttribute('data-pane')] = true;
  });
  document.addEventListener('focusout', function (event) {
    var host = event.target.closest ? event.target.closest('[data-pane]') : null;
    if (!host) return;
    var name = host.getAttribute('data-pane');
    setTimeout(function () {
      if (!host.contains(document.activeElement)) editing[name] = false;
    }, 0);
  });

  document.addEventListener('change', function (event) {
    var control = event.target;
    if (control.hasAttribute && control.hasAttribute('data-scale-label')) return;
    var key = control.getAttribute && control.getAttribute('data-setting');
    if (!key) return;
    var value;
    if (control.type === 'checkbox') value = control.checked;
    else if (control.type === 'range' || control.type === 'number') value = Number(control.value);
    else value = control.value;
    act(function () {
      return api('/api/settings', { key: key, value: value }).then(function (payload) {
        if (payload && payload.settings) data.settings = payload.settings;
        return key === 'web_admin_enabled' ? '设置已保存' : '已保存';
      });
    });
  });

  document.addEventListener('input', function (event) {
    var control = event.target;
    if (!control.getAttribute || control.getAttribute('data-setting') !== 'ui_font_scale') return;
    var label = control.parentNode ? control.parentNode.querySelector('[data-scale-label]') : null;
    if (label) label.textContent = Math.round(Number(control.value) * 100) + '%';
  });

  document.addEventListener('click', function (event) {
    var tab = event.target.closest ? event.target.closest('[data-tab]') : null;
    if (tab) {
      var name = tab.getAttribute('data-tab');
      Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (item) {
        item.classList.toggle('active', item === tab);
      });
      Array.prototype.forEach.call(document.querySelectorAll('.pane'), function (item) {
        item.classList.toggle('active', item.getAttribute('data-pane') === name);
      });
      editing[name] = false;
      render();
      return;
    }
    var target = event.target.closest ? event.target.closest('[data-act]') : null;
    if (!target) return;
    var action = target.getAttribute('data-act');
    if (action === 'refresh') { act(function () { return '已刷新'; }); return; }
    if (action === 'session-start') {
      var mode = $('#start-mode') ? $('#start-mode').value : 'medium';
      var minutes = $('#start-minutes') ? Number($('#start-minutes').value) : 25;
      if (!minutes || minutes < 1) { toast('请填写有效时长', true); return; }
      act(function () {
        return api('/api/session', { action: 'start', mode: mode, minutes: minutes })
          .then(function () { return '已开始专注'; });
      });
      return;
    }
    if (action === 'session-stop') {
      act(function () {
        return api('/api/session', { action: 'stop' }).then(function () { return '已结束专注'; });
      });
      return;
    }
    if (action === 'space-add') {
      act(function () {
        return api('/api/spaces', { action: 'add', mode: target.getAttribute('data-mode') })
          .then(function () { return '已新增空间'; });
      });
      return;
    }
    if (action === 'space-delete') {
      var deleteId = target.getAttribute('data-id');
      if (!confirm('确定删除这个空间？')) return;
      act(function () {
        return api('/api/spaces', { action: 'delete', spaceId: deleteId })
          .then(function () { return '已删除空间'; });
      });
      return;
    }
    if (action === 'space-save') {
      var spaceId = target.getAttribute('data-id');
      var nameInput = document.querySelector('[data-space-name="' + spaceId + '"]');
      var minuteInput = document.querySelector('[data-space-minutes="' + spaceId + '"]');
      var tasks = [];
      if (nameInput && String(nameInput.value || '').trim()) {
        tasks.push(api('/api/spaces', { action: 'rename', spaceId: spaceId, name: nameInput.value.trim() }));
      }
      if (minuteInput && minuteInput.value !== '') {
        tasks.push(api('/api/spaces', { action: 'minutes', spaceId: spaceId, minutes: Number(minuteInput.value) }));
      }
      if (!tasks.length) { toast('没有要保存的改动', true); return; }
      act(function () {
        return Promise.all(tasks).then(function () { return '空间已保存'; });
      });
      return;
    }
    if (action === 'store-install') {
      act(function () {
        return api('/api/store/install', { itemId: target.getAttribute('data-id') })
          .then(function (payload) { return (payload && payload.message) || '已安装'; });
      });
    }
  });

  // 主题下拉单独走 /api/theme（概览与设置页都有）
  document.addEventListener('change', function (event) {
    var select = event.target;
    if (!select || select.id !== 'theme-select') return;
    act(function () {
      return api('/api/theme', { mode: select.value }).then(function () { return '已切换主题'; });
    });
  });

  refresh();
  setInterval(refresh, 2000);
})();
</script>
</body>
</html>"""
