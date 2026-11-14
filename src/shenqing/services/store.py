"""v0.18 商店服务：目录拉取 / 内置兜底 / 评论审核 / 插件 zip 安装。

对外只提供可预期的结果或 `StoreError`（消息可直接展示给用户）：

- 目录：优先请求 settings 里的 `store_catalog_url`（6 秒超时），失败或为空时
  回退内置示例目录（6 个主题包 + 4 个插件）；成功结果缓存 10 分钟；
- 评论：本地演示审核，新评论一律 `pending`，只有 `approved` 对外展示；
- 插件：只接受 zip，校验 `plugin.json` 且清单 id 必须与商店条目一致，
  解压时拒绝路径穿越 / 绝对路径 / 符号链接，最终落到
  `%APPDATA%\\ShenQing\\plugins\\<id>`。
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from ..consts import APP_VERSION, GITHUB_REPO
from ..paths import app_data_dir
from ..plugins.api import ManifestError, PluginManifest

logger = logging.getLogger("shenqing.store")

#: 默认商店目录地址（仓库 store 分支的 catalog.json）；
#: settings 可覆盖，留空则只用内置目录。
DEFAULT_CATALOG_URL = (
    "https://raw.githubusercontent.com/Kryon2025/Clarity/store/catalog.json"
)
#: 远程目录超时（秒）
TIMEOUT_SECONDS = 6.0
#: 目录缓存时间（秒）
CACHE_TTL_SECONDS = 600.0
USER_AGENT = f"ShenQing/{APP_VERSION} (+https://github.com/{GITHUB_REPO})"

#: 自定义主题 palette 的必填键（顺序固定，方便前端拼接）
PALETTE_KEYS = ("bgTop", "bgMid", "bgBottom", "accent", "cardBg", "textPrimary")
#: 自定义主题数量上限
MAX_CUSTOM_THEMES = 20
#: 单条评论文本上限（字符）
MAX_COMMENT_TEXT = 500
#: 同一 item 的评论限流：窗口内最多若干条
COMMENT_RATE_LIMIT = 3
COMMENT_RATE_WINDOW_SECONDS = 60.0
#: 每个 item 最多保留的评论条数（避免 settings.json 无限膨胀）
MAX_COMMENTS_PER_ITEM = 200
#: 插件包解压限制
MAX_PLUGIN_FILES = 2000
MAX_PLUGIN_BYTES = 200 * 1024 * 1024

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_THEME_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")
_COMMENT_STATUSES = ("pending", "approved", "rejected")

__all__ = [
    "CACHE_TTL_SECONDS",
    "DEFAULT_CATALOG_URL",
    "MAX_CUSTOM_THEMES",
    "PALETTE_KEYS",
    "TIMEOUT_SECONDS",
    "CatalogService",
    "CommentService",
    "StoreError",
    "add_comment",
    "builtin_catalog",
    "default_plugins_dir",
    "download_file",
    "filter_items",
    "install_plugin_zip",
    "list_comments",
    "normalize_custom_theme",
    "normalize_custom_themes",
    "normalize_item",
    "normalize_palette",
    "normalize_theme_id",
    "palette_is_light",
    "parse_catalog",
    "set_comment_status",
    "validate_comment_input",
]


class StoreError(RuntimeError):
    """商店操作里的可预期错误（消息可直接展示给用户）。"""


def _format_timestamp(timestamp: float) -> str:
    """时间戳 -> ISO 字符串；Windows 对 1970 附近时间会报错，兜底用当前时间。"""
    try:
        return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return datetime.now().astimezone().isoformat(timespec="seconds")


# ================= 通用工具 =================
def describe_error(exc: BaseException) -> str:
    """把网络 / 解析异常转成可读中文提示（不含敏感信息）。"""
    if isinstance(exc, StoreError):
        return str(exc) or "商店操作失败"
    if isinstance(exc, urllib.error.HTTPError):
        code = int(getattr(exc, "code", 0) or 0)
        if code in (401, 403):
            return f"服务器拒绝访问（HTTP {code}）"
        if code == 404:
            return "商店目录不存在（HTTP 404）"
        return f"服务器返回 HTTP {code}"
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        return f"网络请求失败：{reason or exc}"
    if isinstance(exc, json.JSONDecodeError):
        return "商店目录不是有效的 JSON"
    if isinstance(exc, OSError):
        return f"网络或磁盘错误：{exc}"
    return str(exc) or "未知错误"


def is_hex_color(value: object) -> bool:
    """颜色必须是 #RRGGBB。"""
    return isinstance(value, str) and bool(_HEX_COLOR.fullmatch(value.strip()))


def normalize_palette(palette: object) -> dict:
    """校验并返回只有 6 个必填键的 palette；不合法抛 StoreError。"""
    if not isinstance(palette, Mapping):
        raise StoreError("主题配色必须是对象")
    missing = [key for key in PALETTE_KEYS if key not in palette]
    if missing:
        raise StoreError("主题配色缺少字段：" + "、".join(missing))
    result: dict[str, str] = {}
    for key in PALETTE_KEYS:
        value = palette.get(key)
        if not is_hex_color(value):
            raise StoreError(f"主题颜色 {key} 必须是 #RRGGBB 格式")
        result[key] = str(value).strip()
    return result


def normalize_theme_id(theme_id: object) -> str:
    """自定义主题 id：字母数字开头，只含字母数字点下划线短横线。"""
    text = str(theme_id or "").strip()
    if not text or not _THEME_ID.fullmatch(text) or ".." in text:
        raise StoreError("主题 id 只能包含字母、数字、点、下划线、短横线")
    return text


def normalize_custom_theme(theme_id: object, raw: object) -> dict | None:
    """归一化 settings 里的一条自定义主题；坏数据返回 None（跳过而不报错）。"""
    try:
        wanted = normalize_theme_id(theme_id)
    except StoreError:
        return None
    if not isinstance(raw, Mapping):
        return None
    try:
        palette = normalize_palette(raw.get("palette"))
    except StoreError:
        return None
    name = str(raw.get("name") or wanted).strip()[:40] or wanted
    description = str(raw.get("description") or "").strip()[:200]
    return {"id": wanted, "name": name, "description": description, "palette": palette}


def normalize_custom_themes(raw: object) -> dict[str, dict]:
    """把 settings["custom_themes"] 归一化成 {id: {id,name,description,palette}}。"""
    result: dict[str, dict] = {}
    if not isinstance(raw, Mapping):
        return result
    for key, value in raw.items():
        item = normalize_custom_theme(key, value)
        if item is not None:
            result[item["id"]] = item
    return result


def _channel_luminance(value: int) -> float:
    channel = max(0, min(255, int(value))) / 255.0
    if channel <= 0.03928:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def palette_is_light(palette: Mapping) -> bool:
    """粗判 palette 是否为浅色（用于窗口 chrome 选 Light/Dark）。"""
    try:
        color = str(palette.get("bgTop") or "").strip().lstrip("#")
        red, green, blue = (int(color[index : index + 2], 16) for index in (0, 2, 4))
    except (AttributeError, TypeError, ValueError):
        return False
    luminance = (
        0.2126 * _channel_luminance(red)
        + 0.7152 * _channel_luminance(green)
        + 0.0722 * _channel_luminance(blue)
    )
    return luminance > 0.5


# ================= 目录：远程 + 内置兜底 =================
def _as_rating(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(5.0, number)), 1)


def _as_downloads(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _as_text_list(value: object, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def normalize_item(raw: object) -> dict | None:
    """把远程 / 内置目录项归一化成统一字段；不合法返回 None。"""
    if not isinstance(raw, Mapping):
        return None
    item_id = str(raw.get("id") or "").strip()
    kind = str(raw.get("kind") or "").strip().lower()
    if not item_id or kind not in ("theme", "plugin"):
        return None
    if kind == "theme":
        try:
            palette = normalize_palette(raw.get("palette"))
        except StoreError:
            return None
    else:
        palette = {}
    download_url = str(raw.get("download_url") or "").strip() if kind == "plugin" else ""
    return {
        "id": item_id,
        "kind": kind,
        "name": str(raw.get("name") or item_id).strip()[:80] or item_id,
        "author": str(raw.get("author") or "").strip()[:60],
        "summary": str(raw.get("summary") or "").strip()[:200],
        "description": str(raw.get("description") or "").strip()[:2000],
        "version": str(raw.get("version") or "1.0.0").strip()[:32],
        "rating": _as_rating(raw.get("rating")),
        "downloads": _as_downloads(raw.get("downloads")),
        "tags": _as_text_list(raw.get("tags"), 10),
        "screenshots": _as_text_list(raw.get("screenshots"), 8),
        "download_url": download_url,
        "palette": palette,
        "published_at": str(raw.get("published_at") or "").strip()[:32],
    }


def parse_catalog(payload: object) -> list[dict]:
    """解析目录 JSON（顶层 list 或 {items:[...]}）；没有有效条目抛 StoreError。"""
    if isinstance(payload, Mapping):
        raw_items = payload.get("items")
    else:
        raw_items = payload
    if not isinstance(raw_items, list):
        raise StoreError("商店目录格式不正确：缺少 items 列表")
    items: list[dict] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = normalize_item(raw)
        if item is None or item["id"] in seen:
            continue
        seen.add(item["id"])
        items.append(item)
    if not items:
        raise StoreError("商店目录为空")
    return items


def _read_json(url: str) -> Any:
    """请求一个 JSON 地址；失败抛异常（调用方用 describe_error 转文案）。"""
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        payload = response.read().decode("utf-8", errors="replace")
    return json.loads(payload)


def load_catalog(url: str) -> list[dict]:
    """拉取并解析远程目录；失败抛异常。"""
    return parse_catalog(_read_json(url))


def _builtin_theme(
    item_id: str,
    name: str,
    author: str,
    summary: str,
    description: str,
    palette: dict,
    rating: float,
    downloads: int,
    tags: list[str],
    published_at: str,
) -> dict:
    return {
        "id": item_id,
        "kind": "theme",
        "name": name,
        "author": author,
        "summary": summary,
        "description": description,
        "version": "1.0.0",
        "rating": rating,
        "downloads": downloads,
        "tags": tags,
        "screenshots": [],
        "download_url": "",
        "palette": palette,
        "published_at": published_at,
    }


def _builtin_plugin(
    item_id: str,
    name: str,
    author: str,
    summary: str,
    description: str,
    rating: float,
    downloads: int,
    tags: list[str],
    published_at: str,
) -> dict:
    return {
        "id": item_id,
        "kind": "plugin",
        "name": name,
        "author": author,
        "summary": summary,
        "description": description,
        "version": "1.0.0",
        "rating": rating,
        "downloads": downloads,
        "tags": tags,
        "screenshots": [],
        "download_url": (
            "https://raw.githubusercontent.com/Kryon2025/Clarity/store/plugins/"
            f"{item_id}.zip"
        ),
        "palette": {},
        "published_at": published_at,
    }


def builtin_catalog() -> list[dict]:
    """内置示例目录：6 个主题包 + 4 个插件（远程不可用时的兜底）。"""
    raw_items: list[dict] = [
        _builtin_theme(
            "theme-aurora",
            "极光",
            "Clarity Studio",
            "青绿极光掠过深夜海面",
            "以深海为底、极光青绿为强调色的深色主题包，适合夜间专注。",
            {
                "bgTop": "#0A1F2E",
                "bgMid": "#06202C",
                "bgBottom": "#04121A",
                "accent": "#35E0C8",
                "cardBg": "#0D2634",
                "textPrimary": "#EAF8FC",
            },
            4.8,
            12840,
            ["深色", "青绿", "夜间"],
            "2025-10-02",
        ),
        _builtin_theme(
            "theme-sakura",
            "樱雾",
            "Aki",
            "淡粉雾气里的安静书桌",
            "低饱和樱粉浅色主题，配深莓强调色，白天的清空间会更柔和。",
            {
                "bgTop": "#F6EEF1",
                "bgMid": "#F1E3E9",
                "bgBottom": "#E9D6DE",
                "accent": "#D46A8C",
                "cardBg": "#FFFFFF",
                "textPrimary": "#3A2230",
            },
            4.6,
            9360,
            ["浅色", "樱粉", "温柔"],
            "2025-09-18",
        ),
        _builtin_theme(
            "theme-forest",
            "苔原",
            "青苔",
            "安静生长的深林绿",
            "以苔绿与松针色构成的深色主题，长时间盯屏幕也不刺眼。",
            {
                "bgTop": "#0C1F16",
                "bgMid": "#0A291C",
                "bgBottom": "#07170F",
                "accent": "#6FD8A0",
                "cardBg": "#103024",
                "textPrimary": "#E9F7EF",
            },
            4.5,
            7710,
            ["深色", "自然", "护眼"],
            "2025-08-30",
        ),
        _builtin_theme(
            "theme-mono",
            "墨白",
            "Norr",
            "只有黑白灰的极简空间",
            "去掉彩色干扰的墨白浅色主题，强调色仍是近黑，适合写作阅读。",
            {
                "bgTop": "#F7F7F5",
                "bgMid": "#EFEFEB",
                "bgBottom": "#E6E6E0",
                "accent": "#2B2B2B",
                "cardBg": "#FFFFFF",
                "textPrimary": "#1B1B1B",
            },
            4.3,
            5620,
            ["浅色", "极简", "写作"],
            "2025-08-12",
        ),
        _builtin_theme(
            "theme-sunset",
            "暮橘",
            "Haru",
            "黄昏落在桌面的一角",
            "暮色酒红与暖橘强调色，给夜晚的专注一点温度。",
            {
                "bgTop": "#2C1420",
                "bgMid": "#3A1A1E",
                "bgBottom": "#1A0B12",
                "accent": "#FF9E64",
                "cardBg": "#3A1C24",
                "textPrimary": "#FFE9DC",
            },
            4.7,
            11050,
            ["深色", "暖色", "黄昏"],
            "2025-09-01",
        ),
        _builtin_theme(
            "theme-cyber",
            "霓虹夜",
            "Nova",
            "霓虹紫在电路板上呼吸",
            "高对比霓虹紫主题包，配合深紫卡片，适合喜欢赛博感的用户。",
            {
                "bgTop": "#0B0B1A",
                "bgMid": "#14102B",
                "bgBottom": "#07060F",
                "accent": "#B45CFF",
                "cardBg": "#171330",
                "textPrimary": "#EDE6FF",
            },
            4.4,
            6890,
            ["深色", "赛博", "紫色"],
            "2025-10-11",
        ),
        _builtin_plugin(
            "pomodoro-plus",
            "清番增强",
            "社区",
            "更细的番茄钟节奏与统计",
            "增加长休息提示、今日完成轮次与周统计，数据保存在插件目录。",
            4.6,
            8450,
            ["专注", "统计", "番茄钟"],
            "2025-09-22",
        ),
        _builtin_plugin(
            "muyu",
            "木鱼",
            "社区",
            "敲一下，功德加一",
            "遮罩右下角的小木鱼，点击有敲击动画与功德计数，专注时放松一下。",
            4.9,
            15230,
            ["趣味", "遮罩组件", "解压"],
            "2025-10-05",
        ),
        _builtin_plugin(
            "water-reminder",
            "喝水提醒",
            "社区",
            "按时提醒你补充水分",
            "专注期间定时弹出轻提示，最多每小时一次，不打断锁定流程。",
            4.2,
            4980,
            ["健康", "提醒"],
            "2025-08-20",
        ),
        _builtin_plugin(
            "media-island",
            "媒体岛增强",
            "社区",
            "把正在播放的歌放得更显眼",
            "遮罩顶部增加媒体信息与音量入口，支持常见播放器的 SMTC 信息。",
            4.5,
            7030,
            ["媒体", "遮罩组件"],
            "2025-09-10",
        ),
    ]
    result: list[dict] = []
    for raw in raw_items:
        item = normalize_item(raw)
        if item is not None:  # 内置数据一定合法，这里只是统一字段
            result.append(item)
    return result


def filter_items(items: list[dict], kind: str = "", sort: str = "") -> list[dict]:
    """按 kind 过滤、按 sort 排序；未知 kind 返回 []，未知 sort 保持原顺序。"""
    kind_text = str(kind or "").strip().lower()
    result = [
        copy.deepcopy(item)
        for item in items
        if kind_text in ("", "all") or str(item.get("kind")) == kind_text
    ]
    sort_text = str(sort or "").strip().lower()
    if sort_text in ("rating", "rating_desc"):
        result.sort(
            key=lambda item: (
                -float(item.get("rating") or 0.0),
                -int(item.get("downloads") or 0),
                str(item.get("name") or ""),
            )
        )
    elif sort_text in ("downloads", "popular", "downloads_desc"):
        result.sort(
            key=lambda item: (
                -int(item.get("downloads") or 0),
                -float(item.get("rating") or 0.0),
                str(item.get("name") or ""),
            )
        )
    elif sort_text in ("newest", "published", "published_at"):
        result.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
    elif sort_text == "name":
        result.sort(key=lambda item: str(item.get("name") or "").casefold())
    return result


class CatalogService:
    """商店目录：缓存 + 远程失败回退内置目录。"""

    def __init__(
        self,
        settings: Any,
        *,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._now = now or time.time
        self._items: list[dict] = []
        self._status = "builtin"
        self._error = ""
        self._fetched_at = 0.0

    @property
    def status(self) -> str:
        """online / builtin / error:<原因>。"""
        return self._status

    @property
    def error(self) -> str:
        """最近一次远程目录失败原因（空 = 无错误）。"""
        return self._error

    def _url(self) -> str:
        value = self._settings.get("store_catalog_url", DEFAULT_CATALOG_URL)
        return str(value or "").strip()

    def _cache_valid(self) -> bool:
        return bool(self._items) and (self._now() - self._fetched_at) < CACHE_TTL_SECONDS

    def ensure(self) -> None:
        """必要时加载目录（缓存 10 分钟）。"""
        if self._cache_valid():
            return
        self.reload()

    def refresh(self) -> str:
        """强制重新拉取目录，返回最新状态。"""
        self._items = []
        self._fetched_at = 0.0
        self.reload()
        return self._status

    def reload(self) -> None:
        url = self._url()
        self._fetched_at = self._now()
        if not url:
            self._items = builtin_catalog()
            self._status = "builtin"
            self._error = ""
            return
        try:
            items = load_catalog(url)
        except Exception as exc:  # noqa: BLE001 - 任何远程失败都回退内置目录
            self._error = describe_error(exc)
            self._items = builtin_catalog()
            self._status = "error:" + self._error
            logger.warning("商店目录拉取失败，使用内置目录：%s", self._error)
            return
        self._items = items
        self._status = "online"
        self._error = ""

    def items(self) -> list[dict]:
        self.ensure()
        return copy.deepcopy(self._items)

    def get(self, item_id: object) -> dict | None:
        wanted = str(item_id or "").strip()
        if not wanted:
            return None
        self.ensure()
        for item in self._items:
            if str(item.get("id")) == wanted:
                return copy.deepcopy(item)
        return None

    def has(self, item_id: object) -> bool:
        return self.get(item_id) is not None


# ================= 评论与本地审核演示 =================
def _item_key(item_id: object) -> str:
    return str(item_id or "").strip()


def normalize_comment(raw: object) -> dict | None:
    """归一化一条已存评论；字段不合法返回 None。"""
    if not isinstance(raw, Mapping):
        return None
    text = str(raw.get("text") or "").strip()
    if not text:
        return None
    try:
        rating = int(raw.get("rating"))
    except (TypeError, ValueError):
        return None
    if not 1 <= rating <= 5:
        return None
    status = str(raw.get("status") or "pending").strip().lower()
    if status not in _COMMENT_STATUSES:
        status = "pending"
    return {
        "id": str(raw.get("id") or ""),
        "author": str(raw.get("author") or "匿名").strip()[:40] or "匿名",
        "rating": rating,
        "text": text[:MAX_COMMENT_TEXT],
        "created_at": str(raw.get("created_at") or ""),
        "status": status,
    }


def _read_comment_map(settings: Any) -> dict:
    raw = settings.get("store_comments", {})
    return copy.deepcopy(dict(raw)) if isinstance(raw, Mapping) else {}


def list_comments(settings: Any, item_id: object) -> dict:
    """返回 {comments:[approved...], pendingCount:int}。"""
    wanted = _item_key(item_id)
    approved: list[dict] = []
    pending = 0
    if not wanted:
        return {"comments": approved, "pendingCount": pending}
    for raw in _read_comment_map(settings).get(wanted, []):
        comment = normalize_comment(raw)
        if comment is None:
            continue
        if comment["status"] == "approved":
            approved.append(comment)
        elif comment["status"] == "pending":
            pending += 1
    approved.sort(key=lambda comment: comment["created_at"], reverse=True)
    return {"comments": approved, "pendingCount": pending}


def set_comment_status(settings: Any, item_id: object, comment_id: object, status: str) -> bool:
    """审核演示：把一条评论改成 approved / rejected。"""
    if status not in ("approved", "rejected"):
        return False
    wanted = _item_key(item_id)
    cid = str(comment_id or "").strip()
    if not wanted or not cid:
        return False
    store_map = _read_comment_map(settings)
    entries = store_map.get(wanted)
    if not isinstance(entries, list):
        return False
    changed = False
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("id") or "") == cid:
            entry["status"] = status
            changed = True
            break
    if changed:
        settings.set("store_comments", store_map)
    return changed


def validate_comment_input(rating: object, text: object) -> tuple[int, str]:
    """校验评分 / 正文，返回 (1-5 星, 去空白正文)；不合法抛 StoreError。"""
    try:
        value = int(rating)
    except (TypeError, ValueError):
        raise StoreError("评分必须是 1-5 星") from None
    if not 1 <= value <= 5:
        raise StoreError("评分必须是 1-5 星")
    body = str(text or "").strip()
    if not body:
        raise StoreError("评论内容不能为空")
    if len(body) > MAX_COMMENT_TEXT:
        raise StoreError(f"评论最多 {MAX_COMMENT_TEXT} 字")
    return value, body


def add_comment(
    settings: Any,
    item_id: object,
    rating: object,
    text: object,
    *,
    author: str = "我",
    now: float | None = None,
) -> dict:
    """写入一条 pending 评论（不做限流；限流在 CommentService 里）。"""
    wanted = _item_key(item_id)
    if not wanted:
        raise StoreError("缺少商店条目 id")
    value, body = validate_comment_input(rating, text)
    timestamp = float(now if now is not None else time.time())
    created_at = _format_timestamp(timestamp)
    comment = {
        "id": "c-" + uuid.uuid4().hex[:10],
        "author": str(author or "我").strip()[:40] or "我",
        "rating": value,
        "text": body,
        "created_at": created_at,
        "status": "pending",
    }
    store_map = _read_comment_map(settings)
    entries = store_map.get(wanted)
    entries = list(entries) if isinstance(entries, list) else []
    entries.append(comment)
    del entries[:-MAX_COMMENTS_PER_ITEM]
    store_map[wanted] = entries
    settings.set("store_comments", store_map)
    return dict(comment)


class CommentService:
    """商店评论：pending 审核 + 同一 item 每分钟 3 条限流。"""

    def __init__(
        self,
        settings: Any,
        *,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._now = now or time.time
        self._hits: dict[str, deque[float]] = {}

    def list(self, item_id: object) -> dict:
        return list_comments(self._settings, item_id)

    def _check_rate_limit(self, item_id: str) -> float:
        timestamp = float(self._now())
        hits = self._hits.setdefault(item_id, deque())
        while hits and timestamp - hits[0] >= COMMENT_RATE_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= COMMENT_RATE_LIMIT:
            raise StoreError(
                f"评论太频繁，同一项目每分钟最多 {COMMENT_RATE_LIMIT} 条"
            )
        hits.append(timestamp)
        return timestamp

    def add(
        self,
        item_id: object,
        rating: object,
        text: object,
        *,
        author: str = "我",
    ) -> dict:
        wanted = _item_key(item_id)
        if not wanted:
            raise StoreError("缺少商店条目 id")
        # 先校验内容，非法提交不占用每分钟 3 条的额度
        validate_comment_input(rating, text)
        timestamp = self._check_rate_limit(wanted)
        return add_comment(
            self._settings, wanted, rating, text, author=author, now=timestamp
        )

    def set_status(self, item_id: object, comment_id: object, status: str) -> bool:
        return set_comment_status(self._settings, item_id, comment_id, status)

    def approve(self, item_id: object, comment_id: object) -> bool:
        return self.set_status(item_id, comment_id, "approved")

    def reject(self, item_id: object, comment_id: object) -> bool:
        return self.set_status(item_id, comment_id, "rejected")


# ================= 插件 zip 安装 =================
def default_plugins_dir() -> Path:
    """用户插件目录：SHENQING_PLUGINS_DIR 优先，否则 %APPDATA%\\ShenQing\\plugins。"""
    raw = os.environ.get("SHENQING_PLUGINS_DIR", "").strip()
    if raw:
        first = next((part for part in raw.split(os.pathsep) if part.strip()), "")
        if first:
            return Path(first)
    return app_data_dir() / "plugins"


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def download_file(url: object, dest: object) -> Path:
    """把 http(s)/file 地址（或本地路径）下载到 dest；失败抛 StoreError。"""
    text = str(url or "").strip()
    if not text:
        raise StoreError("插件下载地址为空")
    target = Path(str(dest))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StoreError(f"无法创建临时目录：{exc}") from exc
    local: Path | None = None
    try:
        candidate = Path(text)
        if candidate.is_file():
            local = candidate
    except OSError:  # pragma: no cover - 非法路径字符
        local = None
    if local is not None:
        try:
            shutil.copyfile(local, target)
        except OSError as exc:
            raise StoreError(f"读取插件包失败：{exc}") from exc
        return target
    scheme = urllib.parse.urlsplit(text).scheme.lower()
    if scheme not in ("http", "https", "file"):
        raise StoreError("插件下载地址必须是 http/https 链接")
    try:
        request = urllib.request.Request(text, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            with target.open("wb") as handle:
                shutil.copyfileobj(response, handle)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _remove_file(target)
        raise StoreError(f"下载插件失败：{describe_error(exc)}") from exc
    if target.stat().st_size <= 0:
        _remove_file(target)
        raise StoreError("下载的插件包为空")
    return target


def _member_parts(name: object) -> list[str] | None:
    """把 zip 成员名拆成安全路径分段；目录返回 None，非法抛 StoreError。"""
    text = str(name or "").replace("\\", "/").strip()
    if not text or text.endswith("/"):
        return None
    if text.startswith("/") or _DRIVE_PATTERN.match(text):
        raise StoreError("插件包包含绝对路径，已拒绝安装")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts:
        return None
    if any(part == ".." for part in parts):
        raise StoreError("插件包包含非法路径（..），已拒绝安装")
    if any(":" in part for part in parts):
        raise StoreError("插件包包含非法文件名，已拒绝安装")
    return parts


def _select_members(
    archive: zipfile.ZipFile,
) -> list[tuple[zipfile.ZipInfo, list[str]]]:
    """选出可解压成员（按 plugin.json 所在目录剥掉可选的顶层目录）。"""
    validated: list[tuple[zipfile.ZipInfo, list[str]]] = []
    for info in archive.infolist():
        parts = _member_parts(info.filename)
        if parts is not None:
            validated.append((info, parts))
    manifest_parts: list[str] | None = None
    for _info, parts in validated:
        if parts[-1] == "plugin.json":
            if len(parts) <= 2 and (manifest_parts is None or len(parts) < len(manifest_parts)):
                manifest_parts = parts
    if manifest_parts is None:
        raise StoreError("插件包内缺少 plugin.json")
    prefix = manifest_parts[:-1]
    selected: list[tuple[zipfile.ZipInfo, list[str]]] = []
    total_bytes = 0
    for info, parts in validated:
        if len(parts) <= len(prefix) or parts[: len(prefix)] != prefix:
            continue
        relative = parts[len(prefix) :]
        if not relative:
            continue
        marker = info.external_attr >> 16
        if (marker & 0o170000) == 0o120000:
            raise StoreError("插件包包含符号链接，已拒绝安装")
        total_bytes += max(0, int(info.file_size or 0))
        selected.append((info, relative))
        if len(selected) > MAX_PLUGIN_FILES:
            raise StoreError("插件包文件数量过多，已拒绝安装")
    if not selected:
        raise StoreError("插件包为空")
    if total_bytes > MAX_PLUGIN_BYTES:
        raise StoreError("插件包解压后体积过大，已拒绝安装")
    return selected


def _extract_selected(
    archive: zipfile.ZipFile,
    selected: list[tuple[zipfile.ZipInfo, list[str]]],
    dest: Path,
) -> None:
    dest_resolved = dest.resolve()
    for info, relative in selected:
        target = dest.joinpath(*relative)
        resolved = target.resolve()
        if resolved != dest_resolved and dest_resolved not in resolved.parents:
            raise StoreError("插件包路径越界，已拒绝安装")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)
        except StoreError:
            raise
        except Exception as exc:  # noqa: BLE001 - 解压异常统一转可读文案
            raise StoreError(f"解压插件包失败：{exc}") from exc


def _replace_plugin_dir(root: Path, plugin_id: str, staging: Path) -> Path:
    dest = root / plugin_id
    try:
        if dest.is_dir():
            shutil.rmtree(dest)
        elif dest.exists():
            dest.unlink()
        staging.rename(dest)
    except OSError as exc:
        raise StoreError(f"写入插件目录失败：{exc}") from exc
    return dest


def install_plugin_zip(
    zip_path: object,
    expected_id: object,
    plugins_dir: object | None = None,
) -> Path:
    """把插件 zip 安装到插件目录并返回目标目录；任何问题抛 StoreError。"""
    expected = str(expected_id or "").strip()
    if not expected:
        raise StoreError("插件条目缺少 id")
    source = Path(str(zip_path))
    if not source.is_file():
        raise StoreError("插件包不存在")
    root = Path(str(plugins_dir)) if plugins_dir else default_plugins_dir()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StoreError(f"无法创建插件目录：{exc}") from exc
    # 清理上次安装中断留下的临时目录，避免插件管理器把它当成插件加载
    for stale in root.glob(".install-*"):
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as exc:
        raise StoreError(f"插件包不是有效的 zip 文件：{exc}") from exc
    staging: Path | None = None
    try:
        selected = _select_members(archive)
        try:
            staging = Path(tempfile.mkdtemp(prefix=".install-", dir=str(root)))
        except OSError as exc:
            raise StoreError(f"无法创建临时目录：{exc}") from exc
        _extract_selected(archive, selected, staging)
        manifest_path = staging / "plugin.json"
        try:
            manifest = PluginManifest.from_file(manifest_path)
        except ManifestError as exc:
            raise StoreError(f"插件清单无效：{exc}") from exc
        if manifest.id != expected:
            raise StoreError(
                f"插件 id 不匹配：商店条目为 {expected}，插件包内为 {manifest.id}"
            )
        entry = (staging / manifest.entry).resolve()
        staging_resolved = staging.resolve()
        if entry != staging_resolved and staging_resolved not in entry.parents:
            raise StoreError("插件入口路径越界，已拒绝安装")
        if not entry.is_file():
            raise StoreError(f"插件入口文件不存在：{manifest.entry}")
        target = _replace_plugin_dir(root, manifest.id, staging)
        staging = None  # 目录已移交，finally 不再清理
        return target
    finally:
        archive.close()
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
