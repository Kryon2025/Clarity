"""更新渠道（正式版 / 预览版）测试。"""

from __future__ import annotations

import unittest
from unittest import mock

from shenqing.services import updater


def _release(tag: str, draft: bool = False) -> dict:
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": "-" in tag,
        "body": "notes",
        "assets": [{"name": "ShenQing-Setup.exe", "browser_download_url": "https://x/s.exe"}],
    }


class ChannelTest(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(updater.normalize_channel("preview"), "preview")
        self.assertEqual(updater.normalize_channel("PREVIEW"), "preview")
        self.assertEqual(updater.normalize_channel("stable"), "stable")
        self.assertEqual(updater.normalize_channel(""), "stable")
        self.assertEqual(updater.normalize_channel(None), "stable")

    def test_preview_picks_prerelease(self) -> None:
        releases = [_release("v0.21.0-beta.1"), _release("v0.20.1")]
        with mock.patch.object(updater, "_read_json", return_value=releases):
            info, error = updater.check_latest_detail("0.20.0", source_id="github", channel="preview")
        self.assertEqual(error, "")
        self.assertIsNotNone(info)
        self.assertEqual(info["version"], "0.21.0-beta.1")
        self.assertEqual(info["channel"], "preview")

    def test_preview_skips_draft(self) -> None:
        releases = [_release("v0.22.0-draft", draft=True), _release("v0.21.0-beta.1")]
        with mock.patch.object(updater, "_read_json", return_value=releases):
            info, _ = updater.check_latest_detail("0.20.0", source_id="github", channel="preview")
        self.assertIsNotNone(info)
        self.assertEqual(info["version"], "0.21.0-beta.1")

    def test_stable_uses_latest_endpoint(self) -> None:
        with mock.patch.object(updater, "_fetch_release", return_value=_release("v0.20.1")) as fetcher:
            info, error = updater.check_latest_detail("0.20.0", source_id="github", channel="stable")
        self.assertEqual(error, "")
        self.assertEqual(info["version"], "0.20.1")
        self.assertEqual(info["channel"], "stable")
        fetcher.assert_called_once()


if __name__ == "__main__":
    unittest.main()
