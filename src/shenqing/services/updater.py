"""更新检查与下载（v0.16 多下载源）。

内置源：
- github：GitHub Releases（api.github.com/repos/Kryon2025/Clarity）
- gitlink：GitLink（Gitea 风格 API；/releases/latest 失败时回退 /releases 列表取首个）
- gitee：Gitee OpenAPI（gitee.com/api/v5/repos/kryonF/Clarity）
- 自定义源：用户填写的 JSON API URL（可带 Token），兼容
  {tag_name|version, body|notes, assets:[{name, browser_download_url|url}]}

公开接口：
- fetch_release(source_id) -> dict | None：拉取并归一化某个源的 release
- fetch_release_detail() -> (dict | None, str)：同上，附带可读错误信息
- check_latest()/check_latest_detail()：只在远端版本 > 当前 APP_VERSION 时返回信息
- download()：分块下载安装包，可回调进度、可取消
- version_tuple()/is_newer()：宽松版本比较

全部为纯函数 / 阻塞 IO，供 bridge 在后台线程调用，不直接依赖 Qt。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from ..consts import APP_VERSION, GITHUB_REPO

logger = logging.getLogger("shenqing.updater")

# ---------- 内置下载源 ----------
GITHUB_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"

GITLINK_REPO = "Kryon/Clarity"
GITLINK_LATEST = "https://gitlink.org.cn/api/v1/repos/Kryon/Clarity/releases/latest"
GITLINK_RELEASES = "https://gitlink.org.cn/api/v1/repos/Kryon/Clarity/releases"
GITLINK_PAGE = "https://gitlink.org.cn/Kryon/Clarity/releases"

GITEE_REPO = "kryonF/Clarity"
GITEE_LATEST = "https://gitee.com/api/v5/repos/kryonF/Clarity/releases/latest"
GITEE_PAGE = "https://gitee.com/kryonF/Clarity/releases"

#: 兼容旧代码 / 旧测试的别名
API_LATEST = GITHUB_LATEST

DEFAULT_SOURCE_ID = "github"
CUSTOM_SOURCE_PREFIX = "custom:"

BUILTIN_SOURCES: list[dict[str, Any]] = [
    {
        "id": "github",
        "name": "GitHub",
        "kind": "github",
        "url": GITHUB_LATEST,
        "page": RELEASES_PAGE,
    },
    {
        "id": "gitlink",
        "name": "GitLink",
        "kind": "gitlink",
        "url": GITLINK_LATEST,
        "fallbackUrl": GITLINK_RELEASES,
        "page": GITLINK_PAGE,
    },
    {
        "id": "gitee",
        "name": "Gitee",
        "kind": "gitee",
        "url": GITEE_LATEST,
        "page": GITEE_PAGE,
    },
]

USER_AGENT = "ShenQing-Updater"
ACCEPT = "application/json"
TIMEOUT_SECONDS = 20
CHUNK_SIZE = 64 * 1024


class CancelToken:
    """下载取消令牌（线程安全）。"""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def is_set(self) -> bool:
        return self._event.is_set()


# ---------- 版本 / 资产 ----------
def version_tuple(version: object) -> tuple[int, ...]:
    """'v0.6.10' → (0, 6, 10)；非数字段丢弃，至少返回一个元素。"""
    text = str(version or "").strip().lower()
    if text.startswith("v"):
        text = text[1:]
    parts = re.findall(r"\d+", text)
    if not parts:
        return (0,)
    return tuple(int(part) for part in parts)


def is_newer(remote: object, current: object = APP_VERSION) -> bool:
    """远端版本是否严格大于当前版本（长度不同按 0 补齐）。"""
    left = version_tuple(remote)
    right = version_tuple(current)
    length = max(len(left), len(right))
    left = left + (0,) * (length - len(left))
    right = right + (0,) * (length - len(right))
    return left > right


def select_asset(assets: list[dict] | None) -> dict | None:
    """只挑安装包：优先文件名含 Setup 的 .exe，其次第一个 .exe。"""
    exes: list[dict] = []
    for asset in assets or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if name.lower().endswith(".exe"):
            exes.append(asset)
    if not exes:
        return None
    for asset in exes:
        if "setup" in str(asset.get("name") or "").lower():
            return asset
    return exes[0]


# ---------- 源注册 ----------
def source_choices(custom_sources: list[dict] | None = None) -> list[dict]:
    """给 QML 的源列表：[{id,name,kind}]（不暴露自定义源 Token）。"""
    result = [
        {
            "id": str(item["id"]),
            "name": str(item["name"]),
            "kind": str(item["kind"]),
            "custom": False,
        }
        for item in BUILTIN_SOURCES
    ]
    for item in custom_sources or []:
        if not isinstance(item, Mapping):
            continue
        source_id = str(item.get("id") or "")
        if not source_id:
            continue
        result.append(
            {
                "id": source_id,
                "name": str(item.get("name") or "自定义源"),
                "kind": "custom",
                "custom": True,
            }
        )
    return result


def resolve_source(
    source_id: object, custom_sources: list[dict] | None = None
) -> dict | None:
    """按 id 找源（内置或自定义）；找不到返回 None。"""
    wanted = str(source_id or "").strip()
    if not wanted:
        wanted = DEFAULT_SOURCE_ID
    for item in BUILTIN_SOURCES:
        if item["id"] == wanted:
            return dict(item)
    for item in custom_sources or []:
        if isinstance(item, Mapping) and str(item.get("id") or "") == wanted:
            source = dict(item)
            source["kind"] = "custom"
            return source
    return None


def resolve_source_id(
    source_id: object, custom_sources: list[dict] | None = None
) -> str:
    source = resolve_source(source_id, custom_sources)
    return str(source.get("id") or "") if source else ""


def is_valid_source_url(url: object) -> bool:
    """自定义源必须是 http/https 绝对地址。"""
    text = str(url or "").strip()
    if not text:
        return False
    try:
        parts = urllib.parse.urlsplit(text)
    except ValueError:
        return False
    return parts.scheme.lower() in ("http", "https") and bool(parts.netloc)


def make_custom_source(
    name: object,
    url: object,
    token: object = "",
    existing: list[dict] | None = None,
) -> dict:
    """校验并生成一个自定义源；非法时抛 ValueError（消息可直接展示）。"""
    text_url = str(url or "").strip()
    if not is_valid_source_url(text_url):
        raise ValueError("更新源地址无效，需要 http/https 开头的 JSON API 地址")
    for item in existing or []:
        if isinstance(item, Mapping) and str(item.get("url") or "").strip() == text_url:
            raise ValueError("该更新源地址已存在")
    text_name = str(name or "").strip() or "自定义源"
    return {
        "id": CUSTOM_SOURCE_PREFIX + uuid.uuid4().hex[:8],
        "name": text_name[:40],
        "url": text_url,
        "token": str(token or "").strip(),
    }


# ---------- HTTP / 归一化 ----------
def describe_error(exc: BaseException) -> str:
    """把网络异常转成可读中文提示（不含 Token / 敏感查询串）。"""
    if isinstance(exc, urllib.error.HTTPError):
        code = int(getattr(exc, "code", 0) or 0)
        if code in (401, 403):
            return f"服务器拒绝访问（HTTP {code}，可能需要 Token 或触发限流）"
        if code == 404:
            return "接口不存在（HTTP 404），请检查更新源地址"
        return f"服务器返回 HTTP {code}"
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        return f"网络请求失败：{reason or exc}"
    if isinstance(exc, json.JSONDecodeError):
        return "返回内容不是有效的 JSON"
    if isinstance(exc, ValueError):
        return str(exc) or "更新源数据格式不正确"
    if isinstance(exc, OSError):
        return f"网络请求失败：{exc}"
    return str(exc) or "未知错误"


def _read_json(url: str, token: str = "") -> Any:
    """请求一个 JSON 接口；失败抛异常（调用方用 describe_error 转可读文案）。"""
    headers = {"Accept": ACCEPT, "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"token {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        payload = response.read().decode("utf-8", errors="replace")
    return json.loads(payload)


def _fetch_release() -> dict | None:
    """请求 GitHub latest release；失败抛异常（调用方决定错误文案）。"""
    data = _read_json(GITHUB_LATEST)
    return data if isinstance(data, dict) else None


def _first_asset_url(asset: Mapping) -> str:
    for key in ("browser_download_url", "download_url", "downloadUrl", "url"):
        value = str(asset.get(key) or "").strip()
        if value:
            return value
    return ""


def normalize_release(payload: object) -> dict | None:
    """把各源不同的 release JSON 归一化成 GitHub 风格。

    - 兼容字段：tag_name|tagName|version|name、body|notes|description、
      html_url|htmlUrl|page_url|url、assets|files
    - 兼容 assets 里的 browser_download_url|download_url|url
    - payload 是列表时取第一个元素（GitLink /releases 回退）
    """
    if isinstance(payload, list):
        payload = next((item for item in payload if isinstance(item, dict)), None)
    if not isinstance(payload, dict):
        return None
    tag = ""
    for key in ("tag_name", "tagName", "version", "name", "tag"):
        tag = str(payload.get(key) or "").strip()
        if tag:
            break
    notes = ""
    for key in ("body", "notes", "description", "release_notes"):
        value = payload.get(key)
        if value:
            notes = str(value)
            break
    page = ""
    for key in ("html_url", "htmlUrl", "page_url", "pageUrl", "url"):
        value = payload.get(key)
        if value:
            page = str(value)
            break
    raw_assets = payload.get("assets") or payload.get("files") or []
    assets: list[dict] = []
    if isinstance(raw_assets, list):
        for raw in raw_assets:
            if not isinstance(raw, Mapping):
                continue
            url = _first_asset_url(raw)
            name = str(raw.get("name") or raw.get("filename") or "").strip()
            if not name and url:
                name = url.rsplit("/", 1)[-1]
            try:
                size = int(raw.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            assets.append(
                {"name": name, "browser_download_url": url, "size": max(0, size)}
            )
    return {"tag_name": tag, "body": notes, "html_url": page, "assets": assets}


def _release_from_payload(payload: object, source_name: str) -> tuple[dict | None, str]:
    release = normalize_release(payload)
    if release is None or not release.get("tag_name"):
        return None, f"{source_name} 源未返回可用的发布信息"
    return release, ""


# ---------- 拉取 ----------
def fetch_release_detail(
    source_id: object = DEFAULT_SOURCE_ID,
    custom_sources: list[dict] | None = None,
) -> tuple[dict | None, str]:
    """按源拉取 release；返回 (归一化 release, 可读错误信息)。"""
    source = resolve_source(source_id, custom_sources)
    if source is None:
        return None, f"未知的更新源：{source_id}"
    kind = str(source.get("kind") or "custom")
    name = str(source.get("name") or kind)

    if kind == "github":
        try:
            payload = _fetch_release()
        except Exception as exc:  # noqa: BLE001 - 后台线程不能崩
            return None, "GitHub 源检查失败：" + describe_error(exc)
        return _release_from_payload(payload, "GitHub")

    if kind == "gitlink":
        errors: list[str] = []
        latest = str(source.get("url") or GITLINK_LATEST)
        try:
            payload = _read_json(latest)
        except Exception as exc:  # noqa: BLE001
            errors.append("latest：" + describe_error(exc))
            payload = None
        if payload is not None:
            release, error = _release_from_payload(payload, "GitLink")
            if release is not None:
                return release, ""
            errors.append(error)
        fallback = str(source.get("fallbackUrl") or GITLINK_RELEASES)
        try:
            release, error = _release_from_payload(_read_json(fallback), "GitLink")
        except Exception as exc:  # noqa: BLE001
            errors.append("releases：" + describe_error(exc))
            release, error = None, ""
        if release is not None:
            return release, ""
        if error:
            errors.append(error)
        return None, "GitLink 源检查失败：" + ("；".join(errors) or "无响应")

    if kind == "gitee":
        try:
            payload = _read_json(str(source.get("url") or GITEE_LATEST))
        except Exception as exc:  # noqa: BLE001
            return None, "Gitee 源检查失败：" + describe_error(exc)
        return _release_from_payload(payload, "Gitee")

    # 自定义源
    url = str(source.get("url") or "").strip()
    if not is_valid_source_url(url):
        return None, f"{name} 的地址无效，需要 http/https 开头的 JSON API 地址"
    token = str(source.get("token") or "")
    try:
        payload = _read_json(url, token)
    except Exception as exc:  # noqa: BLE001
        return None, f"{name} 源检查失败：" + describe_error(exc)
    return _release_from_payload(payload, name)


def fetch_release(
    source_id: object = DEFAULT_SOURCE_ID,
    custom_sources: list[dict] | None = None,
) -> dict | None:
    """拉取指定源的 release（归一化后）；失败返回 None 并记录可读日志。"""
    release, error = fetch_release_detail(source_id, custom_sources)
    if error:
        logger.warning("获取更新源 %s 失败：%s", source_id, error)
    return release


# ---------- 检查更新 ----------
def check_latest_detail(
    current_version: str | None = None,
    source_id: object = None,
    custom_sources: list[dict] | None = None,
) -> tuple[dict | None, str]:
    """检查当前源最新版本；返回 (更新信息, 错误信息)，两者互斥。"""
    current = current_version or APP_VERSION
    source = resolve_source(source_id, custom_sources)
    if source is None:
        return None, f"未知的更新源：{source_id}"
    release, error = fetch_release_detail(source.get("id"), custom_sources)
    if error:
        logger.warning("检查更新失败：%s", error)
        return None, error
    if not release:
        return None, "更新源没有返回发布信息"
    tag = str(release.get("tag_name") or "").strip()
    version = tag[1:] if tag.lower().startswith("v") else tag
    if not version:
        return None, "发布信息缺少版本号"
    if not is_newer(version, current):
        return None, ""
    asset = select_asset(release.get("assets"))
    return {
        "version": version,
        "tag": tag,
        "notes": str(release.get("body") or ""),
        "pageUrl": str(release.get("html_url") or source.get("page") or RELEASES_PAGE),
        "assetName": str(asset.get("name") or "") if asset else "",
        "assetUrl": str(asset.get("browser_download_url") or "") if asset else "",
        "assetSize": int(asset.get("size") or 0) if asset else 0,
        "source": str(source.get("id") or ""),
        "sourceName": str(source.get("name") or ""),
    }, ""


def check_latest(
    current_version: str | None = None,
    source_id: object = None,
    custom_sources: list[dict] | None = None,
) -> dict | None:
    """检查最新版本；有更新返回信息 dict，否则/失败返回 None（兼容旧接口）。"""
    info, _error = check_latest_detail(current_version, source_id, custom_sources)
    return info


# ---------- 下载 ----------
def download(
    asset_url: str,
    dest_path: str | Path,
    on_progress: Callable[[int], None] | None = None,
    cancel: CancelToken | None = None,
) -> bool:
    """分块下载安装包到 dest_path；成功返回 True。可被 cancel 中途取消。"""
    url = str(asset_url or "").strip()
    if not url:
        return False
    dest = Path(dest_path)
    part = dest.with_name(dest.name + ".part")
    notified = -1

    def _progress(value: int) -> None:
        nonlocal notified
        if on_progress is None:
            return
        value = max(0, min(100, int(value)))
        if value == notified:
            return
        notified = value
        try:
            on_progress(value)
        except Exception as exc:  # noqa: BLE001 - 进度回调不能影响下载
            logger.warning("下载进度回调失败：%s", exc)

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            total = int(response.headers.get("Content-Length") or 0)
            received = 0
            _progress(0)
            with part.open("wb") as handle:
                while True:
                    if cancel is not None and cancel.cancelled:
                        handle.close()
                        _remove(part)
                        logger.info("更新下载已取消")
                        return False
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
                    received += len(chunk)
                    if total > 0:
                        _progress(received * 100 // total)
        if part.exists() and part.stat().st_size <= 0:
            _remove(part)
            return False
        part.replace(dest)
        _progress(100)
        return True
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning("下载更新失败：%s", exc)
        _remove(part)
        return False


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def release_page_url(fallback: str = "") -> str:
    return fallback or RELEASES_PAGE


def format_notes(notes: object, limit: int = 4000) -> str:
    text = str(notes or "").strip()
    return text[:limit]
