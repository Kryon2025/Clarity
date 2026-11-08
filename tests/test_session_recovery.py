"""v0.14 专注恢复 + 鼠标点击计数测试。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SHENQING_NO_SCAN"] = "1"
os.environ["SHENQING_NO_KEEPER"] = "1"

from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

from shenqing.bridge.app_bridge import AppBridge  # noqa: E402
from shenqing.core.session import SessionState  # noqa: E402
from shenqing.services import click_counter  # noqa: E402


class ClickCounterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.down = False
        self.counter = click_counter.ClickCounter(
            button_provider=lambda: self.down, poll_interval_ms=1000
        )
        self.counts: list[int] = []
        self.counter.changed.connect(self.counts.append)

    def tearDown(self) -> None:
        self.counter.stop()

    def test_hook_fallback_poll_edges(self) -> None:
        with mock.patch.object(self.counter, "_install_hook", return_value=False):
            self.counter.start()
        self.assertTrue(self.counter.active)
        self.assertTrue(self.counter.fallback)
        sequence = [False, True, True, False, True]
        for down in sequence:
            self.down = down
            self.counter._poll()
        self.assertEqual(self.counter.count, 2)
        self.assertEqual(self.counter.stop(), 2)
        self.assertFalse(self.counter.active)
        # 重启清零
        with mock.patch.object(self.counter, "_install_hook", return_value=False):
            self.counter.start()
        self.assertEqual(self.counter.count, 0)

    def test_hook_path_counts_and_ignores_inactive(self) -> None:
        self.counter.simulate_click()
        self.assertEqual(self.counter.count, 0)
        with mock.patch.object(self.counter, "_install_hook", return_value=True):
            self.counter.start()
        self.assertFalse(self.counter.fallback)
        self.counter.simulate_click()
        self.counter.simulate_click()
        self.assertEqual(self.counter.count, 2)
        self.assertEqual(self.counter.stop(), 2)
        self.counter.simulate_click()
        self.assertEqual(self.counter.count, 2)

    def test_hook_callback_left_button(self) -> None:
        with mock.patch.object(self.counter, "_install_hook", return_value=True):
            self.counter.start()
        self.counter._hook_callback(0, click_counter.WM_LBUTTONDOWN, 0)
        self.counter._hook_callback(0, 0x0200, 0)  # 鼠标移动不计数
        self.assertEqual(self.counter.count, 1)
        self.counter.stop()

    def test_changed_signal(self) -> None:
        with mock.patch.object(self.counter, "_install_hook", return_value=True):
            self.counter.start()
        self.counter.simulate_click()
        self.assertIn(1, self.counts)


class SessionRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SHENQING_DATA_DIR"] = self._tmp.name
        self.bridge = AppBridge()
        self.toasts: list[str] = []
        self.bridge.toast.connect(self.toasts.append)
        self.state_path = Path(self._tmp.name) / "session_state.json"
        self.space = self.bridge._spaces.get_by_mode("medium")
        self.assertIsNotNone(self.space)

    def tearDown(self) -> None:
        self.bridge._shutdown_services()
        try:
            self.bridge.deleteLater()
        except RuntimeError:
            pass
        self._tmp.cleanup()
        os.environ.pop("SHENQING_DATA_DIR", None)

    def _now_ms(self) -> int:
        return int(datetime.now().timestamp() * 1000)

    def _write_state(self, **overrides) -> dict:
        now = self._now_ms()
        payload = {
            "spaceId": str(self.space["id"]),
            "mode": "medium",
            "endAt": now + 120_000,
            "startedAt": now - 60_000,
            "planSeconds": 180,
            "paused": False,
            "remainingSeconds": 120,
        }
        payload.update(overrides)
        self.state_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def test_begin_writes_state_and_finish_cleans(self) -> None:
        self.bridge._begin_space_session(self.space, "medium", 1)
        self.assertTrue(self.state_path.is_file())
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["mode"], "medium")
        self.assertEqual(state["spaceId"], self.space["id"])
        self.assertEqual(state["planSeconds"], 60)
        self.assertGreater(state["endAt"], self._now_ms())
        self.bridge._session.stop()
        self.assertFalse(self.state_path.exists())

    def test_restore_unexpired_relocks(self) -> None:
        self._write_state()
        self.assertTrue(self.bridge.restore_session_if_needed())
        self.assertTrue(self.bridge.busy)
        self.assertEqual(self.bridge.sessionLevel, "medium")
        self.assertGreater(self.bridge.remainingSeconds, 100)
        self.assertTrue(self.state_path.exists())
        self.assertTrue(any("已恢复锁定" in text for text in self.toasts))
        self.bridge._session.stop()
        self.assertFalse(self.state_path.exists())

    def test_restore_expired_settles_stats(self) -> None:
        now = self._now_ms()
        self._write_state(
            endAt=now - 10_000,
            startedAt=now - 610_000,
            planSeconds=600,
        )
        self.assertFalse(self.bridge.restore_session_if_needed())
        self.assertFalse(self.bridge.busy)
        self.assertFalse(self.state_path.exists())
        last = self.bridge._stats.last_session()
        self.assertTrue(last.get("recovered"))
        self.assertTrue(last.get("completed"))
        self.assertEqual(last.get("minutes"), 10.0)
        self.assertEqual(last.get("clicks"), 0)

    def test_no_state_file(self) -> None:
        self.assertFalse(self.bridge.restore_session_if_needed())
        self.assertFalse(self.bridge.busy)

    def test_paused_state_restored_paused(self) -> None:
        now = self._now_ms()
        self._write_state(endAt=now + 90_000, paused=True, remainingSeconds=90)
        self.assertTrue(self.bridge.restore_session_if_needed())
        self.assertEqual(self.bridge._session.state, SessionState.PAUSED)
        self.bridge.resumeSession()
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertFalse(state["paused"])
        self.bridge._session.stop()

    def test_finish_records_clicks(self) -> None:
        self.bridge._begin_space_session(self.space, "medium", 1)
        self.bridge._session_clicks = 7
        # 模拟已专注 1 分钟（否则 0 秒会被判“时间太短”不写统计）
        self.bridge._session._remaining = 0
        with mock.patch.object(self.bridge._click_counter, "stop", return_value=7):
            self.bridge._session.stop()
        last = self.bridge._stats.last_session()
        self.assertEqual(last.get("clicks"), 7)
        self.assertEqual(self.bridge.lastSessionClicks, 7)
        self.assertEqual(self.bridge.sessionClicks, 7)
        self.assertTrue(self.bridge.lastSession.get("clicks") == 7)
        self.assertGreaterEqual(self.bridge.todayClicks, 7)


if __name__ == "__main__":
    unittest.main()
