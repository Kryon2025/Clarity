"""v0.20 账户同步测试。

覆盖：
- services/cloud_sync.py：登录 / 拉取 / 推送 / 409 冲突重试 / 超时错误 / 地址规范化；
- 同步快照 payload 字段（白名单设置 + 空间 + 统计，敏感键不上传）；
- 拉取前自动备份（backups/cloud-pre-pull-*.json）与写回；
- AppBridge 的异步流程（登录 / 仅上传 / 仅下载 / 立即同步 + 冲突重试）。

全部用本机 127.0.0.1 上的 http.server 模拟深清商店服务端，不访问外网、不用真实数据目录。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SHENQING_NO_SCAN"] = "1"
os.environ["SHENQING_NO_KEEPER"] = "1"

from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

from shenqing.bridge.app_bridge import AppBridge  # noqa: E402
from shenqing.consts import APP_VERSION  # noqa: E402
from shenqing.core.spaces import SpaceManager  # noqa: E402
from shenqing.core.stats import StatsStore  # noqa: E402
from shenqing.services import cloud_sync  # noqa: E402
from shenqing.settings import Settings  # noqa: E402

EMAIL = "user@example.com"
PASSWORD = "secret-password"
TOKEN = "tok-abc123"


class FakeStoreServer:
    """极简商店服务端：/api/auth/login + GET/PUT /api/sync（内存里存一份快照）。"""

    def __init__(self) -> None:
        self.email = EMAIL
        self.password = PASSWORD
        self.token = TOKEN
        self.revision = 0
        self.payload: dict | None = None
        self.updated_at = ""
        self.device_name = ""
        #: 下一次 PUT 强制返回 409（用这个 revision），模拟别的设备刚推过
        self.force_conflict_revision: int | None = None
        #: 接口延迟（秒），超时测试用
        self.delay = 0.0
        self.login_calls = 0
        self.pull_calls = 0
        self.put_attempts = 0
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> FakeStoreServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        try:
            self._server.shutdown()
        finally:
            self._server.server_close()

    def _handler(self):  # noqa: ANN202 - 内部类
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args, **kwargs) -> None:  # noqa: ANN002,ANN003
                pass

            def _send(self, code: int, data: dict) -> None:
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            def _body(self) -> dict:
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    length = 0
                if length <= 0:
                    return {}
                try:
                    data = json.loads(self.rfile.read(length).decode("utf-8"))
                except (ValueError, UnicodeDecodeError, OSError):
                    return {}
                return data if isinstance(data, dict) else {}

            def _authed(self) -> bool:
                return self.headers.get("Authorization", "") == f"Bearer {outer.token}"

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 接口
                if self.path != "/api/auth/login":
                    return self._send(404, {"detail": "接口不存在"})
                outer.login_calls += 1
                body = self._body()
                if outer.delay:
                    time.sleep(outer.delay)
                if body.get("email") != outer.email or body.get("password") != outer.password:
                    return self._send(401, {"detail": "邮箱或密码不正确"})
                self._send(200, {"token": outer.token, "user": {"email": outer.email}})

            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/api/sync":
                    return self._send(404, {"detail": "接口不存在"})
                outer.pull_calls += 1
                if outer.delay:
                    time.sleep(outer.delay)
                if not self._authed():
                    return self._send(401, {"detail": "未授权"})
                self._send(
                    200,
                    {
                        "revision": outer.revision,
                        "updated_at": outer.updated_at,
                        "payload": outer.payload,
                        "device_name": outer.device_name,
                    },
                )

            def do_PUT(self) -> None:  # noqa: N802
                if self.path != "/api/sync":
                    return self._send(404, {"detail": "接口不存在"})
                outer.put_attempts += 1
                body = self._body()
                if outer.delay:
                    time.sleep(outer.delay)
                if not self._authed():
                    return self._send(401, {"detail": "未授权"})
                if outer.force_conflict_revision is not None:
                    revision = int(outer.force_conflict_revision)
                    outer.force_conflict_revision = None
                    outer.revision = revision
                    return self._send(
                        409, {"detail": "版本冲突，请先拉取", "revision": revision}
                    )
                try:
                    revision = int(body.get("revision") or 0)
                except (TypeError, ValueError):
                    revision = 0
                if revision != outer.revision:
                    return self._send(
                        409, {"detail": "版本冲突，请先拉取", "revision": outer.revision}
                    )
                outer.revision += 1
                incoming = body.get("payload")
                outer.payload = incoming if isinstance(incoming, dict) else None
                outer.device_name = str(body.get("device") or "")
                outer.updated_at = "2026-11-14T22:10:00"
                self._send(200, {"revision": outer.revision, "updated_at": outer.updated_at})

        return Handler


def _remote_payload(theme_mode: str = "ocean") -> dict:
    return {
        "version": APP_VERSION,
        "exported_at": "2026-11-14T22:00:00",
        "settings": {"theme_mode": theme_mode, "default_minutes": 30},
        "spaces": {
            "schemaVersion": 6,
            "items": [
                {
                    "id": "sp_light",
                    "mode": "light",
                    "name": "浅清空间",
                    "minutes": 30,
                    "atmosphere": "静谧",
                    "allowed_apps": [],
                },
                {
                    "id": "sp_medium",
                    "mode": "medium",
                    "name": "覆清空间",
                    "minutes": 60,
                    "atmosphere": "静谧",
                    "allowed_apps": [],
                },
                {
                    "id": "sp_heavy",
                    "mode": "heavy",
                    "name": "深清空间",
                    "minutes": 1,
                    "atmosphere": "静谧",
                    "allowed_apps": [],
                },
            ],
        },
        "stats": {
            "total_sessions": 1,
            "total_minutes": 30.0,
            "sessions": [
                {
                    "date": "2026-11-13",
                    "minutes": 30.0,
                    "level": "light",
                    "completed": True,
                    "interruptions": 0,
                    "ts": "2026-11-13T09:00:00",
                }
            ],
        },
    }


class CloudSyncServiceTest(unittest.TestCase):
    """cloud_sync 的三个接口 + 超时 + 地址规范化。"""

    def setUp(self) -> None:
        self.server = FakeStoreServer().start()

    def tearDown(self) -> None:
        self.server.stop()

    def test_normalize_url(self) -> None:
        self.assertEqual(cloud_sync.normalize_url(""), "")
        self.assertEqual(cloud_sync.normalize_url("  "), "")
        self.assertEqual(
            cloud_sync.normalize_url("store.example.com/"),
            "https://store.example.com",
        )
        self.assertEqual(
            cloud_sync.normalize_url("https://store.example.com/api/"),
            "https://store.example.com/api",
        )
        with self.assertRaises(cloud_sync.CloudSyncError):
            cloud_sync.normalize_url("ftp://store.example.com")

    def test_api_url(self) -> None:
        self.assertEqual(
            cloud_sync.api_url("store.example.com", "/api/sync"),
            "https://store.example.com/api/sync",
        )
        with self.assertRaises(cloud_sync.CloudSyncError):
            cloud_sync.api_url("", "/api/sync")

    def test_default_device_name(self) -> None:
        name = cloud_sync.default_device_name()
        self.assertTrue(name)
        self.assertLessEqual(len(name), cloud_sync.DEVICE_NAME_LIMIT)

    def test_login_returns_token(self) -> None:
        token = cloud_sync.login(self.server.url, EMAIL, PASSWORD)
        self.assertEqual(token, TOKEN)
        self.assertEqual(self.server.login_calls, 1)

    def test_login_requires_url_and_email(self) -> None:
        with self.assertRaises(cloud_sync.CloudSyncError) as ctx:
            cloud_sync.login("", EMAIL, PASSWORD)
        self.assertIn("服务器地址", str(ctx.exception))
        with self.assertRaises(cloud_sync.CloudSyncError) as ctx:
            cloud_sync.login(self.server.url, "not-an-email", PASSWORD)
        self.assertIn("邮箱", str(ctx.exception))
        with self.assertRaises(cloud_sync.CloudSyncError) as ctx:
            cloud_sync.login(self.server.url, EMAIL, "")
        self.assertIn("密码", str(ctx.exception))

    def test_login_wrong_password(self) -> None:
        with self.assertRaises(cloud_sync.CloudSyncError) as ctx:
            cloud_sync.login(self.server.url, EMAIL, "wrong")
        self.assertIn("邮箱或密码不正确", str(ctx.exception))

    def test_pull_empty_snapshot(self) -> None:
        result = cloud_sync.pull(self.server.url, TOKEN)
        self.assertEqual(result["revision"], 0)
        self.assertEqual(result["payload"], {})
        self.assertEqual(self.server.pull_calls, 1)

    def test_pull_requires_token(self) -> None:
        with self.assertRaises(cloud_sync.CloudSyncError) as ctx:
            cloud_sync.pull(self.server.url, "")
        self.assertIn("登录", str(ctx.exception))

    def test_pull_rejects_bad_token(self) -> None:
        with self.assertRaises(cloud_sync.CloudSyncError) as ctx:
            cloud_sync.pull(self.server.url, "bad-token")
        self.assertIn("登录已失效", str(ctx.exception))

    def test_push_success(self) -> None:
        payload = _remote_payload()
        ok, revision = cloud_sync.push(self.server.url, TOKEN, payload, 0, "我的电脑")
        self.assertTrue(ok)
        self.assertEqual(revision, 1)
        self.assertEqual(self.server.revision, 1)
        self.assertEqual(self.server.payload, payload)
        self.assertEqual(self.server.device_name, "我的电脑")

    def test_push_conflict_returns_remote_revision(self) -> None:
        self.server.revision = 6
        ok, revision = cloud_sync.push(
            self.server.url, TOKEN, _remote_payload(), 3, "我的电脑"
        )
        self.assertFalse(ok)
        self.assertEqual(revision, 6)

    def test_push_conflict_retry_with_remote_revision(self) -> None:
        self.server.revision = 3
        self.server.force_conflict_revision = 4
        ok, revision = cloud_sync.push(
            self.server.url, TOKEN, _remote_payload(), 3, "我的电脑"
        )
        self.assertFalse(ok)
        self.assertEqual(revision, 4)
        ok, revision = cloud_sync.push(
            self.server.url, TOKEN, _remote_payload(), revision, "我的电脑"
        )
        self.assertTrue(ok)
        self.assertEqual(revision, 5)
        self.assertEqual(self.server.put_attempts, 2)

    def test_timeout_is_readable(self) -> None:
        self.server.delay = 1.2
        with mock.patch.object(cloud_sync, "TIMEOUT_SECONDS", 0.25):
            with self.assertRaises(cloud_sync.CloudSyncError) as ctx:
                cloud_sync.login(self.server.url, EMAIL, PASSWORD)
        self.assertIn("超时", str(ctx.exception))


class CloudSyncPayloadTest(unittest.TestCase):
    """同步快照只带白名单设置，敏感键绝不上传。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.settings = Settings(self.root / "settings.json")
        self.spaces = SpaceManager(self.root / "spaces.json")
        self.stats = StatsStore(self.root / "stats.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_payload_fields(self) -> None:
        self.settings.set("theme_mode", "ocean")
        self.settings.set("default_minutes", 40)
        self.settings.set("ai_api_key", "sk-should-not-sync")
        self.settings.set("pin", "1234")
        self.settings.set("cloud_sync_token", TOKEN)
        self.settings.set("web_admin_token", "admin-token")
        self.stats.record(30.0, "light", completed=True, interruptions=0)

        payload = cloud_sync.build_payload(self.settings, self.spaces, self.stats)
        self.assertEqual(
            set(payload), {"version", "exported_at", "settings", "spaces", "stats"}
        )
        self.assertEqual(payload["version"], APP_VERSION)
        self.assertTrue(payload["exported_at"])
        # 设置：只带白名单键，敏感键一个都不出现
        synced = payload["settings"]
        self.assertEqual(synced["theme_mode"], "ocean")
        self.assertEqual(synced["default_minutes"], 40)
        self.assertTrue(set(synced).issubset(set(cloud_sync.SYNC_SETTINGS_KEYS)))
        for key in ("ai_api_key", "pin", "pin_enabled", "cloud_sync_token", "web_admin_token"):
            self.assertNotIn(key, synced)
        self.assertFalse(set(synced) & set(cloud_sync.SECRET_SETTINGS_KEYS))
        # 空间：三档齐全
        modes = [item["mode"] for item in payload["spaces"]["items"]]
        self.assertEqual(modes, ["light", "medium", "heavy"])
        self.assertEqual(payload["spaces"]["schemaVersion"], cloud_sync.SPACES_SCHEMA_VERSION)
        # 统计：有汇总也有明细
        self.assertEqual(payload["stats"]["total_sessions"], 1)
        self.assertAlmostEqual(payload["stats"]["total_minutes"], 30.0, places=1)
        self.assertEqual(len(payload["stats"]["sessions"]), 1)

    def test_payload_without_stores(self) -> None:
        payload = cloud_sync.build_payload(None, None, None)
        self.assertEqual(payload["settings"], {})
        self.assertEqual(payload["spaces"]["items"], [])
        self.assertEqual(payload["stats"]["sessions"], [])


class CloudSyncBackupApplyTest(unittest.TestCase):
    """拉取前备份 + 写回（与「导入备份」同一批数据文件）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "settings.json").write_text(
            json.dumps({"theme_mode": "solid", "pin": "keep-me"}, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.root / "spaces.json").write_text(
            json.dumps({"schemaVersion": 6, "spaces": []}), encoding="utf-8"
        )
        (self.root / "stats.json").write_text(
            json.dumps({"sessions": []}), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_backup_before_pull(self) -> None:
        path = cloud_sync.backup_current(self.root, now=None)
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent.name, "backups")
        self.assertTrue(path.name.startswith("cloud-pre-pull-"))
        self.assertTrue(path.name.endswith(".json"))
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["settings"]["pin"], "keep-me")
        self.assertIn("spaces", snapshot)
        self.assertIn("stats", snapshot)
        self.assertEqual(snapshot["version"], APP_VERSION)

    def test_apply_payload_merges_settings_only(self) -> None:
        counts = cloud_sync.apply_payload(_remote_payload("ocean"), self.root)
        self.assertEqual(counts["settings"], 2)
        self.assertEqual(counts["spaces"], 3)
        self.assertEqual(counts["stats"], 1)
        settings = json.loads((self.root / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["theme_mode"], "ocean")
        self.assertEqual(settings["default_minutes"], 30)
        # 非白名单键保持不变（本机 pin 不能被云端覆盖 / 也没上传）
        self.assertEqual(settings["pin"], "keep-me")
        spaces = json.loads((self.root / "spaces.json").read_text(encoding="utf-8"))
        self.assertEqual(spaces["schemaVersion"], 6)
        self.assertEqual(len(spaces["spaces"]), 3)
        stats = json.loads((self.root / "stats.json").read_text(encoding="utf-8"))
        self.assertEqual(len(stats["sessions"]), 1)

    def test_apply_payload_ignores_garbage(self) -> None:
        counts = cloud_sync.apply_payload({"settings": "nope", "spaces": 5}, self.root)
        self.assertEqual(counts, {"settings": 0, "spaces": 0, "stats": 0})


class CloudSyncBridgeTest(unittest.TestCase):
    """AppBridge 的异步流程：登录 / 仅上传 / 仅下载（含备份）/ 立即同步（含冲突重试）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        os.environ["SHENQING_DATA_DIR"] = str(self.data_dir)
        self.server = FakeStoreServer().start()
        self.bridge = AppBridge()
        self.toasts: list[str] = []
        self.bridge.toast.connect(self.toasts.append)
        self.bridge._settings.set("cloud_sync_url", self.server.url)

    def tearDown(self) -> None:
        self._wait(lambda: not self.bridge.cloudSyncBusy, timeout=5.0)
        try:
            self.bridge._shutdown_services()
            self.bridge.deleteLater()
        except RuntimeError:
            pass
        self.server.stop()
        self._tmp.cleanup()
        os.environ.pop("SHENQING_DATA_DIR", None)

    def _wait(self, predicate, timeout: float = 10.0) -> bool:  # noqa: ANN001
        deadline = time.time() + timeout
        while time.time() < deadline:
            _APP.processEvents()
            try:
                if predicate():
                    return True
            except RuntimeError:
                return False
            time.sleep(0.02)
        return False

    def _wait_idle(self, timeout: float = 10.0) -> bool:
        return self._wait(lambda: not self.bridge.cloudSyncBusy, timeout=timeout)

    def _login(self) -> None:
        self.assertTrue(self.bridge.cloudLogin(EMAIL, PASSWORD))
        self.assertTrue(self._wait_idle())
        self.assertTrue(self.bridge.cloudSyncLoggedIn)

    def test_login_and_logout(self) -> None:
        self.assertFalse(self.bridge.cloudSyncLoggedIn)
        self._login()
        self.assertEqual(self.bridge.cloudSyncEmail, EMAIL)
        self.assertIn("已登录", self.bridge.cloudSyncStatus)
        self.assertEqual(self.bridge.cloudSyncError, "")
        self.bridge.cloudLogout()
        self.assertFalse(self.bridge.cloudSyncLoggedIn)
        self.assertEqual(self.bridge.cloudSyncStatus, "已退出登录")

    def test_login_failure_keeps_running(self) -> None:
        self.assertTrue(self.bridge.cloudLogin(EMAIL, "wrong-password"))
        self.assertTrue(self._wait_idle())
        self.assertFalse(self.bridge.cloudSyncLoggedIn)
        self.assertIn("邮箱或密码不正确", self.bridge.cloudSyncError)
        self.assertTrue(any("邮箱或密码不正确" in text for text in self.toasts))

    def test_login_without_url(self) -> None:
        self.bridge._settings.set("cloud_sync_url", "")
        self.assertFalse(self.bridge.cloudLogin(EMAIL, PASSWORD))
        self.assertIn("服务器地址", self.bridge.cloudSyncError)

    def test_push_requires_login(self) -> None:
        self.bridge.cloudPush()
        self.assertIn("登录", self.bridge.cloudSyncError)
        self.assertFalse(self.bridge.cloudSyncBusy)

    def test_push_uploads_payload(self) -> None:
        self._login()
        self.bridge.cloudPush()
        self.assertTrue(self._wait_idle())
        self.assertIn("已上传", self.bridge.cloudSyncStatus)
        self.assertEqual(self.bridge.cloudSyncError, "")
        self.assertEqual(self.server.revision, 1)
        payload = self.server.payload or {}
        self.assertEqual(payload.get("version"), APP_VERSION)
        self.assertEqual(self.server.device_name, self.bridge.cloudSyncDevice)
        self.assertIn("settings", payload)
        self.assertEqual(payload["settings"]["theme_mode"], "solid")
        self.assertTrue(self.bridge.cloudSyncLastAt)

    def test_pull_creates_backup_and_applies(self) -> None:
        self._login()
        self.server.payload = _remote_payload("ocean")
        self.server.revision = 4
        self.bridge.cloudPull()
        self.assertTrue(self._wait_idle())
        self.assertIn("已从云端恢复", self.bridge.cloudSyncStatus)
        backups = sorted((self.data_dir / "backups").glob("cloud-pre-pull-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.bridge._settings.get("cloud_sync_revision"), 4)
        # 写回后内存里的设置也刷新了
        self.assertEqual(self.bridge.themeMode, "ocean")
        saved = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["theme_mode"], "ocean")
        self.assertTrue(self.bridge.cloudSyncLastAt)

    def test_pull_empty_cloud(self) -> None:
        self._login()
        self.bridge.cloudPull()
        self.assertTrue(self._wait_idle())
        self.assertIn("云端还没有数据", self.bridge.cloudSyncStatus)
        self.assertFalse((self.data_dir / "backups").exists())

    def test_sync_now_pushes_when_cloud_empty(self) -> None:
        self._login()
        self.bridge.cloudSyncNow()
        self.assertTrue(self._wait_idle())
        self.assertIn("已上传", self.bridge.cloudSyncStatus)
        self.assertEqual(self.server.revision, 1)
        self.assertEqual(self.bridge._settings.get("cloud_sync_revision"), 1)

    def test_sync_now_pulls_when_remote_newer(self) -> None:
        self._login()
        self.server.payload = _remote_payload("light")
        self.server.revision = 9
        self.bridge.cloudSyncNow()
        self.assertTrue(self._wait_idle())
        self.assertIn("已从云端恢复", self.bridge.cloudSyncStatus)
        self.assertEqual(self.bridge._settings.get("cloud_sync_revision"), 9)
        self.assertEqual(self.server.revision, 9)
        self.assertEqual(len(list((self.data_dir / "backups").glob("cloud-pre-pull-*.json"))), 1)

    def test_sync_now_retries_once_after_conflict(self) -> None:
        self._login()
        # 本机与云端都是 revision 3，但 PUT 前别的设备又推了一次（服务端强制 409）
        self.bridge._settings.set("cloud_sync_revision", 3)
        self.server.revision = 3
        self.server.payload = _remote_payload("solid")
        self.server.force_conflict_revision = 4
        self.bridge.cloudSyncNow()
        self.assertTrue(self._wait_idle())
        self.assertEqual(self.server.put_attempts, 2)
        self.assertIn("已上传", self.bridge.cloudSyncStatus)
        self.assertEqual(self.bridge._settings.get("cloud_sync_revision"), 5)
        self.assertEqual(self.bridge.cloudSyncError, "")


if __name__ == "__main__":
    unittest.main()
