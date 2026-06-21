import json
import unittest
from unittest.mock import patch

from ComPort_Zone.version_check import (
    GITHUB_LATEST_RELEASE_API_URL,
    GITHUB_RELEASES_URL,
    build_version_check_result,
    compare_versions,
    fetch_latest_release,
    is_newer_version,
    release_info_from_payload,
)


class VersionCheckTests(unittest.TestCase):
    def test_compares_dotted_versions_with_optional_v_prefix(self) -> None:
        self.assertEqual(compare_versions("v0.2.10", "0.2.9"), 1)
        self.assertEqual(compare_versions("0.2", "0.2.0"), 0)
        self.assertEqual(compare_versions("0.1.9", "0.2.0"), -1)
        self.assertTrue(is_newer_version("ComPort Zone v1.3.0", "1.2.9"))

    def test_builds_update_result_from_github_release_payload(self) -> None:
        release = release_info_from_payload(
            {
                "tag_name": "v0.2.6",
                "name": "ComPort Zone v0.2.6",
                "html_url": "https://github.com/shuky-shukrun/ComPort-Zone/releases/tag/v0.2.6",
            }
        )

        result = build_version_check_result("0.2.5", release)

        self.assertTrue(result.update_available)
        self.assertEqual(result.latest_version, "0.2.6")
        self.assertEqual(result.release_name, "ComPort Zone v0.2.6")
        self.assertIn("/releases/tag/v0.2.6", result.release_url)

    def test_release_payload_falls_back_to_releases_page_link(self) -> None:
        release = release_info_from_payload({"tag_name": "v0.2.5"})
        result = build_version_check_result("0.2.5", release)

        self.assertFalse(result.update_available)
        self.assertEqual(result.release_url, GITHUB_RELEASES_URL)

    def test_fetch_latest_release_uses_urllib_not_qt(self) -> None:
        # The fix routes the update check through Python's urllib/SSL stack
        # (off Qt's OpenSSL path). Verify it requests the right URL/headers
        # and parses the response into a ReleaseInfo.
        body = json.dumps(
            {"tag_name": "v9.9.9", "name": "Big Release", "html_url": "https://x/9"}
        ).encode("utf-8")
        captured: dict[str, object] = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return body

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["user_agent"] = request.headers.get("User-agent")
            captured["accept"] = request.headers.get("Accept")
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            info = fetch_latest_release(user_agent="ComPort-Zone/1.2.3")

        self.assertEqual(info.version, "9.9.9")
        self.assertEqual(info.html_url, "https://x/9")
        self.assertEqual(captured["url"], GITHUB_LATEST_RELEASE_API_URL)
        self.assertEqual(captured["user_agent"], "ComPort-Zone/1.2.3")
        self.assertEqual(captured["accept"], "application/vnd.github+json")
        self.assertIsNotNone(captured["timeout"])


if __name__ == "__main__":
    unittest.main()
