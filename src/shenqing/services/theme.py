"""v0.21 外观：样式 + 配色（系统深浅解析）。

style（solid / glass / ocean / custom:<id>）与 scheme（auto / light / dark）正交：

- scheme = auto 时用 QStyleHints.colorScheme()（Qt 6.5+）读取系统深浅；
- 读取失败回退注册表 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize
  的 AppsUseLightTheme（1 = 浅色 / 0 = 深色）；
- 再失败按深色处理，避免浅色界面在深色系统上刺眼。

本模块只依赖 Qt / winreg，不依赖 Settings；测试可直接替换
_style_hints_scheme / _registry_scheme / winreg 来模拟系统。
"""

from __future__ import annotations

import logging

from ..consts import THEME_SCHEME_VALUES

logger = logging.getLogger("shenqing.theme")

SCHEME_AUTO = "auto"
SCHEME_LIGHT = "light"
SCHEME_DARK = "dark"
#: 合法配色值（顺序与 consts.THEME_SCHEMES 一致）
SCHEMES = THEME_SCHEME_VALUES

#: Windows 个人化设置注册表位置（系统浅色/深色）
_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_REGISTRY_VALUE = "AppsUseLightTheme"

try:  # Qt 缺失时只走注册表兜底（例如纯逻辑脚本）
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
except Exception:  # noqa: BLE001 - PySide6 是桌面端依赖，导入失败不致命
    Qt = None  # type: ignore[assignment]
    QGuiApplication = None  # type: ignore[assignment]

try:  # 非 Windows 平台没有 winreg
    import winreg
except Exception:  # noqa: BLE001
    winreg = None  # type: ignore[assignment]


def _style_hints_scheme() -> str | None:
    """Qt 6.5+：QStyleHints.colorScheme()；Unknown / 不可用时返回 None。"""
    if QGuiApplication is None or Qt is None:
        return None
    try:
        hints = QGuiApplication.styleHints()
        value = hints.colorScheme()
    except Exception:  # noqa: BLE001 - 老 Qt / 离屏平台可能没有该接口
        return None
    try:
        color_scheme = getattr(Qt, "ColorScheme", None)
        if color_scheme is not None:
            if value == getattr(color_scheme, "Light", object()):
                return SCHEME_LIGHT
            if value == getattr(color_scheme, "Dark", object()):
                return SCHEME_DARK
    except Exception:  # noqa: BLE001
        return None
    return None


def _registry_scheme() -> str | None:
    """注册表 AppsUseLightTheme：1 = 浅色，0 = 深色；读不到返回 None。"""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REGISTRY_PATH) as key:
            value, _kind = winreg.QueryValueEx(key, _REGISTRY_VALUE)
    except OSError:
        return None
    try:
        light = int(value)
    except (TypeError, ValueError):
        return None
    return SCHEME_LIGHT if light else SCHEME_DARK


def system_scheme() -> str:
    """系统当前深浅：优先 Qt styleHints，其次注册表，最后深色。"""
    return _style_hints_scheme() or _registry_scheme() or SCHEME_DARK


def normalize_scheme(value: object) -> str | None:
    """合法配色（auto/light/dark）原样返回（小写），否则 None。"""
    text = str(value or "").strip().lower()
    return text if text in SCHEMES else None


def resolve_scheme(configured: object) -> str:
    """把配置值解析成实际深浅；auto / 非法值都跟随系统。"""
    value = normalize_scheme(configured)
    if value in (SCHEME_LIGHT, SCHEME_DARK):
        return value
    return system_scheme()


def style_hints():  # noqa: ANN201 - 返回 QStyleHints | None
    """当前 QStyleHints（不可用时返回 None，供系统深浅变化监听用）。"""
    if QGuiApplication is None:
        return None
    try:
        return QGuiApplication.styleHints()
    except Exception:  # noqa: BLE001
        return None


def connect_color_scheme_changed(callback) -> bool:  # noqa: ANN001
    """监听系统深浅切换：QStyleHints.colorSchemeChanged。

    成功连接返回 True；Qt 版本过旧 / 平台不支持时返回 False（不抛异常）。
    """
    hints = style_hints()
    if hints is None:
        return False
    signal = getattr(hints, "colorSchemeChanged", None)
    if signal is None:
        return False
    try:
        signal.connect(callback)
        return True
    except Exception as exc:  # noqa: BLE001 - 监听失败不能影响主流程
        logger.warning("系统深浅变化监听挂载失败：%s", exc)
        return False
