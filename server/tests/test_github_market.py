"""GitHub 发布源同步 + 开发者发布 Token 测试（CW2 式插件广场能力）。

运行（仓库根目录）：
    python -m unittest discover -s server/tests

覆盖：GitHub 地址必填/格式校验（仓库与 releases 页面）、发布源附加字段、
版本与下载地址自动同步（mock GitHub API，不联网）、同步失败只写错误、
同步统计与管理员权限、商店/catalog 暴露 github_url 与 last_sync_at、
发布 Token 创建（一次性明文）/列表/撤销/过期/最后使用、用 Token 提交与更新、
新列迁移幂等。
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

# 允许直接运行单文件：把仓库根目录加进 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from server import db  # noqa: E402
from server.config import Settings  # noqa: E402
from server.main import GITHUB_URL_REQUIRED_DETAIL, create_app  # noqa: E402
from server.services import github_sync  # noqa: E402

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-pass-123"
PASSWORD = "pass1234"
GITHUB_REPO_URL = "https://github.com/example/aurora-theme"
GITHUB_RELEASES_URL = "https://github.com/example/focus-plugin/releases"

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
        "github_url": GITHUB_REPO_URL,
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
        "github_url": GITHUB_RELEASES_URL,
    }
    payload.update(overrides)
    return payload


def release_payload(**overrides) -> dict:
    """GitHub releases/latest 的简化响应（含 Setup / Portable 两个资产）。"""
    payload = {
        "tag_name": "v1.2.3",
        "name": "v1.2.3",
        "html_url": "https://github.com/example/aurora-theme/releases/tag/v1.2.3",
        "published_at": "2026-01-02T03:04:05Z",
        "assets": [
            {
                "name": "Aurora-Theme-1.2.3-Portable.zip",
                "browser_download_url": "https://example.com/aurora-portable.zip",
            },
            {
                "name": "Aurora-Theme-1.2.3-Setup.exe",
                "browser_download_url": "https://example.com/aurora-setup.exe",
            },
        ],
    }
    payload.update(overrides)
    return payload


def parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(str(text).replace("Z", "+00:00"))


class MarketApiTestCase(unittest.TestCase):
    """每个用例独立临时数据库；关掉后台同步线程，网络用 mock 替身。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="shenqing-market-test-")
        self.addCleanup(self._tmp.cleanup)
        self.settings = Settings(
            secret_key="market-unit-test-secret",
            admin_email=ADMIN_EMAIL,
            admin_password=ADMIN_PASSWORD,
            database_path=os.path.join(self._tmp.name, "store.db"),
            static_dir=os.path.join(self._tmp.name, "static"),
            token_ttl_seconds=3600,
            # 测试不启动后台线程（否则每 6 小时才会触发一次，但没必要留线程）
            github_sync_enabled=False,
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)
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

    def register(self, email: str, name: str = "测试用户") -> dict:
        sent = self.post(
            "/api/auth/send-code", json={"email": email, "purpose": "register"}
        )
        self.assertEqual(sent.status_code, 200, sent.text)
        response = self.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "name": name,
                "code": sent.json()["dev_code"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def login(self, email: str, password: str = PASSWORD) -> str:
        response = self.post("/api/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    def admin_token(self) -> str:
        return self.login(ADMIN_EMAIL, ADMIN_PASSWORD)

    def promote(self, token: str, user_id: int, role: str = "developer"):
        return self.post(
            "/api/admin/users/{}/role".format(user_id), token, json={"role": role}
        )

    def make_developer(self, email: str) -> tuple[str, dict]:
        account = self.register(email)
        promoted = self.promote(self.admin_token(), account["user"]["id"])
        self.assertEqual(promoted.status_code, 200, promoted.text)
        return account["token"], account["user"]

    def submit(self, token: str, payload: dict):
        return self.post("/api/dev/items", token, json=payload)

    def make_item(self, token: str, payload: dict) -> dict:
        response = self.submit(token, payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def approve(self, token: str, item_id: str):
        return self.post(
            "/api/admin/review", token, json={"item_id": item_id, "action": "approve"}
        )

    def make_approved(self, token: str, payload: dict) -> dict:
        item = self.make_item(token, payload)
        approved = self.approve(self.admin_token(), item["id"])
        self.assertEqual(approved.status_code, 200, approved.text)
        return approved.json()

    def run_sync(self, release: dict | None = None, error: Exception | None = None):
        """mock 掉 GitHub API 后触发一次手动同步，返回响应。"""
        admin = self.admin_token()
        if error is not None:
            patch = mock.patch.object(
                github_sync, "fetch_latest_release", side_effect=error
            )
        else:
            patch = mock.patch.object(
                github_sync, "fetch_latest_release", return_value=release or release_payload()
            )
        with patch:
            return self.post("/api/admin/sync", admin)

    def db_item(self, item_id: str) -> dict:
        conn = db.connect(self.settings.database_path)
        try:
            row = conn.execute(
                "SELECT * FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        finally:
            conn.close()
        return dict(row) if row is not None else {}

    def db_execute(self, sql: str, params: tuple = ()) -> None:
        conn = db.connect(self.settings.database_path)
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()


class GithubUrlValidationTests(MarketApiTestCase):
    """提交/更新时 GitHub 地址必填，且必须指向 github.com 的仓库或发布页。"""

    def test_github_url_is_required(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        missing = self.submit(developer, theme_payload(github_url=""))
        self.assertEqual(missing.status_code, 400, missing.text)
        self.assertEqual(missing.json()["detail"], GITHUB_URL_REQUIRED_DETAIL)

        absent = theme_payload()
        absent.pop("github_url")
        no_field = self.submit(developer, absent)
        self.assertEqual(no_field.status_code, 400, no_field.text)
        self.assertEqual(no_field.json()["detail"], GITHUB_URL_REQUIRED_DETAIL)

    def test_github_url_must_be_github_repo_or_releases(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        bad_urls = (
            "https://gitlab.com/example/theme",
            "https://example.com/example/theme",
            "ftp://github.com/example/theme",
            "https://github.com/only-owner",
            "https://github.com/example/theme/tree/main",
            "https://github.com/example/theme/issues",
            "not a url",
        )
        for bad in bad_urls:
            with self.subTest(url=bad):
                response = self.submit(developer, theme_payload(github_url=bad))
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["detail"], GITHUB_URL_REQUIRED_DETAIL)

    def test_github_url_accepts_repo_and_releases(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        repo_item = self.make_item(developer, theme_payload())
        self.assertEqual(repo_item["github_url"], GITHUB_REPO_URL)
        # 默认字段：分支 main、README.md、icon.png、同步字段为空
        self.assertEqual(repo_item["repo_branch"], "main")
        self.assertEqual(repo_item["readme_path"], "README.md")
        self.assertEqual(repo_item["icon_path"], "icon.png")
        self.assertEqual(repo_item["api_version"], "")
        self.assertEqual(repo_item["last_sync_at"], "")
        self.assertEqual(repo_item["last_sync_error"], "")

        plugin_item = self.make_item(developer, plugin_payload(id="com.example.focus"))
        self.assertEqual(plugin_item["github_url"], GITHUB_RELEASES_URL)

        # 尾部斜杠 / .git / 大小写主机名都会被归一化
        normalized = self.make_item(
            developer,
            theme_payload(
                id="theme-normalized",
                github_url="HTTP://GitHub.com/Example/Aurora-Theme.git/",
            ),
        )
        self.assertEqual(normalized["github_url"], "https://github.com/Example/Aurora-Theme")

        with_extra = self.make_item(
            developer,
            plugin_payload(
                id="com.example.extra",
                repo_branch="release/1.0",
                api_version="1",
                readme_path="docs/README.md",
                icon_path="assets/icon.png",
            ),
        )
        self.assertEqual(with_extra["repo_branch"], "release/1.0")
        self.assertEqual(with_extra["api_version"], "1")
        self.assertEqual(with_extra["readme_path"], "docs/README.md")
        self.assertEqual(with_extra["icon_path"], "assets/icon.png")

    def test_publish_source_fields_validation(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        bad_cases = (
            {"repo_branch": "feature/有空格 分支"},
            {"repo_branch": "bad..branch"},
            {"readme_path": "../README.md"},
            {"readme_path": "/README.md"},
            {"icon_path": "https://example.com/icon.png"},
            {"api_version": "x" * 33},
        )
        for overrides in bad_cases:
            with self.subTest(field=overrides):
                response = self.submit(developer, theme_payload(**overrides))
                self.assertEqual(response.status_code, 400, response.text)

        item = self.make_item(developer, theme_payload())
        # 更新时不传 github_url 表示保持原值
        renamed = self.put("/api/dev/items/" + item["id"], developer, json={"name": "改名"})
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["github_url"], GITHUB_REPO_URL)
        # 更新时传非法地址 -> 400，且不落库
        rejected = self.put(
            "/api/dev/items/" + item["id"],
            developer,
            json={"github_url": "https://gitlab.com/a/b"},
        )
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertEqual(rejected.json()["detail"], GITHUB_URL_REQUIRED_DETAIL)
        # 更新时可以换发布源
        moved = self.put(
            "/api/dev/items/" + item["id"],
            developer,
            json={"github_url": "https://github.com/example/aurora-theme/releases"},
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(
            moved.json()["github_url"],
            "https://github.com/example/aurora-theme/releases",
        )


class GithubSyncTests(MarketApiTestCase):
    """GitHub Releases -> 版本/下载地址自动同步（全程 mock，不联网）。"""

    def test_sync_fills_version_and_download_url(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        item = self.make_approved(developer, theme_payload(version="0.0.0"))

        response = self.run_sync()
        self.assertEqual(response.status_code, 200, response.text)
        stats = response.json()
        self.assertTrue(stats["ok"])
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["success"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertTrue(stats["finished_at"].endswith("Z"))

        detail = self.get("/api/store/items/" + item["id"]).json()
        self.assertEqual(detail["version"], "1.2.3")
        # Setup 资产优先于 Portable
        self.assertEqual(detail["download_url"], "https://example.com/aurora-setup.exe")
        self.assertTrue(detail["last_sync_at"].endswith("Z"))
        self.assertEqual(detail["last_sync_error"], "")

    def test_sync_picks_portable_then_first_asset_then_release_page(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        item = self.make_approved(developer, theme_payload())

        portable = release_payload(
            assets=[
                {
                    "name": "Aurora-Portable.zip",
                    "browser_download_url": "https://example.com/portable.zip",
                }
            ]
        )
        self.run_sync(portable)
        detail = self.get("/api/store/items/" + item["id"]).json()
        self.assertEqual(detail["download_url"], "https://example.com/portable.zip")

        first_asset = release_payload(
            assets=[
                {
                    "name": "aurora.zip",
                    "browser_download_url": "https://example.com/aurora.zip",
                }
            ]
        )
        self.run_sync(first_asset)
        detail = self.get("/api/store/items/" + item["id"]).json()
        self.assertEqual(detail["download_url"], "https://example.com/aurora.zip")

        no_assets = release_payload(assets=[])
        self.run_sync(no_assets)
        detail = self.get("/api/store/items/" + item["id"]).json()
        self.assertEqual(
            detail["download_url"],
            "https://github.com/example/aurora-theme/releases/tag/v1.2.3",
        )

    def test_sync_failure_only_records_error(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        item = self.make_approved(developer, theme_payload(version="2.5.0"))

        response = self.run_sync(
            error=github_sync.GitHubSyncError("该仓库还没有发布 Release（或仓库不存在）")
        )
        self.assertEqual(response.status_code, 200, response.text)
        stats = response.json()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["success"], 0)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(len(stats["errors"]), 1)
        self.assertEqual(stats["errors"][0]["item_id"], item["id"])

        detail = self.get("/api/store/items/" + item["id"]).json()
        self.assertIn("Release", detail["last_sync_error"])
        # 失败不影响条目本身：版本、下载地址、审核状态都不变
        self.assertEqual(detail["version"], "2.5.0")
        self.assertEqual(detail["download_url"], "")
        self.assertEqual(detail["status"], "approved")
        self.assertEqual(detail["last_sync_at"], "")

        status = self.get("/api/admin/sync/status", self.admin_token()).json()
        self.assertEqual(status["failed"], 1)
        self.assertEqual(status["success"], 0)
        self.assertEqual(status["errors"][0]["item_id"], item["id"])
        self.assertFalse(status["running"])

    def test_sync_skips_pending_items_and_reports_counts(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        approved = self.make_approved(developer, theme_payload())
        pending = self.make_item(developer, theme_payload(id="theme-pending", name="待审"))

        stats = self.run_sync().json()
        self.assertEqual(stats["total"], 1)
        pending_row = self.get("/api/dev/items", developer).json()
        by_id = {row["id"]: row for row in pending_row}
        self.assertEqual(by_id[pending["id"]]["last_sync_at"], "")
        self.assertEqual(by_id[pending["id"]]["version"], "1.0.0")
        self.assertEqual(by_id[approved["id"]]["version"], "1.2.3")

    def test_sync_does_not_touch_other_fields(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        item = self.make_approved(
            developer,
            plugin_payload(id="com.example.focus", summary="原始简介"),
        )
        self.run_sync()
        detail = self.get("/api/store/items/" + item["id"]).json()
        self.assertEqual(detail["name"], "专注统计")
        self.assertEqual(detail["summary"], "原始简介")
        self.assertEqual(detail["description"], "安装后自动记录专注时长。")
        self.assertEqual(detail["tags"], ["统计"])
        self.assertEqual(detail["platforms"], ["desktop"])
        self.assertEqual(detail["status"], "approved")
        self.assertEqual(detail["github_url"], GITHUB_RELEASES_URL)

    def test_store_catalog_expose_github_and_sync_fields(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        item = self.make_approved(developer, theme_payload())
        self.run_sync()

        listed = self.get("/api/store/items").json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["github_url"], GITHUB_REPO_URL)
        self.assertEqual(listed[0]["version"], "1.2.3")
        self.assertTrue(listed[0]["last_sync_at"])

        catalog = self.get("/api/catalog.json").json()["items"]
        row = next(entry for entry in catalog if entry["id"] == item["id"])
        self.assertEqual(row["github_url"], GITHUB_REPO_URL)
        self.assertEqual(row["version"], "1.2.3")
        self.assertTrue(row["last_sync_at"])

    def test_changing_publish_source_resets_sync_error(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        item = self.make_item(developer, theme_payload())
        # 模拟上一轮同步失败留下的错误（待审核条目不会被后台同步，直接写库）
        self.db_execute(
            "UPDATE items SET last_sync_error = ? WHERE id = ?",
            ("旧错误", item["id"]),
        )

        moved = self.put(
            "/api/dev/items/" + item["id"],
            developer,
            json={"github_url": "https://github.com/example/other-theme"},
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(moved.json()["github_url"], "https://github.com/example/other-theme")
        self.assertEqual(moved.json()["last_sync_error"], "")

        # 只改名字不动发布源时保留原错误（等下一轮同步再校验）
        self.db_execute(
            "UPDATE items SET last_sync_error = ? WHERE id = ?",
            ("另一个错误", item["id"]),
        )
        renamed = self.put(
            "/api/dev/items/" + item["id"], developer, json={"name": "改名"}
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["last_sync_error"], "另一个错误")

        # 审核通过后同步成功：版本被 GitHub 版本覆盖，错误清空
        self.approve(self.admin_token(), item["id"])
        self.run_sync()
        detail = self.get("/api/store/items/" + item["id"]).json()
        self.assertEqual(detail["version"], "1.2.3")
        self.assertEqual(detail["last_sync_error"], "")
        self.assertEqual(
            detail["github_url"], "https://github.com/example/other-theme"
        )

    def test_sync_endpoints_are_admin_only(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        user = self.register("plain@example.com")["token"]
        for token in (developer, user):
            self.assertEqual(self.post("/api/admin/sync", token).status_code, 403)
            self.assertEqual(self.get("/api/admin/sync/status", token).status_code, 403)
        self.assertEqual(self.post("/api/admin/sync").status_code, 401)

        status = self.get("/api/admin/sync/status", self.admin_token()).json()
        self.assertEqual(status["last_run_at"], "")
        self.assertEqual(status["total"], 0)
        self.assertFalse(status["enabled"])
        self.assertEqual(status["interval_seconds"], 6 * 60 * 60)


class DevTokenTests(MarketApiTestCase):
    """开发者发布 Token：一次性明文、列表、撤销、过期、最后使用、Token 发布。"""

    def create_token(self, jwt: str, name: str = "CI 发布", **extra) -> dict:
        response = self.post("/api/dev/tokens", jwt, json={"name": name, **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_create_token_returns_plaintext_once(self) -> None:
        developer, user = self.make_developer("dev@example.com")
        created = self.create_token(developer)
        self.assertTrue(created["token"].startswith("cwpt_"))
        self.assertTrue(created["prefix"].startswith("cwpt_"))
        self.assertEqual(created["prefix"], created["token"][: len(created["prefix"])])
        self.assertEqual(created["scope"], "all")
        self.assertEqual(created["status"], "active")
        self.assertEqual(created["last_used_at"], "")
        self.assertEqual(created["expires_at"], "")
        self.assertEqual(created["user_id"], user["id"])
        self.assertNotIn("token_hash", created)

        listed = self.get("/api/dev/tokens", developer).json()
        self.assertEqual(len(listed), 1)
        self.assertNotIn("token", listed[0])
        self.assertNotIn("token_hash", listed[0])
        self.assertEqual(listed[0]["prefix"], created["prefix"])
        self.assertEqual(listed[0]["name"], "CI 发布")

        # 库里只存 sha256 摘要，绝不存明文
        conn = db.connect(self.settings.database_path)
        try:
            row = conn.execute(
                "SELECT token_hash, prefix FROM developer_tokens WHERE id = ?",
                (created["id"],),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["token_hash"], db.hash_developer_token(created["token"]))
        self.assertNotIn(created["token"], str(dict(row)))

    def test_token_list_order_and_revoke(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        first = self.create_token(developer, "第一个")
        second = self.create_token(developer, "第二个")

        listed = self.get("/api/dev/tokens", developer).json()
        self.assertEqual([row["prefix"] for row in listed], [second["prefix"], first["prefix"]])
        self.assertEqual([row["status"] for row in listed], ["active", "active"])

        revoked = self.post(
            "/api/dev/tokens/{}/revoke".format(first["id"]), developer
        )
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual(revoked.json()["status"], "revoked")
        self.assertTrue(revoked.json()["revoked_at"].endswith("Z"))

        # 撤销是幂等的：再撤一次仍返回 200 + revoked
        again = self.post("/api/dev/tokens/{}/revoke".format(first["id"]), developer)
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(again.json()["status"], "revoked")

        self.assertEqual(
            self.post("/api/dev/tokens/9999/revoke", developer).status_code, 404
        )
        # 别人的 Token 撤不了（统一 404，避免泄露 id）
        other, _ = self.make_developer("other@example.com")
        self.assertEqual(
            self.post("/api/dev/tokens/{}/revoke".format(second["id"]), other).status_code,
            404,
        )
        self.assertEqual(
            [row["status"] for row in self.get("/api/dev/tokens", developer).json()],
            ["active", "revoked"],
        )

    def test_token_expiry_and_revocation_reject_publishing(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        expiring = self.create_token(developer, "会过期", expires_days=1)
        self.assertNotIn(expiring["expires_at"], ("", None))
        delta = parse_iso(expiring["expires_at"]) - datetime.now(timezone.utc)
        self.assertGreater(delta.total_seconds(), 23 * 3600)
        self.assertLess(delta.total_seconds(), 25 * 3600)

        # 直接把过期时间改到过去，模拟 Token 过期
        self.db_execute(
            "UPDATE developer_tokens SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00Z", expiring["id"]),
        )
        expired = self.submit(expiring["token"], theme_payload())
        self.assertEqual(expired.status_code, 401, expired.text)
        self.assertIn("过期", expired.json()["detail"])

        usable = self.create_token(developer, "马上撤销")
        self.post("/api/dev/tokens/{}/revoke".format(usable["id"]), developer)
        revoked = self.submit(usable["token"], theme_payload())
        self.assertEqual(revoked.status_code, 401, revoked.text)
        self.assertIn("撤销", revoked.json()["detail"])

        unknown = self.submit("cwpt_not-a-real-token", theme_payload())
        self.assertEqual(unknown.status_code, 401, unknown.text)
        self.assertIn("无效", unknown.json()["detail"])
        # 登录 JWT 失效时依旧是 401（不会误当成发布 Token）
        self.assertEqual(self.submit("not-a-jwt", theme_payload()).status_code, 401)

    def test_token_can_submit_and_update_items(self) -> None:
        developer, user = self.make_developer("dev@example.com")
        token = self.create_token(developer, "发布用")

        created = self.submit(token["token"], plugin_payload(id="com.example.ci"))
        self.assertEqual(created.status_code, 200, created.text)
        item = created.json()
        self.assertEqual(item["author_id"], user["id"])
        self.assertEqual(item["author"], "测试用户")
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["github_url"], GITHUB_RELEASES_URL)

        # 用过一次之后 last_used_at 有值（列表里可见）
        listed = self.get("/api/dev/tokens", developer).json()
        self.assertTrue(listed[0]["last_used_at"].endswith("Z"))

        updated = self.put(
            "/api/dev/items/" + item["id"],
            token["token"],
            json={"name": "CI 改名", "github_url": "https://github.com/example/ci-plugin"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["name"], "CI 改名")
        self.assertEqual(
            updated.json()["github_url"], "https://github.com/example/ci-plugin"
        )

        # 撤销后立刻不能再用 Token 发布
        self.post("/api/dev/tokens/{}/revoke".format(token["id"]), developer)
        after = self.submit(token["token"], theme_payload())
        self.assertEqual(after.status_code, 401, after.text)
        self.assertIn("撤销", after.json()["detail"])

    def test_token_validation_and_limits(self) -> None:
        developer, _ = self.make_developer("dev@example.com")
        self.assertEqual(
            self.post("/api/dev/tokens", developer, json={"name": "  "}).status_code, 400
        )
        self.assertEqual(
            self.post(
                "/api/dev/tokens",
                developer,
                json={"name": "负数", "expires_days": -1},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.post(
                "/api/dev/tokens",
                developer,
                json={"name": "太长", "expires_days": 99999},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.post(
                "/api/dev/tokens",
                developer,
                json={"name": "scope", "scope": "items"},
            ).status_code,
            400,
        )

        for index in range(db.DEVELOPER_TOKEN_MAX_PER_USER):
            self.create_token(developer, "批量 {}".format(index))
        over = self.post("/api/dev/tokens", developer, json={"name": "超额"})
        self.assertEqual(over.status_code, 400, over.text)
        self.assertIn("上限", over.json()["detail"])

    def test_tokens_require_developer_role(self) -> None:
        user = self.register("plain@example.com")["token"]
        self.assertEqual(
            self.post("/api/dev/tokens", user, json={"name": "x"}).status_code, 403
        )
        self.assertEqual(self.get("/api/dev/tokens", user).status_code, 403)
        self.assertEqual(self.get("/api/dev/tokens").status_code, 401)


class GithubMigrationTests(MarketApiTestCase):
    """老库补列：新列与 developer_tokens 表都能幂等创建，旧数据有安全默认值。"""

    def test_market_columns_migration_is_idempotent(self) -> None:
        legacy_path = os.path.join(self._tmp.name, "legacy.db")
        conn = db.connect(legacy_path)
        try:
            conn.executescript(
                """
                CREATE TABLE users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    name          TEXT NOT NULL,
                    role          TEXT NOT NULL DEFAULT 'user',
                    created_at    TEXT NOT NULL
                );
                CREATE TABLE items (
                    id               TEXT PRIMARY KEY,
                    kind             TEXT NOT NULL,
                    name             TEXT NOT NULL,
                    summary          TEXT NOT NULL DEFAULT '',
                    description      TEXT NOT NULL DEFAULT '',
                    author_id        INTEGER NOT NULL,
                    version          TEXT NOT NULL DEFAULT '1.0.0',
                    download_url     TEXT NOT NULL DEFAULT '',
                    palette_json     TEXT NOT NULL DEFAULT '{}',
                    tags_json        TEXT NOT NULL DEFAULT '[]',
                    screenshots_json TEXT NOT NULL DEFAULT '[]',
                    status           TEXT NOT NULL DEFAULT 'pending',
                    reject_reason    TEXT NOT NULL DEFAULT '',
                    downloads        INTEGER NOT NULL DEFAULT 0,
                    created_at       TEXT NOT NULL,
                    updated_at       TEXT NOT NULL
                );
                """
            )
            now = db.utc_now()
            conn.execute(
                "INSERT INTO users (email, password_hash, name, role, created_at) "
                "VALUES ('old@example.com', 'x', '老用户', 'developer', ?)",
                (now,),
            )
            conn.execute(
                "INSERT INTO items (id, kind, name, summary, description, author_id, version, "
                "download_url, palette_json, tags_json, screenshots_json, status, reject_reason, "
                "downloads, created_at, updated_at) "
                "VALUES ('theme-legacy', 'theme', '老主题', '', '', 1, '1.0.0', '', '{}', "
                "'[]', '[]', 'approved', '', 0, ?, ?)",
                (now, now),
            )
            conn.commit()
        finally:
            conn.close()

        # 连续迁移两次：列与表都只创建一遍，旧行拿到安全默认值
        db.init_db(legacy_path)
        db.init_db(legacy_path)
        conn = db.connect(legacy_path)
        try:
            columns = [str(row[1]) for row in conn.execute("PRAGMA table_info(items)").fetchall()]
            for name in (
                "github_url",
                "repo_branch",
                "api_version",
                "readme_path",
                "icon_path",
                "last_sync_at",
                "last_sync_error",
            ):
                self.assertEqual(columns.count(name), 1, name)
            row = conn.execute(
                "SELECT github_url, repo_branch, readme_path, icon_path, last_sync_at "
                "FROM items WHERE id = 'theme-legacy'",
            ).fetchone()
            self.assertEqual(str(row["github_url"]), "")
            self.assertEqual(str(row["repo_branch"]), "main")
            self.assertEqual(str(row["readme_path"]), "README.md")
            self.assertEqual(str(row["icon_path"]), "icon.png")
            self.assertEqual(str(row["last_sync_at"]), "")
            tables = {
                str(item[0])
                for item in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        finally:
            conn.close()
        self.assertIn("developer_tokens", tables)

        # 老条目在接口里仍然可读：github_url 为空串，前端据此不展示链接
        self.settings = Settings(
            secret_key="market-unit-test-secret",
            admin_email=ADMIN_EMAIL,
            admin_password=ADMIN_PASSWORD,
            database_path=legacy_path,
            static_dir=os.path.join(self._tmp.name, "static-legacy"),
            github_sync_enabled=False,
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)
        rows = self.get("/api/store/items").json()
        self.assertEqual([row["id"] for row in rows], ["theme-legacy"])
        self.assertEqual(rows[0]["github_url"], "")
        self.assertEqual(rows[0]["repo_branch"], "main")


class GithubSyncHelperTests(unittest.TestCase):
    """纯函数单元：地址归一化、版本提取、下载地址挑选（不碰数据库）。"""

    def test_normalize_and_parse_github_url(self) -> None:
        self.assertEqual(
            github_sync.normalize_github_url("https://github.com/Example/Repo/"),
            "https://github.com/Example/Repo",
        )
        self.assertEqual(
            github_sync.normalize_github_url("https://github.com/Example/Repo/releases/tag/v1.0.0"),
            "https://github.com/Example/Repo/releases",
        )
        self.assertEqual(
            github_sync.parse_github_repo("github.com/Example/Repo.git"),
            ("Example", "Repo"),
        )
        for bad in (
            "",
            "https://gitlab.com/a/b",
            "https://github.com/a",
            "https://github.com/a/b/tree/main",
            "ftp://github.com/a/b",
        ):
            with self.subTest(url=bad):
                self.assertEqual(github_sync.normalize_github_url(bad), "")
                self.assertFalse(github_sync.is_github_url(bad))

    def test_release_version_and_download_url(self) -> None:
        self.assertEqual(github_sync.release_version({"tag_name": "v2.0.0"}), "2.0.0")
        self.assertEqual(github_sync.release_version({"tag_name": "V2.0.0"}), "2.0.0")
        self.assertEqual(github_sync.release_version({"tag_name": "release-3"}), "release-3")
        self.assertEqual(github_sync.release_version({"name": "3.1.0"}), "3.1.0")
        self.assertEqual(github_sync.release_version({}), "")

        with_setup = release_payload()
        self.assertEqual(
            github_sync.pick_download_url(with_setup),
            "https://example.com/aurora-setup.exe",
        )
        no_assets = release_payload(assets=[])
        self.assertEqual(
            github_sync.pick_download_url(no_assets),
            "https://github.com/example/aurora-theme/releases/tag/v1.2.3",
        )
        broken_assets = release_payload(assets=[{"name": "x"}, "bad", None])
        self.assertEqual(
            github_sync.pick_download_url(broken_assets),
            "https://github.com/example/aurora-theme/releases/tag/v1.2.3",
        )

    def test_sync_item_reports_invalid_url(self) -> None:
        result = github_sync.sync_item({"github_url": "https://gitlab.com/a/b"})
        self.assertFalse(result["ok"])
        self.assertIn("GitHub 地址无效", result["error"])


if __name__ == "__main__":
    unittest.main()
