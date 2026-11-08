"""v0.15 网站屏蔽 / 结束卡片背景 / 还清第 4 档测试。"""

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

from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

_APP = QApplication.instance() or QApplication([])

from shenqing.bridge.app_bridge import AppBridge  # noqa: E402
from shenqing.services import site_blocker  # noqa: E402


class SiteBlockerServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.hosts = self.root / "hosts"
        self.backup = self.root / "hosts.backup"
        self.original = "127.0.0.1 localhost\n::1 localhost\n"
        self.hosts.write_text(self.original, encoding="utf-8")
        self.admin = True
        self.blocker = site_blocker.HostsSiteBlocker(
            path=self.hosts,
            backup=self.backup,
            admin_checker=lambda: self.admin,
            flush_dns=False,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_normalize_domain(self) -> None:
        cases = {
            "HTTPS://Example.com/path?q=1": "example.com",
            "example.com:443": "example.com",
            "  b23.tv  ": "b23.tv",
            "sub.domain.example.com": "sub.domain.example.com",
            "bad_domain": "",
            "not a domain": "",
            "http://": "",
            "": "",
        }
        for raw, expected in cases.items():
            self.assertEqual(site_blocker.normalize_domain(raw), expected, raw)
        values = site_blocker.normalize_domains(
            ["https://A.com", "a.com", "B.com/x", "bad_domain", "b.com"]
        )
        self.assertEqual(values, ["a.com", "b.com"])

    def test_apply_and_restore_markers(self) -> None:
        ok, message = self.blocker.apply(["https://www.bilibili.com/video", "bilibili.com"])
        self.assertTrue(ok, message)
        text = self.hosts.read_text(encoding="utf-8")
        self.assertIn(site_blocker.BLOCK_START, text)
        self.assertIn(site_blocker.BLOCK_END, text)
        self.assertIn("0.0.0.0 www.bilibili.com", text)
        self.assertIn("::1 www.bilibili.com", text)
        self.assertIn("0.0.0.0 bilibili.com", text)
        self.assertEqual(text.count(site_blocker.BLOCK_START), 1)
        self.assertTrue(self.backup.is_file())
        self.assertEqual(self.backup.read_text(encoding="utf-8"), self.original)
        # 再次应用不重复
        self.assertTrue(self.blocker.apply(["bilibili.com"])[0])
        self.assertEqual(
            self.hosts.read_text(encoding="utf-8").count(site_blocker.BLOCK_START), 1
        )
        # 用户在我们应用后新增的条目在恢复时保留
        with self.hosts.open("a", encoding="utf-8") as handle:
            handle.write("192.168.1.5 myhost\n")
        ok, message = self.blocker.restore()
        self.assertTrue(ok, message)
        restored = self.hosts.read_text(encoding="utf-8")
        self.assertNotIn(site_blocker.BLOCK_START, restored)
        self.assertNotIn("0.0.0.0", restored)
        self.assertIn("127.0.0.1 localhost", restored)
        self.assertIn("192.168.1.5 myhost", restored)

    def test_non_admin_apply_does_not_touch_hosts(self) -> None:
        self.admin = False
        ok, message = self.blocker.apply(["bilibili.com"])
        self.assertFalse(ok)
        self.assertIn("管理员", message)
        self.assertEqual(self.hosts.read_text(encoding="utf-8"), self.original)
        self.assertFalse(self.backup.exists())

    def test_cleanup_stale(self) -> None:
        self.assertTrue(self.blocker.apply(["bilibili.com"])[0])
        self.admin = False
        stale = site_blocker.HostsSiteBlocker(
            path=self.hosts, backup=self.backup, admin_checker=lambda: False, flush_dns=False
        )
        self.assertFalse(stale.cleanup_stale()[0])
        self.admin = True
        ok, message = self.blocker.cleanup_stale()
        self.assertTrue(ok, message)
        self.assertNotIn(site_blocker.BLOCK_START, self.hosts.read_text(encoding="utf-8"))


class SiteBlockerBridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        os.environ["SHENQING_DATA_DIR"] = str(self.root)
        self.bridge = AppBridge()
        self.hosts = self.root / "test-hosts"
        self.backup = self.root / "test-hosts.backup"
        self.original = "127.0.0.1 localhost\n"
        self.hosts.write_text(self.original, encoding="utf-8")
        self.admin = True
        self.bridge._site_blocker = site_blocker.HostsSiteBlocker(
            path=self.hosts,
            backup=self.backup,
            admin_checker=lambda: self.admin,
            flush_dns=False,
        )
        self.toasts: list[str] = []
        self.bridge.toast.connect(self.toasts.append)

    def tearDown(self) -> None:
        self.bridge._shutdown_services()
        try:
            self.bridge.deleteLater()
        except RuntimeError:
            pass
        self._tmp.cleanup()
        os.environ.pop("SHENQING_DATA_DIR", None)

    def test_blocked_sites_crud(self) -> None:
        bridge = self.bridge
        self.assertEqual(bridge.blockedSites, [])
        self.assertTrue(bridge.addBlockedSite("https://Example.com/path"))
        self.assertEqual(bridge.blockedSites, ["example.com"])
        self.assertFalse(bridge.addBlockedSite("example.com"))
        self.assertTrue(bridge.addBlockedSite("b23.tv"))
        self.assertEqual(bridge.blockedSites, ["example.com", "b23.tv"])
        self.assertTrue(bridge.removeBlockedSite("EXAMPLE.COM"))
        self.assertEqual(bridge.blockedSites, ["b23.tv"])
        bridge.setSiteBlockEnabled(False)
        self.assertFalse(bridge.siteBlockEnabled)

    def test_session_applies_and_restores_hosts(self) -> None:
        bridge = self.bridge
        self.assertTrue(bridge.addBlockedSite("bilibili.com"))
        space = bridge._spaces.get_by_mode("medium")
        bridge._begin_space_session(space, "medium", 1)
        text = self.hosts.read_text(encoding="utf-8")
        self.assertIn("0.0.0.0 bilibili.com", text)
        self.assertTrue(any("已屏蔽" in item for item in self.toasts))
        bridge._session.stop()
        self.assertNotIn(site_blocker.BLOCK_START, self.hosts.read_text(encoding="utf-8"))

    def test_non_admin_session_toast(self) -> None:
        bridge = self.bridge
        self.admin = False
        self.assertTrue(bridge.addBlockedSite("bilibili.com"))
        space = bridge._spaces.get_by_mode("medium")
        bridge._begin_space_session(space, "medium", 1)
        self.assertEqual(self.hosts.read_text(encoding="utf-8"), self.original)
        self.assertTrue(any("管理员" in item for item in self.toasts))
        bridge._session.stop()

    def test_cleanup_stale_via_bridge(self) -> None:
        # 模拟崩溃：hosts 里留下标记段，进程重启后清理
        ok, message = self.bridge._site_blocker.apply(["bilibili.com"])
        self.assertTrue(ok, message)
        self.assertIn(site_blocker.BLOCK_START, self.hosts.read_text(encoding="utf-8"))
        self.assertTrue(self.bridge.cleanup_stale_site_block())
        self.assertNotIn(site_blocker.BLOCK_START, self.hosts.read_text(encoding="utf-8"))


class CardBackgroundTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        os.environ["SHENQING_DATA_DIR"] = str(self.root)
        self.bridge = AppBridge()
        self.source = self.root / "src-bg.png"
        self.source.write_bytes(b"\x89PNG\r\n\x1a\nfake-image")

    def tearDown(self) -> None:
        self.bridge._shutdown_services()
        try:
            self.bridge.deleteLater()
        except RuntimeError:
            pass
        self._tmp.cleanup()
        os.environ.pop("SHENQING_DATA_DIR", None)

    def test_set_copy_and_url(self) -> None:
        bridge = self.bridge
        self.assertEqual(bridge._settings.get("card_background"), "")
        self.assertTrue(bridge.setCardBackground(str(self.source)))
        saved = str(bridge._settings.get("card_background"))
        self.assertTrue(Path(saved).is_file())
        self.assertIn("backgrounds", saved)
        self.assertNotEqual(Path(saved), self.source)
        self.assertTrue(bridge.cardBackgroundUrl.startswith("file://"))
        bridge.clearCardBackground()
        self.assertEqual(bridge._settings.get("card_background"), "")
        self.assertEqual(bridge.cardBackgroundUrl, bridge.bingWallpaperUrl)

    def test_invalid_background(self) -> None:
        bad = self.root / "bad.txt"
        bad.write_text("nope", encoding="utf-8")
        self.assertFalse(self.bridge.setCardBackground(str(bad)))
        self.assertFalse(self.bridge.setCardBackground(""))
        self.assertFalse(self.bridge.setCardBackground(str(self.root / "missing.png")))

    def test_pick_background_dialog(self) -> None:
        with mock.patch.object(
            QFileDialog, "getOpenFileName", return_value=(str(self.source), "")
        ):
            saved = self.bridge.pickCardBackground()
        self.assertTrue(saved)
        self.assertTrue(Path(saved).is_file())
        self.assertEqual(self.bridge._settings.get("card_background"), saved)
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=("", "")):
            self.assertEqual(self.bridge.pickCardBackground(), "")


class ModesAndSleepSummaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SHENQING_DATA_DIR"] = self._tmp.name
        self.bridge = AppBridge()

    def tearDown(self) -> None:
        self.bridge._shutdown_services()
        try:
            self.bridge.deleteLater()
        except RuntimeError:
            pass
        self._tmp.cleanup()
        os.environ.pop("SHENQING_DATA_DIR", None)

    def test_four_modes(self) -> None:
        modes = self.bridge.modes
        self.assertEqual([item["value"] for item in modes], ["light", "medium", "heavy", "sleep"])
        self.assertEqual(modes[3]["label"], "还清")
        self.assertEqual(modes[3]["desc"], "按作息时间自动锁定")

    def test_sleep_mode_summary(self) -> None:
        bridge = self.bridge
        self.assertIn("未设置作息时间", bridge.sleepModeSummary)
        bridge.addSleepSchedule("23:30")
        bridge.addSleepSchedule("00:30")
        summary = bridge.sleepModeSummary
        self.assertIn("23:30", summary)
        self.assertIn("00:30", summary)
        self.assertIn("本月剩余", summary)
        self.assertIn(str(bridge.unlockChances), summary)


if __name__ == "__main__":
    unittest.main()
