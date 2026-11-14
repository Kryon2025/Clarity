"""v0.19 网页管理测试：鉴权 / 设置白名单 / 端口回退 / 启停 / state / 空间 / 主题 / 桥接。

全部使用临时数据目录 + 127.0.0.1 随机端口，不占用默认 8765，也不访问外网。
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SHENQING_NO_SCAN"] = "1"
os.environ["SHENQING_NO_KEEPER"] = "1"

from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

from shenqing.bridge.app_bridge import AppBridge  # noqa: E402
from shenqing.consts import APP_VERSION, CUSTOM_THEME_PREFIX  # noqa: E402
from shenqing.core.spaces import SpaceManager  # noqa: E402
from shenqing.core.stats import StatsStore  # noqa: E402
from shenqing.services import webadmin  # noqa: E402
from shenqing.settings import Settings  # noqa: E402


def free_port() -> int:
    """让系统分配一个空闲端口（绑定 0 后立刻释放）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http(url: str, *, method: str = "GET", body=None, headers=None, timeout: float = 5.0):
    """发一个请求，返回 (状态码, 文本)。4xx/5xx 不抛异常。"""
    data = None
    final_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        final_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=final_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


class _FakeSessionHost(webadmin.WebAdminHost):
    """假会话：不碰 Qt 会话/遮罩，只记录调用。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.started: list[tuple[str, object, str]] = []
        self.active = False

    def start_session(self, mode, minutes, space_id):
        if not mode and not space_id:
            return False, "缺少参数"
        self.started.append((str(mode), minutes, str(space_id)))
        self.active = True
        return True, "已开始专注"

    def stop_session(self):
        if not self.active:
            return False, "当前没有正在进行的专注"
        self.active = False
        return True, "已结束专注"

    def session_snapshot(self):
        return {
            "state": "running" if self.active else "idle",
            "remainingSeconds": 60 if self.active else 0,
            "spaceName": "测试空间" if self.active else "",
            "level": "light" if self.active else "",
        }

    def install_store_item(self, item_id):
        if str(item_id) == "missing":
            return False, "商店里没有这个条目"
        return True, f"已安装 {item_id}"


class _ServiceCase(unittest.TestCase):
    """起一个真实的本地 HTTP 服务（临时目录 + 随机端口）。"""

    host_factory = webadmin.WebAdminHost

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_data = os.environ.get("SHENQING_DATA_DIR")
        os.environ["SHENQING_DATA_DIR"] = self._tmp.name
        self.settings = Settings(Path(self._tmp.name) / "settings.json")
        self.settings.set("web_admin_port", free_port())
        self.settings.save()
        self.spaces = SpaceManager(Path(self._tmp.name) / "spaces.json")
        self.stats = StatsStore(Path(self._tmp.name) / "stats.json")
        self.host = self.host_factory(self.settings, self.spaces, self.stats)
        self.service = webadmin.WebAdminService(self.settings, self.host)
        self.assertTrue(self.service.start(), "网页管理服务应能启动")
        self.base = f"http://127.0.0.1:{self.service.port}"
        self.token = str(self.settings.get("web_admin_token") or "")

    def tearDown(self) -> None:
        self.service.stop()
        os.environ.pop("SHENQING_DATA_DIR", None)
        if self._old_data is not None:
            os.environ["SHENQING_DATA_DIR"] = self._old_data
        self._tmp.cleanup()

    # ---- 辅助 ----
    def url_for(self, path: str, token: str | None = None) -> str:
        value = self.token if token is None else token
        return f"{self.base}{path}?token={urllib.parse.quote(str(value))}"

    def get_state(self, token: str | None = None):
        status, text = http(self.url_for("/api/state", token))
        return status, json.loads(text)

    def post(self, path: str, payload: dict, token: str | None = None):
        status, text = http(self.url_for(path, token), method="POST", body=payload)
        return status, json.loads(text)


class AuthenticationTest(_ServiceCase):
    def test_api_without_token_is_401(self) -> None:
        status, text = http(f"{self.base}/api/state")
        self.assertEqual(status, 401)
        self.assertFalse(json.loads(text)["ok"])

    def test_api_with_wrong_token_is_401(self) -> None:
        status, _text = http(self.url_for("/api/state", "not-the-token"))
        self.assertEqual(status, 401)

    def test_api_with_query_token_is_200(self) -> None:
        status, payload = self.get_state()
        self.assertEqual(status, 200)
        self.assertEqual(payload["version"], APP_VERSION)

    def test_api_with_header_token_is_200(self) -> None:
        status, _text = http(
            f"{self.base}/api/state",
            headers={webadmin.TOKEN_HEADER: self.token},
        )
        self.assertEqual(status, 200)

    def test_page_without_token_shows_input(self) -> None:
        status, text = http(f"{self.base}/")
        self.assertEqual(status, 200)
        self.assertIn("网页管理", text)
        self.assertIn('id="t"', text)

    def test_page_with_token_serves_panel(self) -> None:
        status, text = http(self.url_for("/"))
        self.assertEqual(status, 200)
        for marker in ("概览", "空间", "设置", "统计", "商店"):
            self.assertIn(marker, text)
        # 浅色 + 移动端自适应 + 轮询
        self.assertIn("prefers-color-scheme", text)
        self.assertIn("viewport", text)
        self.assertIn("setInterval(refresh", text)

    def test_unknown_api_is_404(self) -> None:
        status, _text = http(self.url_for("/api/nope"))
        self.assertEqual(status, 404)


class StateTest(_ServiceCase):
    def test_state_structure(self) -> None:
        self.stats.record(25, "medium", True, space="覆清空间")
        status, state = self.get_state()
        self.assertEqual(status, 200)
        for key in (
            "version",
            "themeMode",
            "themes",
            "spaces",
            "stats",
            "settings",
            "plugins",
            "storeStatus",
        ):
            self.assertIn(key, state)
        self.assertEqual(state["version"], APP_VERSION)
        self.assertEqual(set(state["spaces"].keys()), {"light", "medium", "heavy"})
        for mode in ("light", "medium", "heavy"):
            self.assertTrue(state["spaces"][mode], f"{mode} 至少一个空间")
        self.assertEqual(set(state["settings"].keys()), set(webadmin.SETTINGS_KEYS))
        stats_keys = set(state["stats"].keys())
        self.assertTrue({"todayMinutes", "weekMinutes", "heatmap"} <= stats_keys)
        self.assertEqual(len(state["stats"]["heatmap"]), webadmin.HEATMAP_DAYS)
        self.assertEqual(state["stats"]["todayMinutes"], 25.0)
        self.assertEqual(state["stats"]["todaySessions"], 1)
        self.assertTrue(any(item["value"] == "ocean" for item in state["themes"]))
        self.assertTrue(state["webAdmin"]["running"])

    def test_store_status_builtin_without_store(self) -> None:
        _status, state = self.get_state()
        self.assertEqual(state["storeStatus"], "builtin")


class SettingsWhitelistTest(_ServiceCase):
    def test_theme_mode_allowed(self) -> None:
        status, payload = self.post("/api/settings", {"key": "theme_mode", "value": "ocean"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(self.settings.get("theme_mode"), "ocean")
        _status, state = self.get_state()
        self.assertEqual(state["themeMode"], "ocean")

    def test_unknown_theme_rejected(self) -> None:
        status, payload = self.post("/api/settings", {"key": "theme_mode", "value": "neon"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_token_and_port_not_editable(self) -> None:
        for key in ("web_admin_token", "web_admin_port", "ai_api_key"):
            status, payload = self.post("/api/settings", {"key": key, "value": "x"})
            self.assertEqual(status, 400, key)
            self.assertFalse(payload["ok"])

    def test_language_and_nav_mode(self) -> None:
        status, _payload = self.post("/api/settings", {"key": "language", "value": "en_US"})
        self.assertEqual(status, 200)
        self.assertEqual(self.settings.get("language"), "en_US")
        status, _payload = self.post("/api/settings", {"key": "language", "value": "xx_YY"})
        self.assertEqual(status, 400)
        status, _payload = self.post("/api/settings", {"key": "nav_mode", "value": "icons"})
        self.assertEqual(status, 200)
        self.assertEqual(self.settings.get("nav_mode"), "icons")
        status, _payload = self.post("/api/settings", {"key": "nav_mode", "value": "wide"})
        self.assertEqual(status, 400)

    def test_font_scale_clamped(self) -> None:
        status, _payload = self.post("/api/settings", {"key": "ui_font_scale", "value": 3.2})
        self.assertEqual(status, 200)
        self.assertEqual(self.settings.get("ui_font_scale"), 1.4)
        self.post("/api/settings", {"key": "ui_font_scale", "value": 0.1})
        self.assertEqual(self.settings.get("ui_font_scale"), 0.8)

    def test_default_minutes_clamped(self) -> None:
        self.post("/api/settings", {"key": "default_minutes", "value": 999})
        self.assertEqual(self.settings.get("default_minutes"), 240)
        self.post("/api/settings", {"key": "default_minutes", "value": 0})
        self.assertEqual(self.settings.get("default_minutes"), 1)

    def test_booleans(self) -> None:
        self.post("/api/settings", {"key": "auto_update", "value": False})
        self.assertFalse(self.settings.get("auto_update"))
        self.post("/api/settings", {"key": "auto_update", "value": "true"})
        self.assertTrue(self.settings.get("auto_update"))
        self.post("/api/settings", {"key": "site_block_enabled", "value": 0})
        self.assertFalse(self.settings.get("site_block_enabled"))

    def test_font_family(self) -> None:
        self.post("/api/settings", {"key": "ui_font_family", "value": "  微软雅黑  "})
        self.assertEqual(self.settings.get("ui_font_family"), "微软雅黑")

    def test_missing_key(self) -> None:
        status, _payload = self.post("/api/settings", {"value": "ocean"})
        self.assertEqual(status, 400)

    def test_web_admin_enabled_stays_running(self) -> None:
        status, _payload = self.post("/api/settings", {"key": "web_admin_enabled", "value": True})
        self.assertEqual(status, 200)
        self.assertTrue(self.service.running)
        self.assertTrue(self.settings.get("web_admin_enabled"))


class SpacesApiTest(_ServiceCase):
    def _light_ids(self) -> list[str]:
        _status, state = self.get_state()
        return [item["id"] for item in state["spaces"]["light"]]

    def test_add_space(self) -> None:
        status, payload = self.post("/api/spaces", {"action": "add", "mode": "light"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(self.spaces.by_mode("light")), 2)
        self.assertEqual(payload["space"]["mode"], "light")

    def test_add_heavy_rejected(self) -> None:
        status, payload = self.post("/api/spaces", {"action": "add", "mode": "heavy"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_rename_space(self) -> None:
        space_id = self._light_ids()[0]
        status, payload = self.post(
            "/api/spaces", {"action": "rename", "spaceId": space_id, "name": "写作空间"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.spaces.get(space_id)["name"], "写作空间")
        self.assertTrue(payload["ok"])

    def test_rename_heavy_rejected(self) -> None:
        _status, state = self.get_state()
        heavy_id = state["spaces"]["heavy"][0]["id"]
        status, _payload = self.post(
            "/api/spaces", {"action": "rename", "spaceId": heavy_id, "name": "改名"}
        )
        self.assertEqual(status, 400)

    def test_rename_empty_rejected(self) -> None:
        space_id = self._light_ids()[0]
        status, _payload = self.post(
            "/api/spaces", {"action": "rename", "spaceId": space_id, "name": "   "}
        )
        self.assertEqual(status, 400)

    def test_change_minutes(self) -> None:
        space_id = self._light_ids()[0]
        status, payload = self.post(
            "/api/spaces", {"action": "minutes", "spaceId": space_id, "minutes": 45}
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.spaces.get(space_id)["minutes"], 45)
        self.assertEqual(payload["space"]["minutes"], 45)

    def test_heavy_minutes_allowed(self) -> None:
        _status, state = self.get_state()
        heavy_id = state["spaces"]["heavy"][0]["id"]
        status, _payload = self.post(
            "/api/spaces", {"action": "minutes", "spaceId": heavy_id, "minutes": 30}
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.spaces.get(heavy_id)["minutes"], 30)

    def test_delete_space(self) -> None:
        _status, payload = self.post("/api/spaces", {"action": "add", "mode": "medium"})
        new_id = payload["space"]["id"]
        status, _payload = self.post("/api/spaces", {"action": "delete", "spaceId": new_id})
        self.assertEqual(status, 200)
        self.assertIsNone(self.spaces.get(new_id))

    def test_delete_last_space_rejected(self) -> None:
        space_id = self._light_ids()[0]
        status, _payload = self.post("/api/spaces", {"action": "delete", "spaceId": space_id})
        self.assertEqual(status, 400)

    def test_missing_space_id(self) -> None:
        status, _payload = self.post("/api/spaces", {"action": "minutes", "minutes": 20})
        self.assertEqual(status, 400)

    def test_unknown_action(self) -> None:
        status, _payload = self.post("/api/spaces", {"action": "explode"})
        self.assertEqual(status, 400)


class ThemeApiTest(_ServiceCase):
    def test_switch_builtin_theme(self) -> None:
        status, payload = self.post("/api/theme", {"mode": "light"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["themeMode"], "light")
        self.assertEqual(self.settings.get("theme_mode"), "light")

    def test_unknown_theme(self) -> None:
        status, _payload = self.post("/api/theme", {"mode": "neon"})
        self.assertEqual(status, 400)

    def test_custom_theme(self) -> None:
        self.settings.set(
            "custom_themes",
            {
                "demo": {
                    "name": "演示主题",
                    "description": "测试",
                    "palette": {
                        "bgTop": "#0A1F2E",
                        "bgMid": "#06202C",
                        "bgBottom": "#04121A",
                        "accent": "#35E0C8",
                        "cardBg": "#0D2634",
                        "textPrimary": "#EAF8FC",
                    },
                }
            },
        )
        status, payload = self.post("/api/theme", {"mode": CUSTOM_THEME_PREFIX + "demo"})
        self.assertEqual(status, 200)
        self.assertEqual(self.settings.get("theme_mode"), CUSTOM_THEME_PREFIX + "demo")
        _status, state = self.get_state()
        self.assertTrue(any(item.get("custom") for item in state["themes"]))


class SessionApiTest(_ServiceCase):
    host_factory = _FakeSessionHost

    def test_start_requires_mode_and_minutes(self) -> None:
        status, _payload = self.post("/api/session", {"action": "start", "mode": "light"})
        self.assertEqual(status, 400)
        status, _payload = self.post("/api/session", {"action": "start", "minutes": 25})
        self.assertEqual(status, 400)

    def test_start_with_mode_and_minutes(self) -> None:
        status, payload = self.post(
            "/api/session", {"action": "start", "mode": "light", "minutes": 30}
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(self.host.started, [("light", 30, "")])
        self.assertEqual(payload["session"]["state"], "running")

    def test_start_with_space_id(self) -> None:
        _status, state = self.get_state()
        space_id = state["spaces"]["medium"][0]["id"]
        status, _payload = self.post("/api/session", {"action": "start", "spaceId": space_id})
        self.assertEqual(status, 200)
        self.assertEqual(self.host.started[0][2], space_id)

    def test_stop(self) -> None:
        self.post("/api/session", {"action": "start", "mode": "light", "minutes": 30})
        status, payload = self.post("/api/session", {"action": "stop"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["session"]["state"], "idle")
        status, _payload = self.post("/api/session", {"action": "stop"})
        self.assertEqual(status, 400)

    def test_unknown_action(self) -> None:
        status, _payload = self.post("/api/session", {"action": "pause"})
        self.assertEqual(status, 400)


class StoreInstallApiTest(_ServiceCase):
    host_factory = _FakeSessionHost

    def test_install_missing_item(self) -> None:
        status, payload = self.post("/api/store/install", {"itemId": "missing"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_install_ok(self) -> None:
        status, payload = self.post("/api/store/install", {"itemId": "theme-aurora"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

    def test_install_requires_item_id(self) -> None:
        status, _payload = self.post("/api/store/install", {})
        self.assertEqual(status, 400)


class PortFallbackTest(unittest.TestCase):
    """端口被占用时自动 +1（最多 20 次）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_data = os.environ.get("SHENQING_DATA_DIR")
        os.environ["SHENQING_DATA_DIR"] = self._tmp.name

    def tearDown(self) -> None:
        os.environ.pop("SHENQING_DATA_DIR", None)
        if self._old_data is not None:
            os.environ["SHENQING_DATA_DIR"] = self._old_data
        self._tmp.cleanup()

    def test_port_fallback(self) -> None:
        blocker = None
        blocked = 0
        for _ in range(30):
            candidate = free_port()
            if candidate + 1 > 65535:
                continue
            blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                blocker.bind(("127.0.0.1", candidate))
                blocker.listen(1)
            except OSError:
                blocker.close()
                blocker = None
                continue
            blocked = candidate
            break
        self.assertIsNotNone(blocker, "找不到可占用的端口")
        settings = Settings(Path(self._tmp.name) / "settings.json")
        settings.set("web_admin_port", blocked)
        spaces = SpaceManager(Path(self._tmp.name) / "spaces.json")
        service = webadmin.WebAdminService(settings, webadmin.WebAdminHost(settings, spaces))
        try:
            self.assertTrue(service.start())
            self.assertNotEqual(service.port, blocked)
            self.assertGreater(service.port, blocked)
            self.assertLessEqual(service.port, blocked + webadmin.MAX_PORT_ATTEMPTS)
            running, url, error = service.status()
            self.assertTrue(running)
            self.assertIn(f":{service.port}/", url)
            self.assertIn("token=", url)
            self.assertEqual(error, "")
        finally:
            service.stop()
            if blocker is not None:
                blocker.close()
        self.assertFalse(service.running)

    def test_auto_port_zero(self) -> None:
        """web_admin_port=0 时由系统分配端口（测试/嵌入场景）。"""
        settings = Settings(Path(self._tmp.name) / "settings.json")
        settings.set("web_admin_port", 0)
        spaces = SpaceManager(Path(self._tmp.name) / "spaces.json")
        service = webadmin.WebAdminService(settings, webadmin.WebAdminHost(settings, spaces))
        try:
            self.assertTrue(service.start())
            self.assertGreater(service.port, 0)
        finally:
            service.stop()


class LifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_data = os.environ.get("SHENQING_DATA_DIR")
        os.environ["SHENQING_DATA_DIR"] = self._tmp.name
        self.settings = Settings(Path(self._tmp.name) / "settings.json")
        self.settings.set("web_admin_port", free_port())
        self.spaces = SpaceManager(Path(self._tmp.name) / "spaces.json")
        self.host = webadmin.WebAdminHost(self.settings, self.spaces)
        self.service = webadmin.WebAdminService(self.settings, self.host)

    def tearDown(self) -> None:
        self.service.stop()
        os.environ.pop("SHENQING_DATA_DIR", None)
        if self._old_data is not None:
            os.environ["SHENQING_DATA_DIR"] = self._old_data
        self._tmp.cleanup()

    def test_token_generated_once_and_persisted(self) -> None:
        self.assertEqual(self.settings.get("web_admin_token"), "")
        token = self.service.ensure_token()
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(self.settings.get("web_admin_token"), token)
        # 已持久化：重新读设置还是同一个 token
        reloaded = Settings(Path(self._tmp.name) / "settings.json")
        self.assertEqual(reloaded.get("web_admin_token"), token)
        self.assertEqual(self.service.ensure_token(), token)

    def test_regenerate_token_changes_and_persists(self) -> None:
        first = self.service.ensure_token()
        second = self.service.regenerate_token()
        self.assertNotEqual(first, second)
        self.assertEqual(self.settings.get("web_admin_token"), second)
        self.assertEqual(self.service.token, second)

    def test_start_stop_start(self) -> None:
        self.assertFalse(self.service.running)
        self.assertEqual(self.service.status(), (False, "", ""))
        self.assertTrue(self.service.start())
        self.assertTrue(self.service.running)
        running, url, error = self.service.status()
        self.assertTrue(running)
        self.assertTrue(url.startswith("http://127.0.0.1:"))
        self.assertTrue(url.endswith("?token=" + self.service.token))
        self.assertEqual(error, "")
        status, _text = http(url.replace("/?token=", "/api/state?token="))
        self.assertEqual(status, 200)
        self.service.stop()
        self.assertFalse(self.service.running)
        self.assertEqual(self.service.url, "")
        # 再启动：同端口可以继续用
        self.assertTrue(self.service.start())
        self.assertTrue(self.service.running)

    def test_set_enabled_toggles_setting(self) -> None:
        self.assertTrue(self.service.set_enabled(True))
        self.assertTrue(self.service.running)
        self.assertTrue(self.settings.get("web_admin_enabled"))
        self.assertTrue(self.service.set_enabled(False))
        self.assertFalse(self.service.running)
        self.assertFalse(self.settings.get("web_admin_enabled"))

    def test_start_twice_is_idempotent(self) -> None:
        self.assertTrue(self.service.start())
        port = self.service.port
        self.assertTrue(self.service.start())
        self.assertEqual(self.service.port, port)

    def test_web_admin_enabled_off_by_default(self) -> None:
        fresh = Settings(Path(self._tmp.name) / "fresh.json")
        self.assertFalse(fresh.get("web_admin_enabled"))
        self.assertEqual(fresh.get("web_admin_port"), 8765)
        self.assertEqual(fresh.get("web_admin_token"), "")


class BridgeWebAdminTest(unittest.TestCase):
    """桥接层：属性 / Slot / 信号（app.py 用这些接口）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_data = os.environ.get("SHENQING_DATA_DIR")
        os.environ["SHENQING_DATA_DIR"] = self._tmp.name
        settings = Settings(Path(self._tmp.name) / "settings.json")
        settings.set("web_admin_port", free_port())
        # 用内置目录，避免测试联网
        settings.set("store_catalog_url", "")
        settings.save()
        self.bridge = AppBridge()
        self.settings = self.bridge._settings

    def tearDown(self) -> None:
        self.bridge.stopWebAdmin()
        os.environ.pop("SHENQING_DATA_DIR", None)
        if self._old_data is not None:
            os.environ["SHENQING_DATA_DIR"] = self._old_data
        self._tmp.cleanup()

    def test_defaults(self) -> None:
        self.assertFalse(self.bridge.webAdminEnabled)
        self.assertEqual(self.bridge.webAdminUrl, "")
        self.assertEqual(self.bridge.webAdminError, "")

    def test_enable_starts_and_exposes_url(self) -> None:
        changes: list[int] = []
        self.bridge.webAdminChanged.connect(lambda: changes.append(1))
        self.bridge.setWebAdminEnabled(True)
        self.assertTrue(self.bridge.webAdminEnabled)
        url = self.bridge.webAdminUrl
        self.assertTrue(url.startswith("http://127.0.0.1:"))
        self.assertIn("token=", url)
        token = str(self.settings.get("web_admin_token") or "")
        self.assertIn(token, url)
        self.assertEqual(self.bridge.webAdminError, "")
        self.assertTrue(changes)
        # 管理页能读到真实状态
        base = url.split("/?token=")[0]
        status, text = http(f"{url.replace('/?token=', '/api/state?token=')}")
        self.assertEqual(status, 200)
        payload = json.loads(text)
        self.assertEqual(payload["version"], APP_VERSION)
        self.assertTrue(payload["webAdmin"]["running"])
        self.assertEqual(len(payload["spaces"]["light"]), 1)
        self.assertIn("plugins", payload)
        # 关掉：地址失效
        self.bridge.setWebAdminEnabled(False)
        self.assertEqual(self.bridge.webAdminUrl, "")
        with self.assertRaises((urllib.error.URLError, OSError)):
            http(f"{base}/api/state?token={token}", timeout=1.5)

    def test_regenerate_token(self) -> None:
        self.bridge.setWebAdminEnabled(True)
        old_url = self.bridge.webAdminUrl
        old_token = str(self.settings.get("web_admin_token") or "")
        new_token = self.bridge.regenerateWebAdminToken()
        self.assertNotEqual(new_token, old_token)
        self.assertIn(new_token, self.bridge.webAdminUrl)
        self.assertNotIn(old_token, self.bridge.webAdminUrl)
        base = old_url.split("/?token=")[0]
        status, _text = http(f"{base}/api/state?token={old_token}")
        self.assertEqual(status, 401)
        status, _text = http(f"{base}/api/state?token={new_token}")
        self.assertEqual(status, 200)

    def test_open_web_admin_uses_desktop_services(self) -> None:
        from PySide6.QtGui import QDesktopServices

        self.bridge.setWebAdminEnabled(True)
        url = self.bridge.webAdminUrl
        opened: list[str] = []
        with mock.patch.object(
            QDesktopServices, "openUrl", side_effect=lambda qurl: opened.append(qurl.toString())
        ) as patched:
            self.bridge.openWebAdmin()
        self.assertTrue(patched.called)
        self.assertEqual(opened, [url])

    def test_start_web_admin_respects_setting(self) -> None:
        self.assertFalse(self.bridge.startWebAdmin())
        self.assertFalse(self.bridge._web_admin.running)

    def test_disable_from_web_page(self) -> None:
        """在管理页里关掉网页管理：先正常回包，再停止服务。"""
        self.bridge.setWebAdminEnabled(True)
        url = self.bridge.webAdminUrl
        token = str(self.settings.get("web_admin_token") or "")
        base = url.split("/?token=")[0]
        status, text = http(
            url.replace("/?token=", "/api/settings?token="),
            method="POST",
            body={"key": "web_admin_enabled", "value": False},
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(text)["ok"])
        self.assertFalse(self.settings.get("web_admin_enabled"))
        for _ in range(40):
            if not self.bridge._web_admin.running:
                break
            time.sleep(0.05)
        self.assertFalse(self.bridge._web_admin.running)
        self.assertEqual(self.bridge.webAdminUrl, "")
        with self.assertRaises((urllib.error.URLError, OSError)):
            http(f"{base}/api/state?token={token}", timeout=1.5)

    def test_web_settings_apply_to_bridge(self) -> None:
        self.bridge.setWebAdminEnabled(True)
        url = self.bridge.webAdminUrl
        status, _text = http(
            url.replace("/?token=", "/api/settings?token="),
            method="POST",
            body={"key": "theme_mode", "value": "ocean"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.bridge.themeMode, "ocean")
        self.assertEqual(str(self.settings.get("theme_mode")), "ocean")


if __name__ == "__main__":
    unittest.main()
