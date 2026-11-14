"""深清商店后端单元测试。

运行（仓库根目录）：
    python -m unittest discover -s server/tests

覆盖：注册/登录/鉴权、角色权限、提交/审核/拒绝、公开可见性、评论审核与评分、
catalog.json 结构、管理员调整角色、排序筛选、输入校验、静态前端回退。
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

from server import auth, db  # noqa: E402
from server.config import Settings  # noqa: E402
from server.main import create_app  # noqa: E402

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-pass-123"

THEME_PALETTE = {
    "bgTop": "#0A1F2E",
    "bgMid": "#06202C",
    "bgBottom": "#04121A",
    "accent": "#35E0C8",
    "cardBg": "#0D2634",
    "textPrimary": "#EAF8FC",
}


def theme_payload(**overrides) -> dict:
    payload = {
        "kind": "theme",
        "name": "极光",
        "summary": "青绿极光掠过深夜海面",
        "description": "以深海为底、极光青绿为强调色的深色主题包。",
        "version": "1.0.0",
        "download_url": "",
        "palette": dict(THEME_PALETTE),
        "tags": ["深色", "青绿"],
        "screenshots": [],
    }
    payload.update(overrides)
    return payload


def plugin_payload(**overrides) -> dict:
    payload = {
        "kind": "plugin",
        "name": "专注统计",
        "summary": "把每次专注写进统计",
        "description": "安装后自动记录专注时长。",
        "version": "1.2.0",
        "download_url": "https://example.com/plugins/focus.zip",
        "palette": {},
        "tags": ["统计"],
        "screenshots": [],
    }
    payload.update(overrides)
    return payload


class StoreApiTestCase(unittest.TestCase):
    """每个用例独立临时数据库，互不影响。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="shenqing-store-test-")
        self.addCleanup(self._tmp.cleanup)
        self.settings = Settings(
            secret_key="unit-test-secret-key",
            admin_email=ADMIN_EMAIL,
            admin_password=ADMIN_PASSWORD,
            database_path=os.path.join(self._tmp.name, "store.db"),
            static_dir=os.path.join(self._tmp.name, "static"),
            token_ttl_seconds=3600,
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)
        # 发送限流用可控时钟：测试可以「快进」，不用真的等 60 秒
        self._mail_now = 1_700_000_000.0
        self.app.state.send_limiter.clock = lambda: self._mail_now
        # 开发模式会把验证码写 WARNING 日志，测试里不必刷屏（assertLogs 会自己接管）
        logging.getLogger("shenqing.mailer").setLevel(logging.ERROR)

    # ---------- 辅助 ----------
    def post(self, path: str, token: str | None = None, **kwargs):
        headers = {"Authorization": "Bearer " + token} if token else {}
        return self.client.post(path, headers=headers, **kwargs)

    def put(self, path: str, token: str | None = None, **kwargs):
        headers = {"Authorization": "Bearer " + token} if token else {}
        return self.client.put(path, headers=headers, **kwargs)

    def get(self, path: str, token: str | None = None, **kwargs):
        headers = {"Authorization": "Bearer " + token} if token else {}
        return self.client.get(path, headers=headers, **kwargs)

    def advance_mail_clock(self, seconds: float = 60.0) -> None:
        """把发送限流的时钟往前推（不影响验证码自身的过期时间）。"""
        self._mail_now += float(seconds)

    def send_code(self, email: str, purpose: str = "register", *, advance_on_limit: bool = True):
        """请求一次验证码；撞上 60 秒限流时自动快进时钟重试一次。"""
        payload = {"email": email, "purpose": purpose}
        response = self.post("/api/auth/send-code", json=payload)
        if (
            advance_on_limit
            and response.status_code == 429
            and "太频繁" in str(response.json().get("detail", ""))
        ):
            self.advance_mail_clock(120)
            response = self.post("/api/auth/send-code", json=payload)
        return response

    def request_code(self, email: str, purpose: str = "register") -> str:
        """发一次验证码并返回 dev_code（测试环境没有 SMTP，dev_code 必然存在）。"""
        response = self.send_code(email, purpose)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["dev_code"]

    def register(self, email: str, password: str = "pass1234", name: str = "测试用户") -> dict:
        # 注册现在必须带邮箱验证码；邮箱已注册时 send-code 会 400，此时不带 code，
        # 让 register 走 409 分支（保持原来的重复注册用例语义）。
        code_response = self.send_code(email, "register")
        payload = {"email": email, "password": password, "name": name}
        if code_response.status_code == 200:
            payload["code"] = code_response.json()["dev_code"]
        response = self.post("/api/auth/register", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def login(self, email: str, password: str = "pass1234") -> str:
        response = self.post("/api/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    def admin_token(self) -> str:
        return self.login(ADMIN_EMAIL, ADMIN_PASSWORD)

    def promote(self, token: str, user_id: int, role: str = "developer"):
        return self.post("/api/admin/users/{}/role".format(user_id), token, json={"role": role})

    def submit(self, token: str, payload: dict):
        return self.post("/api/dev/items", token, json=payload)

    def approve(self, token: str, item_id: str):
        return self.post(
            "/api/admin/review", token, json={"item_id": item_id, "action": "approve"}
        )

    def make_item(self, token: str, payload: dict) -> dict:
        response = self.submit(token, payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def make_approved(self, token: str, payload: dict) -> dict:
        """开发者提交 + 管理员审核通过，返回 approved 条目。"""
        item = self.make_item(token, payload)
        response = self.approve(self.admin_token(), item["id"])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def make_developer(self, email: str) -> tuple[str, dict]:
        account = self.register(email)
        admin = self.admin_token()
        response = self.promote(admin, account["user"]["id"])
        self.assertEqual(response.status_code, 200, response.text)
        return account["token"], account["user"]


class AuthTests(StoreApiTestCase):
    def test_register_login_and_me(self) -> None:
        account = self.register("Alice@Example.com", "secret123", "爱丽丝")
        self.assertEqual(account["user"]["role"], "user")
        self.assertEqual(account["user"]["email"], "alice@example.com")
        self.assertTrue(account["token"])

        me = self.get("/api/auth/me", account["token"])
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["name"], "爱丽丝")

        # 大小写不敏感登录
        token = self.login("ALICE@example.com", "secret123")
        self.assertTrue(token)

    def test_login_errors(self) -> None:
        self.register("bob@example.com", "secret123", "Bob")
        wrong = self.post("/api/auth/login", json={"email": "bob@example.com", "password": "bad-pass"})
        self.assertEqual(wrong.status_code, 401)
        self.assertIn("detail", wrong.json())

        unknown = self.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"})
        self.assertEqual(unknown.status_code, 401)

    def test_duplicate_email_conflict(self) -> None:
        self.register("dup@example.com")
        duplicated = self.post(
            "/api/auth/register",
            json={"email": "DUP@example.com", "password": "pass1234", "name": "重复"},
        )
        self.assertEqual(duplicated.status_code, 409)
        self.assertIn("已注册", duplicated.json()["detail"])

    def test_auth_required(self) -> None:
        no_token = self.get("/api/auth/me")
        self.assertEqual(no_token.status_code, 401)
        bad_token = self.get("/api/auth/me", "not-a-real-token")
        self.assertEqual(bad_token.status_code, 401)
        wrong_scheme = self.client.get("/api/auth/me", headers={"Authorization": "Basic abc"})
        self.assertEqual(wrong_scheme.status_code, 401)

    def test_register_validation(self) -> None:
        bad_email = self.post(
            "/api/auth/register", json={"email": "not-an-email", "password": "pass1234", "name": "A"}
        )
        self.assertEqual(bad_email.status_code, 400)
        short_password = self.post(
            "/api/auth/register", json={"email": "a@b.com", "password": "123", "name": "A"}
        )
        self.assertEqual(short_password.status_code, 400)
        empty_name = self.post(
            "/api/auth/register", json={"email": "a@b.com", "password": "pass1234", "name": "  "}
        )
        self.assertEqual(empty_name.status_code, 400)

    def test_token_primitives(self) -> None:
        hashed = auth.hash_password("pass1234")
        self.assertTrue(auth.verify_password("pass1234", hashed))
        self.assertFalse(auth.verify_password("pass1235", hashed))
        self.assertFalse(auth.verify_password("pass1234", "garbage"))

        user = {"id": 7, "email": "a@b.com", "role": "developer"}
        token = auth.create_token(user, "secret", 60, now=1000)
        payload = auth.decode_token(token, "secret", now=1010)
        self.assertEqual(payload["sub"], "7")
        self.assertEqual(payload["role"], "developer")

        with self.assertRaises(auth.TokenError):
            auth.decode_token(token, "other-secret", now=1010)
        with self.assertRaises(auth.TokenError):
            auth.decode_token(token, "secret", now=2000)  # 过期
        tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
        with self.assertRaises(auth.TokenError):
            auth.decode_token(tampered, "secret", now=1010)


class RolePermissionTests(StoreApiTestCase):
    def test_user_cannot_submit_developer_can_admin_reviews(self) -> None:
        user_token = self.register("user@example.com")["token"]
        user_id = self.get("/api/auth/me", user_token).json()["id"]

        denied = self.submit(user_token, theme_payload())
        self.assertEqual(denied.status_code, 403)
        self.assertIn("detail", denied.json())

        admin = self.admin_token()
        promoted = self.promote(admin, user_id, "developer")
        self.assertEqual(promoted.status_code, 200, promoted.text)
        self.assertEqual(promoted.json()["role"], "developer")

        item = self.make_item(user_token, theme_payload())
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["author"], "测试用户")
        self.assertEqual(item["palette"]["accent"], "#35E0C8")
        self.assertEqual(item["tags"], ["深色", "青绿"])

        # developer 不能审核、不能管理用户
        self.assertEqual(self.get("/api/admin/submissions", user_token).status_code, 403)
        self.assertEqual(self.get("/api/admin/users", user_token).status_code, 403)
        review_denied = self.post(
            "/api/admin/review", user_token, json={"item_id": item["id"], "action": "approve"}
        )
        self.assertEqual(review_denied.status_code, 403)

        # 管理员能看到待审队列并通过
        pending = self.get("/api/admin/submissions?status=pending", admin)
        self.assertEqual(pending.status_code, 200)
        self.assertEqual([row["id"] for row in pending.json()], [item["id"]])

        approved = self.approve(admin, item["id"])
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(approved.json()["published_at"], approved.json()["created_at"][:10])

        public = self.get("/api/store/items")
        self.assertEqual(public.status_code, 200)
        self.assertEqual([row["id"] for row in public.json()], [item["id"]])

    def test_pending_invisible_until_approved(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        item = self.make_item(developer, theme_payload(name="尚未过审"))

        self.assertEqual(self.get("/api/store/items").json(), [])
        self.assertEqual(self.get("/api/store/items/" + item["id"]).status_code, 404)
        self.assertEqual(self.get("/api/catalog.json").json()["items"], [])

        # 作者与管理员可以看详情
        self.assertEqual(self.get("/api/store/items/" + item["id"], developer).status_code, 200)
        admin = self.admin_token()
        self.assertEqual(self.get("/api/store/items/" + item["id"], admin).status_code, 200)

        self.approve(admin, item["id"])
        self.assertEqual(len(self.get("/api/store/items").json()), 1)
        self.assertEqual(self.get("/api/store/items/" + item["id"]).status_code, 200)

    def test_developer_item_isolation(self) -> None:
        first, _ = self.make_developer("dev1@example.com")
        second, _ = self.make_developer("dev2@example.com")
        item = self.make_item(first, theme_payload())

        self.assertEqual(self.get("/api/dev/items", second).json(), [])
        other_update = self.put("/api/dev/items/" + item["id"], second, json={"name": "偷改"})
        self.assertEqual(other_update.status_code, 403)
        self.assertEqual(len(self.get("/api/dev/items", first).json()), 1)


class ReviewFlowTests(StoreApiTestCase):
    def test_update_pending_then_reject_and_lock(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        item = self.make_item(developer, theme_payload())

        updated = self.put(
            "/api/dev/items/" + item["id"],
            developer,
            json={"name": "极光 2", "summary": "换了个描述", "tags": ["深色", "夜间"]},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["name"], "极光 2")
        self.assertEqual(updated.json()["tags"], ["深色", "夜间"])
        self.assertEqual(updated.json()["palette"]["accent"], "#35E0C8")

        admin = self.admin_token()
        no_reason = self.post(
            "/api/admin/review", admin, json={"item_id": item["id"], "action": "reject"}
        )
        self.assertEqual(no_reason.status_code, 400)

        rejected = self.post(
            "/api/admin/review",
            admin,
            json={"item_id": item["id"], "action": "reject", "reason": "配色与描述不符"},
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["status"], "rejected")
        self.assertEqual(rejected.json()["reject_reason"], "配色与描述不符")

        mine = self.get("/api/dev/items", developer).json()
        self.assertEqual(mine[0]["status"], "rejected")
        self.assertEqual(mine[0]["reject_reason"], "配色与描述不符")

        locked = self.put("/api/dev/items/" + item["id"], developer, json={"name": "再改"})
        self.assertEqual(locked.status_code, 409)

        self.assertEqual(self.get("/api/store/items").json(), [])
        self.assertEqual(self.get("/api/catalog.json").json()["items"], [])

    def test_unknown_action_and_missing_item(self) -> None:
        admin = self.admin_token()
        bad_action = self.post(
            "/api/admin/review", admin, json={"item_id": "theme-x", "action": "delete"}
        )
        self.assertEqual(bad_action.status_code, 400)
        missing = self.post(
            "/api/admin/review", admin, json={"item_id": "theme-missing", "action": "approve"}
        )
        self.assertEqual(missing.status_code, 404)


class CommentTests(StoreApiTestCase):
    def test_comment_pending_then_approved_and_rating(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        item = self.make_approved(developer, theme_payload())

        user1 = self.register("u1@example.com")["token"]
        user2 = self.register("u2@example.com")["token"]

        first = self.post(
            "/api/store/items/{}/comments".format(item["id"]),
            user1,
            json={"rating": 5, "text": "很好看"},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["status"], "pending")
        self.assertEqual(first.json()["user_name"], "测试用户")

        self.post(
            "/api/store/items/{}/comments".format(item["id"]),
            user2,
            json={"rating": 4, "text": "不错"},
        )
        self.assertEqual(self.get("/api/store/items/{}/comments".format(item["id"])).json(), [])
        self.assertEqual(self.get("/api/store/items/" + item["id"]).json()["rating"], 0)

        admin = self.admin_token()
        pending = self.get("/api/admin/comments?status=pending", admin).json()
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0]["item_name"], "极光")

        approve_one = self.post(
            "/api/admin/comments/{}/review".format(pending[0]["id"]),
            admin,
            json={"action": "approve"},
        )
        self.assertEqual(approve_one.status_code, 200)
        self.assertEqual(approve_one.json()["status"], "approved")

        listed = self.get("/api/store/items/{}/comments".format(item["id"])).json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["rating"], 5)
        self.assertEqual(self.get("/api/store/items/" + item["id"]).json()["rating"], 5.0)

        self.post(
            "/api/admin/comments/{}/review".format(pending[1]["id"]),
            admin,
            json={"action": "approve"},
        )
        self.assertEqual(self.get("/api/store/items/" + item["id"]).json()["rating"], 4.5)

        reject_one = self.post(
            "/api/store/items/{}/comments".format(item["id"]),
            user1,
            json={"rating": 1, "text": "差评"},
        ).json()
        self.post(
            "/api/admin/comments/{}/review".format(reject_one["id"]),
            admin,
            json={"action": "reject"},
        )
        self.assertEqual(len(self.get("/api/store/items/{}/comments".format(item["id"])).json()), 2)

    def test_comment_validation_and_visibility(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        approved_item = self.make_approved(developer, theme_payload())
        pending_item = self.make_item(developer, theme_payload(name="未过审"))
        user = self.register("u@example.com")["token"]

        self.assertEqual(
            self.post(
                "/api/store/items/{}/comments".format(approved_item["id"]),
                json={"rating": 5, "text": "没登录"},
            ).status_code,
            401,
        )
        bad_rating = self.post(
            "/api/store/items/{}/comments".format(approved_item["id"]),
            user,
            json={"rating": 6, "text": "超范围"},
        )
        self.assertEqual(bad_rating.status_code, 400)
        empty_text = self.post(
            "/api/store/items/{}/comments".format(approved_item["id"]),
            user,
            json={"rating": 5, "text": "   "},
        )
        self.assertEqual(empty_text.status_code, 400)
        hidden = self.post(
            "/api/store/items/{}/comments".format(pending_item["id"]),
            user,
            json={"rating": 5, "text": "评论未过审条目"},
        )
        self.assertEqual(hidden.status_code, 404)


class CatalogTests(StoreApiTestCase):
    def test_catalog_structure_and_absolute_urls(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        theme = self.make_approved(developer, theme_payload(id="theme-aurora"))
        plugin = self.make_approved(
            developer,
            plugin_payload(
                id="com.example.focus",
                download_url="/downloads/com.example.focus-1.2.0.zip",
            ),
        )
        absolute_plugin = self.make_approved(
            developer,
            plugin_payload(
                id="com.example.ambient",
                name="白噪音",
                download_url="https://cdn.example.com/ambient.zip",
            ),
        )
        self.make_item(developer, theme_payload(id="theme-pending", name="待审主题"))

        payload = self.get("/api/catalog.json").json()
        self.assertEqual(payload["version"], self.settings.app_version)
        self.assertTrue(payload["updated_at"].endswith("Z"))
        self.assertEqual(len(payload["items"]), 3)
        ids = [row["id"] for row in payload["items"]]
        self.assertNotIn("theme-pending", ids)
        self.assertIn(theme["id"], ids)

        by_id = {row["id"]: row for row in payload["items"]}
        theme_row = by_id[theme["id"]]
        self.assertEqual(theme_row["kind"], "theme")
        self.assertEqual(theme_row["download_url"], "")
        self.assertEqual(set(theme_row["palette"]), set(THEME_PALETTE))
        self.assertEqual(
            set(theme_row),
            {
                "id",
                "kind",
                "name",
                "author",
                "summary",
                "description",
                "version",
                "rating",
                "downloads",
                "tags",
                "screenshots",
                "download_url",
                "palette",
                "published_at",
            },
        )

        relative_plugin = by_id[plugin["id"]]
        self.assertTrue(relative_plugin["download_url"].startswith("http://testserver/"))
        self.assertTrue(relative_plugin["download_url"].endswith("/downloads/com.example.focus-1.2.0.zip"))

        absolute_row = by_id[absolute_plugin["id"]]
        self.assertEqual(absolute_row["download_url"], "https://cdn.example.com/ambient.zip")
        self.assertEqual(absolute_row["palette"], {})

    def test_public_base_url_override(self) -> None:
        self.settings = Settings(
            secret_key="unit-test-secret-key",
            admin_email=ADMIN_EMAIL,
            admin_password=ADMIN_PASSWORD,
            database_path=os.path.join(self._tmp.name, "store2.db"),
            static_dir=os.path.join(self._tmp.name, "static2"),
            public_base_url="https://store.example.com",
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)
        developer, _ = self.make_developer("dev@example.com")
        self.make_approved(
            developer,
            plugin_payload(id="com.example.demo", download_url="/files/demo.zip"),
        )
        item = self.get("/api/catalog.json").json()["items"][0]
        self.assertEqual(item["download_url"], "https://store.example.com/files/demo.zip")


class AdminTests(StoreApiTestCase):
    def test_list_users_and_change_role(self) -> None:
        user = self.register("target@example.com")
        admin = self.admin_token()

        users = self.get("/api/admin/users", admin)
        self.assertEqual(users.status_code, 200)
        emails = [row["email"] for row in users.json()]
        self.assertIn(ADMIN_EMAIL, emails)
        self.assertIn("target@example.com", emails)
        admin_row = next(row for row in users.json() if row["email"] == ADMIN_EMAIL)
        self.assertEqual(admin_row["role"], "admin")

        promoted = self.promote(admin, user["user"]["id"], "developer")
        self.assertEqual(promoted.status_code, 200)
        self.assertEqual(promoted.json()["role"], "developer")

        # 提升后立刻可以提交
        created = self.submit(user["token"], theme_payload())
        self.assertEqual(created.status_code, 200, created.text)

        demoted = self.promote(admin, user["user"]["id"], "user")
        self.assertEqual(demoted.status_code, 200)
        self.assertEqual(demoted.json()["role"], "user")
        self.assertEqual(self.submit(user["token"], theme_payload(name="降级后")).status_code, 403)

        invalid = self.promote(admin, user["user"]["id"], "superadmin")
        self.assertEqual(invalid.status_code, 400)
        missing = self.promote(admin, 9999, "developer")
        self.assertEqual(missing.status_code, 404)

    def test_cannot_change_own_role(self) -> None:
        admin = self.admin_token()
        admin_id = self.get("/api/auth/me", admin).json()["id"]
        response = self.promote(admin, admin_id, "user")
        self.assertEqual(response.status_code, 400)

    def test_non_admin_cannot_manage(self) -> None:
        user = self.register("plain@example.com")["token"]
        self.assertEqual(self.get("/api/admin/users", user).status_code, 403)
        self.assertEqual(
            self.post("/api/admin/review", user, json={"item_id": "x", "action": "approve"}).status_code,
            403,
        )
        self.assertEqual(self.get("/api/admin/submissions", user).status_code, 403)
        self.assertEqual(self.get("/api/admin/comments", user).status_code, 403)


class StoreListTests(StoreApiTestCase):
    def test_kind_filter_search_and_sort(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        theme_a = self.make_approved(
            developer,
            theme_payload(id="theme-aaa", name="雪原", summary="雪地", description="纯白雪山主题"),
        )
        theme_b = self.make_approved(developer, theme_payload(id="theme-bbb", name="极光", summary="夜空极光"))
        plugin = self.make_approved(developer, plugin_payload(id="com.example.stats", name="统计插件"))

        # 给 theme-bbb 一条 5 星评论、theme-aaa 一条 3 星评论，验证按评分排序
        user = self.register("rater@example.com")["token"]
        admin = self.admin_token()
        for item_id, rating in ((theme_b["id"], 5), (theme_a["id"], 3)):
            comment = self.post(
                "/api/store/items/{}/comments".format(item_id),
                user,
                json={"rating": rating, "text": "评分 " + str(rating)},
            ).json()
            self.post(
                "/api/admin/comments/{}/review".format(comment["id"]),
                admin,
                json={"action": "approve"},
            )

        # 直接改 downloads，验证下载排序
        conn = db.connect(self.settings.database_path)
        try:
            conn.execute("UPDATE items SET downloads = 10 WHERE id = ?", (theme_b["id"],))
            conn.execute("UPDATE items SET downloads = 99 WHERE id = ?", (theme_a["id"],))
            conn.commit()
        finally:
            conn.close()

        themes = self.get("/api/store/items?kind=theme").json()
        self.assertEqual({row["id"] for row in themes}, {theme_a["id"], theme_b["id"]})
        plugins = self.get("/api/store/items?kind=plugin").json()
        self.assertEqual([row["id"] for row in plugins], [plugin["id"]])
        self.assertEqual(self.get("/api/store/items?kind=bad").status_code, 400)

        search = self.get("/api/store/items?q=极光").json()
        self.assertEqual([row["id"] for row in search], [theme_b["id"]])
        search_author = self.get("/api/store/items?q=测试用户").json()
        self.assertEqual(len(search_author), 3)

        rating_sorted = self.get("/api/store/items?sort=rating").json()
        self.assertEqual(rating_sorted[0]["id"], theme_b["id"])
        self.assertEqual(rating_sorted[0]["rating"], 5.0)

        downloads_sorted = self.get("/api/store/items?sort=downloads").json()
        self.assertEqual(downloads_sorted[0]["id"], theme_a["id"])

        name_sorted = self.get("/api/store/items?sort=name").json()
        names = [row["name"] for row in name_sorted]
        self.assertEqual(names, sorted(names))

        self.assertEqual(len(self.get("/api/store/items?sort=latest").json()), 3)
        self.assertEqual(len(self.get("/api/store/items?sort=whatever").json()), 3)


class ValidationTests(StoreApiTestCase):
    def test_item_validation(self) -> None:
        developer, _ = self.make_developer("dev@example.com")

        no_palette = self.submit(developer, theme_payload(palette=None))
        self.assertEqual(no_palette.status_code, 400)

        missing_key = dict(THEME_PALETTE)
        missing_key.pop("accent")
        self.assertEqual(self.submit(developer, theme_payload(palette=missing_key)).status_code, 400)
        self.assertEqual(
            self.submit(developer, theme_payload(palette=dict(THEME_PALETTE, accent="green"))).status_code,
            400,
        )
        self.assertEqual(self.submit(developer, theme_payload(kind="app")).status_code, 400)
        self.assertEqual(self.submit(developer, theme_payload(name="")).status_code, 400)
        self.assertEqual(
            self.submit(developer, plugin_payload(download_url="")).status_code, 400
        )
        self.assertEqual(
            self.submit(developer, plugin_payload(download_url="ftp://example.com/x.zip")).status_code,
            400,
        )
        self.assertEqual(
            self.submit(developer, theme_payload(id="../evil")).status_code, 400
        )

        first = self.make_item(developer, theme_payload(id="theme-dup"))
        self.assertEqual(first["id"], "theme-dup")
        duplicate = self.submit(developer, theme_payload(id="theme-dup"))
        self.assertEqual(duplicate.status_code, 409)

    def test_request_shape_errors_are_readable(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        bad_json = self.client.post(
            "/api/dev/items",
            headers={"Authorization": "Bearer " + developer},
            json={"kind": ["theme"], "name": 1},
        )
        self.assertEqual(bad_json.status_code, 422)
        self.assertIn("detail", bad_json.json())
        self.assertIsInstance(bad_json.json()["detail"], str)


class ConcurrencyTests(StoreApiTestCase):
    """并发回归：FastAPI 同步依赖可能在线程池的不同线程里创建/关闭连接。"""

    def test_connection_can_be_closed_from_another_thread(self) -> None:
        import threading

        conn = db.connect(self.settings.database_path)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                self.assertEqual(conn.execute("SELECT 1").fetchone()[0], 1)
                conn.close()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(10)
        self.assertFalse(errors, errors)

    def test_parallel_requests_do_not_return_500(self) -> None:
        from concurrent.futures import ThreadPoolExecutor

        account = self.register("parallel@example.com")
        token = account["token"]

        def hit(_index: int) -> list[int]:
            codes: list[int] = []
            for _ in range(4):
                codes.append(self.get("/api/store/items").status_code)
                codes.append(self.get("/api/catalog.json").status_code)
                codes.append(self.get("/api/auth/me", token).status_code)
            return codes

        with ThreadPoolExecutor(max_workers=8) as pool:
            codes = [code for batch in pool.map(hit, range(8)) for code in batch]
        bad = [code for code in codes if code != 200]
        self.assertFalse(bad, "并发请求出现非 200：" + repr(bad[:10]))


class StaticSiteTests(StoreApiTestCase):
    def test_api_priority_and_spa_fallback(self) -> None:
        items = self.get("/api/store/items")
        self.assertEqual(items.status_code, 200)
        self.assertEqual(items.headers["content-type"].split(";")[0], "application/json")

        root = self.get("/")
        self.assertEqual(root.status_code, 200)
        self.assertIn("深清", root.text)

        spa = self.get("/some/deep/link")
        self.assertEqual(spa.status_code, 200)
        self.assertIn("深清", spa.text)

        unknown_api = self.get("/api/nope")
        self.assertEqual(unknown_api.status_code, 404)


if __name__ == "__main__":
    unittest.main()
