"""歌词解析与时间轴测试。"""
from __future__ import annotations

import unittest
from unittest import mock

from shenqing.services import lyrics


class ParseLrcTest(unittest.TestCase):
    def test_basic(self) -> None:
        text = "[00:01.50]第一句\n[00:05.00][00:09.00]重复句\n[00:12.25]第三句"
        lines = lyrics.parse_lrc(text)
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0], {"t": 1.5, "text": "第一句"})
        self.assertEqual([item["t"] for item in lines], [1.5, 5.0, 9.0, 12.25])

    def test_ignores_metadata_and_empty(self) -> None:
        text = "[00:00.00]作词：某人\n[00:01.00]\n[ar:歌手]\n[00:02.00]正文"
        lines = lyrics.parse_lrc(text)
        self.assertEqual([item["text"] for item in lines], ["正文"])

    def test_pick_line(self) -> None:
        lines = [{"t": 1.0, "text": "a"}, {"t": 5.0, "text": "b"}, {"t": 9.0, "text": "c"}]
        self.assertEqual(lyrics.pick_line(lines, 0.2), ("", "a"))
        self.assertEqual(lyrics.pick_line(lines, 1.1), ("a", "b"))
        self.assertEqual(lyrics.pick_line(lines, 6.0), ("b", "c"))
        self.assertEqual(lyrics.pick_line(lines, 99), ("c", ""))
        self.assertEqual(lyrics.pick_line([], 10), ("", ""))

    def test_fetch_without_title(self) -> None:
        self.assertEqual(lyrics.fetch_lyrics("", "x")["lines"], [])

    def test_fetch_search_failure(self) -> None:
        with mock.patch.object(lyrics, "_post_json", return_value={}):
            result = lyrics.fetch_lyrics("不存在的歌名 xyz", "未知")
        self.assertEqual(result["lines"], [])
        self.assertNotEqual(result["error"], "")

    def test_fetch_success_and_cache(self) -> None:
        calls = {"n": 0}

        def fake_post(url, params):  # noqa: ANN001
            calls["n"] += 1
            if "search" in url:
                return {"result": {"songs": [{"id": 42}]}}
            return {"lrc": {"lyric": "[00:01.00]hello\n[00:03.00]world"}}

        with mock.patch.object(lyrics, "_post_json", side_effect=fake_post):
            first = lyrics.fetch_lyrics("测试歌曲缓存", "测试歌手")
            second = lyrics.fetch_lyrics("测试歌曲缓存", "测试歌手")
        self.assertEqual(first["error"], "")
        self.assertEqual([item["text"] for item in first["lines"]], ["hello", "world"])
        self.assertEqual(first["lines"], second["lines"])
        self.assertEqual(calls["n"], 2)  # 第二次命中缓存，只付一次搜索 + 一次歌词


if __name__ == "__main__":
    unittest.main()
