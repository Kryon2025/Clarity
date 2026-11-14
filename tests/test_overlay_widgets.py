"""右侧组件（v0.21）测试：布局规范化 / 增删改 / 天气与一言回退 / Bridge 读写。

全部不联网：天气与一言的 HTTP 一律 mock.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SHENQING_NO_SCAN"] = "1"
os.environ["SHENQING_NO_KEEPER"] = "1"

from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

from shenqing.bridge import app_bridge  # noqa: E402
from shenqing.bridge.app_bridge import AppBridge, _WidgetDataTask  # noqa: E402
from shenqing.consts import OVERLAY_WIDGET_DEFAULT_LAYOUT, QUOTES  # noqa: E402
from shenqing.services import overlay_widgets as widgets  # noqa: E402


class _FakeResponse:
    """最小化的 urlopen 返回对象（with 语句 + read()）。"""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _json_response(payload: object) -> _FakeResponse:
    return _FakeResponse(json.dumps(payload).encode("utf-8"))


NMC_PAYLOAD = {
    "code": 0,
    "msg": "success",
    "data": {
        "real": {
            "station": {"code": "58362", "city": "北京市", "province": "北京市"},
            "publish_time": "2026-11-14 08:00",
            "weather": {"temperature": 12.0, "info": "晴", "humidity": 40},
        },
        "predict": {"detail": []},
    },
}

HITOKOTO_PAYLOAD = {"id": 1, "hitokoto": "先把眼前这一件事做完。", "from": "深清测试"}


# ================= 纯函数：布局 =================
class LayoutTest(unittest.TestCase):
    def test_default_layout_is_clock_today_quote(self) -> None:
        layout = widgets.default_layout()
        self.assertEqual([item["type"] for item in layout], ["clock", "today", "quote"])
        self.assertEqual([item["id"] for item in layout], ["clock-1", "today-1", "quote-1"])
        for item in layout:
            self.assertTrue(item["visible"])
            self.assertTrue(0.0 <= item["x"] <= 1.0)
            self.assertGreaterEqual(item["w"], widgets.MIN_WIDGET_SIZE)
            self.assertLessEqual(item["x"] + item["w"], 1.0)
            self.assertLessEqual(item["y"] + item["h"], 1.0)
        # 默认布局来自 consts，但读取时已补齐 props 默认值
        self.assertEqual(layout[0]["props"], {"format": "24h", "showSeconds": False})
        self.assertEqual(layout[1]["props"], {"showMinutes": True, "showCount": True})
        self.assertEqual(
            layout[2]["props"],
            {"category": "d", "showSource": True},
        )

    def test_default_layout_returns_fresh_copies(self) -> None:
        first = widgets.default_layout()
        first[0]["x"] = 0.9
        self.assertNotEqual(widgets.default_layout()[0]["x"], 0.9)
        self.assertEqual(
            [item["type"] for item in OVERLAY_WIDGET_DEFAULT_LAYOUT],
            ["clock", "today", "quote"],
        )

    def test_normalize_clamps_out_of_range(self) -> None:
        layout = widgets.normalize_layout(
            [
                {"id": "a", "type": "clock", "x": 2.0, "y": -1.0, "w": 5.0, "h": 0.001},
                {"id": "b", "type": "weather", "x": -0.5, "y": 0.99, "w": 0.2, "h": 0.5},
            ]
        )
        clock, weather = layout
        self.assertEqual(clock["x"], 0.0)
        self.assertEqual(clock["y"], 0.0)
        self.assertEqual(clock["w"], 1.0)
        self.assertEqual(clock["h"], widgets.MIN_WIDGET_SIZE)
        # x+w<=1 / y+h<=1 自动收敛（贴边而不是丢弃）
        self.assertLessEqual(weather["x"] + weather["w"], 1.0)
        self.assertLessEqual(weather["y"] + weather["h"], 1.0)
        self.assertAlmostEqual(weather["y"], 0.5)

    def test_normalize_drops_invalid_entries(self) -> None:
        layout = widgets.normalize_layout(
            [
                "not-a-dict",
                None,
                {"type": "unknown-kind"},
                {"type": "clock", "x": 0.1},  # 合法性由 id 补齐
                {"id": "ok", "type": "streak"},
                {"id": "ok2", "type": "quote", "visible": "false", "props": {"category": "z"}},
            ]
        )
        self.assertEqual([item["type"] for item in layout], ["clock", "streak", "quote"])
        self.assertEqual(layout[0]["id"], "clock-1")  # 缺 id → 自动补
        self.assertFalse(layout[2]["visible"])
        self.assertEqual(layout[2]["props"]["category"], "d")  # 非法 select → 默认值

    def test_normalize_dedupes_ids_keeping_first(self) -> None:
        layout = widgets.normalize_layout(
            [
                {"id": "dup", "type": "clock", "x": 0.0},
                {"id": "dup", "type": "today", "x": 0.5},
                {"id": "news", "type": "weather"},
            ]
        )
        self.assertEqual([item["type"] for item in layout], ["clock", "weather"])
        self.assertEqual([item["id"] for item in layout], ["dup", "news"])

    def test_normalize_limits_to_twelve(self) -> None:
        raw = [{"id": f"w{index}", "type": "clock"} for index in range(20)]
        layout = widgets.normalize_layout(raw)
        self.assertEqual(len(layout), widgets.MAX_WIDGETS)
        self.assertEqual(layout[0]["id"], "w0")
        self.assertEqual(layout[-1]["id"], "w11")

    def test_normalize_rejects_non_list(self) -> None:
        self.assertEqual(widgets.normalize_layout(None), [])
        self.assertEqual(widgets.normalize_layout("oops"), [])
        self.assertEqual(widgets.normalize_layout({"type": "clock"}), [])

    def test_props_only_keeps_schema_keys(self) -> None:
        layout = widgets.normalize_layout(
            [
                {
                    "id": "c",
                    "type": "clock",
                    "props": {"showSeconds": "yes", "format": "12h", "bogus": 1},
                }
            ]
        )
        self.assertEqual(layout[0]["props"], {"format": "12h", "showSeconds": True})

    def test_add_widget(self) -> None:
        layout = widgets.add_widget([], "weather")
        self.assertEqual(len(layout), 1)
        self.assertEqual(layout[0]["type"], "weather")
        self.assertEqual(layout[0]["id"], "weather-1")
        self.assertTrue(layout[0]["props"]["cityId"])
        again = widgets.add_widget(layout, "weather")
        self.assertEqual([item["id"] for item in again], ["weather-1", "weather-2"])

    def test_add_widget_rejects_unknown_and_full(self) -> None:
        layout = widgets.default_layout()
        self.assertEqual(widgets.add_widget(layout, "nope"), layout)
        full = widgets.normalize_layout(
            [{"id": f"c{index}", "type": "clock"} for index in range(widgets.MAX_WIDGETS)]
        )
        self.assertEqual(len(widgets.add_widget(full, "today")), widgets.MAX_WIDGETS)

    def test_remove_widget(self) -> None:
        layout = widgets.default_layout()
        removed = widgets.remove_widget(layout, "today-1")
        self.assertEqual([item["id"] for item in removed], ["clock-1", "quote-1"])
        self.assertEqual(widgets.remove_widget(layout, "missing"), layout)

    def test_update_widget(self) -> None:
        layout = widgets.default_layout()
        updated = widgets.update_widget(
            layout, "clock-1", {"x": 0.5, "w": 0.3, "visible": False, "props": {"format": "12h"}}
        )
        clock = updated[0]
        self.assertAlmostEqual(clock["x"], 0.5)
        self.assertAlmostEqual(clock["w"], 0.3)
        self.assertFalse(clock["visible"])
        self.assertEqual(clock["props"]["format"], "12h")
        self.assertFalse(clock["props"]["showSeconds"])  # 未 patch 的 props 保留
        self.assertEqual(clock["type"], "clock")  # type 不可改
        self.assertEqual(widgets.update_widget(layout, "missing", {"x": 0.1}), layout)
        self.assertEqual(widgets.update_widget(layout, "clock-1", "oops"), layout)

    def test_update_widget_type_is_immutable(self) -> None:
        layout = widgets.default_layout()
        updated = widgets.update_widget(layout, "clock-1", {"type": "weather"})
        self.assertEqual(updated[0]["type"], "clock")

    def test_reset_layout(self) -> None:
        layout = widgets.add_widget(widgets.add_widget(widgets.default_layout(), "streak"), "weather")
        reset = widgets.reset_layout()
        self.assertEqual([item["id"] for item in reset], ["clock-1", "today-1", "quote-1"])
        self.assertNotEqual(layout, reset)

    def test_functions_do_not_mutate_input(self) -> None:
        raw = [{"id": "a", "type": "clock", "x": 0.3, "props": {"format": "12h"}}]
        snapshot = json.loads(json.dumps(raw))
        widgets.normalize_layout(raw)
        widgets.add_widget(raw, "today")
        widgets.remove_widget(raw, "a")
        widgets.update_widget(raw, "a", {"x": 0.7})
        self.assertEqual(raw, snapshot)


# ================= 天气（mock http） =================
class WeatherTest(unittest.TestCase):
    def setUp(self) -> None:
        widgets.clear_weather_cache()

    def tearDown(self) -> None:
        widgets.clear_weather_cache()

    def test_fetch_weather_success(self) -> None:
        with mock.patch.object(
            widgets.urllib.request, "urlopen", return_value=_json_response(NMC_PAYLOAD)
        ) as opener:
            result = widgets.fetch_weather("58362")
        self.assertTrue(result["ok"])
        self.assertEqual(result["temp"], "12°")
        self.assertEqual(result["tempValue"], 12.0)
        self.assertEqual(result["weather"], "晴")
        self.assertEqual(result["city"], "北京市")
        self.assertEqual(result["updated"], "11-14 08:00")
        self.assertEqual(result["error"], "")
        self.assertEqual(opener.call_count, 1)

    def test_fetch_weather_cached_fifteen_minutes(self) -> None:
        with mock.patch.object(
            widgets.urllib.request, "urlopen", return_value=_json_response(NMC_PAYLOAD)
        ) as opener:
            widgets.fetch_weather("58362", now=1000.0)
            second = widgets.fetch_weather("58362", now=1000.0 + 600)
            widgets.fetch_weather("58362", now=1000.0 + widgets.WEATHER_CACHE_SECONDS + 1)
        self.assertTrue(second["ok"])
        self.assertEqual(opener.call_count, 2)

    def test_fetch_weather_failure_returns_readable_error(self) -> None:
        with mock.patch.object(
            widgets.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("boom"),
        ):
            result = widgets.fetch_weather("58362")
        self.assertFalse(result["ok"])
        self.assertIn("网络连接失败", result["error"])
        self.assertEqual(result["temp"], "")
        self.assertEqual(result["updated"], "")
        # 失败不写缓存：再拉一次仍会走网络
        with mock.patch.object(
            widgets.urllib.request, "urlopen", return_value=_json_response(NMC_PAYLOAD)
        ) as opener:
            ok_again = widgets.fetch_weather("58362")
        self.assertTrue(ok_again["ok"])
        self.assertEqual(opener.call_count, 1)

    def test_fetch_weather_timeout(self) -> None:
        with mock.patch.object(
            widgets.urllib.request, "urlopen", side_effect=TimeoutError("timed out")
        ):
            result = widgets.fetch_weather("58362")
        self.assertFalse(result["ok"])
        self.assertIn("超时", result["error"])

    def test_fetch_weather_http_error(self) -> None:
        error = urllib.error.HTTPError("http://www.nmc.cn", 503, "unavailable", {}, None)
        with mock.patch.object(widgets.urllib.request, "urlopen", side_effect=error):
            result = widgets.fetch_weather("58362")
        self.assertFalse(result["ok"])
        self.assertIn("503", result["error"])

    def test_fetch_weather_bad_json(self) -> None:
        with mock.patch.object(
            widgets.urllib.request, "urlopen", return_value=_FakeResponse(b"<html>502</html>")
        ):
            result = widgets.fetch_weather("58362")
        self.assertFalse(result["ok"])
        self.assertIn("解析失败", result["error"])

    def test_fetch_weather_empty_data(self) -> None:
        with mock.patch.object(
            widgets.urllib.request, "urlopen", return_value=_json_response({"code": 1})
        ):
            result = widgets.fetch_weather("58362")
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"])


# ================= 每日一言（mock http） =================
class QuoteTest(unittest.TestCase):
    def setUp(self) -> None:
        widgets.clear_quote_cache()

    def tearDown(self) -> None:
        widgets.clear_quote_cache()

    def test_fetch_quote_online(self) -> None:
        with mock.patch.object(
            widgets.urllib.request, "urlopen", return_value=_json_response(HITOKOTO_PAYLOAD)
        ) as opener:
            result = widgets.fetch_quote(day=date(2026, 11, 14))
        self.assertEqual(result["text"], HITOKOTO_PAYLOAD["hitokoto"])
        self.assertEqual(result["source"], "hitokoto")
        self.assertEqual(result["from"], "深清测试")
        self.assertEqual(result["error"], "")
        request = opener.call_args[0][0]
        self.assertIn("hitokoto.cn", request.full_url)

    def test_fetch_quote_falls_back_to_builtin(self) -> None:
        with mock.patch.object(
            widgets.urllib.request, "urlopen", side_effect=urllib.error.URLError("blocked")
        ):
            result = widgets.fetch_quote(day=date(2026, 11, 14))
        self.assertEqual(result["source"], "builtin")
        self.assertIn(result["text"], QUOTES)
        self.assertIn("网络连接失败", result["error"])

    def test_fetch_quote_fallback_uses_injected_rng(self) -> None:
        class _Rng:
            def choice(self, seq):  # noqa: ANN001, ANN202
                return seq[3]

        with mock.patch.object(
            widgets.urllib.request, "urlopen", side_effect=ValueError("空内容")
        ):
            result = widgets.fetch_quote(day=date(2026, 11, 14), rng=_Rng())
        self.assertEqual(result["text"], QUOTES[3])
        self.assertEqual(result["source"], "builtin")

    def test_fetch_quote_cached_per_day(self) -> None:
        day = date(2026, 11, 14)
        with mock.patch.object(
            widgets.urllib.request, "urlopen", return_value=_json_response(HITOKOTO_PAYLOAD)
        ) as opener:
            first = widgets.fetch_quote(day=day)
            second = widgets.fetch_quote(day=day)
            third = widgets.fetch_quote(day=day + timedelta(days=1))
        self.assertEqual(first, second)
        self.assertEqual(third["source"], "hitokoto")
        self.assertEqual(opener.call_count, 2)  # 同一天只拉一次

    def test_fetch_quote_category(self) -> None:
        with mock.patch.object(
            widgets.urllib.request, "urlopen", return_value=_json_response(HITOKOTO_PAYLOAD)
        ) as opener:
            widgets.fetch_quote(category="i", day=date(2026, 11, 14))
        request = opener.call_args[0][0]
        self.assertIn("c=i", request.full_url)


# ================= Bridge =================
class BridgeWidgetsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SHENQING_DATA_DIR"] = self._tmp.name
        self.bridge = AppBridge()
        self.changed: list[int] = []
        self.bridge.overlayWidgetsChanged.connect(lambda: self.changed.append(1))

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

    def _settings_json(self) -> dict:
        path = Path(self._tmp.name) / "settings.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_defaults(self) -> None:
        bridge = self.bridge
        self.assertEqual(
            [item["type"] for item in bridge.overlayWidgets], ["clock", "today", "quote"]
        )
        self.assertTrue(bridge.overlayWidgetsEnabled)
        catalog = bridge.widgetCatalog
        self.assertEqual(
            [item["type"] for item in catalog],
            ["clock", "countdown", "today", "streak", "quote", "weather"],
        )
        for item in catalog:
            self.assertTrue({"type", "name", "desc", "defaultSize", "propsSchema"} <= set(item))
            self.assertIn("w", item["defaultSize"])
            self.assertIn("h", item["defaultSize"])
        self.assertEqual(bridge.weatherCityId, widgets.DEFAULT_WEATHER_CITY)

    def test_catalog_is_not_shared(self) -> None:
        self.bridge.widgetCatalog[0]["name"] = "hacked"
        self.assertEqual(self.bridge.widgetCatalog[0]["name"], "时钟")

    def test_add_widget_persists(self) -> None:
        bridge = self.bridge
        new_id = bridge.addOverlayWidget("weather")
        self.assertEqual(new_id, "weather-1")
        self.assertEqual(len(bridge.overlayWidgets), 4)
        self.assertTrue(self.changed)
        self.assertEqual(len(self._settings_json()["overlay_widgets"]), 4)
        # 未知 type 不加、返回空串
        self.assertEqual(bridge.addOverlayWidget("not-a-type"), "")
        self.assertEqual(len(bridge.overlayWidgets), 4)

    def test_add_widget_up_to_limit(self) -> None:
        bridge = self.bridge
        for _ in range(9):
            bridge.addOverlayWidget("streak")
        self.assertEqual(len(bridge.overlayWidgets), widgets.MAX_WIDGETS)
        self.assertEqual(bridge.addOverlayWidget("streak"), "")
        self.assertEqual(len(bridge.overlayWidgets), widgets.MAX_WIDGETS)

    def test_update_widget_accepts_json_patch(self) -> None:
        bridge = self.bridge
        ok = bridge.updateOverlayWidget("clock-1", '{"x": 0.02, "w": 0.5, "visible": false}')
        self.assertTrue(ok)
        clock = bridge.overlayWidgets[0]
        self.assertAlmostEqual(clock["x"], 0.02)
        self.assertAlmostEqual(clock["w"], 0.5)
        self.assertFalse(clock["visible"])
        # 持久化到 settings.json
        saved = self._settings_json()["overlay_widgets"]
        self.assertAlmostEqual(saved[0]["w"], 0.5)
        # 非法 patch / 未知 id
        self.assertFalse(bridge.updateOverlayWidget("clock-1", "not json"))
        self.assertFalse(bridge.updateOverlayWidget("missing", {"x": 0.1}))

    def test_update_widget_accepts_object_patch(self) -> None:
        self.assertTrue(self.bridge.updateOverlayWidget("today-1", {"h": 0.3}))
        self.assertAlmostEqual(self.bridge.overlayWidgets[1]["h"], 0.3)

    def test_update_widget_json_slot_for_qml(self) -> None:
        """QML 只能调 str 参数槽（object 参数会被 PySide 拒），因此单开 JSON 版本。"""
        bridge = self.bridge
        self.assertTrue(
            bridge.updateOverlayWidgetJson("clock-1", '{"x": 0.3, "w": 0.5, "visible": false}')
        )
        clock = bridge.overlayWidgets[0]
        self.assertAlmostEqual(clock["x"], 0.3)
        self.assertAlmostEqual(clock["w"], 0.5)
        self.assertFalse(clock["visible"])
        self.assertFalse(bridge.updateOverlayWidgetJson("clock-1", "not json"))
        self.assertFalse(bridge.updateOverlayWidgetJson("clock-1", ""))
        self.assertFalse(bridge.updateOverlayWidgetJson("missing", '{"x": 0.1}'))

    def test_remove_widget(self) -> None:
        bridge = self.bridge
        self.assertTrue(bridge.removeOverlayWidget("today-1"))
        self.assertNotIn("today-1", [item["id"] for item in bridge.overlayWidgets])
        self.assertFalse(bridge.removeOverlayWidget("today-1"))
        self.assertEqual(len(self._settings_json()["overlay_widgets"]), 2)

    def test_reset_widgets(self) -> None:
        bridge = self.bridge
        bridge.addOverlayWidget("weather")
        bridge.resetOverlayWidgets()
        self.assertEqual(
            [item["id"] for item in bridge.overlayWidgets], ["clock-1", "today-1", "quote-1"]
        )

    def test_toggle_enabled_persists(self) -> None:
        bridge = self.bridge
        bridge.setOverlayWidgetsEnabled(False)
        self.assertFalse(bridge.overlayWidgetsEnabled)
        self.assertFalse(self._settings_json()["overlay_widgets_enabled"])
        self.assertTrue(self.changed)

    def test_layout_normalizes_broken_settings(self) -> None:
        self.bridge._settings.set(
            "overlay_widgets",
            [
                {"id": "clock-1", "type": "clock", "x": 3.0, "y": -2.0, "w": 8.0, "h": 0.01},
                {"type": "bogus"},
                {"id": "clock-1", "type": "today"},
            ],
        )
        layout = self.bridge.overlayWidgets
        self.assertEqual(len(layout), 1)
        self.assertEqual(layout[0]["type"], "clock")
        self.assertEqual(layout[0]["x"], 0.0)
        self.assertEqual(layout[0]["w"], 1.0)
        self.assertEqual(layout[0]["h"], widgets.MIN_WIDGET_SIZE)

    def test_widget_data_ready_updates_properties(self) -> None:
        bridge = self.bridge
        payload = {
            "weather": {
                "ok": True,
                "temp": "12°",
                "tempValue": 12.0,
                "weather": "晴",
                "city": "北京市",
                "updated": "11-14 08:00",
                "error": "",
            },
            "quote": {
                "text": "先把眼前这一件事做完。",
                "source": "hitokoto",
                "from": "深清测试",
                "error": "",
            },
        }
        synced: list[int] = []
        bridge.widgetDataChanged.connect(lambda: synced.append(1))
        bridge._on_widget_data_ready(payload)
        self.assertEqual(bridge.weatherWidgetData["temp"], "12°")
        self.assertEqual(bridge.weatherWidgetData["weather"], "晴")
        self.assertEqual(bridge.weatherWidgetError, "")
        self.assertEqual(bridge.quoteWidgetText, "先把眼前这一件事做完。")
        self.assertEqual(bridge.quoteWidgetSource, "hitokoto")
        self.assertEqual(bridge.quoteWidgetFrom, "深清测试")
        self.assertTrue(synced)

    def test_widget_data_failure_sets_readable_error(self) -> None:
        bridge = self.bridge
        bridge._on_widget_data_ready(
            {
                "weather": {"ok": False, "error": "天气网络连接失败：boom"},
                "quote": {
                    "text": QUOTES[0],
                    "source": "builtin",
                    "from": "深清",
                    "error": "一言服务超时",
                },
            }
        )
        self.assertIn("网络连接失败", bridge.weatherWidgetError)
        self.assertEqual(bridge.quoteWidgetSource, "builtin")
        self.assertIn("超时", bridge.quoteWidgetError)

    def test_weather_widget_defaults(self) -> None:
        data = self.bridge.weatherWidgetData
        self.assertEqual(
            {"temp", "tempValue", "weather", "city", "updated"}, set(data)
        )
        self.assertEqual(data["temp"], "")
        self.assertEqual(self.bridge.weatherWidgetError, "")
        self.assertEqual(self.bridge.quoteWidgetText, "")

    def test_set_weather_city(self) -> None:
        bridge = self.bridge
        bridge.setWeatherCityId("  59287 ")
        self.assertEqual(bridge.weatherCityId, "59287")
        self.assertEqual(self._settings_json()["weather_city_id"], "59287")
        bridge.setWeatherCityId("")
        self.assertEqual(bridge.weatherCityId, widgets.DEFAULT_WEATHER_CITY)

    def test_refresh_widget_data_runs_in_thread_pool(self) -> None:
        bridge = self.bridge
        started: list[object] = []

        class _Pool:
            def start(self, task: object) -> None:
                started.append(task)

        with mock.patch.dict(os.environ, {"SHENQING_NO_SCAN": "0"}), mock.patch.object(
            app_bridge, "QThreadPool"
        ) as pool_class:
            pool_class.globalInstance.return_value = _Pool()
            bridge.refreshWidgetData()
        self.assertEqual(len(started), 1)
        self.assertIsInstance(started[0], _WidgetDataTask)

    def test_widget_data_task_fetches_and_emits(self) -> None:
        bridge = self.bridge
        task = _WidgetDataTask(bridge, "58362", "i")
        weather = {
            "ok": True,
            "temp": "-3°",
            "tempValue": -3.0,
            "weather": "雪",
            "city": "沈阳市",
            "updated": "11-14 09:00",
            "error": "",
        }
        quote = {"text": "雪落无声。", "source": "hitokoto", "from": "测试", "error": ""}
        with mock.patch.object(
            widgets, "fetch_weather", return_value=weather
        ) as fetch_weather, mock.patch.object(
            widgets, "fetch_quote", return_value=quote
        ) as fetch_quote:
            task.run()  # 同线程 emit → 直接落到 _on_widget_data_ready
        self.assertEqual(fetch_weather.call_args[0][0], "58362")
        self.assertEqual(fetch_quote.call_args.kwargs.get("category"), "i")
        self.assertEqual(bridge.weatherWidgetData["temp"], "-3°")
        self.assertEqual(bridge.quoteWidgetText, "雪落无声。")

    def test_widget_city_and_quote_category_from_props(self) -> None:
        bridge = self.bridge
        bridge.addOverlayWidget("weather")
        bridge.addOverlayWidget("quote")
        layout = bridge.overlayWidgets
        weather_id = next(item["id"] for item in layout if item["type"] == "weather")
        quote_id = next(item["id"] for item in layout if item["type"] == "quote")
        bridge.updateOverlayWidget(weather_id, {"props": {"cityId": "59287"}})
        bridge.updateOverlayWidget(quote_id, {"props": {"category": "k"}})
        self.assertEqual(bridge._widget_city_id(), "59287")
        self.assertEqual(bridge._widget_quote_category(), "k")


if __name__ == "__main__":
    unittest.main()
