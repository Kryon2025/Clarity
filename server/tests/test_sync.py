"""账户云同步（/api/sync）接口测试。

运行（仓库根目录）：
    python -m unittest discover -s server/tests

覆盖：登录鉴权、空快照、首次写入、乐观并发（409 回传最新 revision）、
重复写入递增、payload 体积/类型校验、删除后归零、双账号隔离、写入限流。
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

# 允许直接运行单文件：把仓库根目录加进 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from server import db  # noqa: E402
from server.config import Settings  # noqa: E402
from server.main import SYNC_MAX_PAYLOAD_BYTES, create_app  # noqa: E402

PASSWORD = "pass1234"
SYNC_PATH = "/api/sync"


class SyncApiTestCase(unittest.TestCase):
    """每个用例独立临时数据库；写限流用注入的假时钟，不用真等 30 秒。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="shenqing-sync-test-")
        self.addCleanup(self._tmp.cleanup)
        self.settings = Settings(
            secret_key="sync-unit-test-secret",
            bootstrap_admin=False,
            database_path=os.path.join(self._tmp.name, "store.db"),
            static_dir=os.path.join(self._tmp.name, "static"),
            token_ttl_seconds=3600,
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)
        # 可控时钟：验证码发送限流 + 云同步写限流
        self._now = 1_700_000_000.0
        self.app.state.sync_limiter.clock = lambda: self._now
        self.app.state.send_limiter.clock = lambda: self._now
        logging.getLogger("shenqing.mailer").setLevel(logging.ERROR)

    # ---------- 辅助 ----------
    def headers(self, token: str | None) -> dict:
        return {"Authorization": "Bearer " + token} if token else {}

    def get(self, token: str | None = None, path: str = SYNC_PATH):
        return self.client.get(path, headers=self.headers(token))

    def put(self, token: str | None = None, path: str = SYNC_PATH, **kwargs):
        return self.client.put(path, headers=self.headers(token), **kwargs)

    def delete(self, token: str | None = None, path: str = SYNC_PATH):
        return self.client.delete(path, headers=self.headers(token))

    def register(self, email: str) -> str:
        """发验证码（测试环境必然返回 dev_code）并注册，返回 token。"""
        sent = self.client.post(
            "/api/auth/send-code", json={"email": email, "purpose": "register"}
        )
        self.assertEqual(sent.status_code, 200, sent.text)
        response = self.client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "name": "同步用户",
                "code": sent.json()["dev_code"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    def push(self, token: str, payload: dict, revision: int, device: str = "test-device"):
        return self.put(
            token, json={"payload": payload, "revision": revision, "device": device}
        )

    def advance_clock(self, seconds: float = 30.0) -> None:
        self._now += float(seconds)


class SyncAuthTests(SyncApiTestCase):
    def test_requires_login(self) -> None:
        for response in (
            self.get(),
            self.put(json={"payload": {"a": 1}, "revision": 0, "device": "x"}),
            self.delete(),
        ):
            self.assertEqual(response.status_code, 401, response.text)
            self.assertIn("detail", response.json())

    def test_invalid_token_is_401(self) -> None:
        self.assertEqual(self.get("not-a-real-token").status_code, 401)


class SyncBasicTests(SyncApiTestCase):
    def test_empty_snapshot(self) -> None:
        token = self.register("empty@example.com")
        response = self.get(token)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {"revision": 0, "updated_at": 0, "payload": None, "device_name": ""},
        )

    def test_first_push_creates_revision_one(self) -> None:
        token = self.register("first@example.com")
        payload = {"sessions": [{"start": 1700000000, "seconds": 1500}], "settings": {"goal": 4}}
        response = self.push(token, payload, 0, device="MacBook Pro")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["revision"], 1)
        self.assertIsInstance(body["updated_at"], int)
        self.assertGreater(body["updated_at"], 0)

        snapshot = self.get(token).json()
        self.assertEqual(snapshot["revision"], 1)
        self.assertEqual(snapshot["payload"], payload)
        self.assertEqual(snapshot["device_name"], "MacBook Pro")
        self.assertEqual(snapshot["updated_at"], body["updated_at"])

    def test_payload_must_be_object(self) -> None:
        token = self.register("object@example.com")
        for bad in ([1, 2, 3], "text", 42, None):
            response = self.push(token, bad, 0)  # type: ignore[arg-type]
            self.assertEqual(response.status_code, 400, response.text)
            self.assertIn("JSON 对象", response.json()["detail"])
        # 失败的写入不占版本
        self.assertEqual(self.get(token).json()["revision"], 0)

    def test_device_name_is_optional_and_trimmed(self) -> None:
        token = self.register("device@example.com")
        response = self.put(token, json={"payload": {"a": 1}, "revision": 0})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.get(token).json()["device_name"], "")

        response = self.push(token, {"a": 2}, 1, device="  小米手机  ")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.get(token).json()["device_name"], "小米手机")

        too_long = self.push(token, {"a": 3}, 2, device="x" * 100)
        self.assertEqual(too_long.status_code, 400, too_long.text)

    def test_payload_at_limit_is_accepted(self) -> None:
        token = self.register("limit-ok@example.com")
        payload = {"blob": "x" * (SYNC_MAX_PAYLOAD_BYTES - 64)}
        self.assertLessEqual(len(db.dumps(payload).encode("utf-8")), SYNC_MAX_PAYLOAD_BYTES)
        response = self.push(token, payload, 0)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["revision"], 1)

    def test_oversize_payload_rejected(self) -> None:
        token = self.register("too-big@example.com")
        payload = {"blob": "x" * (SYNC_MAX_PAYLOAD_BYTES + 1024)}
        response = self.push(token, payload, 0)
        self.assertEqual(response.status_code, 413, response.text)
        self.assertIn("payload 过大", response.json()["detail"])
        # 被拒的写入既不落库也不推进版本
        self.assertEqual(self.get(token).json()["revision"], 0)
        self.assertIsNone(self.get(token).json()["payload"])

    def test_delete_resets_snapshot(self) -> None:
        token = self.register("delete@example.com")
        self.assertEqual(self.push(token, {"keep": True}, 0).json()["revision"], 1)
        response = self.delete(token)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"ok": True, "revision": 0})

        snapshot = self.get(token).json()
        self.assertEqual(snapshot["revision"], 0)
        self.assertIsNone(snapshot["payload"])
        self.assertEqual(snapshot["device_name"], "")

        # 清空后可以重新从版本 0 开始
        self.assertEqual(self.push(token, {"again": True}, 0).json()["revision"], 1)


class SyncConcurrencyTests(SyncApiTestCase):
    def test_revision_mismatch_returns_409_with_latest(self) -> None:
        token = self.register("conflict@example.com")
        original = {"value": "first"}
        self.assertEqual(self.push(token, original, 0).json()["revision"], 1)

        stale = self.push(token, {"value": "stale"}, 0)
        self.assertEqual(stale.status_code, 409, stale.text)
        body = stale.json()
        self.assertIn("detail", body)
        self.assertEqual(body["revision"], 1)

        # 409 不会覆盖、也不会推进版本
        snapshot = self.get(token).json()
        self.assertEqual(snapshot["revision"], 1)
        self.assertEqual(snapshot["payload"], original)

    def test_future_revision_also_conflicts(self) -> None:
        token = self.register("future@example.com")
        self.push(token, {"n": 1}, 0)
        self.push(token, {"n": 2}, 1)

        for bogus in (0, 1, 99):
            response = self.push(token, {"n": 999}, bogus)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()["revision"], 2)
        self.assertEqual(self.get(token).json()["payload"], {"n": 2})

    def test_repeated_pushes_increment(self) -> None:
        token = self.register("increment@example.com")
        for revision in range(0, 4):
            response = self.push(token, {"n": revision}, revision)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["revision"], revision + 1)

        snapshot = self.get(token).json()
        self.assertEqual(snapshot["revision"], 4)
        self.assertEqual(snapshot["payload"], {"n": 3})


class SyncIsolationTests(SyncApiTestCase):
    def test_two_users_cannot_see_each_other(self) -> None:
        alice = self.register("alice-sync@example.com")
        bob = self.register("bob-sync@example.com")

        self.assertEqual(self.push(alice, {"who": "alice"}, 0, device="Alice-PC").json()["revision"], 1)

        bob_snapshot = self.get(bob).json()
        self.assertEqual(bob_snapshot["revision"], 0)
        self.assertIsNone(bob_snapshot["payload"])
        self.assertEqual(bob_snapshot["device_name"], "")

        # Bob 的版本从 0 开始，不受 Alice 影响
        self.assertEqual(self.push(bob, {"who": "bob"}, 0).json()["revision"], 1)
        self.assertEqual(self.get(alice).json()["payload"], {"who": "alice"})
        self.assertEqual(self.get(bob).json()["payload"], {"who": "bob"})

        # 删自己的不影响别人
        self.assertEqual(self.delete(bob).status_code, 200)
        self.assertIsNone(self.get(bob).json()["payload"])
        self.assertEqual(self.get(alice).json()["payload"], {"who": "alice"})

    def test_concurrent_style_push_by_second_device_gets_409(self) -> None:
        token = self.register("two-device@example.com")
        first = self.push(token, {"device": "A"}, 0, device="device-A")
        self.assertEqual(first.json()["revision"], 1)
        # 第二台设备还以为版本是 0（离线修改后回传）
        second = self.push(token, {"device": "B"}, 0, device="device-B")
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["revision"], 1)
        # 拉最新版本后按 1 覆盖
        third = self.push(token, {"device": "B"}, 1, device="device-B")
        self.assertEqual(third.status_code, 200, third.text)
        self.assertEqual(third.json()["revision"], 2)
        self.assertEqual(self.get(token).json()["device_name"], "device-B")


class SyncRateLimitTests(SyncApiTestCase):
    def test_write_rate_limit_and_recovery(self) -> None:
        token = self.register("ratelimit@example.com")
        # 30 秒窗口内 10 次写全部成功
        for revision in range(0, 10):
            response = self.push(token, {"n": revision}, revision)
            self.assertEqual(response.status_code, 200, response.text)

        blocked = self.push(token, {"n": 10}, 10)
        self.assertEqual(blocked.status_code, 429, blocked.text)
        self.assertIn("太频繁", blocked.json()["detail"])
        self.assertGreater(int(blocked.headers.get("Retry-After", "0")), 0)

        # DELETE 也算写，同样受限
        self.assertEqual(self.delete(token).status_code, 429)

        # 窗口滑过之后恢复
        self.advance_clock(31)
        recovered = self.push(token, {"n": 10}, 10)
        self.assertEqual(recovered.status_code, 200, recovered.text)
        self.assertEqual(recovered.json()["revision"], 11)

    def test_reads_are_not_rate_limited(self) -> None:
        token = self.register("readlimit@example.com")
        self.push(token, {"n": 0}, 0)
        for _ in range(20):
            self.assertEqual(self.get(token).status_code, 200)

    def test_rate_limit_is_per_user(self) -> None:
        heavy = self.register("heavy@example.com")
        light = self.register("light@example.com")
        for revision in range(0, 10):
            self.push(heavy, {"n": revision}, revision)
        self.assertEqual(self.push(heavy, {"n": 10}, 10).status_code, 429)
        # 另一个账号不受影响
        response = self.push(light, {"n": 0}, 0)
        self.assertEqual(response.status_code, 200, response.text)


if __name__ == "__main__":
    unittest.main()
