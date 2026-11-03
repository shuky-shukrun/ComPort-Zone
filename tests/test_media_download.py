"""Verify range assembly and atomic integrity checks without network/models."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.media.download_range import download


class MediaDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name) / "checkpoint.bin"
        self.payload = b"a small checkpoint with several byte ranges"
        self.sha = hashlib.sha256(self.payload).hexdigest()

    def response(self, request, **_kwargs):
        first, last = map(int, request.get_header("Range").removeprefix("bytes=").split("-"))
        response = io.BytesIO(self.payload[first:last + 1])
        response.status = 206
        response.headers = {"Content-Range": f"bytes {first}-{last}/{len(self.payload)}"}
        return response

    def test_ranges_assemble_exactly_and_match_checksum(self):
        with patch("tools.media.download_range.urlopen", side_effect=self.response):
            result = download("https://example.test/model", self.target, len(self.payload), self.sha, workers=2, chunk_size=7)
        self.assertEqual(result, self.target)
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual(list(self.target.parent.glob("*.chunks-*")), [])

    def test_valid_existing_download_does_not_access_network(self):
        self.target.write_bytes(self.payload)
        with patch("tools.media.download_range.urlopen") as open_url:
            download("https://example.test/model", self.target, len(self.payload), self.sha)
        open_url.assert_not_called()

    def test_wrong_checksum_preserves_existing_file(self):
        self.target.write_bytes(b"previous file")
        with patch("tools.media.download_range.urlopen", side_effect=self.response):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                download("https://example.test/model", self.target, len(self.payload), "0" * 64, workers=1, chunk_size=7)
        self.assertEqual(self.target.read_bytes(), b"previous file")
        self.assertFalse(self.target.with_name("checkpoint.bin.verified-part").exists())

    def test_ignored_range_is_rejected_before_replacing_output(self):
        def ignored(request, **kwargs):
            response = self.response(request, **kwargs)
            response.status = 200
            return response
        with patch("tools.media.download_range.urlopen", side_effect=ignored), patch("tools.media.download_range.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "Range"):
                download("https://example.test/model", self.target, len(self.payload), self.sha, workers=1, chunk_size=len(self.payload))
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
