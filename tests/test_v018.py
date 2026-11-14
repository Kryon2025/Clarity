"""v0.18 后端测试：自定义主题包 / 商店目录 / 评论审核 / 插件 zip 安装。

不依赖网络：远程目录失败用 mock，在线目录与插件包使用本机 file:// / 本地 zip。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
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
from shenqing.bridge.app_bridge import AppBridge  # noqa: E402
from shenqing.consts import (  # noqa: E402
    APP_VERSION,
    CUSTOM_THEME_PREFIX,
    DEFAULT_THEME,
)
from shenqing.paths import app_data_dir  # noqa: E402
from shenqing.services import store  # noqa: E402
from shenqing.settings import Settings  # noqa: E402

PALETTE = {
    "bgTop": "#0A1F2E",
    "bgMid": "#06202C",
    "bgBottom": "#04121A",
    "accent": "#35E0C8",
    "cardBg": "#0D2634",
    "textPrimary": "#EAF8FC",
}
LIGHT_PALETTE = {
    "bgTop": "#F6EEF1",
    "bgMid": "#F1E3E9",
    "bgBottom": "#E9D6DE",
    "accent": "#D46A8C",
    "cardBg": "#FFFFFF",
    "textPrimary": "#3A2230",
}

_PLUGIN_MAIN = """from shenqing.plugins.api import PluginBase


class Plugin(PluginBase):
    pass
"""


def _write_zip(path: Path, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def _plugin_zip(
    path: Path,
    plugin_id: str = "demo.plugin",
    *,
    top_dir: str = "",
    entry: str = "main.py",
    extra: dict[str, str] | None = None,
) -> Path:
    manifest = {
        "id": plugin_id,
        "name": "演示插件",
        "version": "1.0.0",
        "api_version": "0.1",
        "entry": entry,
        "author": "测试",
        "description": "用于安装测试",
    }
    prefix = f"{top_dir}/" if top_dir else ""
    members: dict[str, str] = {
        prefix + "plugin.json": json.dumps(manifest, ensure_ascii=False),
        prefix + "main.py": _PLUGIN_MAIN,
    }
    members.update(extra or {})
    return _write_zip(path, members)


def _catalog_uri(directory: Path, items: list[dict]) -> str:
    path = directory / "catalog.json"
    path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return path.as_uri()


def _theme_item(item_id: str, **overrides) -> dict:
    item = {
        "id": item_id,
        "kind": "theme",
        "name": f"主题 {item_id}",
        "author": "测试",
        "summary": "摘要",
        "description": "描述",
        "version": "1.0.0",
        "rating": 4.5,
        "downloads": 100,
        "tags": ["测试"],
        "screenshots": [],
        "download_url": "",
        "palette": dict(PALETTE),
        "published_at": "2025-10-01",
    }
    item.update(overrides)
    return item


def _plugin_item(item_id: str, download_url: str, **overrides) -> dict:
    item = {
        "id": item_id,
        "kind": "plugin",
        "name": f"插件 {item_id}",
        "author": "测试",
        "summary": "摘要",
        "description": "描述",
        "version": "1.0.0",
        "rating": 4.0,
        "downloads": 50,
        "tags": ["测试"],
        "screenshots": [],
        "download_url": download_url,
        "palette": {},
        "published_at": "2025-10-01",
    }
    item.update(overrides)
    return item


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


# ================= 1. 自定义主题包 =================
class CustomThemeBridgeTest(_BridgeCase):
    def test_install_switches_and_persists(self) -> None:
        bridge = self.bridge
        changes: list[str] = []
        bridge.themeChanged.connect(changes.append)
        self.assertEqual(bridge.customThemes, [])
        self.assertEqual(bridge.customThemePalette, {})

        self.assertTrue(bridge.installCustomTheme("aurora", "极光", "深夜海面", PALETTE))
        self.assertEqual(bridge.themeMode, "custom:aurora")
        self.assertEqual(bridge.customThemePalette, PALETTE)
        self.assertEqual(changes, ["Dark"])
        themes = bridge.customThemes
        self.assertEqual([item["id"] for item in themes], ["aurora"])
        self.assertEqual(themes[0]["name"], "极光")
        self.assertEqual(themes[0]["description"], "深夜海面")
        self.assertEqual(themes[0]["palette"], PALETTE)
        self.assertTrue(any("已安装主题" in item for item in self.toasts))

        reloaded = self._reload()
        self.assertEqual(reloaded.themeMode, "custom:aurora")
        self.assertEqual(reloaded.customThemePalette, PALETTE)
        self.assertEqual([item["id"] for item in reloaded.customThemes], ["aurora"])

    def test_light_palette_uses_light_chrome(self) -> None:
        changes: list[str] = []
        self.bridge.themeChanged.connect(changes.append)
        self.assertTrue(self.bridge.installCustomTheme("sakura", "樱雾", "", LIGHT_PALETTE))
        self.assertEqual(changes, ["Light"])
        self.assertEqual(self.bridge.customThemePalette, LIGHT_PALETTE)

    def test_invalid_palette_and_id_rejected(self) -> None:
        bridge = self.bridge
        bad_color = dict(PALETTE, accent="#GGGGGG")
        self.assertFalse(bridge.installCustomTheme("bad", "坏色", "", bad_color))
        self.assertFalse(bridge.installCustomTheme("bad", "缺键", "", {"bgTop": "#112233"}))
        self.assertFalse(bridge.installCustomTheme("bad", "不是对象", "", "not-a-dict"))
        self.assertFalse(bridge.installCustomTheme("../evil", "坏 id", "", PALETTE))
        self.assertEqual(bridge.customThemes, [])
        self.assertEqual(bridge.themeMode, DEFAULT_THEME)
        self.assertTrue(any("#RRGGBB" in item or "配色" in item for item in self.toasts))

    def test_theme_limit_is_twenty(self) -> None:
        bridge = self.bridge
        for index in range(store.MAX_CUSTOM_THEMES):
            self.assertTrue(bridge.installCustomTheme(f"t{index}", f"T{index}", "", PALETTE))
        self.assertEqual(len(bridge.customThemes), store.MAX_CUSTOM_THEMES)
        self.assertFalse(bridge.installCustomTheme("t20", "T20", "", PALETTE))
        self.assertEqual(len(bridge.customThemes), store.MAX_CUSTOM_THEMES)
        self.assertTrue(any("最多" in item for item in self.toasts))
        # 已存在的 id 允许更新，不占新名额
        self.assertTrue(bridge.installCustomTheme("t0", "T0 新名字", "", PALETTE))
        self.assertEqual(len(bridge.customThemes), store.MAX_CUSTOM_THEMES)
        self.assertEqual(bridge.customThemes[0]["name"], "T0 新名字")

    def test_remove_current_falls_back_to_solid(self) -> None:
        bridge = self.bridge
        self.assertTrue(bridge.installCustomTheme("a", "A", "", PALETTE))
        self.assertTrue(bridge.installCustomTheme("b", "B", "", PALETTE))
        self.assertEqual(bridge.themeMode, "custom:b")
        # 删除非当前主题不影响当前模式
        self.assertTrue(bridge.removeCustomTheme("a"))
        self.assertEqual(bridge.themeMode, "custom:b")
        self.assertEqual([item["id"] for item in bridge.customThemes], ["b"])
        # 删除当前主题 → 回退 solid
        self.assertTrue(bridge.removeCustomTheme("b"))
        self.assertEqual(bridge.themeMode, DEFAULT_THEME)
        self.assertEqual(bridge.customThemePalette, {})
        self.assertEqual(bridge.customThemes, [])
        self.assertFalse(bridge.removeCustomTheme("b"))

    def test_set_theme_mode_custom_rules(self) -> None:
        bridge = self.bridge
        bridge.setThemeMode("custom:missing")
        self.assertEqual(bridge.themeMode, DEFAULT_THEME)
        self.assertTrue(bridge.installCustomTheme("aurora", "极光", "", PALETTE))
        bridge.setThemeMode("solid")
        self.assertEqual(bridge.themeMode, "solid")
        self.assertEqual(bridge.customThemePalette, {})
        bridge.setThemeMode("custom:aurora")
        self.assertEqual(bridge.themeMode, "custom:aurora")
        self.assertEqual(bridge.customThemePalette, PALETTE)
        bridge.setThemeMode("ocean")
        self.assertEqual(bridge.themeMode, "ocean")
        self.assertEqual(bridge.customThemePalette, {})
        # 设置里残留未知 custom:<id> → 回退 solid（旧值兼容）
        bridge._settings.set("theme_mode", "custom:ghost")
        self.assertEqual(bridge.themeMode, DEFAULT_THEME)
        # 内置主题列表仍然只有 4 个（自定义主题单独暴露）
        self.assertEqual(
            [item["value"] for item in bridge.themes], ["solid", "light", "glass", "ocean"]
        )


# ================= 2. 商店目录：内置 / 远程 / 缓存 =================
class StoreCatalogUnitTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(Path(self._tmp.name) / "settings.json")
        self.clock = [1000.0]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _service(self) -> store.CatalogService:
        return store.CatalogService(self.settings, now=lambda: self.clock[0])

    def test_builtin_catalog_fields(self) -> None:
        items = store.builtin_catalog()
        self.assertEqual(len(items), 10)
        themes = [item for item in items if item["kind"] == "theme"]
        plugins = [item for item in items if item["kind"] == "plugin"]
        self.assertEqual(len(themes), 6)
        self.assertEqual(len(plugins), 4)
        required = {
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
        }
        for item in items:
            self.assertTrue(required <= set(item), item)
            self.assertGreaterEqual(item["rating"], 0)
            self.assertLessEqual(item["rating"], 5)
        for theme in themes:
            self.assertEqual(set(theme["palette"]), set(store.PALETTE_KEYS))
            self.assertEqual(theme["download_url"], "")
        for plugin in plugins:
            self.assertTrue(plugin["download_url"].startswith("http"))
            self.assertEqual(plugin["palette"], {})
        # 过滤 / 排序
        self.assertEqual(store.filter_items(items, "theme", "rating")[0]["rating"], 4.8)
        self.assertEqual(store.filter_items(items, "bogus"), [])
        self.assertEqual(len(store.filter_items(items, "all")), 10)
        self.assertEqual(
            [item["kind"] for item in store.filter_items(items, "plugin")], ["plugin"] * 4
        )
        newest = store.filter_items(items, "", "newest")
        self.assertEqual(newest[0]["published_at"], "2025-10-11")

    def test_empty_url_uses_builtin(self) -> None:
        self.settings.set("store_catalog_url", "")
        service = self._service()
        self.assertEqual(len(service.items()), 10)
        self.assertEqual(service.status, "builtin")
        self.assertEqual(service.error, "")

    def test_online_and_cache_ttl(self) -> None:
        self.settings.set("store_catalog_url", "https://example.com/catalog.json")
        remote = [_theme_item("remote-one")]
        calls: list[str] = []

        def loader(url: str) -> list[dict]:
            calls.append(url)
            return remote

        with mock.patch.object(store, "load_catalog", side_effect=loader):
            service = self._service()
            self.assertEqual([item["id"] for item in service.items()], ["remote-one"])
            self.assertEqual(service.status, "online")
            self.assertEqual(calls, ["https://example.com/catalog.json"])
            service.items()
            self.assertEqual(len(calls), 1)  # 10 分钟内命中缓存
            self.clock[0] += store.CACHE_TTL_SECONDS + 1
            service.items()
            self.assertEqual(len(calls), 2)  # 过期后重新拉取
            self.assertEqual(service.refresh(), "online")
            self.assertEqual(len(calls), 3)  # refresh 强制拉取

    def test_remote_failure_falls_back_to_builtin(self) -> None:
        self.settings.set("store_catalog_url", "https://example.com/catalog.json")
        with mock.patch.object(store, "load_catalog", side_effect=URLError("blocked")):
            service = self._service()
            items = service.items()
        self.assertEqual(len(items), 10)
        self.assertTrue(service.status.startswith("error:"))
        self.assertIn("网络请求失败", service.status)
        # 失败结果也缓存，不会每次重试
        with mock.patch.object(store, "load_catalog") as loader:
            service.items()
            self.assertEqual(loader.call_count, 0)

    def test_http_error_readable(self) -> None:
        self.settings.set("store_catalog_url", "https://example.com/catalog.json")
        error = HTTPError("https://example.com/catalog.json", 404, "Not Found", None, None)
        with mock.patch.object(store, "load_catalog", side_effect=error):
            service = self._service()
            service.items()
        self.assertIn("HTTP 404", service.status)

    def test_parse_catalog_validation(self) -> None:
        with self.assertRaises(store.StoreError):
            store.parse_catalog({})
        with self.assertRaises(store.StoreError):
            store.parse_catalog([])
        with self.assertRaises(store.StoreError):
            store.parse_catalog([{"id": "", "kind": "theme"}])
        items = store.parse_catalog(
            {
                "items": [
                    {"id": "bad-theme", "kind": "theme", "palette": {"bgTop": "#XYZXYZ"}},
                    _theme_item("good-theme"),
                    _theme_item("good-theme"),
                    _plugin_item("good-plugin", "https://example.com/p.zip"),
                ]
            }
        )
        self.assertEqual([item["id"] for item in items], ["good-theme", "good-plugin"])

    def test_normalize_custom_themes_skips_bad_data(self) -> None:
        normalized = store.normalize_custom_themes(
            {
                "ok": {"name": "OK", "description": "", "palette": dict(PALETTE)},
                "bad": {"name": "BAD", "palette": {"bgTop": "#123"}},
                "../evil": {"name": "X", "palette": dict(PALETTE)},
                "not-a-dict": "text",
            }
        )
        self.assertEqual(list(normalized), ["ok"])
        self.assertEqual(normalized["ok"]["palette"], PALETTE)


class StoreCatalogBridgeTest(_BridgeCase):
    def setUp(self) -> None:
        super().setUp()
        self.bridge._settings.set("store_catalog_url", "")

    def test_builtin_items_and_filters(self) -> None:
        bridge = self.bridge
        self.assertEqual(len(bridge.storeItems("")), 10)
        self.assertEqual(len(bridge.storeItems("theme")), 6)
        self.assertEqual(len(bridge.storeItems("plugin")), 4)
        self.assertEqual(bridge.storeCatalogStatus, "builtin")
        ratings = [item["rating"] for item in bridge.storeItems("theme", "rating")]
        self.assertEqual(ratings, sorted(ratings, reverse=True))
        self.assertEqual(bridge.storeItems("bogus"), [])
        item = bridge.storeItem("theme-aurora")
        self.assertEqual(item["kind"], "theme")
        self.assertEqual(item["name"], "极光")
        self.assertEqual(set(item["palette"]), set(store.PALETTE_KEYS))
        self.assertEqual(bridge.storeItem("no-such-item"), {})

    def test_remote_failure_status_and_fallback(self) -> None:
        self.bridge._settings.set("store_catalog_url", "https://example.com/catalog.json")
        with mock.patch.object(store, "load_catalog", side_effect=URLError("blocked")):
            items = self.bridge.storeItems("theme")
        self.assertEqual(len(items), 6)
        self.assertTrue(self.bridge.storeCatalogStatus.startswith("error:"))
        self.assertIn("网络请求失败", self.bridge.storeCatalogError)

    def test_refresh_store_with_local_catalog(self) -> None:
        first = _catalog_uri(Path(self._tmp.name), [_theme_item("local-one")])
        self.bridge._settings.set("store_catalog_url", first)
        self.assertEqual(self.bridge.refreshStore(), "online")
        self.assertEqual(
            [item["id"] for item in self.bridge.storeItems("theme")], ["local-one"]
        )
        # 目录文件变化后，10 分钟缓存内仍返回旧结果
        second = _catalog_uri(Path(self._tmp.name), [_theme_item("local-two")])
        self.assertEqual(second, first)  # 同一路径，内容已改
        self.assertEqual(
            [item["id"] for item in self.bridge.storeItems("theme")], ["local-one"]
        )
        # refreshStore 强制重读
        self.assertEqual(self.bridge.refreshStore(), "online")
        self.assertEqual(
            [item["id"] for item in self.bridge.storeItems("theme")], ["local-two"]
        )
        self.assertEqual(self.bridge.storeItem("local-two")["kind"], "theme")


# ================= 3. 评论与审核 =================
class CommentServiceUnitTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(Path(self._tmp.name) / "settings.json")
        self.clock = [1000.0]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _service(self) -> store.CommentService:
        return store.CommentService(self.settings, now=lambda: self.clock[0])

    def test_pending_approve_reject_flow(self) -> None:
        service = self._service()
        first = service.add("item-one", 4, "  很好用  ")
        self.assertEqual(first["status"], "pending")
        self.assertEqual(first["rating"], 4)
        self.assertEqual(first["text"], "很好用")
        self.assertEqual(service.list("item-one"), {"comments": [], "pendingCount": 1})

        self.assertTrue(service.approve("item-one", first["id"]))
        visible = service.list("item-one")
        self.assertEqual(visible["pendingCount"], 0)
        self.assertEqual([item["id"] for item in visible["comments"]], [first["id"]])
        self.assertEqual(visible["comments"][0]["rating"], 4)

        second = service.add("item-one", 5, "第二条")
        self.assertTrue(service.reject("item-one", second["id"]))
        self.assertEqual(service.list("item-one")["pendingCount"], 0)
        self.assertEqual(len(service.list("item-one")["comments"]), 1)
        self.assertFalse(service.approve("item-one", "missing-id"))
        # 审核可以改主意：被拒绝的评论仍可再通过
        self.assertTrue(service.approve("item-one", second["id"]))
        self.assertEqual(len(service.list("item-one")["comments"]), 2)

    def test_validation(self) -> None:
        service = self._service()
        for rating in (0, 6, -1):
            with self.assertRaises(store.StoreError):
                service.add("item", rating, "文字")
        with self.assertRaises(store.StoreError):
            service.add("item", 5, "   ")
        with self.assertRaises(store.StoreError):
            service.add("item", 5, "字" * (store.MAX_COMMENT_TEXT + 1))
        with self.assertRaises(store.StoreError):
            service.add("", 5, "文字")
        # 非法提交不占用限流额度
        for index in range(3):
            service.add("item", 5, f"正常 {index}")
        self.assertEqual(service.list("item")["pendingCount"], 3)

    def test_rate_limit_per_item(self) -> None:
        service = self._service()
        for index in range(3):
            service.add("item", 5, f"第 {index} 条")
        with self.assertRaises(store.StoreError) as context:
            service.add("item", 5, "第四条")
        self.assertIn("3", str(context.exception))
        self.assertEqual(service.list("item")["pendingCount"], 3)
        # 其他 item 不受影响
        service.add("other", 5, "别的条目")
        self.assertEqual(service.list("other")["pendingCount"], 1)
        # 60 秒之后恢复
        self.clock[0] += store.COMMENT_RATE_WINDOW_SECONDS + 1
        service.add("item", 5, "一分钟之后")
        self.assertEqual(service.list("item")["pendingCount"], 4)

    def test_persistence_and_corrupt_entries(self) -> None:
        service = self._service()
        service.add("item", 4, "持久化")
        reloaded = Settings(Path(self._tmp.name) / "settings.json")
        self.assertEqual(store.list_comments(reloaded, "item")["pendingCount"], 1)
        reloaded.set(
            "store_comments",
            {
                "item": [
                    {"id": "bad-rating", "rating": 9, "text": "x", "status": "pending"},
                    {"id": "empty-text", "rating": 3, "text": "", "status": "pending"},
                    "not-a-dict",
                ]
            },
        )
        self.assertEqual(store.list_comments(reloaded, "item"), {"comments": [], "pendingCount": 0})


class StoreCommentsBridgeTest(_BridgeCase):
    def test_comment_flow_and_moderation(self) -> None:
        bridge = self.bridge
        self.assertEqual(bridge.storeComments("theme-aurora"), {"comments": [], "pendingCount": 0})
        result = bridge.addStoreComment("theme-aurora", 5, "很棒的主题")
        self.assertTrue(result["ok"])
        self.assertEqual(result["pendingCount"], 1)
        self.assertEqual(bridge.storeComments("theme-aurora")["comments"], [])
        entries = bridge._settings.get("store_comments")["theme-aurora"]
        comment_id = entries[0]["id"]
        self.assertTrue(bridge.approveStoreComment("theme-aurora", comment_id))
        visible = bridge.storeComments("theme-aurora")
        self.assertEqual(visible["pendingCount"], 0)
        self.assertEqual(len(visible["comments"]), 1)
        self.assertEqual(visible["comments"][0]["rating"], 5)
        self.assertEqual(visible["comments"][0]["text"], "很棒的主题")
        self.assertFalse(bridge.approveStoreComment("theme-aurora", "missing"))

        bridge.addStoreComment("theme-aurora", 3, "再补一条")
        entries = bridge._settings.get("store_comments")["theme-aurora"]
        pending_id = entries[-1]["id"]
        self.assertTrue(bridge.rejectStoreComment("theme-aurora", pending_id))
        visible = bridge.storeComments("theme-aurora")
        self.assertEqual(visible["pendingCount"], 0)
        self.assertEqual(len(visible["comments"]), 1)

    def test_comment_validation_and_rate_limit(self) -> None:
        bridge = self.bridge
        self.assertFalse(bridge.addStoreComment("item", 0, "文字")["ok"])
        self.assertFalse(bridge.addStoreComment("item", 6, "文字")["ok"])
        self.assertFalse(bridge.addStoreComment("item", 5, "  ")["ok"])
        self.assertFalse(bridge.addStoreComment("item", 5, "字" * 501)["ok"])
        for index in range(3):
            self.assertTrue(bridge.addStoreComment("item", 5, f"正常 {index}")["ok"])
        blocked = bridge.addStoreComment("item", 5, "第四条")
        self.assertFalse(blocked["ok"])
        self.assertIn("3", blocked["message"])
        self.assertTrue(any("频繁" in item for item in self.toasts))


# ================= 4. 插件商店安装（本地 zip） =================
class StorePluginInstallTest(_BridgeCase):
    def setUp(self) -> None:
        super().setUp()
        root = Path(self._tmp.name)
        self.root = root
        plugin_dir = root / "packages"
        plugin_dir.mkdir()
        self.good_zip = _plugin_zip(plugin_dir / "demo.zip", "demo.plugin")
        self.fileurl_zip = _plugin_zip(plugin_dir / "fileurl.zip", "fileurl.plugin")
        self.nested_zip = _plugin_zip(
            plugin_dir / "nested.zip", "nested.plugin", top_dir="nested-plugin"
        )
        self.mismatch_zip = _plugin_zip(plugin_dir / "mismatch.zip", "other.plugin")
        self.missing_manifest_zip = _write_zip(
            plugin_dir / "missing.zip", {"main.py": _PLUGIN_MAIN}
        )
        self.traversal_zip = _plugin_zip(
            plugin_dir / "traversal.zip",
            "traversal.plugin",
            extra={"../../evil.txt": "evil"},
        )
        self.corrupt_zip = plugin_dir / "corrupt.zip"
        self.corrupt_zip.write_bytes(b"this is not a zip")
        self.entries = [
            _plugin_item("demo.plugin", str(self.good_zip)),
            _plugin_item("fileurl.plugin", self.fileurl_zip.as_uri()),
            _plugin_item("nested.plugin", str(self.nested_zip)),
            _plugin_item("mismatch.plugin", str(self.mismatch_zip)),
            _plugin_item("missing.plugin", str(self.missing_manifest_zip)),
            _plugin_item("traversal.plugin", str(self.traversal_zip)),
            _plugin_item("corrupt.plugin", str(self.corrupt_zip)),
            _plugin_item("no-url.plugin", ""),
            _theme_item("theme-item"),
        ]
        self.bridge._settings.set(
            "store_catalog_url", _catalog_uri(root, self.entries)
        )
        self.assertEqual(self.bridge.refreshStore(), "online")

    def _plugins_root(self) -> Path:
        return app_data_dir() / "plugins"

    def test_install_success_and_reload(self) -> None:
        result = self.bridge.installStorePlugin("demo.plugin")
        self.assertTrue(result["ok"], result)
        target = self._plugins_root() / "demo.plugin"
        self.assertTrue((target / "plugin.json").is_file())
        self.assertTrue((target / "main.py").is_file())
        plugin_ids = [item["id"] for item in self.bridge.plugins]
        self.assertIn("demo.plugin", plugin_ids)
        self.assertTrue(any("已安装" in item for item in self.toasts))
        # 再装一次可覆盖升级
        result = self.bridge.installStorePlugin("demo.plugin")
        self.assertTrue(result["ok"], result)

    def test_install_from_file_url(self) -> None:
        result = self.bridge.installStorePlugin("fileurl.plugin")
        self.assertTrue(result["ok"], result)
        target = self._plugins_root() / "fileurl.plugin"
        self.assertTrue((target / "plugin.json").is_file())

    def test_install_flattens_single_top_directory(self) -> None:
        result = self.bridge.installStorePlugin("nested.plugin")
        self.assertTrue(result["ok"], result)
        target = self._plugins_root() / "nested.plugin"
        self.assertTrue((target / "plugin.json").is_file())
        self.assertFalse((target / "nested-plugin").exists())

    def test_invalid_packages_rejected(self) -> None:
        mismatch = self.bridge.installStorePlugin("mismatch.plugin")
        self.assertFalse(mismatch["ok"])
        self.assertIn("不匹配", mismatch["message"])
        self.assertFalse((self._plugins_root() / "mismatch.plugin").exists())

        missing = self.bridge.installStorePlugin("missing.plugin")
        self.assertFalse(missing["ok"])
        self.assertIn("plugin.json", missing["message"])

        corrupt = self.bridge.installStorePlugin("corrupt.plugin")
        self.assertFalse(corrupt["ok"])
        self.assertIn("zip", corrupt["message"])

        traversal = self.bridge.installStorePlugin("traversal.plugin")
        self.assertFalse(traversal["ok"])
        self.assertIn("非法路径", traversal["message"])
        self.assertFalse((self.root / "evil.txt").exists())

    def test_theme_and_missing_url_rejected(self) -> None:
        theme = self.bridge.installStorePlugin("theme-item")
        self.assertFalse(theme["ok"])
        self.assertIn("不是插件", theme["message"])
        no_url = self.bridge.installStorePlugin("no-url.plugin")
        self.assertFalse(no_url["ok"])
        self.assertIn("下载地址", no_url["message"])
        unknown = self.bridge.installStorePlugin("ghost")
        self.assertFalse(unknown["ok"])
        self.assertIn("没有这个条目", unknown["message"])

    def test_download_failure_readable(self) -> None:
        item = store.normalize_item(
            _plugin_item("net.plugin", "https://example.invalid/net.zip")
        )
        assert item is not None
        self.bridge._store._items = [item]
        self.bridge._store._fetched_at = time.time()
        self.bridge._store._status = "builtin"
        with mock.patch.object(
            store.urllib.request, "urlopen", side_effect=URLError("blocked")
        ):
            result = self.bridge.installStorePlugin("net.plugin")
        self.assertFalse(result["ok"])
        self.assertIn("下载插件失败", result["message"])
        self.assertFalse((self._plugins_root() / "net.plugin").exists())


# ================= 5. 版本 =================
class VersionTest(unittest.TestCase):
    def test_v018_version(self) -> None:
        version_tuple = tuple(int(part) for part in APP_VERSION.split("."))
        self.assertGreaterEqual(version_tuple, (0, 18, 0))
        self.assertEqual(pkg_version, APP_VERSION)
        self.assertEqual(CUSTOM_THEME_PREFIX, "custom:")


if __name__ == "__main__":
    unittest.main()
