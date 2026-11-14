"""更新源兜底测试：Gitee update.json / GitLink 暂不可用。"""

from __future__ import annotations

import unittest
from unittest import mock

from shenqing.services import updater


MANIFEST = {
    "version": "0.20.0",
    "notes": "",
    "assets": [
        {
            "name": "ShenQing-Setup-0.20.0.exe",
            "url": "https://github.com/Kryon2025/Clarity/releases/download/v0.20.0/ShenQing-Setup-0.20.0.exe",
        }
    ],
}


class ManifestParseTest(unittest.TestCase):
    def test_manifest_parsed(self) -> None:
        release = updater.release_from_manifest(MANIFEST)
        assert release is not None
        self.assertEqual(release["tag_name"], "v0.20.0")
        self.assertEqual(len(release["assets"]), 1)
        self.assertIn("Setup", release["assets"][0]["name"])

    def test_manifest_with_tag_name(self) -> None:
        data = {"tag_name": "v1.2.3", "body": "notes", "assets": [{"name": "a.exe", "browser_download_url": "https://x/a.exe"}]}
        release = updater.release_from_manifest(data)
        assert release is not None
        self.assertEqual(release["tag_name"], "v1.2.3")
        self.assertEqual(release["body"], "notes")

    def test_invalid_manifest(self) -> None:
        self.assertIsNone(updater.release_from_manifest({}))
        self.assertIsNone(updater.release_from_manifest({"version": "1.0.0"}))
        self.assertIsNone(updater.release_from_manifest("bad"))


class GiteeFallbackTest(unittest.TestCase):
    def test_gitee_falls_back_to_manifest(self) -> None:
        def fake_read_json(url: str, token: str = ""):
            if "releases/latest" in url:
                raise OSError("HTTP 404")
            if url.endswith("/releases"):
                return []
            if "packaging/update.json" in url:
                return MANIFEST
            raise OSError("unexpected " + url)

        with mock.patch.object(updater, "_read_json", side_effect=fake_read_json):
            release, error = updater.fetch_release_detail("gitee")
        self.assertTrue(release)
        self.assertEqual(error, "")
        self.assertEqual(release["tag_name"], "v0.20.0")

    def test_gitee_all_fail(self) -> None:
        with mock.patch.object(updater, "_read_json", side_effect=OSError("offline")):
            release, error = updater.fetch_release_detail("gitee")
        self.assertIsNone(release)
        self.assertIn("Gitee 源检查失败", error)


class GitLinkUnavailableTest(unittest.TestCase):
    def test_gitlink_reports_unavailable(self) -> None:
        release, error = updater.fetch_release_detail("gitlink")
        self.assertIsNone(release)
        self.assertIn("GitLink", error)
        self.assertIn("暂未提供公开", error)

    def test_source_metadata(self) -> None:
        sources = {item["id"]: item for item in updater.BUILTIN_SOURCES}
        self.assertFalse(sources["gitlink"]["available"])
        self.assertTrue(sources["gitee"]["available"])


if __name__ == "__main__":
    unittest.main()
