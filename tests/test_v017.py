"""v0.17 后端测试：单实例激活 / 海洋主题 / 中文字体优先 / 系统音量刷新。"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
import types
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SHENQING_NO_SCAN"] = "1"
os.environ["SHENQING_NO_KEEPER"] = "1"

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

from shenqing import app as app_module  # noqa: E402
from shenqing import __version__ as pkg_version  # noqa: E402
from shenqing.app import (  # noqa: E402
    SHOW_MAIN_MESSAGE,
    SINGLE_INSTANCE_NAME,
    SingleInstanceServer,
    _activate_main_window,
    _notify_existing_instance,
    _send_single_instance_message,
    _single_instance_enabled,
    acquire_single_instance,
)
from shenqing.bridge.app_bridge import AppBridge  # noqa: E402
from shenqing.consts import (  # noqa: E402
    APP_VERSION,
    DEFAULT_THEME,
    MAX_FONT_FAMILIES,
    PREFERRED_CJK_FONTS,
    THEMES,
)
from shenqing.services import system_control  # noqa: E402


def _wait_until(predicate, timeout: float = 5.0) -> bool:  # noqa: ANN001
    deadline = time.time() + timeout
    while time.time() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return bool(predicate())


class _BridgeCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SHENQING_DATA_DIR"] = self._tmp.name
        self.bridge = AppBridge()
        self.toasts: list[str] = []
        self.bridge.toast.connect(self.toasts.append)

    def tearDown(self) -> None:
        try:
            self.bridge._session.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.bridge._pomodoro.stop()
        except Exception:  # noqa: BLE001
            pass
        self.bridge._shutdown_services()
        try:
            self.bridge.deleteLater()
        except RuntimeError:
            pass
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


# ================= 1. 海洋主题 =================
class ThemesConstTest(unittest.TestCase):
    def test_four_themes_in_order(self) -> None:
        self.assertEqual(
            [item["value"] for item in THEMES], ["solid", "light", "glass", "ocean"]
        )
        self.assertEqual(len(THEMES), 4)
        ocean = THEMES[-1]
        self.assertEqual(ocean["label"], "海洋")
        self.assertEqual(ocean["desc"], "深海渐变与静态浪花")
        self.assertFalse(ocean["experimental"])
        self.assertEqual(DEFAULT_THEME, "solid")
        # 前三项保持原样
        self.assertEqual([item["value"] for item in THEMES[:3]], ["solid", "light", "glass"])


class ThemeModeBridgeTest(_BridgeCase):
    def test_themes_property_exposes_ocean(self) -> None:
        themes = self.bridge.themes
        self.assertEqual(len(themes), 4)
        self.assertEqual([item["value"] for item in themes], ["solid", "light", "glass", "ocean"])
        self.assertEqual(themes[-1]["label"], "海洋")
        self.assertFalse(themes[-1]["experimental"])

    def test_set_theme_ocean_takes_effect(self) -> None:
        changes: list[str] = []
        self.bridge.themeChanged.connect(changes.append)
        self.assertEqual(self.bridge.themeMode, "solid")
        self.bridge.setThemeMode("ocean")
        self.assertEqual(self.bridge.themeMode, "ocean")
        self.assertEqual(changes, ["Dark"])
        # 持久化：重开桥后仍是海洋
        reloaded = self._reload()
        self.assertEqual(reloaded.themeMode, "ocean")
        self.assertEqual(reloaded._settings.get("theme_mode"), "ocean")

    def test_invalid_theme_rejected(self) -> None:
        self.bridge.setThemeMode("ocean")
        for bad in ("nope", "", "OCEAN", "glass "):
            self.bridge.setThemeMode(bad)
            self.assertEqual(self.bridge.themeMode, "ocean")

    def test_legacy_bad_theme_mode_falls_back_to_solid(self) -> None:
        self.bridge._settings.set("theme_mode", "legacy-dark")
        self.assertEqual(self.bridge.themeMode, DEFAULT_THEME)
        # 旧设置里没有 theme_mode → 默认 solid
        self.bridge._settings.set("theme_mode", "")
        self.assertEqual(self.bridge.themeMode, DEFAULT_THEME)


# ================= 2. 中文字体优先 =================
class FontFamiliesTest(_BridgeCase):
    def _families(self, names: list[str]) -> list[str]:
        with mock.patch.object(QFontDatabase, "families", return_value=list(names)):
            return self.bridge.uiFontFamilies

    def test_preferred_fonts_come_first_in_order(self) -> None:
        families = self._families(
            [
                "@SimSun",
                "Zzz Font",
                "Arial",
                "Microsoft YaHei UI",
                "微软雅黑",
                "Consolas",
            ]
        )
        self.assertEqual(
            families, ["微软雅黑", "Microsoft YaHei UI", "Arial", "Consolas", "Zzz Font"]
        )

    def test_preferred_absent_falls_back_to_sorted_system_fonts(self) -> None:
        families = self._families(["Zzz Font", "Arial", "Consolas"])
        self.assertEqual(families, ["Arial", "Consolas", "Zzz Font"])
        self.assertTrue(all(family not in PREFERRED_CJK_FONTS for family in families))

    def test_limit_dedupe_and_vertical_filter(self) -> None:
        names = [f"Font{index:03d}" for index in range(MAX_FONT_FAMILIES + 50)]
        names += ["Font000", "@VerticalFont"]
        families = self._families(names)
        self.assertEqual(len(families), MAX_FONT_FAMILIES)
        self.assertEqual(len(families), len(set(families)))
        self.assertTrue(all(not family.startswith("@") for family in families))
        self.assertEqual(families, [f"Font{index:03d}" for index in range(MAX_FONT_FAMILIES)])

    def test_empty_enumeration_returns_default_font(self) -> None:
        with mock.patch.object(QFontDatabase, "families", return_value=[]):
            families = self.bridge.uiFontFamilies
            expected = self.bridge.defaultFontFamily
        self.assertEqual(families, [expected])
        self.assertTrue(families[0])

    def test_default_font_is_microsoft_yahei_ui(self) -> None:
        with mock.patch.object(
            QFontDatabase, "families", return_value=["Segoe UI", "Microsoft YaHei UI"]
        ):
            self.assertEqual(self.bridge.defaultFontFamily, "Microsoft YaHei UI")
        with mock.patch.object(
            QFontDatabase, "families", return_value=["Segoe UI", "微软雅黑"]
        ):
            self.assertEqual(self.bridge.defaultFontFamily, "微软雅黑")
        # 没有微软雅黑时回落到 Qt 默认字体（非空）
        with mock.patch.object(QFontDatabase, "families", return_value=["Segoe UI"]):
            self.assertTrue(self.bridge.defaultFontFamily)

    def test_real_environment_order_is_preferred_then_sorted(self) -> None:
        families = self.bridge.uiFontFamilies
        present = [family for family in PREFERRED_CJK_FONTS if family in families]
        self.assertEqual(families[: len(present)], present)
        self.assertEqual(families[len(present) :], sorted(families[len(present) :]))
        self.assertLessEqual(len(families), MAX_FONT_FAMILIES)


# ================= 3. 系统音量定时刷新 =================
class SystemVolumeRefreshTest(_BridgeCase):
    def test_timer_configured(self) -> None:
        self.assertTrue(self.bridge._volume_timer.isActive())
        self.assertEqual(self.bridge._volume_timer.interval(), 2000)

    def test_refresh_updates_value_and_notifies(self) -> None:
        self.bridge._volume = -1
        changes: list[int] = []
        self.bridge.settingsChanged.connect(lambda: changes.append(1))
        with mock.patch.object(system_control, "get_volume", return_value=42):
            self.assertEqual(self.bridge._refresh_system_volume(), 42)
        self.assertEqual(self.bridge.systemVolume, 42)
        self.assertGreaterEqual(len(changes), 1)
        # 值没变不重复发信号
        before = len(changes)
        with mock.patch.object(system_control, "get_volume", return_value=42):
            self.assertEqual(self.bridge._refresh_system_volume(), 42)
        self.assertEqual(len(changes), before)

    def test_refresh_failure_keeps_old_value(self) -> None:
        self.bridge._volume = 30
        with mock.patch.object(system_control, "get_volume", return_value=-1):
            self.assertEqual(self.bridge._refresh_system_volume(), 30)
        self.assertEqual(self.bridge.systemVolume, 30)

    def test_refresh_exception_is_safe(self) -> None:
        self.bridge._volume = 55
        with mock.patch.object(system_control, "get_volume", side_effect=RuntimeError("boom")):
            self.assertEqual(self.bridge._refresh_system_volume(), 55)

    def test_is_admin_readable_from_qml_layer(self) -> None:
        # 需求 4：isAdmin 仍是可通过 App 读取的 Property
        self.assertIsInstance(bool(self.bridge.isAdmin), bool)
        self.assertIsInstance(self.bridge.systemVolume, int)


# ================= 4. 单实例（QLocalServer / QLocalSocket） =================
class _FakeToast:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def emit(self, text: str) -> None:
        self.messages.append(str(text))


class _FakeBridge:
    def __init__(self, busy: bool = False, onboarding: bool = False) -> None:
        self.busy = busy
        self.needsOnboarding = onboarding
        self.toast = _FakeToast()


class _FakeRoot:
    def __init__(self, state: Qt.WindowState = Qt.WindowState.WindowNoState) -> None:
        self.visible = False
        self._state = state
        self.show_calls = 0
        self.show_normal_calls = 0
        self.raise_calls = 0
        self.activate_calls = 0
        self.states: list[object] = []

    def show(self) -> None:
        self.visible = True
        self.show_calls += 1

    def showNormal(self) -> None:
        self.visible = True
        self._state = Qt.WindowState.WindowNoState
        self.show_normal_calls += 1

    def windowState(self):  # noqa: ANN201
        return self._state

    def setWindowState(self, state) -> None:  # noqa: ANN001
        self._state = state
        self.states.append(state)

    def raise_(self) -> None:
        self.raise_calls += 1

    def requestActivate(self) -> None:
        self.activate_calls += 1


def _fake_window(root: _FakeRoot | None) -> types.SimpleNamespace:
    return types.SimpleNamespace(root_window=root)


class ActivationHelperTest(unittest.TestCase):
    def test_hidden_window_is_shown_and_raised(self) -> None:
        root = _FakeRoot()
        window = _fake_window(root)
        self.assertEqual(_activate_main_window(window, _FakeBridge()), "activated")
        self.assertTrue(root.visible)
        self.assertEqual(root.show_calls, 1)
        self.assertGreaterEqual(root.raise_calls, 1)
        self.assertGreaterEqual(root.activate_calls, 1)

    def test_minimized_window_is_restored(self) -> None:
        root = _FakeRoot(Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.assertEqual(_activate_main_window(_fake_window(root), _FakeBridge()), "activated")
        self.assertEqual(root.show_normal_calls, 1)
        self.assertTrue(root.visible)
        state = root.windowState()
        state_value = getattr(state, "value", state)
        self.assertFalse(bool(int(state_value) & Qt.WindowState.WindowMinimized.value))

    def test_locked_session_only_hints(self) -> None:
        root = _FakeRoot()
        bridge = _FakeBridge(busy=True)
        self.assertEqual(_activate_main_window(_fake_window(root), bridge), "locked")
        self.assertEqual(root.show_calls, 0)
        self.assertEqual(root.show_normal_calls, 0)
        self.assertGreaterEqual(root.raise_calls, 1)
        self.assertTrue(any("专注" in message for message in bridge.toast.messages))

    def test_onboarding_only_hints(self) -> None:
        root = _FakeRoot()
        bridge = _FakeBridge(onboarding=True)
        self.assertEqual(_activate_main_window(_fake_window(root), bridge), "onboarding")
        self.assertEqual(root.show_calls, 0)
        self.assertTrue(any("引导" in message for message in bridge.toast.messages))

    def test_busy_takes_priority_over_onboarding(self) -> None:
        root = _FakeRoot()
        bridge = _FakeBridge(busy=True, onboarding=True)
        self.assertEqual(_activate_main_window(_fake_window(root), bridge), "locked")

    def test_no_root_returns_none(self) -> None:
        self.assertEqual(_activate_main_window(_fake_window(None)), "none")
        self.assertEqual(_activate_main_window(None), "none")

    def test_smoke_disables_single_instance(self) -> None:
        self.assertFalse(_single_instance_enabled(argparse.Namespace(smoke=True)))
        self.assertTrue(_single_instance_enabled(argparse.Namespace(smoke=False)))
        self.assertTrue(_single_instance_enabled(argparse.Namespace()))


class SingleInstanceTransportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.name = f"{SINGLE_INSTANCE_NAME}-{uuid.uuid4().hex}"
        self.servers: list[SingleInstanceServer] = []

    def tearDown(self) -> None:
        for server in self.servers:
            server.stop()

    def _server(self) -> SingleInstanceServer:
        server = SingleInstanceServer(self.name)
        self.assertTrue(server.start())
        self.servers.append(server)
        return server

    def test_show_main_roundtrip(self) -> None:
        server = self._server()
        shows: list[int] = []
        messages: list[str] = []
        server.showMainRequested.connect(lambda: shows.append(1))
        server.messageReceived.connect(messages.append)
        self.assertTrue(_notify_existing_instance(self.name, timeout_ms=1000))
        self.assertTrue(_wait_until(lambda: bool(shows)))
        self.assertEqual(messages, [SHOW_MAIN_MESSAGE])

    def test_unknown_message_is_not_show(self) -> None:
        server = self._server()
        shows: list[int] = []
        messages: list[str] = []
        server.showMainRequested.connect(lambda: shows.append(1))
        server.messageReceived.connect(messages.append)
        self.assertTrue(_send_single_instance_message("ping", self.name, timeout_ms=1000))
        self.assertTrue(_wait_until(lambda: bool(messages)))
        QApplication.processEvents()
        self.assertEqual(messages, ["ping"])
        self.assertEqual(shows, [])

    def test_no_primary_instance_returns_false(self) -> None:
        name = f"{SINGLE_INSTANCE_NAME}-{uuid.uuid4().hex}"
        self.assertFalse(_send_single_instance_message(SHOW_MAIN_MESSAGE, name, timeout_ms=100))

    def test_server_name_and_listening(self) -> None:
        server = self._server()
        self.assertEqual(server.name, self.name)
        self.assertTrue(server.listening)
        server.stop()
        self.assertFalse(server.listening)


class TwoInstanceSimulationTest(unittest.TestCase):
    """在同进程里模拟「主实例 + 第二个实例」。"""

    def setUp(self) -> None:
        self.name = f"{SINGLE_INSTANCE_NAME}-{uuid.uuid4().hex}"
        self._tmp = tempfile.TemporaryDirectory()
        self._old_data_dir = os.environ.get("SHENQING_DATA_DIR")
        os.environ["SHENQING_DATA_DIR"] = self._tmp.name
        self.servers: list[SingleInstanceServer] = []

    def tearDown(self) -> None:
        for server in self.servers:
            server.stop()
        if self._old_data_dir is None:
            os.environ.pop("SHENQING_DATA_DIR", None)
        else:
            os.environ["SHENQING_DATA_DIR"] = self._old_data_dir
        self._tmp.cleanup()

    def _args(self, smoke: bool = False, restarted: bool = False) -> argparse.Namespace:
        return argparse.Namespace(smoke=smoke, restarted=restarted)

    def _start_primary(self) -> SingleInstanceServer:
        should_start, server = acquire_single_instance(self._args(), self.name)
        self.assertTrue(should_start)
        self.assertIsNotNone(server)
        assert server is not None
        self.servers.append(server)
        self.assertTrue(server.listening)
        return server

    def test_second_launch_does_not_start_second_instance_and_shows_main(self) -> None:
        server = self._start_primary()
        root = _FakeRoot()
        window = _fake_window(root)
        bridge = _FakeBridge()
        server.showMainRequested.connect(
            lambda: _activate_main_window(window, bridge)
        )

        should_start, second_server = acquire_single_instance(self._args(), self.name)

        # 第二个实例不创建窗口：调用方拿到 False 后 main() 直接 return 0
        self.assertFalse(should_start)
        self.assertIsNone(second_server)
        # 主实例收到 show-main 并激活主界面
        self.assertTrue(_wait_until(lambda: root.show_calls >= 1))
        self.assertTrue(root.visible)
        self.assertGreaterEqual(root.raise_calls, 1)

    def test_second_launch_while_locked_only_hints(self) -> None:
        server = self._start_primary()
        root = _FakeRoot()
        window = _fake_window(root)
        bridge = _FakeBridge(busy=True)
        server.showMainRequested.connect(
            lambda: _activate_main_window(window, bridge)
        )
        should_start, second_server = acquire_single_instance(self._args(), self.name)
        self.assertFalse(should_start)
        self.assertIsNone(second_server)
        self.assertTrue(_wait_until(lambda: bool(bridge.toast.messages)))
        self.assertEqual(root.show_calls, 0)
        self.assertTrue(any("专注" in message for message in bridge.toast.messages))

    def test_second_launch_while_onboarding_only_hints(self) -> None:
        server = self._start_primary()
        root = _FakeRoot()
        window = _fake_window(root)
        bridge = _FakeBridge(onboarding=True)
        server.showMainRequested.connect(
            lambda: _activate_main_window(window, bridge)
        )
        should_start, second_server = acquire_single_instance(self._args(), self.name)
        self.assertFalse(should_start)
        self.assertIsNone(second_server)
        self.assertTrue(_wait_until(lambda: bool(bridge.toast.messages)))
        self.assertEqual(root.show_calls, 0)

    def test_smoke_mode_skips_single_instance(self) -> None:
        should_start, server = acquire_single_instance(self._args(smoke=True), self.name)
        self.assertTrue(should_start)
        self.assertIsNone(server)
        # 冒烟启动不会占用套接字
        self.assertFalse(_notify_existing_instance(self.name, timeout_ms=100))

    def test_restarted_does_not_notify_existing_primary(self) -> None:
        with mock.patch.object(
            app_module, "_single_instance_lock", return_value=None
        ), mock.patch.object(app_module, "_notify_existing_instance") as notify:
            should_start, server = acquire_single_instance(
                self._args(restarted=True), self.name
            )
        self.assertFalse(should_start)
        self.assertIsNone(server)
        self.assertFalse(notify.called)


class VersionTest(unittest.TestCase):
    def test_version_not_older_than_v0163(self) -> None:
        version_tuple = tuple(int(part) for part in APP_VERSION.split("."))
        self.assertGreaterEqual(version_tuple, (0, 16, 3))
        self.assertEqual(pkg_version, APP_VERSION)


if __name__ == "__main__":
    unittest.main()
