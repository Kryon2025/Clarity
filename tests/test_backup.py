"""v0.14 备份/恢复：roundtrip、非法 zip、路径穿越、pre-import 兜底、bridge 接口。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SHENQING_NO_SCAN"] = "1"
os.environ["SHENQING_NO_KEEPER"] = "1"

from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

from shenqing.services import backup as backup_service  # noqa: E402
from shenqing.settings import Settings  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class BackupServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._env = os.environ.get("SHENQING_DATA_DIR")
        os.environ["SHENQING_DATA_DIR"] = str(self.root)
        _write_json(self.root / "settings.json", {"theme": "Light", "ui_font_scale": 1.15})
        _write_json(self.root / "spaces.json", {"schemaVersion": 5, "spaces": []})
        _write_json(self.root / "stats.json", {"sessions": []})
        _write_json(self.root / "app_usage.json", {"2026-11-07": {}})
        _write_json(self.root / "app_usage_overrides.json", {"categories": {}})
        _write_json(self.root / "ai_chats.json", {"currentId": "", "conversations": []})
        _write_json(self.root / "ai_usage.json", {})
        _write_json(self.root / "settings" / "sleep.json", {"schedules": []})
        _write_json(self.root / "blocklist.json", {"processes": []})
        _write_json(self.root / "apps.json", {"apps": []})
        plugin_file = self.root / "plugin_data" / "com.demo" / "state.json"
        plugin_file.parent.mkdir(parents=True, exist_ok=True)
        plugin_file.write_text('{"ok": true}', encoding="utf-8")
        self.backup_path = self.root.parent / (self.root.name + "-backup.zip")

    def tearDown(self) -> None:
        self._tmp.cleanup()
        try:
            self.backup_path.unlink()
        except OSError:
            pass
        if self._env is None:
            os.environ.pop("SHENQING_DATA_DIR", None)
        else:
            os.environ["SHENQING_DATA_DIR"] = self._env

    def test_create_backup_contains_manifest_and_files(self) -> None:
        ok, path = backup_service.create_backup(self.backup_path)
        self.assertTrue(ok, path)
        self.assertTrue(self.backup_path.is_file())
        with zipfile.ZipFile(self.backup_path) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("manifest.json"))
        for expected in (
            "settings.json",
            "spaces.json",
            "stats.json",
            "app_usage.json",
            "app_usage_overrides.json",
            "ai_chats.json",
            "ai_usage.json",
            "sleep.json",
            "blocklist.json",
            "apps.json",
            "plugin_data/com.demo/state.json",
        ):
            self.assertIn(expected, names)
        self.assertEqual(manifest["app"], "ShenQing")
        self.assertTrue(manifest["version"])
        self.assertTrue(manifest["createdAt"])
        self.assertIn("settings.json", manifest["files"])

    def test_roundtrip_restores_and_pre_import_backup(self) -> None:
        self.assertTrue(backup_service.create_backup(self.backup_path)[0])
        _write_json(self.root / "settings.json", {"theme": "Dark", "ui_font_scale": 0.85})
        ok, message = backup_service.restore_backup(self.backup_path)
        self.assertTrue(ok, message)
        restored = json.loads((self.root / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(restored["theme"], "Light")
        self.assertAlmostEqual(restored["ui_font_scale"], 1.15)
        pre_imports = list((self.root / "backups").glob("pre-import-*.zip"))
        self.assertEqual(len(pre_imports), 1)
        self.assertTrue(zipfile.is_zipfile(pre_imports[0]))
        # Settings 读取生效
        self.assertEqual(Settings(self.root / "settings.json").get("theme"), "Light")

    def test_invalid_zip_rejected(self) -> None:
        bad = self.root / "bad.zip"
        bad.write_text("not a zip", encoding="utf-8")
        ok, message = backup_service.restore_backup(bad)
        self.assertFalse(ok)
        self.assertIn("zip", message)

    def test_missing_or_wrong_manifest_rejected(self) -> None:
        missing = self.root / "missing-manifest.zip"
        with zipfile.ZipFile(missing, "w") as archive:
            archive.writestr("settings.json", "{}")
        ok, message = backup_service.restore_backup(missing)
        self.assertFalse(ok)
        self.assertIn("manifest", message)

        wrong = self.root / "wrong-app.zip"
        with zipfile.ZipFile(wrong, "w") as archive:
            archive.writestr(
                "manifest.json",
                json.dumps({"app": "OtherApp", "version": "1.0.0"}),
            )
            archive.writestr("settings.json", "{}")
        ok, message = backup_service.restore_backup(wrong)
        self.assertFalse(ok)
        self.assertIn("不是深清备份", message)

    def test_path_traversal_rejected(self) -> None:
        evil = self.root.parent / "evil-backup.zip"
        target = self.root.parent / "evil.txt"
        try:
            with zipfile.ZipFile(evil, "w") as archive:
                archive.writestr(
                    "manifest.json",
                    json.dumps({"app": "ShenQing", "version": "0.14.0"}),
                )
                archive.writestr("settings.json", "{}")
                archive.writestr("../evil.txt", "pwned")
            ok, message = backup_service.restore_backup(evil)
            self.assertFalse(ok)
            self.assertIn("非法路径", message)
            self.assertFalse(target.exists())
        finally:
            for item in (evil, target):
                try:
                    item.unlink()
                except OSError:
                    pass

    def test_unknown_entries_ignored(self) -> None:
        path = self.root / "extra.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "manifest.json",
                json.dumps({"app": "ShenQing", "version": "0.14.0"}),
            )
            archive.writestr("settings.json", json.dumps({"theme": "Glass"}))
            archive.writestr("evil.txt", "ignored")
        ok, message = backup_service.restore_backup(path)
        self.assertTrue(ok, message)
        self.assertFalse((self.root / "evil.txt").exists())
        self.assertEqual(
            json.loads((self.root / "settings.json").read_text(encoding="utf-8"))["theme"],
            "Glass",
        )


class BackupBridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        os.environ["SHENQING_DATA_DIR"] = str(self.root)
        os.environ["SHENQING_NO_SCAN"] = "1"
        from shenqing.bridge.app_bridge import AppBridge

        _write_json(self.root / "settings.json", {"theme": "Light"})
        self.bridge = AppBridge()
        self.toasts: list[str] = []
        self.bridge.toast.connect(self.toasts.append)
        self.backup_path = self.root.parent / (self.root.name + "-bridge.zip")

    def tearDown(self) -> None:
        self.bridge._shutdown_services()
        try:
            self.bridge.deleteLater()
        except RuntimeError:
            pass
        self._tmp.cleanup()
        try:
            self.backup_path.unlink()
        except OSError:
            pass
        os.environ.pop("SHENQING_DATA_DIR", None)

    def test_export_and_restore_via_bridge(self) -> None:
        bridge = self.bridge
        self.assertTrue(bridge.exportBackupTo(str(self.backup_path)))
        self.assertFalse(bridge.backupBusy)
        self.assertEqual(bridge.lastBackupPath, str(self.backup_path))
        self.assertEqual(bridge.lastBackupError, "")
        self.assertTrue(any("已导出" in text for text in self.toasts))
        # 改设置后用 bridge 恢复
        _write_json(self.root / "settings.json", {"theme": "Dark"})
        with mock.patch.object(bridge, "_restart_after_restore", return_value=True) as restart:
            self.assertTrue(bridge.restoreBackupFile(str(self.backup_path)))
        self.assertTrue(restart.called)
        self.assertFalse(bridge.backupBusy)
        self.assertEqual(bridge.lastBackupPath, str(self.backup_path))
        self.assertEqual(
            json.loads((self.root / "settings.json").read_text(encoding="utf-8"))["theme"],
            "Light",
        )

    def test_export_dialog_and_pick_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        bridge = self.bridge
        with mock.patch.object(
            QFileDialog, "getSaveFileName", return_value=(str(self.backup_path), "")
        ):
            self.assertEqual(bridge.exportBackup(), str(self.backup_path))
        self.assertTrue(self.backup_path.is_file())
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=("", "")):
            self.assertEqual(bridge.pickBackupFile(), "")
        with mock.patch.object(
            QFileDialog, "getOpenFileName", return_value=(str(self.backup_path), "")
        ):
            self.assertEqual(bridge.pickBackupFile(), str(self.backup_path))

    def test_restore_invalid_sets_error(self) -> None:
        bad = self.root / "bad.zip"
        bad.write_text("nope", encoding="utf-8")
        self.assertFalse(self.bridge.restoreBackupFile(str(bad)))
        self.assertTrue(self.bridge.lastBackupError)
        self.assertTrue(any("恢复失败" in text for text in self.toasts))

    def test_import_backup_with_confirm(self) -> None:
        bridge = self.bridge
        self.assertTrue(bridge.exportBackupTo(str(self.backup_path)))
        from PySide6.QtWidgets import QMessageBox

        with (
            mock.patch.object(bridge, "pickBackupFile", return_value=str(self.backup_path)),
            mock.patch.object(
                QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            mock.patch.object(bridge, "_restart_after_restore", return_value=True),
        ):
            self.assertTrue(bridge.importBackup())


if __name__ == "__main__":
    unittest.main()
