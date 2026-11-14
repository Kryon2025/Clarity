"""邮箱验证码（OTP）单元测试。

运行（仓库根目录）：
    python -m unittest discover -s server/tests

覆盖：发送验证码建档（只存摘要）、dev_code 开发模式、注册必须带 code、
错误/过期/用后即废/尝试次数超限、发送限流（60 秒 / 1 小时 / 1 天 / IP）、
验证码登录、找回密码后旧密码失效、SMTP 失败返回可读错误。

复用 test_store_api.StoreApiTestCase 的临时库 + TestClient + 可控限流时钟夹具；
用模块引用导入是为了不让 unittest 把公共基类再收集一遍。
"""

from __future__ import annotations

import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server import db, mailer  # noqa: E402
from server.config import Settings  # noqa: E402
from server.main import create_app  # noqa: E402
from server.tests import test_store_api as shared  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

CODE_INVALID_DETAIL = "验证码错误或已过期"


class EmailCodeCase(shared.StoreApiTestCase):
    """验证码相关用例的公共工具。"""

    def all_rows(self, email: str) -> list[dict]:
        conn = db.connect(self.settings.database_path)
        try:
            rows = conn.execute(
                "SELECT id, email, purpose, code_hash, salt, attempts, created_at, "
                "expires_at, used_at FROM email_codes WHERE email = ? ORDER BY id",
                (email,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def active_row(self, email: str, purpose: str) -> dict | None:
        conn = db.connect(self.settings.database_path)
        try:
            return db.fetch_email_code(conn, email, purpose)
        finally:
            conn.close()

    def expire_code(self, email: str, purpose: str) -> None:
        """把还没用掉的验证码改成已过期（模拟 10 分钟后）。"""
        conn = db.connect(self.settings.database_path)
        try:
            conn.execute(
                "UPDATE email_codes SET expires_at = ? "
                "WHERE email = ? AND purpose = ? AND used_at IS NULL",
                ("2000-01-01T00:00:00Z", email, purpose),
            )
            conn.commit()
        finally:
            conn.close()

    def wrong_code(self, real: str) -> str:
        """造一个一定不等于真实验证码的 6 位码。"""
        return "000000" if real != "000000" else "111111"

    def register_with_code(self, email: str, code: str, password: str = "pass1234", name: str = "用户"):
        return self.post(
            "/api/auth/register",
            json={"email": email, "password": password, "name": name, "code": code},
        )


class SendCodeTests(EmailCodeCase):
    def test_send_code_creates_hashed_row_and_returns_dev_code(self) -> None:
        response = self.post(
            "/api/auth/send-code", json={"email": "New@Example.com", "purpose": "register"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["ttl_seconds"], 600)
        self.assertIn("dev_code", body)
        dev_code = body["dev_code"]
        self.assertRegex(dev_code, r"^[0-9]{6}$")

        rows = self.all_rows("new@example.com")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["purpose"], "register")
        self.assertEqual(row["attempts"], 0)
        self.assertIsNone(row["used_at"])
        self.assertNotEqual(row["code_hash"], dev_code)
        self.assertEqual(len(row["salt"]), 32)
        self.assertGreater(row["expires_at"], row["created_at"])
        # 10 分钟有效期
        self.assertTrue(row["expires_at"].endswith("Z"))
        created = db._parse_datetime(row["created_at"])
        expires = db._parse_datetime(row["expires_at"])
        self.assertEqual(int((expires - created).total_seconds()), 600)
        # 库里任何字段都不该出现明文验证码
        for value in row.values():
            self.assertNotEqual(str(value), dev_code)

    def test_send_code_validation_and_anti_enumeration(self) -> None:
        bad_email = self.post("/api/auth/send-code", json={"email": "nope", "purpose": "register"})
        self.assertEqual(bad_email.status_code, 400)

        bad_purpose = self.post(
            "/api/auth/send-code", json={"email": "a@b.com", "purpose": "delete-account"}
        )
        self.assertEqual(bad_purpose.status_code, 400)

        # login / reset：邮箱不存在也返回成功，但没有 dev_code，也不会建档
        for purpose in ("login", "reset"):
            self.advance_mail_clock(61)  # 同一邮箱 60 秒限流（用途不同也共用这个窗口）
            response = self.post(
                "/api/auth/send-code", json={"email": "ghost@example.com", "purpose": purpose}
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"ok": True, "ttl_seconds": 600})
            self.assertEqual(self.all_rows("ghost@example.com"), [])

        # register：邮箱已注册直接 400
        self.register("taken@example.com")
        self.advance_mail_clock(61)  # 让出 60 秒发送窗口
        taken = self.post(
            "/api/auth/send-code", json={"email": "taken@example.com", "purpose": "register"}
        )
        self.assertEqual(taken.status_code, 400)
        self.assertIn("已注册", taken.json()["detail"])


class RegisterCodeTests(EmailCodeCase):
    def test_register_requires_valid_code(self) -> None:
        missing = self.post(
            "/api/auth/register",
            json={"email": "no-code@example.com", "password": "pass1234", "name": "无码"},
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json()["detail"], CODE_INVALID_DETAIL)

        code = self.request_code("no-code@example.com", "register")
        wrong = self.register_with_code("no-code@example.com", self.wrong_code(code))
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(wrong.json()["detail"], CODE_INVALID_DETAIL)

        # 输错一次后正确验证码仍然可用
        ok = self.register_with_code("no-code@example.com", code)
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertTrue(ok.json()["token"])
        self.assertEqual(ok.json()["user"]["email"], "no-code@example.com")

    def test_code_is_single_use(self) -> None:
        code = self.request_code("once@example.com", "register")
        first = self.register_with_code("once@example.com", code)
        self.assertEqual(first.status_code, 200, first.text)

        again = self.register_with_code("once@example.com", code)
        self.assertEqual(again.status_code, 409)  # 邮箱已注册，409 优先

        other = self.register_with_code("another@example.com", code)
        self.assertEqual(other.status_code, 400)
        self.assertEqual(other.json()["detail"], CODE_INVALID_DETAIL)

        row = self.all_rows("once@example.com")[0]
        self.assertIsNotNone(row["used_at"])

    def test_purpose_must_match(self) -> None:
        self.register("match@example.com")
        login_code = self.request_code("match@example.com", "login")
        used_for_register = self.register_with_code("brand-new@example.com", login_code)
        self.assertEqual(used_for_register.status_code, 400)
        self.assertEqual(used_for_register.json()["detail"], CODE_INVALID_DETAIL)

    def test_wrong_and_expired_code(self) -> None:
        code = self.request_code("exp@example.com", "register")
        wrong = self.register_with_code("exp@example.com", self.wrong_code(code))
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(wrong.json()["detail"], CODE_INVALID_DETAIL)

        self.expire_code("exp@example.com", "register")
        expired = self.register_with_code("exp@example.com", code)
        self.assertEqual(expired.status_code, 400)
        self.assertEqual(expired.json()["detail"], CODE_INVALID_DETAIL)

    def test_attempt_limit_then_too_many(self) -> None:
        email = "attempt@example.com"
        code = self.request_code(email, "register")
        wrong = self.wrong_code(code)
        for index in range(db.EMAIL_CODE_MAX_ATTEMPTS):
            response = self.register_with_code(email, wrong)
            self.assertEqual(response.status_code, 400, "第 " + str(index + 1) + " 次应仍为 400")
            self.assertEqual(response.json()["detail"], CODE_INVALID_DETAIL)
        self.assertEqual(self.active_row(email, "register")["attempts"], 5)

        # 次数用尽后，即使填对也 429
        blocked = self.register_with_code(email, code)
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("次数过多", blocked.json()["detail"])

        # 重新获取验证码后可以正常注册
        fresh = self.request_code(email, "register")
        ok = self.register_with_code(email, fresh)
        self.assertEqual(ok.status_code, 200, ok.text)


class SendRateLimitTests(EmailCodeCase):
    def test_same_email_60_seconds(self) -> None:
        payload = {"email": "rate@example.com", "purpose": "register"}
        first = self.post("/api/auth/send-code", json=payload)
        self.assertEqual(first.status_code, 200, first.text)

        second = self.post("/api/auth/send-code", json=payload)
        self.assertEqual(second.status_code, 429)
        detail = second.json()["detail"]
        self.assertIn("太频繁", detail)
        self.assertIn("60", detail)
        self.assertTrue(second.headers.get("Retry-After", "").isdigit())

        self.advance_mail_clock(61)
        third = self.post("/api/auth/send-code", json=payload)
        self.assertEqual(third.status_code, 200, third.text)
        # 只有最新一条可用
        self.assertEqual(len(self.all_rows("rate@example.com")), 2)
        self.assertIsNotNone(self.active_row("rate@example.com", "register"))

    def test_hourly_and_daily_quota(self) -> None:
        payload = {"email": "quota@example.com", "purpose": "register"}
        for _ in range(5):
            response = self.post("/api/auth/send-code", json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.advance_mail_clock(61)
        hourly_blocked = self.post("/api/auth/send-code", json=payload)
        self.assertEqual(hourly_blocked.status_code, 429)
        self.assertIn("1 小时", hourly_blocked.json()["detail"])

        # 跳过 1 小时窗口：可以继续发，直到一天 10 次用满
        self.advance_mail_clock(3601)
        for _ in range(5):
            response = self.post("/api/auth/send-code", json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.advance_mail_clock(61)
        # 再跳过 1 小时窗口：小时配额清除，但当天次数已满 10 次
        self.advance_mail_clock(3601)
        daily_blocked = self.post("/api/auth/send-code", json=payload)
        self.assertEqual(daily_blocked.status_code, 429)
        self.assertIn("今日", daily_blocked.json()["detail"])

    def test_per_ip_limit(self) -> None:
        for index in range(20):
            response = self.post(
                "/api/auth/send-code",
                json={"email": "ip" + str(index) + "@example.com", "purpose": "register"},
            )
            self.assertEqual(response.status_code, 200, response.text)
        blocked = self.post(
            "/api/auth/send-code", json={"email": "ip20@example.com", "purpose": "register"}
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("请求过于频繁", blocked.json()["detail"])


class CodeLoginTests(EmailCodeCase):
    def test_login_code_returns_token(self) -> None:
        self.register("code-login@example.com", "secret123", "验证码用户")
        code = self.request_code("code-login@example.com", "login")

        response = self.post(
            "/api/auth/login-code", json={"email": "code-login@example.com", "code": code}
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["token"])
        self.assertEqual(body["user"]["email"], "code-login@example.com")
        me = self.get("/api/auth/me", body["token"])
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["name"], "验证码用户")

        # 用后即废
        reused = self.post(
            "/api/auth/login-code", json={"email": "code-login@example.com", "code": code}
        )
        self.assertEqual(reused.status_code, 400)
        self.assertEqual(reused.json()["detail"], CODE_INVALID_DETAIL)

        # 密码登录不受影响
        self.assertTrue(self.login("code-login@example.com", "secret123"))

    def test_login_code_errors(self) -> None:
        wrong = self.post(
            "/api/auth/login-code", json={"email": "nobody@example.com", "code": "123456"}
        )
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(wrong.json()["detail"], CODE_INVALID_DETAIL)


class ResetPasswordTests(EmailCodeCase):
    def test_reset_password_invalidates_old_password(self) -> None:
        email = "reset@example.com"
        self.register(email, "oldpass1", "重置用户")
        self.assertTrue(self.login(email, "oldpass1"))

        code = self.request_code(email, "reset")

        # 新密码不合格：400，且不消耗验证码
        too_short = self.post(
            "/api/auth/reset-password",
            json={"email": email, "code": code, "new_password": "123"},
        )
        self.assertEqual(too_short.status_code, 400)
        self.assertIn("密码", too_short.json()["detail"])

        response = self.post(
            "/api/auth/reset-password",
            json={"email": email, "code": code, "new_password": "newpass9"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"ok": True})

        old = self.post("/api/auth/login", json={"email": email, "password": "oldpass1"})
        self.assertEqual(old.status_code, 401)
        self.assertTrue(self.login(email, "newpass9"))

        # 验证码不能复用
        reused = self.post(
            "/api/auth/reset-password",
            json={"email": email, "code": code, "new_password": "another9"},
        )
        self.assertEqual(reused.status_code, 400)
        self.assertEqual(reused.json()["detail"], CODE_INVALID_DETAIL)
        # 复用失败后密码没被改
        self.assertTrue(self.login(email, "newpass9"))

    def test_reset_requires_matching_purpose_and_existing_email(self) -> None:
        email = "reset2@example.com"
        self.register(email, "oldpass1", "重置用户二")
        login_code = self.request_code(email, "login")
        wrong_purpose = self.post(
            "/api/auth/reset-password",
            json={"email": email, "code": login_code, "new_password": "newpass9"},
        )
        self.assertEqual(wrong_purpose.status_code, 400)

        ghost = self.post(
            "/api/auth/reset-password",
            json={"email": "ghost@example.com", "code": "123456", "new_password": "newpass9"},
        )
        self.assertEqual(ghost.status_code, 400)
        self.assertEqual(ghost.json()["detail"], CODE_INVALID_DETAIL)


class MailDeliveryTests(EmailCodeCase):
    def test_mail_failure_returns_readable_error_and_keeps_no_code(self) -> None:
        with mock.patch.object(
            mailer, "send_code", side_effect=mailer.MailError("邮件发送失败：SMTP 连接超时，请稍后重试")
        ):
            response = self.post(
                "/api/auth/send-code", json={"email": "fail@example.com", "purpose": "register"}
            )
        self.assertEqual(response.status_code, 503, response.text)
        detail = response.json()["detail"]
        self.assertIn("邮件发送失败", detail)
        self.assertNotIn("dev_code", response.json())
        # 没发出去的验证码不能留在库里
        self.assertEqual(self.all_rows("fail@example.com"), [])

    def test_configured_smtp_disables_dev_code(self) -> None:
        # 找一个确定没人在听的本地端口，模拟「配了 SMTP 但连不上」
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        self.settings = Settings(
            secret_key="unit-test-secret-key",
            admin_email=shared.ADMIN_EMAIL,
            admin_password=shared.ADMIN_PASSWORD,
            database_path=self.settings.database_path,
            static_dir=self.settings.static_dir,
            token_ttl_seconds=3600,
            smtp_host="127.0.0.1",
            smtp_port=port,
            smtp_from="noreply@example.com",
            smtp_tls=False,
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)
        self.app.state.send_limiter.clock = lambda: self._mail_now

        response = self.post(
            "/api/auth/send-code", json={"email": "smtp@example.com", "purpose": "register"}
        )
        self.assertEqual(response.status_code, 503, response.text)
        body = response.json()
        self.assertNotIn("dev_code", body)  # 正式模式绝不返回验证码
        self.assertIn("邮件发送失败", body["detail"])
        self.assertEqual(self.all_rows("smtp@example.com"), [])


class MailerUnitTests(unittest.TestCase):
    def test_dev_mode_detection(self) -> None:
        self.assertTrue(mailer.is_dev_mode(mailer.MailConfig()))
        self.assertTrue(mailer.is_dev_mode(mailer.MailConfig(host="smtp.example.com", sender="")))
        self.assertFalse(
            mailer.is_dev_mode(
                mailer.MailConfig(host="smtp.example.com", sender="noreply@example.com")
            )
        )
        self.assertTrue(
            mailer.is_dev_mode(
                mailer.MailConfig(
                    host="smtp.example.com", sender="noreply@example.com", dev_mode=True
                )
            )
        )

    def test_send_code_in_dev_mode_does_not_touch_network(self) -> None:
        config = mailer.MailConfig()
        with self.assertLogs("shenqing.mailer", level="WARNING") as logs:
            sent = mailer.send_code(config, "someone@example.com", "register", "123456", 600)
        self.assertFalse(sent)
        self.assertIn("123456", "\n".join(logs.output))

    def test_message_headers_and_body(self) -> None:
        config = mailer.MailConfig(host="smtp.example.com", sender="noreply@example.com")
        message = mailer.build_message(config, "to@example.com", "reset", "654321", 600)
        self.assertEqual(message["To"], "to@example.com")
        self.assertIn("重置密码", str(message["Subject"]))
        self.assertIn("654321", message.get_content())
        self.assertIn("10 分钟", message.get_content())

    def test_mail_config_from_settings(self) -> None:
        settings = Settings(
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_user="bot@example.com",
            smtp_password="secret",
            smtp_from="noreply@example.com",
            smtp_tls=False,
            smtp_ssl=True,
            mail_dev_mode=True,
        )
        config = mailer.config_from_settings(settings)
        self.assertEqual(config.host, "smtp.example.com")
        self.assertEqual(config.port, 465)
        self.assertTrue(config.ssl)
        self.assertFalse(config.tls)
        self.assertTrue(config.configured)
        self.assertEqual(config.from_address, "noreply@example.com")
        self.assertTrue(config.dev_mode)


if __name__ == "__main__":
    unittest.main()
