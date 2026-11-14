"""v0.21 AI 动作：解析 AI 回复里的动作块，校验成受控、可执行的动作。

AI 回复里出现下面任意一种形式即可：
    ```json
    {"actions": [{"type": "open_page", "page": "settings"}]}
    ```
    （也接受 ``` 无语言标记的代码块、裸 JSON 对象 / 数组 / 带 actions 的对象）

动作类型（ACTION_TYPES）：
    start_space          开始专注（必须二次确认：bridge 只登记 pending）
    open_space           打开空间页并切到该档位
    set_setting          修改 SETTING_SPECS 白名单内的设置项
    open_page            切到指定页面
    add_blocked_site     添加屏蔽网站
    remove_blocked_site  移除屏蔽网站

安全边界：
    - set_setting 只允许白名单键，非法键 / 非法值一律拒绝并给出中文原因；
    - 所有参数都归一化（别名映射、数值夹紧 / 步进、域名校验）；
    - 本模块纯函数、不依赖 Qt、不做 IO，方便单测与在任意线程调用。
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

from ..consts import (
    CUSTOM_THEME_PREFIX,
    MAX_MINUTES,
    MIN_MINUTES,
    MODE_LABELS,
    SPACE_MAX_MINUTES,
    SPACE_MIN_MINUTES,
    THEME_SCHEME_VALUES,
    THEME_STYLES,
)
from .site_blocker import normalize_domain, normalize_domains

#: 合法档位
MODES = ("light", "medium", "heavy")
#: 合法页面（QML 侧 pageRequested 的 key）
PAGES = (
    "spaces",
    "stats",
    "ai",
    "plugins",
    "themes",
    "settings",
    "update",
    "about",
    "store",
)
PAGE_LABELS = {
    "spaces": "空间",
    "stats": "数据",
    "ai": "AI",
    "plugins": "插件",
    "themes": "主题",
    "settings": "设置",
    "update": "更新",
    "about": "关于",
    "store": "商店",
}
#: 合法动作类型
ACTION_TYPES = (
    "start_space",
    "open_space",
    "set_setting",
    "open_page",
    "add_blocked_site",
    "remove_blocked_site",
)
#: 需要用户二次确认的动作类型
CONFIRM_ACTION_TYPES = ("start_space",)

#: 单次回复最多执行的动作数（防止模型输出失控）
MAX_ACTIONS = 10

ACCEPT_LABEL = "确认执行"
CONFIRM_LABELS = {"start_space": "确认开始"}

BUILTIN_STYLE_VALUES = tuple(str(item["value"]) for item in THEME_STYLES)
STYLE_LABELS = {str(item["value"]): str(item["label"]) for item in THEME_STYLES}
SCHEME_LABELS = {"auto": "跟随系统", "light": "浅色", "dark": "深色"}
LANGUAGE_VALUES = ("auto", "zh_CN", "en_US")
LANGUAGE_LABELS = {"auto": "跟随系统", "zh_CN": "简体中文", "en_US": "English"}
NAV_MODES = ("auto", "expanded", "icons", "custom")
NAV_MODE_LABELS = {
    "auto": "自动",
    "expanded": "展开",
    "icons": "仅图标",
    "custom": "自定义",
}
UPDATE_CHANNELS = ("stable", "preview")
CHANNEL_LABELS = {"stable": "正式版", "preview": "预览版"}

MIN_FONT_SCALE = 0.8
MAX_FONT_SCALE = 1.4
FONT_SCALE_STEP = 0.05
FONT_SCALE_DEFAULT = 1.0
FONT_FAMILY_MAX_LENGTH = 64

_UPDATE_SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")
_CUSTOM_THEME_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,48}$")

# ---------- 别名（AI 可能输出中文值） ----------
MODE_ALIASES = {
    "light": "light",
    "浅清": "light",
    "轻度": "light",
    "light 轻": "light",
    "medium": "medium",
    "覆清": "medium",
    "中度": "medium",
    "重覆": "medium",
    "heavy": "heavy",
    "深清": "heavy",
    "重度": "heavy",
}
STYLE_ALIASES = {
    "solid": "solid",
    "纯色": "solid",
    "flat": "solid",
    "glass": "glass",
    "液态玻璃": "glass",
    "玻璃": "glass",
    "ocean": "ocean",
    "海洋": "ocean",
    "波浪": "ocean",
}
SCHEME_ALIASES = {
    "auto": "auto",
    "system": "auto",
    "跟随系统": "auto",
    "自动": "auto",
    "light": "light",
    "浅色": "light",
    "亮色": "light",
    "dark": "dark",
    "深色": "dark",
    "暗色": "dark",
}
LANGUAGE_ALIASES = {
    "auto": "auto",
    "system": "auto",
    "跟随系统": "auto",
    "自动": "auto",
    "zh": "zh_CN",
    "zh_cn": "zh_CN",
    "zh-cn": "zh_CN",
    "chinese": "zh_CN",
    "中文": "zh_CN",
    "简体中文": "zh_CN",
    "cn": "zh_CN",
    "en": "en_US",
    "en_us": "en_US",
    "en-us": "en_US",
    "english": "en_US",
    "英文": "en_US",
}
CHANNEL_ALIASES = {
    "stable": "stable",
    "正式": "stable",
    "正式版": "stable",
    "release": "stable",
    "preview": "preview",
    "预览": "preview",
    "预览版": "preview",
    "beta": "preview",
    "test": "preview",
}
NAV_MODE_ALIASES = {
    "auto": "auto",
    "自动": "auto",
    "expanded": "expanded",
    "展开": "expanded",
    "展开式": "expanded",
    "icons": "icons",
    "仅图标": "icons",
    "图标": "icons",
    "custom": "custom",
    "自定义": "custom",
}
PAGE_ALIASES = {
    "spaces": "spaces",
    "space": "spaces",
    "空间": "spaces",
    "stats": "stats",
    "statistics": "stats",
    "数据": "stats",
    "统计": "stats",
    "ai": "ai",
    "插件": "plugins",
    "plugins": "plugins",
    "plugin": "plugins",
    "themes": "themes",
    "theme": "themes",
    "主题": "themes",
    "settings": "settings",
    "setting": "settings",
    "设置": "settings",
    "update": "update",
    "更新": "update",
    "about": "about",
    "关于": "about",
    "store": "store",
    "商店": "store",
    "市场": "store",
}
TRUE_WORDS = {"1", "true", "on", "yes", "y", "开", "开启", "启用", "打开", "是", "真"}
FALSE_WORDS = {"0", "false", "off", "no", "n", "关", "关闭", "禁用", "否", "假"}

#: set_setting 白名单：键 -> 规格（kind 决定归一化方式）
SETTING_SPECS: dict[str, dict[str, Any]] = {
    "theme_style": {"title": "主题样式", "kind": "theme_style"},
    "theme_scheme": {"title": "主题配色", "kind": "scheme"},
    "language": {"title": "语言", "kind": "language"},
    "ui_font_scale": {"title": "界面字号", "kind": "font_scale"},
    "ui_font_family": {"title": "界面字体", "kind": "font_family"},
    "nav_mode": {"title": "导航方式", "kind": "nav_mode"},
    "default_minutes": {"title": "默认时长", "kind": "minutes"},
    "auto_update": {"title": "自动更新", "kind": "bool"},
    "site_block_enabled": {"title": "网站屏蔽", "kind": "bool"},
    "hide_desktop_icons": {"title": "隐藏桌面图标", "kind": "bool"},
    "update_source": {"title": "更新源", "kind": "source"},
    "update_channel": {"title": "更新渠道", "kind": "channel"},
    "blocked_sites": {"title": "屏蔽网站", "kind": "domains"},
}
#: set_setting 允许的键（顺序稳定）
SETTING_KEYS = tuple(SETTING_SPECS)
#: 中文键别名（用户口语 → 白名单键）
SETTING_KEY_ALIASES = {
    "主题样式": "theme_style",
    "外观样式": "theme_style",
    "主题": "theme_style",
    "主题配色": "theme_scheme",
    "配色": "theme_scheme",
    "深浅色": "theme_scheme",
    "语言": "language",
    "界面字号": "ui_font_scale",
    "字号": "ui_font_scale",
    "字体大小": "ui_font_scale",
    "界面字体": "ui_font_family",
    "字体": "ui_font_family",
    "导航方式": "nav_mode",
    "导航模式": "nav_mode",
    "默认时长": "default_minutes",
    "默认分钟": "default_minutes",
    "自动更新": "auto_update",
    "网站屏蔽": "site_block_enabled",
    "屏蔽网站开关": "site_block_enabled",
    "隐藏桌面图标": "hide_desktop_icons",
    "桌面图标": "hide_desktop_icons",
    "更新源": "update_source",
    "更新渠道": "update_channel",
    "屏蔽网站": "blocked_sites",
    "屏蔽列表": "blocked_sites",
}


# ==================== 基础归一化 ====================
def _text(value: object) -> str:
    return str(value if value is not None else "").strip()


def _lookup(table: dict[str, Any], value: object, default: Any = "") -> Any:
    key = _text(value)
    if not key:
        return default
    lowered = key.lower()
    if lowered in table:
        return table[lowered]
    if key in table:
        return table[key]
    return default


def normalize_mode(value: object) -> str:
    """档位归一化：合法返回 light/medium/heavy，否则空串。"""
    return str(_lookup(MODE_ALIASES, value, "") or "")


def normalize_page(value: object) -> str:
    """页面归一化：合法返回 PAGES 里的 key，否则空串。"""
    return str(_lookup(PAGE_ALIASES, value, "") or "")


def normalize_style(value: object) -> str:
    """主题样式归一化：内置样式或 custom:<id>，否则空串。"""
    text = _text(value)
    if not text:
        return ""
    if text.lower().startswith(CUSTOM_THEME_PREFIX):
        theme_id = text[len(CUSTOM_THEME_PREFIX) :].strip()
        if _CUSTOM_THEME_ID_RE.match(theme_id):
            return CUSTOM_THEME_PREFIX + theme_id
        return ""
    mapped = _lookup(STYLE_ALIASES, text, "")
    return str(mapped or "")


def normalize_scheme(value: object) -> str:
    mapped = _lookup(SCHEME_ALIASES, value, "")
    return str(mapped or "")


def normalize_language(value: object) -> str:
    mapped = _lookup(LANGUAGE_ALIASES, value, "")
    return str(mapped or "")


def normalize_nav_mode(value: object) -> str:
    mapped = _lookup(NAV_MODE_ALIASES, value, "")
    return str(mapped or "")


def normalize_channel(value: object) -> str:
    mapped = _lookup(CHANNEL_ALIASES, value, "")
    return str(mapped or "")


def parse_bool(value: object) -> tuple[bool, bool]:
    """返回 (是否合法, 布尔值)。支持 bool / 数字 / 中英文开关词。"""
    if isinstance(value, bool):
        return True, value
    if isinstance(value, (int, float)):
        return True, bool(value)
    text = _text(value).lower()
    if not text:
        return False, False
    if text in TRUE_WORDS:
        return True, True
    if text in FALSE_WORDS:
        return True, False
    return False, False


def _clamp_int(value: object, low: int, high: int) -> int | None:
    """从数字/带单位文本里取整并夹紧；取不到返回 None。"""
    if isinstance(value, bool):
        return None
    number: float | None = None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = re.search(r"-?\d+(?:\.\d+)?", _text(value))
        if match:
            try:
                number = float(match.group(0))
            except ValueError:
                number = None
    if number is None:
        return None
    return max(low, min(high, int(round(number))))


def normalize_font_scale(value: object) -> float | None:
    """字号归一化：支持 1.2 / "1.2" / "120%" / 120（百分数），夹紧 0.8-1.4 步进 0.05。"""
    if isinstance(value, bool):
        return None
    number: float | None = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number >= 50:  # 120 → 1.2（百分数写法）
            number = number / 100.0
    else:
        text = _text(value).lower()
        if not text:
            return None
        percent = "%" in text
        match = re.search(r"\d+(?:\.\d+)?", text)
        if not match:
            return None
        try:
            number = float(match.group(0))
        except ValueError:
            return None
        if percent or number >= 50:
            number = number / 100.0
    scale = max(MIN_FONT_SCALE, min(MAX_FONT_SCALE, float(number)))
    steps = round((scale - MIN_FONT_SCALE) / FONT_SCALE_STEP)
    return round(MIN_FONT_SCALE + steps * FONT_SCALE_STEP, 2)


def normalize_update_source(value: object) -> str:
    """更新源 id：内置 github/gitlink/gitee 或自定义源 id（是否已安装由 bridge 校验）。"""
    text = _text(value).lower()
    if not text:
        return ""
    return text if _UPDATE_SOURCE_RE.match(text) else ""


def normalize_setting_key(key: object) -> str:
    """设置键归一化：白名单键或中文别名 → 白名单键，否则空串。"""
    text = _text(key)
    if not text:
        return ""
    if text in SETTING_SPECS:
        return text
    lowered = text.lower()
    if lowered in SETTING_SPECS:
        return lowered
    alias = SETTING_KEY_ALIASES.get(text)
    return str(alias or "")


def normalize_setting_value(key: str, value: object) -> tuple[bool, Any, str]:
    """校验并归一化设置值；返回 (ok, 归一化值, 错误原因)。"""
    spec = SETTING_SPECS.get(str(key or ""))
    if spec is None:
        return False, None, f"不支持的设置项：{_text(key)}"
    kind = str(spec.get("kind") or "")
    if kind == "theme_style":
        style = normalize_style(value)
        if not style:
            return False, None, f"未知的主题样式：{_text(value)}"
        return True, style, ""
    if kind == "scheme":
        scheme = normalize_scheme(value)
        if not scheme:
            return False, None, f"未知的配色方案：{_text(value)}"
        return True, scheme, ""
    if kind == "language":
        code = normalize_language(value)
        if not code:
            return False, None, f"不支持的语言：{_text(value)}"
        return True, code, ""
    if kind == "font_scale":
        scale = normalize_font_scale(value)
        if scale is None:
            return False, None, f"字号不正确：{_text(value)}（范围 0.8-1.4）"
        return True, scale, ""
    if kind == "font_family":
        text = _text(value)
        if text.lower() in {"", "default", "auto", "默认", "默认字体", "内置"}:
            return True, "", ""
        if len(text) > FONT_FAMILY_MAX_LENGTH:
            return False, None, "字体名过长"
        return True, text, ""
    if kind == "nav_mode":
        mode = normalize_nav_mode(value)
        if not mode:
            return False, None, f"未知的导航方式：{_text(value)}"
        return True, mode, ""
    if kind == "minutes":
        minutes = _clamp_int(value, MIN_MINUTES, MAX_MINUTES)
        if minutes is None:
            return False, None, f"时长不正确：{_text(value)}"
        return True, minutes, ""
    if kind == "bool":
        ok, flag = parse_bool(value)
        if not ok:
            return False, None, f"开关值不正确：{_text(value)}"
        return True, flag, ""
    if kind == "source":
        source = normalize_update_source(value)
        if not source:
            return False, None, f"更新源 id 不合法：{_text(value)}"
        return True, source, ""
    if kind == "channel":
        channel = normalize_channel(value)
        if not channel:
            return False, None, f"未知的更新渠道：{_text(value)}"
        return True, channel, ""
    if kind == "domains":
        sites: list[str] = []
        if isinstance(value, (list, tuple, set)):
            sites = normalize_domains(list(value))
        else:
            text = _text(value)
            if text:
                sites = normalize_domains(re.split(r"[,，;；\s]+", text))
        return True, sites, ""
    return False, None, f"不支持的设置项：{_text(key)}"


def setting_title(key: str) -> str:
    spec = SETTING_SPECS.get(str(key or ""))
    return str(spec.get("title") or key) if spec else str(key or "")


def setting_value_text(key: str, value: object) -> str:
    """把归一化后的值转成给用户看的中文（用于「已把 X 改为 Y」）。"""
    spec = SETTING_SPECS.get(str(key or ""))
    kind = str((spec or {}).get("kind") or "")
    if kind == "theme_style":
        text = _text(value)
        if text.startswith(CUSTOM_THEME_PREFIX):
            return "自定义主题"
        return STYLE_LABELS.get(text, text)
    if kind == "scheme":
        return SCHEME_LABELS.get(_text(value), _text(value))
    if kind == "language":
        return LANGUAGE_LABELS.get(_text(value), _text(value))
    if kind == "font_scale":
        try:
            return f"{int(round(float(value) * 100))}%"
        except (TypeError, ValueError):
            return _text(value)
    if kind == "font_family":
        return _text(value) or "默认字体"
    if kind == "nav_mode":
        return NAV_MODE_LABELS.get(_text(value), _text(value))
    if kind == "minutes":
        return f"{value} 分钟"
    if kind == "bool":
        return "开启" if value else "关闭"
    if kind == "source":
        return _text(value)
    if kind == "channel":
        return CHANNEL_LABELS.get(_text(value), _text(value))
    if kind == "domains":
        sites = value if isinstance(value, list) else []
        return f"{len(sites)} 个网站" if sites else "已清空"
    return _text(value)


# ==================== 动作校验 ====================
def _validate_start_space(raw: dict) -> tuple[dict | None, str]:
    space_id = _text(raw.get("spaceId") or raw.get("space_id") or "")
    mode = ""
    if _text(raw.get("mode")):
        mode = normalize_mode(raw.get("mode"))
        if not mode:
            return None, f"未知的档位：{_text(raw.get('mode'))}"
    if not space_id and not mode:
        return None, "start_space 需要 mode 或 spaceId"
    raw_minutes = raw.get("minutes", raw.get("duration"))
    minutes = 0
    if raw_minutes not in (None, ""):
        parsed = _clamp_int(raw_minutes, SPACE_MIN_MINUTES, SPACE_MAX_MINUTES)
        if parsed is None:
            return None, f"时长不正确：{_text(raw_minutes)}"
        minutes = parsed
    return {
        "type": "start_space",
        "mode": mode,
        "spaceId": space_id,
        "minutes": minutes,
    }, ""


def _validate_open_space(raw: dict) -> tuple[dict | None, str]:
    mode = normalize_mode(raw.get("mode"))
    if not mode:
        return None, f"未知的档位：{_text(raw.get('mode'))}"
    return {"type": "open_space", "mode": mode}, ""


def _validate_set_setting(raw: dict) -> tuple[dict | None, str]:
    key = normalize_setting_key(raw.get("key"))
    if not key:
        return None, f"不支持的设置项：{_text(raw.get('key'))}"
    if "value" not in raw:
        return None, f"缺少设置值：{key}"
    ok, value, error = normalize_setting_value(key, raw.get("value"))
    if not ok:
        return None, error or f"设置值不正确：{key}"
    return {
        "type": "set_setting",
        "key": key,
        "value": value,
        "title": setting_title(key),
    }, ""


def _validate_open_page(raw: dict) -> tuple[dict | None, str]:
    page = normalize_page(raw.get("page"))
    if not page:
        return None, f"未知的页面：{_text(raw.get('page'))}"
    return {"type": "open_page", "page": page}, ""


def _validate_blocked_site(raw: dict, kind: str) -> tuple[dict | None, str]:
    domain = normalize_domain(raw.get("domain"))
    if not domain:
        return None, f"域名格式不正确：{_text(raw.get('domain'))}"
    return {"type": kind, "domain": domain}, ""


def validate_action(raw: object) -> tuple[dict | None, str]:
    """把一条原始动作校验 / 归一化成可执行动作；非法返回 (None, 原因)。"""
    if not isinstance(raw, dict):
        return None, "动作格式不正确"
    kind = _text(raw.get("type")).lower()
    if not kind:
        return None, "动作缺少 type"
    if kind not in ACTION_TYPES:
        return None, f"不支持的动作类型：{kind}"
    if kind == "start_space":
        return _validate_start_space(raw)
    if kind == "open_space":
        return _validate_open_space(raw)
    if kind == "set_setting":
        return _validate_set_setting(raw)
    if kind == "open_page":
        return _validate_open_page(raw)
    if kind == "add_blocked_site":
        return _validate_blocked_site(raw, "add_blocked_site")
    return _validate_blocked_site(raw, "remove_blocked_site")


def requires_confirmation(action: dict) -> bool:
    return str(action.get("type") or "") in CONFIRM_ACTION_TYPES


def confirm_label(action: dict) -> str:
    return CONFIRM_LABELS.get(str(action.get("type") or ""), ACCEPT_LABEL)


# ==================== 解析 AI 回复 ====================
_FENCE_RE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n?(.*?)```", re.S)


def _try_load(text: str) -> Any:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None


def _balanced_end(text: str, start: int) -> int:
    """从 text[start] 的 { 或 [ 开始找配对的结束位置；找不到返回 -1。"""
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
    return -1


def iter_json_values(text: str) -> Iterator[tuple[Any, tuple[int, int]]]:
    """扫描文本里所有裸 JSON 对象 / 数组，产出 (解析值, (start, end))。"""
    source = str(text or "")
    index = 0
    while index < len(source):
        candidates = [pos for pos in (source.find("{", index), source.find("[", index)) if pos >= 0]
        if not candidates:
            return
        start = min(candidates)
        end = _balanced_end(source, start)
        if end < 0:
            index = start + 1
            continue
        value = _try_load(source[start : end + 1])
        if value is None:
            index = start + 1
            continue
        yield value, (start, end + 1)
        index = end + 1


def _iter_raw_actions(value: Any) -> Iterator[dict]:
    if isinstance(value, dict):
        actions = value.get("actions")
        if isinstance(actions, list):
            for item in actions:
                if isinstance(item, dict):
                    yield item
            return
        if _text(value.get("type")):
            yield value
        return
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and _text(item.get("type")):
                yield item


def parse_reply(text: str) -> dict:
    """解析 AI 回复：返回 {"actions": [...], "errors": [...]}。

    actions 已归一化、可直接执行；errors 是给用户看的中文拒绝原因。
    """
    source = str(text or "")
    values: list[Any] = []
    covered: list[tuple[int, int]] = []
    for match in _FENCE_RE.finditer(source):
        body = match.group(2)
        parsed = _try_load(body)
        if parsed is None:
            node = dict(match.span(2))
            # 代码块内容不是合法 JSON：若块里是裸 JSON，交给整体扫描
            for inner, span in iter_json_values(source):
                if node["start"] <= span[0] and span[1] <= node["stop"]:
                    values.append(inner)
                    covered.append(span)
            continue
        values.append(parsed)
        covered.append(match.span())
    for value, span in iter_json_values(source):
        if any(start <= span[0] and span[1] <= end for start, end in covered):
            continue
        values.append(value)
    actions: list[dict] = []
    errors: list[str] = []
    for value in values:
        for raw in _iter_raw_actions(value):
            if len(actions) >= MAX_ACTIONS:
                errors.append(f"动作过多（最多 {MAX_ACTIONS} 个），其余已忽略")
                return {"actions": actions, "errors": errors}
            action, error = validate_action(raw)
            if action is None:
                if error:
                    errors.append(error)
                continue
            actions.append(action)
    return {"actions": actions, "errors": errors}


def parse_actions(text: str) -> list[dict]:
    """只要合法动作列表（tests / 便捷调用）。"""
    return parse_reply(text)["actions"]


def has_actions(text: str) -> bool:
    return bool(parse_actions(text))


def _action_spans(text: str) -> list[tuple[int, int]]:
    """动作块在原文里的位置（代码块优先，裸 JSON 兜底，互不重叠）。"""
    source = str(text or "")
    spans: list[tuple[int, int]] = []
    for match in _FENCE_RE.finditer(source):
        parsed = _try_load(match.group(2))
        if parsed is not None and list(_iter_raw_actions(parsed)):
            spans.append(match.span())
            continue
        body_start, body_end = match.span(2)
        for value, span in iter_json_values(source):
            if body_start <= span[0] and span[1] <= body_end and list(_iter_raw_actions(value)):
                spans.append(span)
    for value, span in iter_json_values(source):
        if any(start <= span[0] and span[1] <= end for start, end in spans):
            continue
        if list(_iter_raw_actions(value)):
            spans.append(span)
    return spans


def strip_action_blocks(text: str) -> str:
    """去掉回复里的动作块（给聊天界面展示用）；没有动作块时原样返回。"""
    source = str(text or "")
    spans = sorted(_action_spans(source))
    if not spans:
        return source
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        if start < cursor:
            continue
        pieces.append(source[cursor:start])
        cursor = end
    pieces.append(source[cursor:])
    cleaned = re.sub(r"\n{3,}", "\n\n", "".join(pieces))
    return cleaned.strip()


# ==================== 展示文案 ====================
def mode_label(mode: str) -> str:
    return MODE_LABELS.get(str(mode or ""), str(mode or ""))


def describe_action(action: dict) -> str:
    """动作的祈使句式描述（用于 pending 卡 / 结果文案）。"""
    kind = str(action.get("type") or "")
    if kind == "start_space":
        name = _text(action.get("spaceName"))
        label = mode_label(_text(action.get("mode"))) or _text(action.get("modeLabel"))
        target = name or label or "专注"
        minutes = int(action.get("minutes") or 0)
        return f"开始专注：{target} · {minutes} 分钟" if minutes else f"开始专注：{target}"
    if kind == "open_space":
        return f"打开{mode_label(action.get('mode'))}空间"
    if kind == "set_setting":
        key = str(action.get("key") or "")
        return f"把 {setting_title(key)} 改为 {setting_value_text(key, action.get('value'))}"
    if kind == "open_page":
        return f"打开{PAGE_LABELS.get(str(action.get('page')), action.get('page'))}页"
    if kind == "add_blocked_site":
        return f"添加屏蔽网站：{_text(action.get('domain'))}"
    if kind == "remove_blocked_site":
        return f"移除屏蔽网站：{_text(action.get('domain'))}"
    return "执行动作"


def pending_summary(action: dict, action_id: str = "") -> dict:
    """start_space 待确认动作的展示信息（bridge 的 aiActionPending 用它）。"""
    kind = str(action.get("type") or "")
    mode = _text(action.get("mode"))
    minutes = int(action.get("minutes") or 0)
    space_name = _text(action.get("spaceName"))
    label = mode_label(mode) or _text(action.get("modeLabel"))
    pieces: list[str] = []
    if label:
        pieces.append(label)
    if minutes:
        pieces.append(f"{minutes} 分钟")
    summary = "开始" + " · ".join(pieces) if pieces else "开始专注"
    if space_name:
        summary += f"（{space_name}）"
    return {
        "id": str(action_id or action.get("id") or ""),
        "type": kind,
        "title": "开始专注" if kind == "start_space" else describe_action(action),
        "summary": summary,
        "confirmLabel": confirm_label(action),
        "requiresConfirm": True,
        "mode": mode,
        "modeLabel": label,
        "spaceId": _text(action.get("spaceId")),
        "spaceName": space_name,
        "minutes": minutes,
    }


def result_entry(action: dict, ok: bool, text: str, at: str = "") -> dict:
    """统一的动作结果条目（bridge 的 aiActionResult / aiActionLog 用它）。"""
    return {
        "ok": bool(ok),
        "type": str(action.get("type") or ""),
        "text": str(text or ""),
        "at": str(at or ""),
    }


# ==================== 系统提示词 ====================
def system_prompt() -> str:
    """追加到 AI 系统提示词里的动作格式说明。"""
    return (
        "你还能直接操作深清本体。当用户要求「开始专注 / 打开某个页面 / 修改设置 / 增删屏蔽网站」时，"
        "在正常回答之后追加一个 JSON 代码块，格式严格如下（也可以只输出这一段 JSON）：\n"
        "```json\n"
        '{"actions":[{"type":"open_page","page":"settings"}]}\n'
        "```\n"
        "可用动作：\n"
        '- {"type":"start_space","mode":"light|medium|heavy","spaceId":"","minutes":25}'
        " — 开始专注；用户需要再确认一次，mode 与 spaceId 至少给一个，minutes 可省略（用空间自己的时长）\n"
        '- {"type":"open_space","mode":"light|medium|heavy"} — 打开空间页并切到该档位\n'
        '- {"type":"set_setting","key":"<键>","value":<值>} — 修改设置，只能用这些键：'
        + "、".join(SETTING_KEYS)
        + "\n"
        '- {"type":"open_page","page":"' + "|".join(PAGES) + '"} — 切换到指定页面\n'
        '- {"type":"add_blocked_site","domain":"example.com"} / '
        '{"type":"remove_blocked_site","domain":"example.com"} — 增删屏蔽网站\n'
        "规则：只输出完成用户请求所需的最少动作；不确定就不要输出动作；"
        "这些键以外的一律无效；不要编造 deepseek 没有的键或页面。"
    )
