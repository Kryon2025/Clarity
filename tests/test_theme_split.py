"""v0.21 外观拆分测试：样式（solid/glass/ocean/custom）+ 配色（auto/light/dark）。

覆盖：
- 旧 theme_mode 各值迁移到 theme_style/theme_scheme，写回并清理旧键；
- 系统深浅解析（mock QStyleHints / 注册表 / 全部失败兜底 dark）；
- Bridge 的 themeStyle / themeScheme / effectiveScheme / themeStyles / themeSchemes /
  systemScheme 属性与 setThemeStyle / setThemeScheme 非法值拒绝；
- 兼容接口 themeMode / setThemeMode 的映射；
- themeChanged 在样式、配色、系统深浅变化时的触发。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SHENQING_NO_SCAN"] = "1"
os.environ["SHENQING_NO_KEEPER"] = "1"

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

from shenqing.bridge.app_bridge import AppBridge  # noqa: E402
from shenqing.consts import (  # noqa: E402
    DEFAULT_THEME_SCHEME,
    DEFAULT_THEME_STYLE,
)
from shenqing.services import theme as theme_service  # noqa: E402
from shenqing.settings import (  # noqa: E402
    LEGACY_THEME_KEY,
    Settings,
    migrate_theme_mode,
)

PALETTE = {
    "bgTop": "#0A1F2E",
    "bgMid": "#06202C",
    "bgBottom": "#04121A",
    "accent": "#35E0C8",
    "cardBg": "#0D2634",
    "textPrimary": "#EAF8FC",
}

#: 迁移规则表（含未知值兜底）
MIGRATION_CASES = {
    "light": ("solid", "light"),
    "solid": ("solid", "dark"),
    "glass": ("glass", "dark"),
    "ocean": ("ocean", "dark"),
    "custom:aurora": ("custom:aurora", "auto"),
}


class ThemeMigrationTest(unittest.TestCase):
    """旧 theme_mode → theme_style / theme_scheme 的一次性迁移。"""

    def _write(self, data: dict) -> tuple[tempfile.TemporaryDirectory, Path]:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "settings.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return tmp, path

    def test_mapping_table(self) -> None:
        for old, expected in MIGRATION_CASES.items():
            self.assertEqual(migrate_theme_mode(old), expected, old)
        # 未知值 / 空值：保留旧版默认的深色 chrome
        self.assertEqual(migrate_theme_mode("legacy-dark"), ("solid", "dark"))
        self.assertEqual(migrate_theme_mode(""), ("solid", "dark"))
        self.assertEqual(migrate_theme_mode(None), ("solid", "dark"))
        # 空 id 的 custom: 不算有效自定义主题
        self.assertEqual(migrate_theme_mode("custom:"), ("solid", "dark"))

    def test_file_migration_writes_back_and_cleans_legacy(self) -> None:
        for old, (style, scheme) in MIGRATION_CASES.items():
            tmp, path = self._write({"theme_mode": old, "pin": "keep-me"})
            try:
                settings = Settings(path)
                self.assertEqual(settings.get("theme_style"), style, old)
                self.assertEqual(settings.get("theme_scheme"), scheme, old)
                self.assertIsNone(settings.get(LEGACY_THEME_KEY), old)
                raw = json.loads(path.read_text(encoding="utf-8"))
                self.assertNotIn(LEGACY_THEME_KEY, raw, old)
                self.assertEqual(raw["theme_style"], style, old)
                self.assertEqual(raw["theme_scheme"], scheme, old)
                self.assertEqual(raw["pin"], "keep-me", old)
            finally:
                tmp.cleanup()

    def test_new_keys_win_over_legacy(self) -> None:
        tmp, path = self._write(
            {"theme_style": "ocean", "theme_scheme": "light", "theme_mode": "glass"}
        )
        try:
            settings = Settings(path)
            self.assertEqual(settings.get("theme_style"), "ocean")
            self.assertEqual(settings.get("theme_scheme"), "light")
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn(LEGACY_THEME_KEY, raw)
        finally:
            tmp.cleanup()

    def test_partial_new_keys_filled_with_defaults(self) -> None:
        tmp, path = self._write({"theme_style": "glass", "theme_mode": "ocean"})
        try:
            settings = Settings(path)
            self.assertEqual(settings.get("theme_style"), "glass")
            self.assertEqual(settings.get("theme_scheme"), DEFAULT_THEME_SCHEME)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn(LEGACY_THEME_KEY, raw)
        finally:
            tmp.cleanup()

    def test_fresh_settings_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            settings = Settings(path)
            self.assertTrue(settings.is_new)
            self.assertEqual(settings.get("theme_style"), DEFAULT_THEME_STYLE)
            self.assertEqual(settings.get("theme_scheme"), DEFAULT_THEME_SCHEME)
            self.assertIsNone(settings.get(LEGACY_THEME_KEY))
            # 没写过设置时不应该创建文件
            self.assertFalse(path.exists())


class FakeHints:
    def __init__(self, value: object) -> None:
        self._value = value

    def colorScheme(self):  # noqa: ANN201
        return self._value


class FakeGuiApp:
    def __init__(self, value: object) -> None:
        self._hints = FakeHints(value)

    def styleHints(self):  # noqa: ANN201
        return self._hints


class FakeKey:
    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class FakeWinreg:
    HKEY_CURRENT_USER = object()

    def __init__(self, value: object) -> None:
        self._value = value

    def OpenKey(self, root, path):  # noqa: ANN001, ANN201
        if self._value is None:
            raise OSError("no such key")
        return FakeKey()

    def QueryValueEx(self, key, name):  # noqa: ANN001, ANN201
        return (self._value, 1)


class SystemSchemeTest(unittest.TestCase):
    """system_scheme(): QStyleHints → 注册表 → dark。"""

    def test_style_hints(self) -> None:
        with mock.patch.object(
            theme_service, "QGuiApplication", FakeGuiApp(Qt.ColorScheme.Light)
        ):
            self.assertEqual(theme_service.system_scheme(), "light")
        with mock.patch.object(
            theme_service, "QGuiApplication", FakeGuiApp(Qt.ColorScheme.Dark)
        ):
            self.assertEqual(theme_service.system_scheme(), "dark")

    def test_style_hints_unknown_falls_to_registry(self) -> None:
        with mock.patch.object(
            theme_service, "QGuiApplication", FakeGuiApp(Qt.ColorScheme.Unknown)
        ), mock.patch.object(theme_service, "winreg", FakeWinreg(1)):
            self.assertEqual(theme_service.system_scheme(), "light")
        with mock.patch.object(
            theme_service, "QGuiApplication", FakeGuiApp(Qt.ColorScheme.Unknown)
        ), mock.patch.object(theme_service, "winreg", FakeWinreg(0)):
            self.assertEqual(theme_service.system_scheme(), "dark")

    def test_registry_fallback(self) -> None:
        with mock.patch.object(theme_service, "QGuiApplication", None), mock.patch.object(
            theme_service, "winreg", FakeWinreg(1)
        ):
            self.assertEqual(theme_service.system_scheme(), "light")
        with mock.patch.object(theme_service, "QGuiApplication", None), mock.patch.object(
            theme_service, "winreg", FakeWinreg(0)
        ):
            self.assertEqual(theme_service.system_scheme(), "dark")

    def test_registry_missing_key(self) -> None:
        with mock.patch.object(theme_service, "QGuiApplication", None), mock.patch.object(
            theme_service, "winreg", FakeWinreg(None)
        ):
            self.assertEqual(theme_service.system_scheme(), "dark")

    def test_last_resort_dark(self) -> None:
        with mock.patch.object(theme_service, "QGuiApplication", None), mock.patch.object(
            theme_service, "winreg", None
        ):
            self.assertEqual(theme_service.system_scheme(), "dark")

    def test_resolve_scheme(self) -> None:
        with mock.patch.object(theme_service, "system_scheme", return_value="light"):
            self.assertEqual(theme_service.resolve_scheme("auto"), "light")
            self.assertEqual(theme_service.resolve_scheme("light"), "light")
            self.assertEqual(theme_service.resolve_scheme("bogus"), "light")
            self.assertEqual(theme_service.resolve_scheme(None), "light")
        self.assertEqual(theme_service.resolve_scheme("dark"), "dark")

    def test_normalize_scheme(self) -> None:
        self.assertEqual(theme_service.normalize_scheme(" Auto "), "auto")
        self.assertEqual(theme_service.normalize_scheme("LIGHT"), "light")
        self.assertIsNone(theme_service.normalize_scheme("sepia"))
        self.assertIsNone(theme_service.normalize_scheme(""))

    def test_connect_color_scheme_changed(self) -> None:
        connected: list[object] = []

        class FakeSignal:
            def connect(self, callback) -> None:  # noqa: ANN001
                connected.append(callback)

        class FakeHintsWithSignal:
            colorSchemeChanged = FakeSignal()

        with mock.patch.object(
            theme_service, "style_hints", return_value=FakeHintsWithSignal()
        ):
            self.assertTrue(theme_service.connect_color_scheme_changed(lambda: None))
        self.assertEqual(len(connected), 1)
        with mock.patch.object(theme_service, "style_hints", return_value=None):
            self.assertFalse(theme_service.connect_color_scheme_changed(lambda: None))


class _BridgeCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SHENQING_DATA_DIR"] = self._tmp.name
        # auto 会读真实系统深浅：测试固定 dark，断言才有确定性
        self._scheme_patcher = mock.patch.object(
            theme_service, "system_scheme", return_value="dark"
        )
        self._scheme_patcher.start()
        self.bridge = AppBridge()
        self.toasts: list[str] = []
        self.bridge.toast.connect(self.toasts.append)

    def tearDown(self) -> None:
        try:
            self.bridge._session.stop()
        except Exception:  # noqa: BLE001
            pass
        self.bridge._shutdown_services()
        try:
            self.bridge.deleteLater()
        except RuntimeError:
            pass
        self._scheme_patcher.stop()
        self._tmp.cleanup()
        os.environ.pop("SHENQING_DATA_DIR", None)

    def _reload(self) -> AppBridge:
        try:
            self.bridge._shutdown_services()
            self.bridge.deleteLater()
        except RuntimeError:
            pass
        self.bridge = AppBridge()
        return self.bridge


class AppearanceBridgeTest(_BridgeCase):
    def test_defaults_and_lists(self) -> None:
        bridge = self.bridge
        self.assertEqual(bridge.themeStyle, "solid")
        self.assertEqual(bridge.themeScheme, "auto")
        self.assertEqual(bridge.effectiveScheme, "dark")
        self.assertEqual(bridge.systemScheme, "dark")
        self.assertEqual(bridge.themeMode, "solid")
        self.assertEqual(
            [item["value"] for item in bridge.themeStyles], ["solid", "glass", "ocean"]
        )
        glass = bridge.themeStyles[1]
        self.assertEqual(glass["name"], "液态玻璃")
        self.assertTrue(glass["experimental"])
        self.assertEqual(
            [item["value"] for item in bridge.themeSchemes], ["auto", "light", "dark"]
        )
        self.assertEqual(
            [item["name"] for item in bridge.themeSchemes], ["跟随系统", "浅色", "深色"]
        )
        # 兼容 themes：样式列表 + 旧字段
        self.assertEqual(
            [item["value"] for item in bridge.themes], ["solid", "glass", "ocean"]
        )
        self.assertTrue(all("label" in item for item in bridge.themes))

    def test_set_style_and_scheme_emits(self) -> None:
        bridge = self.bridge
        changes: list[str] = []
        bridge.themeChanged.connect(changes.append)
        bridge.setThemeStyle("ocean")
        self.assertEqual(bridge.themeStyle, "ocean")
        self.assertEqual(bridge.themeMode, "ocean")
        self.assertEqual(changes, ["Dark"])
        bridge.setThemeScheme("light")
        self.assertEqual(bridge.themeScheme, "light")
        self.assertEqual(bridge.effectiveScheme, "light")
        self.assertEqual(changes, ["Dark", "Light"])
        # 重复设置同值不重复发信号
        bridge.setThemeStyle("ocean")
        bridge.setThemeScheme("light")
        self.assertEqual(len(changes), 2)

    def test_style_and_scheme_persist(self) -> None:
        bridge = self.bridge
        bridge.setThemeStyle("glass")
        bridge.setThemeScheme("light")
        reloaded = self._reload()
        self.assertEqual(reloaded.themeStyle, "glass")
        self.assertEqual(reloaded.themeScheme, "light")
        self.assertEqual(reloaded._settings.get("theme_style"), "glass")
        self.assertEqual(reloaded._settings.get("theme_scheme"), "light")
        raw = json.loads(
            (Path(os.environ["SHENQING_DATA_DIR"]) / "settings.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(raw["theme_style"], "glass")
        self.assertEqual(raw["theme_scheme"], "light")
        self.assertNotIn(LEGACY_THEME_KEY, raw)

    def test_invalid_style_scheme_rejected(self) -> None:
        bridge = self.bridge
        changes: list[str] = []
        bridge.themeChanged.connect(changes.append)
        bridge.setThemeStyle("ocean")
        bridge.setThemeScheme("light")
        changes.clear()
        for bad in ("nope", "", "Glass", "custom:ghost", "custom:"):
            bridge.setThemeStyle(bad)
        for bad in ("sepia", "", "Auto!", "sepia2"):
            bridge.setThemeScheme(bad)
        self.assertEqual(bridge.themeStyle, "ocean")
        self.assertEqual(bridge.themeScheme, "light")
        self.assertEqual(changes, [])

    def test_theme_mode_compat_mapping(self) -> None:
        bridge = self.bridge
        mapping = [
            ("light", "solid", "light"),
            ("solid", "solid", "dark"),
            ("glass", "glass", "dark"),
            ("ocean", "ocean", "dark"),
        ]
        for old, style, scheme in mapping:
            bridge.setThemeMode(old)
            self.assertEqual(bridge.themeStyle, style, old)
            self.assertEqual(bridge.themeScheme, scheme, old)
            self.assertEqual(bridge.themeMode, style, old)
        self.assertTrue(bridge.installCustomTheme("aurora", "极光", "", PALETTE))
        bridge.setThemeMode("custom:aurora")
        self.assertEqual(bridge.themeStyle, "custom:aurora")
        self.assertEqual(bridge.themeMode, "custom:aurora")
        self.assertEqual(bridge.themeScheme, "auto")
        # 非法旧值忽略
        before = (bridge.themeStyle, bridge.themeScheme)
        bridge.setThemeMode("neon")
        bridge.setThemeMode("custom:missing")
        self.assertEqual((bridge.themeStyle, bridge.themeScheme), before)

    def test_system_scheme_change_emits_only_in_auto(self) -> None:
        bridge = self.bridge
        changes: list[str] = []
        bridge.themeChanged.connect(changes.append)
        self.assertEqual(bridge.themeScheme, "auto")
        with mock.patch.object(theme_service, "system_scheme", return_value="light"):
            bridge._on_system_scheme_changed()
            self.assertEqual(bridge.effectiveScheme, "light")
        self.assertEqual(changes, ["Light"])
        # 显式配色不跟随系统
        bridge.setThemeScheme("dark")
        changes.clear()
        with mock.patch.object(theme_service, "system_scheme", return_value="light"):
            bridge._on_system_scheme_changed()
        self.assertEqual(changes, [])
        self.assertEqual(bridge.effectiveScheme, "dark")

    def test_custom_style_palette_and_fallback(self) -> None:
        bridge = self.bridge
        self.assertTrue(bridge.installCustomTheme("aurora", "极光", "", PALETTE))
        self.assertEqual(bridge.themeStyle, "custom:aurora")
        self.assertEqual(bridge.customThemePalette, PALETTE)
        # 设置里残留已删除的 custom:<id> → 样式回退 solid
        bridge._settings.set("theme_style", "custom:ghost")
        self.assertEqual(bridge.themeStyle, DEFAULT_THEME_STYLE)
        self.assertEqual(bridge.customThemePalette, {})


if __name__ == "__main__":
    unittest.main()
