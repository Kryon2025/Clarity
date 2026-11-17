"""v0.22 灵动岛专辑封面测试：封面缓存纯逻辑 + 取不到封面时的静默降级。

覆盖：
- detect_image_ext 按文件头识别 png/jpg/bmp/webp，垃圾字节返回 ""；
- art_cache_path 稳定（同曲目同路径）与不同曲目/扩展名不同路径；
- save_art_bytes 落盘、同曲目复用同一文件、非法数据返回 ""；
- prune_art_cache 只保留最新 N 个（按 mtime），缺目录/未超限返回 0；
- MediaSmtcService._empty() 带 art 键；无缩略图/读取抛错时 art 静默为 ""；
- 同曲目命中缓存后不再重复读取，读不到封面时重试有限次后放弃。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SHENQING_NO_SCAN"] = "1"

from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

from shenqing.services import media_smtc  # noqa: E402
from shenqing.services.media_smtc import (  # noqa: E402
    MediaSmtcService,
    art_cache_path,
    detect_image_ext,
    prune_art_cache,
    save_art_bytes,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02\x03" * 8
JPG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x11\x22\x33" * 8
BMP = b"BM" + b"\x00" * 30
WEBP = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBP" + b"VP8 " + b"\x00" * 16
GARBAGE = b"definitely not an image, just text"


def _run(coro):
    return asyncio.run(coro)


class DetectImageExtTests(unittest.TestCase):
    def test_png(self) -> None:
        self.assertEqual(detect_image_ext(PNG), "png")

    def test_jpeg(self) -> None:
        self.assertEqual(detect_image_ext(JPG), "jpg")

    def test_bmp(self) -> None:
        self.assertEqual(detect_image_ext(BMP), "bmp")

    def test_webp(self) -> None:
        self.assertEqual(detect_image_ext(WEBP), "webp")

    def test_garbage_returns_empty(self) -> None:
        self.assertEqual(detect_image_ext(GARBAGE), "")
        self.assertEqual(detect_image_ext(b""), "")

    def test_riff_without_webp_is_not_webp(self) -> None:
        self.assertEqual(detect_image_ext(b"RIFF" + b"\x00" * 8 + b"WAVE"), "")

    def test_non_bytes_returns_empty(self) -> None:
        self.assertEqual(detect_image_ext(None), "")  # type: ignore[arg-type]
        self.assertEqual(detect_image_ext("not bytes"), "")  # type: ignore[arg-type]

    def test_bytearray_and_memoryview(self) -> None:
        self.assertEqual(detect_image_ext(bytearray(PNG)), "png")
        self.assertEqual(detect_image_ext(memoryview(JPG)), "jpg")


class ArtCachePathTests(unittest.TestCase):
    def test_stable_for_same_track(self) -> None:
        first = art_cache_path("晴天", "周杰伦", "叶惠美")
        second = art_cache_path("晴天", "周杰伦", "叶惠美")
        self.assertEqual(first, second)
        expected = hashlib.sha1("晴天|周杰伦|叶惠美".encode()).hexdigest()[:16] + ".png"
        self.assertEqual(first.name, expected)
        self.assertEqual(first.parent, media_smtc.ART_CACHE_DIR)

    def test_different_tracks_differ(self) -> None:
        base = art_cache_path("晴天", "周杰伦", "叶惠美")
        self.assertNotEqual(base, art_cache_path("七里香", "周杰伦", "叶惠美"))
        self.assertNotEqual(base, art_cache_path("晴天", "其他歌手", "叶惠美"))
        self.assertNotEqual(base, art_cache_path("晴天", "周杰伦", "其他专辑"))

    def test_extension_normalized(self) -> None:
        self.assertEqual(art_cache_path("t", "a", "b", "jpg").suffix, ".jpg")
        self.assertEqual(art_cache_path("t", "a", "b", ".JPG").suffix, ".jpg")
        self.assertEqual(art_cache_path("t", "a", "b", "").suffix, ".png")

    def test_blank_metadata_ok(self) -> None:
        path = art_cache_path("", "", "")
        self.assertEqual(len(path.stem), 16)
        self.assertEqual(path.suffix, ".png")


class SaveArtBytesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name) / "shenqing-media-art"
        patcher = mock.patch.object(media_smtc, "ART_CACHE_DIR", self.directory)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_save_writes_file(self) -> None:
        path = save_art_bytes(PNG, "晴天", "周杰伦", "叶惠美")
        self.assertTrue(path)
        target = Path(path)
        self.assertTrue(target.is_absolute())
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), PNG)
        self.assertEqual(target.parent, self.directory)
        self.assertEqual(target.suffix, ".png")
        self.assertEqual(target.name, art_cache_path("晴天", "周杰伦", "叶惠美").name)

    def test_extension_follows_content(self) -> None:
        self.assertEqual(Path(save_art_bytes(JPG, "t", "a", "b")).suffix, ".jpg")
        self.assertEqual(Path(save_art_bytes(BMP, "t2", "a", "b")).suffix, ".bmp")
        self.assertEqual(Path(save_art_bytes(WEBP, "t3", "a", "b")).suffix, ".webp")

    def test_same_track_reuses_single_file(self) -> None:
        first = save_art_bytes(PNG, "晴天", "周杰伦", "叶惠美")
        second = save_art_bytes(PNG, "晴天", "周杰伦", "叶惠美")
        self.assertEqual(first, second)
        self.assertEqual(len(list(self.directory.iterdir())), 1)

    def test_invalid_bytes_return_empty(self) -> None:
        self.assertEqual(save_art_bytes(GARBAGE, "t", "a", "b"), "")
        self.assertEqual(save_art_bytes(b"", "t", "a", "b"), "")
        self.assertFalse(self.directory.exists())

    def test_non_bytes_return_empty(self) -> None:
        self.assertEqual(save_art_bytes(None, "t", "a", "b"), "")
        self.assertEqual(save_art_bytes(12345, "t", "a", "b"), "")

    def test_no_temp_file_left_behind(self) -> None:
        save_art_bytes(PNG, "t", "a", "b")
        names = [item.name for item in self.directory.iterdir()]
        self.assertEqual(len(names), 1)
        self.assertFalse(any(name.endswith(".tmp") for name in names))


class PruneArtCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        self.base = 1_600_000_000

    def _make_files(self, count: int) -> None:
        for index in range(count):
            item = self.directory / f"f{index:02d}.png"
            item.write_bytes(b"x")
            stamp = self.base + index
            os.utime(item, (stamp, stamp))

    def test_keeps_newest_n(self) -> None:
        self._make_files(45)
        removed = prune_art_cache(self.directory, 40)
        self.assertEqual(removed, 5)
        names = sorted(item.name for item in self.directory.iterdir())
        self.assertEqual(len(names), 40)
        for old in ("f00.png", "f01.png", "f02.png", "f03.png", "f04.png"):
            self.assertNotIn(old, names)
        self.assertIn("f05.png", names)
        self.assertIn("f44.png", names)

    def test_under_limit_keeps_all(self) -> None:
        self._make_files(3)
        self.assertEqual(prune_art_cache(self.directory, 5), 0)
        self.assertEqual(len(list(self.directory.iterdir())), 3)

    def test_missing_directory_returns_zero(self) -> None:
        self.assertEqual(prune_art_cache(self.directory / "nope", 40), 0)

    def test_keep_zero_removes_all(self) -> None:
        self._make_files(2)
        self.assertEqual(prune_art_cache(self.directory, 0), 2)
        self.assertEqual(list(self.directory.iterdir()), [])


class EmptyPayloadTests(unittest.TestCase):
    def test_empty_has_art_key(self) -> None:
        payload = MediaSmtcService._empty()
        self.assertIn("art", payload)
        self.assertEqual(payload["art"], "")
        self.assertFalse(payload["has"])
        self.assertFalse(payload["playing"])
        for key in ("title", "artist", "album", "app", "appId", "position", "duration"):
            self.assertIn(key, payload)

    def test_empty_is_stable(self) -> None:
        self.assertEqual(MediaSmtcService._empty(), MediaSmtcService._empty())


class MediaArtReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MediaSmtcService(interval=1.0)

    def test_no_thumbnail_returns_empty(self) -> None:
        props = mock.Mock(thumbnail=None)
        self.assertEqual(_run(self.service._read_art(props, "t", "a", "b")), "")

    def test_thumbnail_open_error_is_silent(self) -> None:
        thumbnail = mock.Mock()
        thumbnail.open_read_async = mock.AsyncMock(side_effect=RuntimeError("拒绝访问"))
        props = mock.Mock(thumbnail=thumbnail)
        self.assertEqual(_run(self.service._read_art(props, "t", "a", "b")), "")

    def test_thumbnail_property_error_is_silent(self) -> None:
        class Boom:
            @property
            def thumbnail(self):
                raise RuntimeError("没权限")

        self.assertEqual(_run(self.service._read_art(Boom(), "t", "a", "b")), "")

    def test_existing_cache_file_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "art.png"
            target.write_bytes(PNG)
            reader = mock.AsyncMock(return_value=str(target))
            with mock.patch.object(self.service, "_read_art", new=reader):
                props = mock.Mock(thumbnail=None)
                first = _run(self.service._art_for(props, "t", "a", "b"))
                second = _run(self.service._art_for(props, "t", "a", "b"))
            self.assertEqual(first, str(target))
            self.assertEqual(second, str(target))
            self.assertEqual(reader.await_count, 1)

    def test_switch_track_resets_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            one = Path(tmp) / "one.png"
            two = Path(tmp) / "two.png"
            one.write_bytes(PNG)
            two.write_bytes(PNG)
            reader = mock.AsyncMock(side_effect=[str(one), str(two)])
            with mock.patch.object(self.service, "_read_art", new=reader):
                props = mock.Mock(thumbnail=None)
                self.assertEqual(_run(self.service._art_for(props, "t1", "a", "b")), str(one))
                self.assertEqual(_run(self.service._art_for(props, "t2", "a", "b")), str(two))
            self.assertEqual(reader.await_count, 2)

    def test_gives_up_after_retries(self) -> None:
        reader = mock.AsyncMock(return_value="")
        props = mock.Mock(thumbnail=None)
        with mock.patch.object(self.service, "_read_art", new=reader):
            for _ in range(6):
                self.assertEqual(_run(self.service._art_for(props, "t", "a", "b")), "")
        self.assertEqual(reader.await_count, media_smtc._ART_RETRIES)


if __name__ == "__main__":
    unittest.main()
