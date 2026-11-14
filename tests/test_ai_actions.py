"""v0.21 AI 动作 + 开始专注二次确认：解析 / 白名单 / pending / 接口契约。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SHENQING_NO_SCAN"] = "1"
os.environ["SHENQING_NO_KEEPER"] = "1"

from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

from shenqing.bridge.app_bridge import AppBridge  # noqa: E402
from shenqing.services import ai_actions  # noqa: E402
from shenqing.services.ai import AIService  # noqa: E402
from shenqing.settings import Settings  # noqa: E402


def _actions(reply: str) -> list[dict]:
    return ai_actions.parse_reply(reply)["actions"]


class AiActionsParseTest(unittest.TestCase):
    """解析：json 代码块 / 无语言标记代码块 / 裸 JSON / 非法动作。"""

    def test_parse_json_fence(self) -> None:
        reply = (
            "好的，我帮你切到设置页。\n"
            "```json\n"
            '{"actions": [{"type": "open_page", "page": "settings"}]}\n'
            "```"
        )
        actions = _actions(reply)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["type"], "open_page")
        self.assertEqual(actions[0]["page"], "settings")

    def test_parse_plain_fence(self) -> None:
        reply = "```\n" '{"actions": [{"type": "open_page", "page": "stats"}]}' "\n```"
        self.assertEqual(_actions(reply)[0]["page"], "stats")

    def test_parse_bare_json_object(self) -> None:
        # 单独 JSON（没有动作数组）：直接是一个动作
        reply = '我给你换成深色，{"type": "set_setting", "key": "theme_scheme", "value": "dark"}'
        actions = _actions(reply)
        self.assertEqual(actions[0]["key"], "theme_scheme")
        self.assertEqual(actions[0]["value"], "dark")

    def test_parse_multiple_actions_keep_order(self) -> None:
        reply = (
            '{"actions": ['
            '{"type": "open_page", "page": "spaces"},'
            '{"type": "open_space", "mode": "heavy"},'
            '{"type": "add_blocked_site", "domain": "https://www.bilibili.com/video"}'
            "]}"
        )
        actions = _actions(reply)
        self.assertEqual(
            [item["type"] for item in actions],
            ["open_page", "open_space", "add_blocked_site"],
        )
        self.assertEqual(actions[1]["mode"], "heavy")
        self.assertEqual(actions[2]["domain"], "www.bilibili.com")

    def test_no_actions_returns_empty(self) -> None:
        self.assertEqual(_actions("今天也要专注哦。"), [])
        self.assertEqual(ai_actions.parse_reply(""), {"actions": [], "errors": []})

    def test_non_action_json_ignored(self) -> None:
        reply = '示例配置：```json\n{"foo": 1, "bar": [1, 2]}\n```'
        parsed = ai_actions.parse_reply(reply)
        self.assertEqual(parsed["actions"], [])
        self.assertEqual(parsed["errors"], [])

    def test_invalid_actions_rejected_with_reason(self) -> None:
        reply = (
            '{"actions": ['
            '{"type": "launch_missile"},'
            '{"type": "open_page", "page": "nope"},'
            '{"type": "start_space"},'
            '{"type": "add_blocked_site", "domain": "not a domain"},'
            '{"type": "set_setting", "key": "delete_all_files", "value": 1},'
            '{"type": "set_setting", "key": "ui_font_scale", "value": "巨大"}'
            "]}"
        )
        parsed = ai_actions.parse_reply(reply)
        self.assertEqual(parsed["actions"], [])
        self.assertEqual(len(parsed["errors"]), 6)
        self.assertTrue(any("不支持的动作类型" in item for item in parsed["errors"]))
        self.assertTrue(any("未知的页面" in item for item in parsed["errors"]))
        self.assertTrue(any("start_space" in item for item in parsed["errors"]))
        self.assertTrue(any("域名格式不正确" in item for item in parsed["errors"]))
        self.assertTrue(any("不支持的设置项" in item for item in parsed["errors"]))
        self.assertTrue(any("字号" in item for item in parsed["errors"]))

    def test_action_count_capped(self) -> None:
        actions = "".join(['{"type": "open_page", "page": "spaces"}'] * 15)
        parsed = ai_actions.parse_reply('{"actions": [' + ",".join([actions]) + "]}")
        self.assertEqual(len(parsed["actions"]), ai_actions.MAX_ACTIONS)
        self.assertTrue(parsed["errors"])

    def test_requires_confirmation(self) -> None:
        start = _actions('{"type": "start_space", "mode": "light"}')[0]
        self.assertTrue(ai_actions.requires_confirmation(start))
        self.assertEqual(ai_actions.confirm_label(start), "确认开始")
        page = _actions('{"type": "open_page", "page": "ai"}')[0]
        self.assertFalse(ai_actions.requires_confirmation(page))


class AiActionsSettingWhitelistTest(unittest.TestCase):
    """set_setting 白名单与取值归一化。"""

    def test_required_keys_in_whitelist(self) -> None:
        for key in (
            "theme_style",
            "theme_scheme",
            "language",
            "ui_font_scale",
            "ui_font_family",
            "nav_mode",
            "default_minutes",
            "auto_update",
            "site_block_enabled",
            "hide_desktop_icons",
            "update_source",
            "update_channel",
            "blocked_sites",
        ):
            self.assertIn(key, ai_actions.SETTING_KEYS)

    def test_unknown_key_rejected(self) -> None:
        ok, _value, error = ai_actions.normalize_setting_value("theme", "dark")
        self.assertFalse(ok)
        self.assertIn("不支持", error)
        self.assertEqual(ai_actions.normalize_setting_key("root_shell"), "")

    def test_value_normalization(self) -> None:
        cases = [
            ("theme_style", "液态玻璃", "glass"),
            ("theme_scheme", "深色", "dark"),
            ("language", "english", "en_US"),
            ("nav_mode", "仅图标", "icons"),
            ("update_channel", "预览版", "preview"),
            ("update_source", "GitHub", "github"),
            ("default_minutes", "30 分钟", 30),
            ("auto_update", "关闭", False),
            ("site_block_enabled", "开", True),
            ("hide_desktop_icons", 0, False),
            ("ui_font_scale", "120%", 1.2),
            ("ui_font_scale", 1.0, 1.0),
            ("ui_font_family", "", ""),
        ]
        for key, raw, expected in cases:
            ok, value, error = ai_actions.normalize_setting_value(key, raw)
            self.assertTrue(ok, f"{key}={raw!r} 应合法：{error}")
            self.assertEqual(value, expected, f"{key}={raw!r}")

    def test_value_clamped(self) -> None:
        self.assertEqual(ai_actions.normalize_setting_value("ui_font_scale", 9)[1], 1.4)
        self.assertEqual(ai_actions.normalize_setting_value("ui_font_scale", 0.1)[1], 0.8)
        self.assertEqual(ai_actions.normalize_setting_value("default_minutes", 999)[1], 240)

    def test_blocked_sites_list(self) -> None:
        ok, value, _error = ai_actions.normalize_setting_value(
            "blocked_sites", ["https://www.bilibili.com", "youtube.com"]
        )
        self.assertTrue(ok)
        self.assertEqual(value, ["www.bilibili.com", "youtube.com"])
        ok, value, _error = ai_actions.normalize_setting_value("blocked_sites", "a.com, b.com")
        self.assertTrue(ok)
        self.assertEqual(value, ["a.com", "b.com"])

    def test_setting_value_text(self) -> None:
        self.assertEqual(ai_actions.setting_value_text("ui_font_scale", 1.2), "120%")
        self.assertEqual(ai_actions.setting_value_text("default_minutes", 45), "45 分钟")
        self.assertEqual(ai_actions.setting_value_text("auto_update", True), "开启")
        self.assertEqual(ai_actions.setting_value_text("theme_style", "ocean"), "海洋")

    def test_strip_action_blocks(self) -> None:
        reply = (
            "帮你换成海洋主题。\n"
            "```json\n"
            '{"actions": [{"type": "set_setting", "key": "theme_style", "value": "ocean"}]}\n'
            "```"
        )
        cleaned = ai_actions.strip_action_blocks(reply)
        self.assertEqual(cleaned, "帮你换成海洋主题。")
        # 没有动作块时原样返回
        self.assertEqual(ai_actions.strip_action_blocks("普通回答"), "普通回答")


class AiActionPromptTest(unittest.TestCase):
    def test_system_prompt_mentions_actions(self) -> None:
        prompt = ai_actions.system_prompt()
        for token in ("start_space", "open_space", "set_setting", "open_page", "blocked_site"):
            self.assertIn(token, prompt)
        self.assertIn("ui_font_scale", prompt)

    def test_ai_service_prompt_has_actions(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings(Path(folder) / "settings.json")
            service = AIService(settings)
            try:
                prompt = service.system_prompt()
            finally:
                service.shutdown()
        self.assertIn("深清", prompt)
        self.assertIn("start_space", prompt)
        self.assertIn("actions", prompt)


class BridgeAiActionsTest(unittest.TestCase):
    """Bridge：aiExecuteReply / pending / confirm / 白名单设置 / 跳页。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SHENQING_DATA_DIR"] = self._tmp.name
        self.bridge = AppBridge()
        self.toasts: list[str] = []
        self.pages: list[str] = []
        self.spaces_pages: list[str] = []
        self.bridge.toast.connect(self.toasts.append)
        self.bridge.pageRequested.connect(self.pages.append)
        self.bridge.spacesPageRequested.connect(self.spaces_pages.append)

    def tearDown(self) -> None:
        try:
            self.bridge._session.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.bridge.deleteLater()
        except RuntimeError:
            pass
        self._tmp.cleanup()
        os.environ.pop("SHENQING_DATA_DIR", None)

    def _advance_prepare(self) -> None:
        for _ in range(10):
            self.bridge._tick_prepare()

    def _space(self, mode: str) -> dict:
        return next(item for item in self.bridge.spaces if item["mode"] == mode)

    # ---------- open_page / open_space ----------
    def test_open_page_executes_and_returns_text(self) -> None:
        results = self.bridge.aiExecuteReply(
            "先看设置页。\n```json\n"
            '{"actions": [{"type": "open_page", "page": "settings"}]}\n```'
        )
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"])
        self.assertEqual(results[0]["type"], "open_page")
        self.assertIn("设置", results[0]["text"])
        self.assertEqual(self.pages, ["settings"])
        self.assertEqual(self.bridge.lastRequestedPage, "settings")
        self.assertEqual(self.bridge.aiActionResult["text"], results[0]["text"])
        self.assertEqual(len(self.bridge.aiActionLog), 1)

    def test_open_page_invalid_value_rejected(self) -> None:
        results = self.bridge.aiExecuteReply('{"type": "open_page", "page": "root"}')
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertEqual(self.pages, [])
        self.assertEqual(self.bridge.lastRequestedPage, "")

    def test_open_space_requests_space_page_with_mode(self) -> None:
        results = self.bridge.aiExecuteReply('{"type": "open_space", "mode": "heavy"}')
        self.assertTrue(results[0]["ok"])
        self.assertEqual(self.spaces_pages, ["heavy"])
        self.assertEqual(self.bridge.lastRequestedPage, "spaces")
        self.assertFalse(self.bridge.busy)

    # ---------- start_space 需确认 ----------
    def test_start_space_needs_confirmation(self) -> None:
        results = self.bridge.aiExecuteReply(
            '{"type": "start_space", "mode": "light", "minutes": 25}'
        )
        self.assertTrue(results[0]["pending"])
        self.assertTrue(self.bridge.aiActionPendingActive)
        pending = self.bridge.aiActionPending
        self.assertEqual(pending["type"], "start_space")
        self.assertEqual(pending["mode"], "light")
        self.assertEqual(pending["minutes"], 25)
        self.assertEqual(pending["confirmLabel"], "确认开始")
        self.assertTrue(pending["summary"])
        # 还没开始
        self._advance_prepare()
        self.assertFalse(self.bridge.busy)

    def test_confirm_start_space_really_starts(self) -> None:
        self.bridge.aiExecuteReply('{"type": "start_space", "mode": "light", "minutes": 2}')
        self.assertTrue(self.bridge.aiConfirmAction())
        self.assertFalse(self.bridge.aiActionPendingActive)
        self._advance_prepare()
        self.assertTrue(self.bridge.busy)
        self.assertEqual(self.bridge.sessionLevel, "light")
        self.assertEqual(self.bridge.totalSeconds, 120)
        self.assertTrue(self.bridge.aiActionResult["ok"])
        self.assertIn("开始专注", self.bridge.aiActionResult["text"])
        self.bridge._session.stop()

    def test_cancel_ai_action_does_not_start(self) -> None:
        self.bridge.aiExecuteReply('{"type": "start_space", "mode": "medium"}')
        self.assertTrue(self.bridge.aiCancelAction())
        self.assertFalse(self.bridge.aiActionPendingActive)
        self._advance_prepare()
        self.assertFalse(self.bridge.busy)
        self.assertTrue(any("取消" in text for text in self.toasts))

    def test_confirm_without_pending_returns_false(self) -> None:
        self.assertFalse(self.bridge.aiConfirmAction())
        self.assertFalse(self.bridge.aiCancelAction())

    def test_start_space_missing_space_fails(self) -> None:
        results = self.bridge.aiExecuteReply(
            '{"type": "start_space", "spaceId": "sp_missing"}'
        )
        self.assertFalse(results[0]["ok"])
        self.assertFalse(self.bridge.aiActionPendingActive)

    # ---------- set_setting ----------
    def test_set_setting_font_scale(self) -> None:
        results = self.bridge.aiExecuteReply(
            '{"type": "set_setting", "key": "ui_font_scale", "value": "120%"}'
        )
        self.assertTrue(results[0]["ok"])
        self.assertAlmostEqual(float(self.bridge._settings.get("ui_font_scale")), 1.2)
        self.assertIn("界面字号", results[0]["text"])
        self.assertIn("120%", results[0]["text"])

    def test_set_setting_theme_and_bool(self) -> None:
        self.assertTrue(
            self.bridge.aiExecuteReply(
                '{"type": "set_setting", "key": "theme_style", "value": "海洋"}'
            )[0]["ok"]
        )
        self.assertEqual(self.bridge._settings.get("theme_style"), "ocean")
        self.assertTrue(
            self.bridge.aiExecuteReply(
                '{"type": "set_setting", "key": "auto_update", "value": "关闭"}'
            )[0]["ok"]
        )
        self.assertFalse(bool(self.bridge._settings.get("auto_update")))

    def test_set_setting_illegal_key_not_applied(self) -> None:
        before = dict(self.bridge._settings._data)
        results = self.bridge.aiExecuteReply(
            '{"type": "set_setting", "key": "ai_api_key", "value": "hack"}'
        )
        self.assertFalse(results[0]["ok"])
        self.assertEqual(self.bridge._settings._data, before)

    def test_set_setting_update_channel(self) -> None:
        results = self.bridge.aiExecuteReply(
            '{"type": "set_setting", "key": "update_channel", "value": "预览版"}'
        )
        self.assertTrue(results[0]["ok"])
        self.assertEqual(self.bridge._settings.get("update_channel"), "preview")

    def test_add_and_remove_blocked_site(self) -> None:
        results = self.bridge.aiExecuteReply(
            '{"actions": ['
            '{"type": "add_blocked_site", "domain": "https://bilibili.com/video"},'
            '{"type": "remove_blocked_site", "domain": "bilibili.com"}'
            "]}"
        )
        self.assertTrue(results[0]["ok"])
        self.assertTrue(results[1]["ok"])
        self.assertNotIn("bilibili.com", self.bridge.blockedSites)

    def test_blocked_sites_setting_replaces_list(self) -> None:
        results = self.bridge.aiExecuteReply(
            '{"type": "set_setting", "key": "blocked_sites", "value": ["a.com", "b.com"]}'
        )
        self.assertTrue(results[0]["ok"])
        self.assertEqual(sorted(self.bridge.blockedSites), ["a.com", "b.com"])

    # ---------- 混合 / 自动执行 ----------
    def test_mixed_reply_reports_errors_and_actions(self) -> None:
        results = self.bridge.aiExecuteReply(
            '{"actions": ['
            '{"type": "open_page", "page": "ai"},'
            '{"type": "nope"}'
            "]}"
        )
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0]["ok"])
        self.assertFalse(results[1]["ok"])
        self.assertTrue(any("不支持的动作类型" in text for text in self.toasts))

    def test_ai_result_auto_executes_and_strips_block(self) -> None:
        bridge = self.bridge
        bridge._ai_token = 7
        bridge._ai_mode = "ask"
        bridge._ai_pending_conv = ""
        bridge._on_ai_result(
            7,
            {
                "ok": True,
                "text": '我帮你打开数据页。\n```json\n'
                '{"actions": [{"type": "open_page", "page": "stats"}]}\n```',
                "usage": {},
            },
        )
        self.assertEqual(bridge.aiAnswer, "我帮你打开数据页。")
        self.assertEqual(self.pages, ["stats"])
        self.assertEqual(len(bridge.aiActionLog), 1)

    def test_ai_result_with_only_action_block_uses_fallback_text(self) -> None:
        bridge = self.bridge
        bridge._ai_token = 8
        bridge._ai_mode = "ask"
        bridge._ai_pending_conv = ""
        bridge._on_ai_result(
            8,
            {
                "ok": True,
                "text": '{"actions": [{"type": "open_page", "page": "about"}]}',
                "usage": {},
            },
        )
        self.assertTrue(bridge.aiAnswer)
        self.assertEqual(self.pages, ["about"])


class BridgeStartConfirmationTest(unittest.TestCase):
    """v0.21 开始专注二次确认：requestStart → confirmationPending → confirmStart。"""

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
            self.bridge.deleteLater()
        except RuntimeError:
            pass
        self._tmp.cleanup()
        os.environ.pop("SHENQING_DATA_DIR", None)

    def _advance_prepare(self) -> None:
        for _ in range(10):
            self.bridge._tick_prepare()

    def _space(self, mode: str) -> dict:
        return next(item for item in self.bridge.spaces if item["mode"] == mode)

    def test_request_start_sets_pending_info(self) -> None:
        bridge = self.bridge
        space = self._space("light")
        self.assertTrue(bridge.requestStart(space["id"]))
        self.assertTrue(bridge.confirmationActive)
        info = bridge.confirmationPending
        self.assertEqual(info["spaceId"], space["id"])
        self.assertEqual(info["spaceName"], space["name"])
        self.assertEqual(info["mode"], "light")
        self.assertEqual(info["modeLabel"], "浅清")
        self.assertEqual(info["minutes"], int(space["minutes"]))
        self.assertEqual(info["allowedCount"], 0)
        self.assertIn("白名单", info["whitelistSummary"])
        # 确认摘要与 pending 相同（QML 两个名字都能用）
        self.assertEqual(bridge.confirmationSummary, info)
        # 还没有开始
        self._advance_prepare()
        self.assertFalse(bridge.busy)

    def test_confirm_start_runs_with_space_minutes(self) -> None:
        bridge = self.bridge
        space = self._space("light")
        bridge.setSpaceMinutes(space["id"], 2)
        bridge.toggleSpaceAllowedApp(space["id"], "notion.exe", True)
        self.assertTrue(bridge.requestStart(space["id"]))
        self.assertIn("允许 1 个应用", bridge.confirmationPending["whitelistSummary"])
        self.assertEqual(bridge.confirmationPending["allowedCount"], 1)
        self.assertTrue(bridge.confirmStart())
        self.assertFalse(bridge.confirmationActive)
        self._advance_prepare()
        self.assertTrue(bridge.busy)
        self.assertEqual(bridge.totalSeconds, 120)
        self.assertEqual(bridge.sessionLevel, "light")
        self.assertEqual(bridge.sessionWhitelist, ["notion.exe"])
        bridge._session.stop()

    def test_cancel_start_does_not_run(self) -> None:
        bridge = self.bridge
        self.assertTrue(bridge.requestStartMode("medium"))
        self.assertTrue(bridge.cancelStart())
        self.assertFalse(bridge.confirmationActive)
        self._advance_prepare()
        self.assertFalse(bridge.busy)

    def test_confirm_without_request_returns_false(self) -> None:
        self.assertFalse(self.bridge.confirmStart())
        self.assertFalse(self.bridge.cancelStart())

    def test_request_start_mode_uses_first_space(self) -> None:
        bridge = self.bridge
        second = bridge.addSpaceFor("light")
        bridge.setSpaceMinutesFor("light", 3)
        bridge.setSpaceMinutes(second, 45)
        self.assertTrue(bridge.requestStartMode("light"))
        self.assertEqual(bridge.confirmationPending["minutes"], 3)
        self.assertTrue(bridge.confirmStart())
        self._advance_prepare()
        self.assertEqual(bridge.totalSeconds, 180)
        bridge._session.stop()

    def test_request_start_level_uses_default_minutes(self) -> None:
        bridge = self.bridge
        bridge.setDefaultMinutes(30)
        self.assertTrue(bridge.requestStartLevel("light"))
        self.assertEqual(bridge.confirmationPending["minutes"], 30)
        self.assertTrue(bridge.confirmStart())
        self._advance_prepare()
        self.assertEqual(bridge.totalSeconds, 30 * 60)
        bridge._session.stop()

    def test_request_start_heavy_has_no_whitelist(self) -> None:
        bridge = self.bridge
        heavy = self._space("heavy")
        self.assertTrue(bridge.requestStart(heavy["id"]))
        info = bridge.confirmationPending
        self.assertEqual(info["whitelistSummary"], "")
        self.assertEqual(info["allowedCount"], 0)
        self.assertEqual(info["modeLabel"], "深清")
        bridge.cancelStart()

    def test_request_start_invalid_inputs(self) -> None:
        bridge = self.bridge
        self.assertFalse(bridge.requestStart("sp_missing"))
        self.assertFalse(bridge.requestStartMode("nightmare"))
        self.assertTrue(any("不存在" in text for text in self.toasts))
        self.assertFalse(bridge.confirmationActive)

    def test_request_start_while_busy_refused(self) -> None:
        bridge = self.bridge
        space = self._space("light")
        bridge.startSpace(space["id"])
        self._advance_prepare()
        self.assertTrue(bridge.busy)
        self.assertFalse(bridge.requestStart(space["id"]))
        self.assertFalse(bridge.confirmationActive)
        self.assertTrue(any("已经有正在进行的专注" in text for text in self.toasts))
        bridge._session.stop()

    def test_start_clears_stale_pending(self) -> None:
        bridge = self.bridge
        space = self._space("light")
        self.assertTrue(bridge.requestStart(space["id"]))
        bridge.startSpace(space["id"])
        self.assertFalse(bridge.confirmationActive)
        self._advance_prepare()
        self.assertTrue(bridge.busy)
        bridge._session.stop()

    def test_legacy_start_still_works(self) -> None:
        """startSpace / startMode 语义不变（老调用方不受影响）。"""
        bridge = self.bridge
        space = self._space("light")
        bridge.startSpace(space["id"])
        self._advance_prepare()
        self.assertTrue(bridge.busy)
        bridge._session.stop()
        bridge.startMode("medium")
        self._advance_prepare()
        self.assertTrue(bridge.busy)
        bridge._session.stop()


if __name__ == "__main__":
    unittest.main()
