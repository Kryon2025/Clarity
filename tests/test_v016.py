"""v0.16 后端测试：多下载源 / 无暂停退出 / 连点退出 / 清番 / 首次引导 / 速启重启。"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SHENQING_NO_SCAN"] = "1"
os.environ["SHENQING_NO_KEEPER"] = "1"

from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

from shenqing import __version__ as pkg_version  # noqa: E402
from shenqing.app import _hide_window  # noqa: E402
from shenqing.bridge import app_bridge  # noqa: E402
from shenqing.bridge.app_bridge import AppBridge  # noqa: E402
from shenqing.consts import APP_VERSION  # noqa: E402
from shenqing.services import elevation, keeper, pomodoro, updater  # noqa: E402

_CUSTOM_RELEASE = {
    "version": "1.2.0",
    "notes": "自定义源说明",
    "assets": [
        {"name": "Clarity-portable.exe", "url": "https://example.com/p.exe", "size": 10},
        {"name": "Clarity-Setup.exe", "url": "https://example.com/s.exe", "size": 20},
    ],
}


class _Clock:
    """可控 monotonic 时钟。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.value = float(start)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


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


# ================= 更新下载源 =================
class UpdateSourceServiceTest(unittest.TestCase):
    def test_builtin_sources_constants(self) -> None:
        self.assertEqual(
            updater.GITHUB_LATEST,
            "https://api.github.com/repos/Kryon2025/Clarity/releases/latest",
        )
        self.assertIn("gitlink.org.cn/api/v1/repos/Kryon/Clarity", updater.GITLINK_LATEST)
        self.assertIn("gitee.com/api/v5/repos/kryonF/Clarity", updater.GITEE_LATEST)
        ids = [item["id"] for item in updater.source_choices()]
        self.assertEqual(ids, ["github", "gitlink", "gitee"])
        kinds = [item["kind"] for item in updater.source_choices()]
        self.assertEqual(kinds, ["github", "gitlink", "gitee"])
        self.assertTrue(all(item["custom"] is False for item in updater.source_choices()))

    def test_custom_source_choices_and_validation(self) -> None:
        item = updater.make_custom_source("内部源", "https://example.com/api/releases", "tk")
        self.assertTrue(item["id"].startswith("custom:"))
        self.assertEqual(item["token"], "tk")
        choices = updater.source_choices([item])
        self.assertEqual(choices[-1]["kind"], "custom")
        self.assertTrue(choices[-1]["custom"])
        for bad in ("", "ftp://example.com/x", "not-a-url", "http://"):
            with self.assertRaises(ValueError):
                updater.make_custom_source("bad", bad)
        with self.assertRaises(ValueError):
            updater.make_custom_source("dup", item["url"], "", [item])
        self.assertEqual(updater.resolve_source_id("nope", [item]), "")
        self.assertEqual(updater.resolve_source_id(item["id"], [item]), item["id"])

    def test_github_source(self) -> None:
        release = {
            "tag_name": "v0.16.1",
            "body": "GitHub 更新说明",
            "html_url": "https://github.com/Kryon2025/Clarity/releases/tag/v0.16.1",
            "assets": [
                {"name": "Clarity-portable.exe", "browser_download_url": "https://x/p.exe"},
                {
                    "name": "Clarity-Setup.exe",
                    "browser_download_url": "https://x/s.exe",
                    "size": 20,
                },
            ],
        }
        with mock.patch.object(updater, "_fetch_release", return_value=release):
            info, error = updater.check_latest_detail("0.15.0", source_id="github")
        self.assertEqual(error, "")
        self.assertIsNotNone(info)
        self.assertEqual(info["version"], "0.16.1")
        self.assertEqual(info["assetName"], "Clarity-Setup.exe")
        self.assertEqual(info["source"], "github")

    def test_gitlink_source_and_fallback(self) -> None:
        payload = {
            "tag_name": "v0.16.2",
            "body": "GitLink",
            "assets": [{"name": "Clarity-Setup.exe", "url": "https://gl/s.exe", "size": 7}],
        }
        with mock.patch.object(updater, "_read_json", return_value=payload) as reader:
            info, error = updater.check_latest_detail("0.15.0", source_id="gitlink")
        self.assertEqual(error, "")
        self.assertEqual(info["assetUrl"], "https://gl/s.exe")
        self.assertEqual(reader.call_args.args[0], updater.GITLINK_LATEST)

        # /releases/latest 失败 → 回退 /releases 列表取首个
        with mock.patch.object(
            updater,
            "_read_json",
            side_effect=[URLError("boom"), [payload, {"tag_name": "v0.16.0"}]],
        ) as reader:
            info, error = updater.check_latest_detail("0.15.0", source_id="gitlink")
        self.assertEqual(error, "")
        self.assertEqual(info["version"], "0.16.2")
        self.assertEqual(reader.call_args.args[0], updater.GITLINK_RELEASES)

        # 两个接口都失败 → 可读错误
        with mock.patch.object(updater, "_read_json", side_effect=URLError("down")):
            release, error = updater.fetch_release_detail("gitlink")
        self.assertIsNone(release)
        self.assertIn("GitLink", error)
        self.assertIn("失败", error)

    def test_gitee_source(self) -> None:
        payload = {
            "tag_name": "v0.16.3",
            "body": "Gitee 说明",
            "html_url": "https://gitee.com/kryonF/Clarity/releases/tag/v0.16.3",
            "assets": [
                {"name": "Clarity-Setup.exe", "browser_download_url": "https://gitee.com/s.exe"}
            ],
        }
        with mock.patch.object(updater, "_read_json", return_value=payload):
            info, error = updater.check_latest_detail("0.15.0", source_id="gitee")
        self.assertEqual(error, "")
        self.assertEqual(info["version"], "0.16.3")
        self.assertEqual(info["assetUrl"], "https://gitee.com/s.exe")
        self.assertIn("gitee.com", info["pageUrl"])

    def test_custom_source(self) -> None:
        source = updater.make_custom_source("内部源", "https://example.com/api/releases", "tk")
        with mock.patch.object(
            updater, "_read_json", return_value=_CUSTOM_RELEASE
        ) as reader:
            info, error = updater.check_latest_detail(
                "1.0.0", source_id=source["id"], custom_sources=[source]
            )
        self.assertEqual(error, "")
        self.assertEqual(info["version"], "1.2.0")
        self.assertEqual(info["notes"], "自定义源说明")
        self.assertEqual(info["assetName"], "Clarity-Setup.exe")
        self.assertEqual(info["assetUrl"], "https://example.com/s.exe")
        self.assertEqual(reader.call_args.args[1], "tk")

        # 列表返回（兼容 /releases 风格）也能取首个
        with mock.patch.object(updater, "_read_json", return_value=[_CUSTOM_RELEASE]):
            release = updater.fetch_release(source["id"], [source])
        self.assertEqual(release["tag_name"], "1.2.0")

    def test_custom_source_http_error_readable(self) -> None:
        source = updater.make_custom_source("内部源", "https://example.com/api/releases")
        error = HTTPError("https://example.com/api/releases", 404, "Not Found", {}, None)
        with mock.patch.object(updater, "_read_json", side_effect=error):
            release, message = updater.fetch_release_detail(source["id"], [source])
        self.assertIsNone(release)
        self.assertIn("404", message)
        self.assertIn("内部源", message)


class UpdateSourceBridgeTest(_BridgeCase):
    def test_sources_and_switching(self) -> None:
        bridge = self.bridge
        self.assertEqual(bridge.updateSource, "github")
        ids = [item["id"] for item in bridge.updateSources]
        self.assertEqual(ids, ["github", "gitlink", "gitee"])
        self.assertTrue(all(item["custom"] is False for item in bridge.updateSources))
        self.assertTrue(bridge.setUpdateSource("gitee"))
        self.assertEqual(bridge.updateSource, "gitee")
        self.assertTrue(any("已切换更新源" in item for item in self.toasts))
        self.assertFalse(bridge.setUpdateSource("nope"))
        self.assertEqual(bridge.updateSourceError, "未知的更新源")

    def test_custom_source_crud(self) -> None:
        bridge = self.bridge
        source_id = bridge.addCustomUpdateSource("内部源", "https://example.com/api", "secret")
        self.assertTrue(source_id.startswith("custom:"))
        self.assertEqual(bridge.updateSource, source_id)
        self.assertEqual(
            bridge.customUpdateSources,
            [{"id": source_id, "name": "内部源", "url": "https://example.com/api"}],
        )
        self.assertNotIn("secret", str(bridge.customUpdateSources))
        added = bridge.updateSources[-1]
        self.assertEqual(added["id"], source_id)
        self.assertTrue(added["custom"])
        # 非法 URL
        self.assertEqual(bridge.addCustomUpdateSource("bad", "ftp://x"), "")
        self.assertIn("http", bridge.updateSourceError)
        # 删除当前源 → 回退 GitHub
        self.assertTrue(bridge.removeCustomUpdateSource(source_id))
        self.assertEqual(bridge.updateSource, "github")
        self.assertEqual(bridge.customUpdateSources, [])
        self.assertFalse(bridge.removeCustomUpdateSource(source_id))

    def test_check_update_uses_current_source(self) -> None:
        bridge = self.bridge
        bridge.setUpdateSource("gitee")
        with mock.patch.object(
            updater, "check_latest_detail", return_value=(None, "")
        ) as checker:
            bridge.checkUpdate()
            deadline = time.time() + 5
            while time.time() < deadline and bridge.updateState == "checking":
                QApplication.processEvents()
                time.sleep(0.01)
        self.assertGreaterEqual(checker.call_count, 1)
        kwargs = checker.call_args.kwargs
        self.assertEqual(kwargs.get("source_id"), "gitee")
        self.assertEqual(kwargs.get("custom_sources"), [])

    def test_check_update_error_sets_source_error(self) -> None:
        bridge = self.bridge
        with mock.patch.object(
            updater,
            "check_latest_detail",
            return_value=(None, "GitLink 源检查失败：网络请求失败"),
        ):
            bridge.checkUpdate()
            deadline = time.time() + 5
            while time.time() < deadline and bridge.updateState == "checking":
                QApplication.processEvents()
                time.sleep(0.01)
        self.assertEqual(bridge.updateState, "error")
        self.assertIn("GitLink", bridge.updateSourceError)
        self.assertTrue(any("检查更新失败" in item for item in self.toasts))

    def test_check_update_success_clears_error(self) -> None:
        bridge = self.bridge
        info = {
            "version": "0.16.9",
            "tag": "v0.16.9",
            "notes": "n",
            "pageUrl": "https://x",
            "assetName": "Clarity-Setup.exe",
            "assetUrl": "https://x/s.exe",
            "assetSize": 1,
            "source": "github",
        }
        bridge._update_source_error = "旧错误"
        with mock.patch.object(
            updater, "check_latest_detail", return_value=(info, "")
        ):
            bridge.checkUpdate()
            deadline = time.time() + 5
            while time.time() < deadline and bridge.updateState == "checking":
                QApplication.processEvents()
                time.sleep(0.01)
        self.assertEqual(bridge.updateState, "available")
        self.assertEqual(bridge.updateSourceError, "")
        self.assertEqual(bridge.updateLatestVersion, "0.16.9")


# ================= 覆清/深清 无暂停、无退出 =================
class NoPauseNoStopTest(_BridgeCase):
    def _start(self, mode: str, minutes: int = 2) -> None:
        space = self.bridge._spaces.get_by_mode(mode)
        self.bridge._begin_space_session(space, mode, minutes)

    def test_light_can_pause_resume_and_stop(self) -> None:
        bridge = self.bridge
        self._start("light")
        self.assertTrue(bridge.canPause)
        bridge.pauseSession()
        self.assertEqual(bridge.state, "paused")
        self.assertFalse(bridge.canPause)
        bridge.resumeSession()
        self.assertEqual(bridge.state, "running")
        bridge.stopSession()
        self.assertFalse(bridge.busy)

    def test_medium_pause_rejected(self) -> None:
        bridge = self.bridge
        self._start("medium")
        self.assertFalse(bridge.canPause)
        bridge.pauseSession()
        self.assertEqual(bridge.state, "running")
        self.assertEqual(bridge._session.pauses, 0)
        self.assertTrue(any("没有暂停" in item for item in self.toasts))

    def test_heavy_pause_rejected(self) -> None:
        bridge = self.bridge
        self._start("heavy")
        bridge.pauseSession()
        self.assertEqual(bridge.state, "running")
        self.assertTrue(any("不可暂停" in item for item in self.toasts))

    def test_medium_stop_rejected(self) -> None:
        bridge = self.bridge
        self._start("medium")
        bridge.stopSession()
        self.assertTrue(bridge.busy)
        self.assertTrue(any("覆清不可提前结束" in item for item in self.toasts))

    def test_heavy_stop_rejected(self) -> None:
        bridge = self.bridge
        self._start("heavy")
        bridge.stopSession()
        self.assertTrue(bridge.busy)
        self.assertTrue(any("不可提前结束" in item for item in self.toasts))

    def test_trial_medium_can_stop(self) -> None:
        bridge = self.bridge
        bridge.startTrial("medium")
        self.assertTrue(bridge.busy)
        self.assertTrue(bridge.trialActive)
        bridge.stopSession()
        self.assertFalse(bridge.busy)


# ================= 连点时间显示 10 次 → 警告退出 =================
class TimeClickExitTest(_BridgeCase):
    def _start(self, mode: str, minutes: int = 2) -> None:
        space = self.bridge._spaces.get_by_mode(mode)
        self.bridge._begin_space_session(space, mode, minutes)

    def _click(self, count: int) -> list[bool]:
        return [self.bridge.registerTimeClick() for _ in range(count)]

    def test_medium_ten_clicks_requests_exit_warning(self) -> None:
        bridge = self.bridge
        self._start("medium")
        warnings: list[int] = []
        bridge.exitWarningRequested.connect(lambda: warnings.append(1))
        with mock.patch.object(
            time, "monotonic", side_effect=[i * 0.1 for i in range(10)]
        ):
            results = self._click(10)
        self.assertEqual(warnings, [1])
        self.assertEqual(results, [False] * 9 + [True])
        self.assertTrue(bridge.exitWarningPending)
        # 计数已清零：第 11 次不会立刻再次触发，警告保持到用户取消/确认
        with mock.patch.object(time, "monotonic", return_value=100.0):
            self.assertFalse(bridge.registerTimeClick())
        self.assertEqual(warnings, [1])
        self.assertTrue(bridge.exitWarningPending)

    def test_light_clicks_do_nothing(self) -> None:
        bridge = self.bridge
        self._start("light")
        warnings: list[int] = []
        bridge.exitWarningRequested.connect(lambda: warnings.append(1))
        with mock.patch.object(time, "monotonic", return_value=1.0):
            self.assertEqual(self._click(12), [False] * 12)
        self.assertEqual(warnings, [])

    def test_six_second_window_resets_counter(self) -> None:
        bridge = self.bridge
        self._start("medium")
        warnings: list[int] = []
        bridge.exitWarningRequested.connect(lambda: warnings.append(1))
        # 每次间隔 7 秒，旧点击都被挤出 6 秒窗口，永远凑不满 10 次
        with mock.patch.object(
            time, "monotonic", side_effect=[i * 7.0 for i in range(12)]
        ):
            self.assertEqual(self._click(12), [False] * 12)
        self.assertEqual(warnings, [])

    def test_cancel_clears_warning(self) -> None:
        bridge = self.bridge
        self._start("medium")
        with mock.patch.object(time, "monotonic", return_value=5.0):
            self._click(10)
        self.assertTrue(bridge.exitWarningPending)
        bridge.cancelExitWarning()
        self.assertFalse(bridge.exitWarningPending)

    def test_confirm_force_ends_and_marks_interrupted(self) -> None:
        bridge = self.bridge
        self._start("medium", minutes=2)
        for _ in range(61):
            bridge._session._on_timeout()
        bridge.confirmExitSession()
        self.assertFalse(bridge.busy)
        self.assertFalse(bridge.exitWarningPending)
        last = bridge._stats.last_session()
        self.assertTrue(last.get("interrupted"))
        self.assertFalse(last.get("completed"))
        self.assertGreaterEqual(last.get("minutes", 0), 1)
        self.assertTrue(any("强制结束" in item for item in self.toasts))

    def test_confirm_on_light_does_not_end_session(self) -> None:
        bridge = self.bridge
        self._start("light")
        bridge.confirmExitSession()
        self.assertTrue(bridge.busy)


# ================= 清番（番茄钟） =================
class PomodoroServiceTest(unittest.TestCase):
    SETTINGS = {
        "pomodoro_work_minutes": 25,
        "pomodoro_break_minutes": 5,
        "pomodoro_long_break_minutes": 15,
        "pomodoro_rounds_before_long": 4,
    }

    def test_defaults_and_start(self) -> None:
        timer = pomodoro.PomodoroTimer(self.SETTINGS, now=_Clock())
        self.assertFalse(timer.running)
        self.assertEqual(timer.phase, "idle")
        self.assertTrue(timer.start())
        self.assertTrue(timer.running)
        self.assertFalse(timer.paused)
        self.assertEqual(timer.phase, "work")
        self.assertEqual(timer.remaining, 25 * 60)
        self.assertEqual(timer.preset_total, 25 * 60)
        self.assertEqual(timer.round, 1)
        self.assertFalse(timer.start())  # 已在运行时忽略
        timer.stop()
        self.assertFalse(timer.running)

    def test_pause_resume_uses_monotonic(self) -> None:
        clock = _Clock(1000.0)
        timer = pomodoro.PomodoroTimer(self.SETTINGS, now=clock)
        timer.start()
        clock.advance(30)
        self.assertTrue(timer.pause())
        self.assertTrue(timer.paused)
        self.assertEqual(timer.remaining, 25 * 60 - 30)
        clock.advance(120)
        self.assertEqual(timer.remaining, 25 * 60 - 30)  # 暂停不走表
        self.assertTrue(timer.resume())
        self.assertFalse(timer.paused)
        clock.advance(10)
        self.assertEqual(timer.remaining, 25 * 60 - 40)

    def test_skip_short_and_long_break(self) -> None:
        timer = pomodoro.PomodoroTimer(self.SETTINGS, now=_Clock())
        timer.start()
        timer.skip()  # 第 1 轮工作结束 → 短休息
        self.assertEqual(timer.phase, "break")
        self.assertEqual(timer.preset_total, 5 * 60)
        self.assertFalse(timer.is_long_break)
        timer.skip()  # 休息结束 → 第 2 轮工作
        self.assertEqual(timer.phase, "work")
        self.assertEqual(timer.round, 2)
        # 第 2 轮: 休 → 工3 → 休 → 工4 → 长休
        for _ in range(5):
            timer.skip()
        self.assertEqual(timer.phase, "break")
        self.assertEqual(timer.preset_total, 15 * 60)
        self.assertTrue(timer.is_long_break)
        timer.stop()

    def test_natural_finish_notifies_and_switches(self) -> None:
        settings = dict(self.SETTINGS, pomodoro_work_minutes=1, pomodoro_break_minutes=1)
        clock = _Clock(0.0)
        timer = pomodoro.PomodoroTimer(settings, now=clock)
        notes: list[tuple[str, str]] = []
        timer.notify.connect(lambda title, body: notes.append((title, body)))
        timer.start()
        clock.advance(60)
        timer._on_timeout()
        self.assertEqual(timer.phase, "break")
        self.assertEqual(timer.remaining, 60)
        self.assertEqual(len(notes), 1)
        self.assertIn("专注结束", notes[0][0])
        clock.advance(60)
        timer._on_timeout()
        self.assertEqual(timer.phase, "work")
        self.assertEqual(timer.round, 2)
        self.assertIn("休息结束", notes[-1][0])
        timer.stop()

    def test_reading_settings_defaults_on_bad_values(self) -> None:
        timer = pomodoro.PomodoroTimer({"pomodoro_work_minutes": "bad"})
        self.assertEqual(timer.work_minutes, 25)
        self.assertEqual(timer.rounds_before_long, 4)


class PomodoroBridgeTest(_BridgeCase):
    def test_bridge_properties_and_actions(self) -> None:
        bridge = self.bridge
        self.assertEqual(bridge.pomodoroState, "idle")
        self.assertEqual(bridge.pomodoroTotal, 0)
        self.assertFalse(bridge.pomodoroRunning)
        self.assertTrue(bridge.startPomodoro())
        self.assertTrue(bridge.pomodoroRunning)
        self.assertEqual(bridge.pomodoroState, "work")
        self.assertEqual(bridge.pomodoroPhase, "work")
        self.assertEqual(bridge.pomodoroRemaining, 25 * 60)
        self.assertEqual(bridge.pomodoroPresetTotal, 25 * 60)
        self.assertEqual(bridge.pomodoroRound, 1)
        self.assertEqual(bridge.pomodoroWorkMinutes, 25)
        self.assertEqual(bridge.pomodoroBreakMinutes, 5)
        self.assertEqual(bridge.pomodoroLongBreakMinutes, 15)
        self.assertEqual(bridge.pomodoroRoundsBeforeLong, 4)
        self.assertEqual(bridge.pomodoroRounds, 4)
        self.assertTrue(bridge.pausePomodoro())
        self.assertTrue(bridge.pomodoroPaused)
        self.assertEqual(bridge.pomodoroState, "paused")
        self.assertEqual(bridge.pomodoroPhase, "work")
        self.assertTrue(bridge.resumePomodoro())
        self.assertFalse(bridge.skipPomodoro() is False)
        self.assertEqual(bridge.pomodoroPhase, "break")
        self.assertTrue(bridge.stopPomodoro())
        self.assertEqual(bridge.pomodoroState, "idle")

    def test_pomodoro_independent_from_session_and_guard(self) -> None:
        bridge = self.bridge
        self.assertTrue(bridge.startPomodoro())
        self.assertEqual(bridge.state, "idle")
        self.assertFalse(bridge._guard.active)
        space = bridge._spaces.get_by_mode("light")
        bridge._begin_space_session(space, "light", 1)
        self.assertTrue(bridge.busy)
        self.assertTrue(bridge.pomodoroRunning)
        bridge.stopSession()
        self.assertFalse(bridge.busy)
        self.assertTrue(bridge.pomodoroRunning)
        bridge.stopPomodoro()

    def test_notify_reaches_notification_service(self) -> None:
        bridge = self.bridge
        with mock.patch.object(bridge._notifications, "notify") as notify:
            bridge._pomodoro._emit_notification("work")
        self.assertTrue(notify.called)
        title, body = notify.call_args.args
        self.assertIn("清番", title)
        self.assertTrue(body)


# ================= 首次使用引导 =================
class OnboardingTest(_BridgeCase):
    def test_needs_onboarding_and_finish(self) -> None:
        bridge = self.bridge
        self.assertFalse(bridge.onboardingDone)
        self.assertTrue(bridge.needsOnboarding)
        finished: list[int] = []
        bridge.onboardingFinished.connect(lambda: finished.append(1))
        bridge.finishOnboarding()
        self.assertTrue(bridge.onboardingDone)
        self.assertFalse(bridge.needsOnboarding)
        self.assertEqual(finished, [1])
        self.assertTrue(bridge._settings.get("onboarding_done"))

    def test_legacy_set_onboarding_done(self) -> None:
        bridge = self.bridge
        finished: list[int] = []
        bridge.onboardingFinished.connect(lambda: finished.append(1))
        bridge.setOnboardingDone(True)
        self.assertTrue(bridge.onboardingDone)
        self.assertTrue(finished)
        bridge.setOnboardingDone(False)
        self.assertTrue(bridge.needsOnboarding)

    def test_hide_window_helper(self) -> None:
        class _Root:
            def __init__(self) -> None:
                self.hidden = 0

            def hide(self) -> None:
                self.hidden += 1

        class _Window:
            def __init__(self) -> None:
                self.root_window = _Root()

        window = _Window()
        _hide_window(window)  # type: ignore[arg-type]
        self.assertEqual(window.root_window.hidden, 1)
        empty = _Window()
        empty.root_window = None
        _hide_window(empty)  # type: ignore[arg-type]


# ================= 速启面板：重启 / 管理员重启 =================
class RestartTest(_BridgeCase):
    def test_restart_success(self) -> None:
        bridge = self.bridge
        with mock.patch.object(bridge, "_spawn_restart", return_value=True), mock.patch.object(
            app_bridge.QTimer, "singleShot"
        ) as single_shot:
            bridge.restartApp()
        self.assertTrue(single_shot.called)
        self.assertTrue(any("正在重启" in item for item in self.toasts))

    def test_restart_failure(self) -> None:
        bridge = self.bridge
        with mock.patch.object(bridge, "_spawn_restart", return_value=False), mock.patch.object(
            app_bridge.QTimer, "singleShot"
        ) as single_shot:
            bridge.restartApp()
        self.assertFalse(single_shot.called)
        self.assertTrue(any("重启失败" in item for item in self.toasts))

    def test_spawn_restart_uses_restarted_flag(self) -> None:
        with mock.patch.object(keeper, "stop_keeper") as stop_keeper, mock.patch.object(
            keeper, "main_command", return_value=["python.exe", "run.py"]
        ), mock.patch.object(keeper, "working_directory", return_value="."), mock.patch(
            "PySide6.QtCore.QProcess.startDetached", return_value=True
        ) as start_detached:
            ok = self.bridge._spawn_restart()
        self.assertTrue(ok)
        self.assertTrue(stop_keeper.called)
        args = start_detached.call_args.args
        self.assertEqual(args[0], "python.exe")
        self.assertIn("--restarted", args[1])

    def test_relaunch_as_admin(self) -> None:
        bridge = self.bridge
        quits: list[int] = []
        bridge.quitRequested.connect(lambda: quits.append(1))
        with mock.patch.object(elevation, "is_admin", return_value=False), mock.patch.object(
            elevation, "relaunch_as_admin", return_value=True
        ) as relaunch:
            bridge.relaunchAsAdmin()
        self.assertEqual(quits, [1])
        self.assertEqual(relaunch.call_args.args, ("--restarted",))
        self.assertTrue(any("管理员权限" in item for item in self.toasts))

        with mock.patch.object(elevation, "is_admin", return_value=False), mock.patch.object(
            elevation, "relaunch_as_admin", return_value=False
        ):
            bridge.relaunchAsAdmin()
        self.assertTrue(any("提权失败" in item for item in self.toasts))
        self.assertIn("UAC", self.toasts[-1])

    def test_relaunch_when_already_admin(self) -> None:
        bridge = self.bridge
        with mock.patch.object(elevation, "is_admin", return_value=True), mock.patch.object(
            elevation, "relaunch_as_admin"
        ) as relaunch:
            bridge.relaunchAsAdmin()
        self.assertFalse(relaunch.called)
        self.assertTrue(any("已是管理员" in item for item in self.toasts))


class VersionTest(unittest.TestCase):
    def test_v016_version(self) -> None:
        # 允许从 0.16.0 起继续打补丁版本
        version_tuple = tuple(int(part) for part in APP_VERSION.split("."))
        self.assertGreaterEqual(version_tuple, (0, 16, 0))
        self.assertEqual(pkg_version, APP_VERSION)


if __name__ == "__main__":
    unittest.main()
