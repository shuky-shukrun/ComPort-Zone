import io
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from ComPort_Zone.version_check import (
    GITHUB_RELEASES_ATOM_URL,
    GITHUB_RELEASES_URL,
    GITHUB_REPOSITORY_URL,
    DownloadCancelled,
    build_version_check_result,
    compare_versions,
    describe_check_error,
    download_installer,
    fetch_latest_release,
    installer_asset_name,
    installer_download_url,
    is_newer_version,
    release_info_from_atom,
    release_info_from_payload,
)


def _atom_feed(*entries: tuple[str, str, str]) -> bytes:
    """Build a minimal releases Atom feed from (tag, name, url) tuples."""
    body = ['<?xml version="1.0" encoding="UTF-8"?>', '<feed xmlns="http://www.w3.org/2005/Atom">']
    for tag, name, url in entries:
        body.append(
            f"<entry><id>tag:github.com,2008:Repository/1/{tag}</id>"
            f'<link rel="alternate" type="text/html" href="{url}"/>'
            f"<title>{name}</title></entry>"
        )
    body.append("</feed>")
    return "".join(body).encode("utf-8")


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

    def test_release_info_from_atom_uses_the_first_entry(self) -> None:
        feed = _atom_feed(
            ("v9.9.9", "Big Release", "https://github.com/o/r/releases/tag/v9.9.9"),
            ("v9.9.8", "Older Release", "https://github.com/o/r/releases/tag/v9.9.8"),
        )
        info = release_info_from_atom(feed)
        self.assertEqual(info.tag_name, "v9.9.9")
        self.assertEqual(info.name, "Big Release")
        self.assertEqual(info.version, "9.9.9")
        self.assertEqual(info.html_url, "https://github.com/o/r/releases/tag/v9.9.9")

    def test_release_info_from_atom_rejects_an_empty_feed(self) -> None:
        with self.assertRaises(ValueError):
            release_info_from_atom(b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>')

    def test_fetch_latest_release_uses_atom_feed_over_urllib(self) -> None:
        # The check goes through Python's urllib/SSL stack (off Qt's OpenSSL
        # path) AND through the releases Atom feed, which has no API rate limit.
        body = _atom_feed(("v9.9.9", "Big Release", "https://github.com/o/r/releases/tag/v9.9.9"))
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
        self.assertEqual(info.html_url, "https://github.com/o/r/releases/tag/v9.9.9")
        self.assertEqual(captured["url"], GITHUB_RELEASES_ATOM_URL)
        self.assertEqual(captured["user_agent"], "ComPort-Zone/1.2.3")
        self.assertEqual(captured["accept"], "application/atom+xml")
        self.assertIsNotNone(captured["timeout"])

    def test_installer_asset_name_and_download_url_follow_release_naming(self) -> None:
        self.assertEqual(
            installer_asset_name("v0.6.0"), "ComPort_Zone-0.6.0-win64-setup.exe"
        )
        self.assertEqual(
            installer_download_url("v0.6.0", "0.6.0"),
            f"{GITHUB_REPOSITORY_URL}/releases/download/v0.6.0/"
            "ComPort_Zone-0.6.0-win64-setup.exe",
        )
        # A missing tag falls back to a v-prefixed version.
        self.assertEqual(
            installer_download_url("", "0.6.0"),
            f"{GITHUB_REPOSITORY_URL}/releases/download/v0.6.0/"
            "ComPort_Zone-0.6.0-win64-setup.exe",
        )

    def test_download_installer_streams_to_destination_and_reports_progress(self) -> None:
        body = b"x" * 10
        progress_calls: list[tuple[int, int]] = []

        class FakeResponse:
            def __init__(self) -> None:
                self.headers = {"Content-Length": str(len(body))}
                self._remaining = body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, size):
                chunk, self._remaining = self._remaining[:size], self._remaining[size:]
                return chunk

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "installer.exe"
            with patch("urllib.request.urlopen", lambda request, timeout=None: FakeResponse()):
                result = download_installer(
                    "https://example.invalid/installer.exe",
                    destination,
                    user_agent="ComPort-Zone/1.2.3",
                    chunk_size=4,
                    progress_callback=lambda done, total: progress_calls.append((done, total)),
                )

            self.assertEqual(result, destination)
            self.assertEqual(destination.read_bytes(), body)
            self.assertFalse(destination.with_name(destination.name + ".part").exists())
            self.assertEqual(progress_calls, [(4, 10), (8, 10), (10, 10)])

    def test_download_installer_removes_partial_file_when_cancelled(self) -> None:
        class FakeResponse:
            def __init__(self) -> None:
                self.headers = {}
                self._chunks = iter([b"abcd", b"efgh"])

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, size):
                return next(self._chunks, b"")

        cancel_event = threading.Event()
        cancel_event.set()

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "installer.exe"
            with patch("urllib.request.urlopen", lambda request, timeout=None: FakeResponse()):
                with self.assertRaises(DownloadCancelled):
                    download_installer(
                        "https://example.invalid/installer.exe",
                        destination,
                        user_agent="ComPort-Zone/1.2.3",
                        cancel_event=cancel_event,
                    )

            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name(destination.name + ".part").exists())

    def test_describe_check_error_explains_rate_limit_and_others(self) -> None:
        rate_limited = urllib.error.HTTPError(
            "https://x", 403, "rate limit exceeded", {}, io.BytesIO(b"")
        )
        message = describe_check_error(rate_limited)
        self.assertIn("limited update checks", message)
        self.assertNotIn("403", message)

        offline = urllib.error.URLError("getaddrinfo failed")
        self.assertIn("Could not reach GitHub", describe_check_error(offline))

        self.assertEqual(describe_check_error(ValueError("boom")), "boom")


if __name__ == "__main__":
    unittest.main()
