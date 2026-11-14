"""右侧组件（Overlay Widgets，v0.21）：布局规范化 + 天气 / 每日一言数据。

参考 Class Widgets 2 的组件形态：桌面右侧一列卡片式小组件，位置 / 大小可调。
深清内置 6 种组件，用户在「组件预览」里自定义右半屏显示内容。

- 坐标系：**右半屏自身** 0~1（x 向右、y 向下），与屏幕分辨率无关；
- 布局项：{id, type, x, y, w, h, visible, props}；
- 布局函数全部是纯函数（输入 list → 返回新 list，不改入参），便于单元测试；
- fetch_weather()：中央气象台 NMC 接口，15 分钟缓存，失败返回可读错误；
- fetch_quote()：优先在线 hitokoto，失败回退 consts.QUOTES 随机，按天缓存。
"""

from __future__ import annotations

import copy
import json
import logging
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Any, Mapping

from ..consts import OVERLAY_WIDGET_DEFAULT_LAYOUT, QUOTES

logger = logging.getLogger("shenqing.widgets")

#: 右半屏最多放多少个组件
MAX_WIDGETS = 12
#: 组件宽 / 高最小值、最大值（归一化）
MIN_WIDGET_SIZE = 0.12
MAX_WIDGET_SIZE = 1.0
#: 新组件纵向堆叠的起点与间距
STACK_TOP = 0.04
STACK_GAP = 0.02

#: 天气默认城市编号（中央气象台站点：58362 = 北京）
DEFAULT_WEATHER_CITY = "58362"
NMC_WEATHER_URL = "http://www.nmc.cn/rest/weather?stationid={station}"
WEATHER_HTTP_TIMEOUT = 8
#: 天气结果缓存时长（秒）
WEATHER_CACHE_SECONDS = 15 * 60

HITOKOTO_URL = "https://v1.hitokoto.cn/?c=d&c=i&encode=json"
HITOKOTO_CATEGORY_URL = "https://v1.hitokoto.cn/?c={category}&encode=json"
QUOTE_HTTP_TIMEOUT = 6
QUOTE_MAX_CHARS = 120
#: hitokoto 支持的分类字母（a~k）
QUOTE_CATEGORIES = ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k")

USER_AGENT = "ShenQing-Widgets/0.21"

#: 内置组件目录：type / 名称 / 说明 / 默认大小（右半屏比例）/ 可配置项
BUILTIN_WIDGETS: list[dict] = [
    {
        "type": "clock",
        "name": "时钟",
        "desc": "当前时间与日期",
        "defaultSize": {"w": 0.88, "h": 0.20},
        "propsSchema": [
            {
                "key": "format",
                "label": "时间格式",
                "type": "select",
                "default": "24h",
                "options": [
                    {"value": "24h", "label": "24 小时"},
                    {"value": "12h", "label": "12 小时"},
                ],
            },
            {"key": "showSeconds", "label": "显示秒", "type": "switch", "default": False},
        ],
    },
    {
        "type": "countdown",
        "name": "专注倒计时",
        "desc": "本次专注的剩余时间",
        "defaultSize": {"w": 0.88, "h": 0.22},
        "propsSchema": [
            {
                "key": "mode",
                "label": "数据来源",
                "type": "select",
                "default": "session",
                "options": [
                    {"value": "session", "label": "当前专注"},
                    {"value": "pomodoro", "label": "清番"},
                ],
            }
        ],
    },
    {
        "type": "today",
        "name": "今日专注",
        "desc": "今天的专注时长与次数",
        "defaultSize": {"w": 0.88, "h": 0.22},
        "propsSchema": [
            {"key": "showMinutes", "label": "显示时长", "type": "switch", "default": True},
            {"key": "showCount", "label": "显示次数", "type": "switch", "default": True},
        ],
    },
    {
        "type": "streak",
        "name": "连续打卡",
        "desc": "连续专注天数",
        "defaultSize": {"w": 0.44, "h": 0.18},
        "propsSchema": [
            {"key": "showBest", "label": "显示最佳记录", "type": "switch", "default": False}
        ],
    },
    {
        "type": "quote",
        "name": "每日一言",
        "desc": "每天一句值得读的话",
        "defaultSize": {"w": 0.88, "h": 0.16},
        "propsSchema": [
            {
                "key": "category",
                "label": "分类",
                "type": "select",
                "default": "d",
                "options": [
                    {"value": "d", "label": "文学"},
                    {"value": "i", "label": "诗词"},
                    {"value": "k", "label": "哲学"},
                ],
            },
            {"key": "showSource", "label": "显示出处", "type": "switch", "default": True},
        ],
    },
    {
        "type": "weather",
        "name": "天气",
        "desc": "城市实时天气",
        "defaultSize": {"w": 0.88, "h": 0.18},
        "propsSchema": [
            {"key": "cityId", "label": "城市编号", "type": "text", "default": DEFAULT_WEATHER_CITY},
            {"key": "showCity", "label": "显示城市名", "type": "switch", "default": True},
        ],
    },
]

_WIDGET_TYPES: dict[str, dict] = {item["type"]: item for item in BUILTIN_WIDGETS}

#: 天气缓存：station -> (取到的时间戳, 结果)
_WEATHER_CACHE: dict[str, tuple[float, dict]] = {}
#: 一言缓存：day|category -> 结果（当天只拉一次，失败的回退结果也缓存）
_QUOTE_CACHE: dict[str, dict] = {}


# ================= 组件目录 =================
def widget_types() -> list[str]:
    """内置组件 type 列表（顺序同 BUILTIN_WIDGETS）。"""
    return [item["type"] for item in BUILTIN_WIDGETS]


def widget_catalog() -> list[dict]:
    """组件目录深拷贝（供 Bridge 暴露给 QML，避免外部改动内置定义）。"""
    return copy.deepcopy(BUILTIN_WIDGETS)


def widget_meta(widget_type: str) -> dict:
    """单个组件的目录项；未知 type 返回空 dict。"""
    return copy.deepcopy(_WIDGET_TYPES.get(str(widget_type or "").strip().lower(), {}))


# ================= 布局规范化 =================
def _as_float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return float(default)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return float(default)
    return number


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "on", "yes"):
            return True
        if text in ("0", "false", "off", "no"):
            return False
    return bool(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _clamp_size(value: Any) -> float:
    return _clamp(_as_float(value, MIN_WIDGET_SIZE), MIN_WIDGET_SIZE, MAX_WIDGET_SIZE)


def _clamp_axis(value: Any) -> float:
    return _clamp(_as_float(value, 0.0), 0.0, 1.0)


def _coerce_prop(schema: Mapping, value: Any) -> Any:
    """按 propsSchema 把用户值收敛成安全值（类型不对就用默认值）。"""
    kind = str(schema.get("type") or "text")
    default = schema.get("default")
    if kind == "switch":
        return _as_bool(value, bool(default))
    if kind == "number":
        number = _as_float(value, _as_float(default, 0.0))
        low = schema.get("min")
        high = schema.get("max")
        if isinstance(low, (int, float)) and not isinstance(low, bool):
            number = max(float(low), number)
        if isinstance(high, (int, float)) and not isinstance(high, bool):
            number = min(float(high), number)
        if isinstance(default, int) and not isinstance(default, bool):
            return int(round(number))
        return number
    if kind == "select":
        options = schema.get("options") or []
        allowed = {str(item.get("value")) for item in options if isinstance(item, Mapping)}
        text = str(value).strip() if value is not None else ""
        if text in allowed:
            return text
        return str(default) if default is not None else (next(iter(allowed), ""))
    text = str(value).strip() if value is not None else ""
    return text[:120] if text else (str(default) if default is not None else "")


def _normalize_props(widget_type: str, props: Any) -> dict:
    meta = _WIDGET_TYPES.get(widget_type, {})
    source = props if isinstance(props, Mapping) else {}
    result: dict[str, Any] = {}
    for schema in meta.get("propsSchema", []):
        key = str(schema.get("key") or "")
        if not key:
            continue
        result[key] = _coerce_prop(schema, source.get(key, schema.get("default")))
    return result


def _normalize_item(raw: Mapping) -> dict | None:
    """单个布局项 → 规范化 dict；非法（未知 type 等）返回 None。"""
    widget_type = str(raw.get("type") or "").strip().lower()
    meta = _WIDGET_TYPES.get(widget_type)
    if meta is None:
        return None
    default = meta.get("defaultSize") or {"w": 0.88, "h": 0.2}
    width = _clamp_size(raw.get("w", default["w"]))
    height = _clamp_size(raw.get("h", default["h"]))
    x = _clamp_axis(raw.get("x", 0.0))
    y = _clamp_axis(raw.get("y", 0.0))
    # 自动收敛：保证 x+w <= 1、y+h <= 1（贴边而不是丢弃）
    if x + width > 1.0:
        x = max(0.0, 1.0 - width)
    if y + height > 1.0:
        y = max(0.0, 1.0 - height)
    raw_id = raw.get("id")
    widget_id = raw_id.strip() if isinstance(raw_id, str) else ""
    return {
        "id": widget_id,
        "type": widget_type,
        "x": round(x, 4),
        "y": round(y, 4),
        "w": round(width, 4),
        "h": round(height, 4),
        "visible": _as_bool(raw.get("visible"), True),
        "props": _normalize_props(widget_type, raw.get("props")),
    }


def _unique_id(widget_type: str, used: set[str]) -> str:
    index = 1
    while f"{widget_type}-{index}" in used:
        index += 1
    return f"{widget_type}-{index}"


def normalize_layout(layout: Any) -> list[dict]:
    """规范化布局：丢弃非法条目、去重、夹紧边界、限制个数。

    - 非 dict / 未知 type → 丢弃；
    - 同 id 保留第一个；缺 id（或 id 不是字符串）自动补 `type-n`；
    - w/h 夹到 [0.12, 1.0]，x/y 夹到 [0, 1]，并自动收敛保证不越界；
    - 最多 `MAX_WIDGETS` 个，多出的丢弃（重叠不做处理）。
    """
    if not isinstance(layout, (list, tuple)):
        return []
    items = [item for item in layout if isinstance(item, Mapping)]
    explicit = {
        str(item.get("id")).strip()
        for item in items
        if isinstance(item.get("id"), str) and str(item.get("id")).strip()
    }
    result: list[dict] = []
    used: set[str] = set()
    for raw in items:
        if len(result) >= MAX_WIDGETS:
            break
        item = _normalize_item(raw)
        if item is None:
            continue
        widget_id = item["id"]
        if not widget_id:
            widget_id = _unique_id(item["type"], used | explicit)
            item["id"] = widget_id
        if widget_id in used:
            continue
        used.add(widget_id)
        result.append(item)
    return result


def default_layout() -> list[dict]:
    """内置默认布局：clock / today / quote 三张卡。"""
    return normalize_layout(copy.deepcopy(OVERLAY_WIDGET_DEFAULT_LAYOUT))


def add_widget(layout: Any, widget_type: str) -> list[dict]:
    """加一个组件（贴在现有卡片下方）；未知 type / 已满 12 个时原样返回。"""
    current = normalize_layout(layout)
    kind = str(widget_type or "").strip().lower()
    meta = _WIDGET_TYPES.get(kind)
    if meta is None or len(current) >= MAX_WIDGETS:
        return current
    used = {item["id"] for item in current}
    default = meta.get("defaultSize") or {"w": 0.88, "h": 0.2}
    width = _clamp_size(default["w"])
    height = _clamp_size(default["h"])
    bottom = max((item["y"] + item["h"] for item in current), default=0.0)
    y = STACK_TOP if not current else bottom + STACK_GAP
    if y + height > 1.0:
        y = max(0.0, 1.0 - height)
    current.append(
        {
            "id": _unique_id(kind, used),
            "type": kind,
            "x": round(max(0.0, (1.0 - width) / 2), 4),
            "y": round(y, 4),
            "w": round(width, 4),
            "h": round(height, 4),
            "visible": True,
            "props": _normalize_props(kind, {}),
        }
    )
    return normalize_layout(current)


def remove_widget(layout: Any, widget_id: str) -> list[dict]:
    """删掉指定 id 的组件（不存在则原样返回规范化结果）。"""
    current = normalize_layout(layout)
    target = str(widget_id or "").strip()
    if not target:
        return current
    return [item for item in current if item["id"] != target]


def update_widget(layout: Any, widget_id: str, patch: Any) -> list[dict]:
    """局部更新一个组件：x / y / w / h / visible / props（props 浅合并）。

    type 与 id 不可改（换组件请 remove + add）；id 不存在或 patch 非法时原样返回。
    """
    current = normalize_layout(layout)
    target = str(widget_id or "").strip()
    if not target or not isinstance(patch, Mapping):
        return current
    for index, item in enumerate(current):
        if item["id"] != target:
            continue
        merged = dict(item)
        for key in ("x", "y", "w", "h", "visible"):
            if key in patch:
                merged[key] = patch[key]
        props = patch.get("props")
        if isinstance(props, Mapping):
            merged["props"] = {**item["props"], **props}
        current[index] = merged
        return normalize_layout(current)
    return current


def reset_layout() -> list[dict]:
    """恢复内置默认布局。"""
    return default_layout()


# ================= 天气（中央气象台 NMC） =================
def _http_json(url: str, timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        raw = response.read()
    return json.loads(raw.decode("utf-8", errors="replace"))


def _readable_error(exc: BaseException, what: str) -> str:
    """把网络/解析异常翻成人话（QML 直接展示）。"""
    if isinstance(exc, urllib.error.HTTPError):
        return f"{what}接口返回 HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None) or exc
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return f"{what}服务超时"
        return f"{what}网络连接失败：{reason}"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return f"{what}服务超时"
    if isinstance(exc, json.JSONDecodeError):
        return f"{what}数据解析失败"
    if isinstance(exc, ValueError):
        return f"{what}数据异常：{exc}"
    return f"{what}获取失败：{exc}"


def _deep_first(data: Any, key: str) -> Any:
    """在嵌套 dict / list 里 BFS 找第一个非空 key 的值（NMC 结构有多个版本）。"""
    queue: list[Any] = [data]
    while queue:
        node = queue.pop(0)
        if isinstance(node, Mapping):
            value = node.get(key)
            if value not in (None, "", [], {}):
                return value
            queue.extend(node.values())
        elif isinstance(node, (list, tuple)):
            queue.extend(node)
    return None


def _format_temp(value: Any) -> tuple[str, float | None]:
    """温度 → (展示文本 "12°", 数值 12.0)。"""
    text = str(value if value is not None else "").strip()
    if not text:
        return "", None
    try:
        number = float(text.replace("℃", "").replace("°", "").strip())
    except ValueError:
        return text, None
    shown = str(int(number)) if number == int(number) else f"{number:.1f}"
    return f"{shown}°", number


def _format_updated(publish: Any) -> str:
    """发布时间 → "MM-DD HH:MM"；解析不了就把原文截断。"""
    text = str(publish or "").strip()
    if not text:
        return datetime.now().strftime("%m-%d %H:%M")
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, pattern).strftime("%m-%d %H:%M")
        except ValueError:
            continue
    return text[:16]


def _empty_weather(error: str = "") -> dict:
    return {
        "ok": False,
        "error": error,
        "city": "",
        "temp": "",
        "tempValue": None,
        "weather": "",
        "updated": "",
    }


def _parse_weather(payload: Any) -> dict:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping):
        return _empty_weather("天气数据格式异常")
    real = data.get("real") if isinstance(data.get("real"), Mapping) else {}
    station = real.get("station") if isinstance(real.get("station"), Mapping) else {}
    current = real.get("weather") if isinstance(real.get("weather"), Mapping) else {}
    temp_raw = current.get("temperature")
    if temp_raw in (None, ""):
        temp_raw = _deep_first(data, "temperature")
    weather_raw = current.get("info")
    if not weather_raw:
        weather_raw = _deep_first(data, "info")
    temp, temp_value = _format_temp(temp_raw)
    weather_text = str(weather_raw or "").strip()
    if not temp and not weather_text:
        return _empty_weather("天气数据为空")
    city = str(station.get("city") or station.get("province") or "").strip()
    return {
        "ok": True,
        "error": "",
        "city": city,
        "temp": temp,
        "tempValue": temp_value,
        "weather": weather_text,
        "updated": _format_updated(real.get("publish_time")),
    }


def clear_weather_cache() -> None:
    """清空天气缓存（测试 / 手动刷新用）。"""
    _WEATHER_CACHE.clear()


def fetch_weather(
    city_id: str = DEFAULT_WEATHER_CITY,
    timeout: float = WEATHER_HTTP_TIMEOUT,
    *,
    use_cache: bool = True,
    now: float | None = None,
) -> dict:
    """拉城市实时天气（NMC）。

    返回 {ok, error, city, temp, tempValue, weather, updated}；失败时 ok=False 且 error
    是可读文案（网络断开 / 超时 / 格式异常）。成功结果缓存 15 分钟。
    """
    station = str(city_id or "").strip() or DEFAULT_WEATHER_CITY
    clock = time.time() if now is None else float(now)
    if use_cache:
        cached = _WEATHER_CACHE.get(station)
        if cached is not None and 0.0 <= clock - cached[0] < WEATHER_CACHE_SECONDS:
            return copy.deepcopy(cached[1])
    url = NMC_WEATHER_URL.format(station=urllib.parse.quote(station))
    try:
        payload = _http_json(url, timeout)
    except Exception as exc:  # noqa: BLE001 - 天气失败不能影响主程序
        logger.info("获取天气失败（%s）：%s", station, exc)
        return _empty_weather(_readable_error(exc, "天气"))
    try:
        result = _parse_weather(payload)
    except Exception as exc:  # noqa: BLE001
        logger.info("解析天气失败（%s）：%s", station, exc)
        return _empty_weather(f"天气数据解析失败：{exc}")
    if result.get("ok"):
        _WEATHER_CACHE[station] = (clock, copy.deepcopy(result))
    return result


# ================= 每日一言（hitokoto / 内置回退） =================
def clear_quote_cache() -> None:
    """清空每日一言缓存。"""
    _QUOTE_CACHE.clear()


def _random_quote(rng: Any = None) -> str:
    chooser = rng if rng is not None and hasattr(rng, "choice") else random
    try:
        return str(chooser.choice(QUOTES))
    except Exception:  # noqa: BLE001 - 兜底永远有文案
        return str(QUOTES[0])


def _quote_url(category: str) -> str:
    kind = str(category or "").strip().lower()
    if kind in QUOTE_CATEGORIES:
        return HITOKOTO_CATEGORY_URL.format(category=urllib.parse.quote(kind))
    return HITOKOTO_URL


def fetch_quote(
    timeout: float = QUOTE_HTTP_TIMEOUT,
    *,
    category: str = "",
    use_cache: bool = True,
    day: date | None = None,
    rng: Any = None,
) -> dict:
    """每日一言：优先在线 hitokoto，失败回退 consts.QUOTES 随机。

    返回 {text, source, from, error}；source 为 "hitokoto"（在线）或 "builtin"（回退）。
    结果按「日期 + 分类」缓存，当天失败也不会反复重试网络。
    """
    today = day or date.today()
    kind = str(category or "").strip().lower()
    key = f"{today.isoformat()}|{kind}"
    if use_cache and key in _QUOTE_CACHE:
        return copy.deepcopy(_QUOTE_CACHE[key])
    try:
        payload = _http_json(_quote_url(kind), timeout)
        text = str(payload.get("hitokoto") or "").strip() if isinstance(payload, Mapping) else ""
        if not text:
            raise ValueError("一言接口返回空内容")
        result = {
            "text": text[:QUOTE_MAX_CHARS],
            "source": "hitokoto",
            "from": str(payload.get("from") or "").strip(),
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001 - 回退内置文案
        logger.info("获取每日一言失败，回退内置文案：%s", exc)
        result = {
            "text": _random_quote(rng),
            "source": "builtin",
            "from": "深清",
            "error": _readable_error(exc, "一言"),
        }
    if use_cache:
        _QUOTE_CACHE[key] = copy.deepcopy(result)
    return result
