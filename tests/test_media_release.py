"""Release integrity and PR policy checks without GitHub, Qt, or speech models."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.media.check_docs import forbidden_asset, review_errors
from tools.media.common import (
    MANUAL_ASSET, REPOSITORY, VIDEO_ASSETS, asset_info, manual_fingerprint, sha256,
    manual_metadata, video_fingerprint,
)
from tools.media.release_media import (
    CHECKSUM_ASSET, RECEIPT_ASSET, checked_package, make_plan, package,
    updated_notes, validate_previous, verify,
)


class MediaReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / "work"
        paths = [
            "src/ComPort_Zone/VERSION", "src/ComPort_Zone/app.py",
            "docs/USER_MANUAL.md", "tools/media/capture.py", "tools/media/demo_device.py",
            "tools/media/build.py", "tools/media/common.py", "tools/media/storyboard.json",
            "tools/media/requirements.txt", "tools/media/requirements-pdf.txt", "tools/media/manual_pdf.py",
            "tools/media/download_models.py",
            "examples/tutorial/check.cpz",
        ]
        for relative in paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("source\n", encoding="utf-8")
        self.set_version("0.9.0")
        (self.root / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="0.9.0"\ndependencies=[]\n')
        self.work.mkdir()
        self.media = self.root / "docs/media"
        self.media.mkdir()
        for name in (MANUAL_ASSET, *VIDEO_ASSETS):
            (self.media / name).write_bytes(f"Verified test artifact: {name}".encode())
        self.build_receipts()

    def set_version(self, version):
        (self.root / "src/ComPort_Zone/VERSION").write_text(version + "\n")
        (self.root / "docs/USER_MANUAL.md").write_text(
            f"# Manual\n\n**English edition | ComPort Zone {version} | Reviewed 2026-11-03**\n", encoding="utf-8")

    def build_receipts(self):
        version = (self.root / "src/ComPort_Zone/VERSION").read_text().strip()
        manual = {**manual_metadata(self.root), "inputs_sha256": manual_fingerprint(self.root),
                  "asset": asset_info(self.media / MANUAL_ASSET, version)}
        video = {"version": version, "inputs_sha256": video_fingerprint(self.root),
                 "narrator": {"provider": "kokoro-onnx", "voice": "am_michael"},
                 "assets": [asset_info(self.media / n, version) for n in VIDEO_ASSETS]}
        for name, receipt in (("manual", manual), ("video", video)):
            (self.work / f"{name}-build.json").write_text(json.dumps(receipt), encoding="utf-8")

    def published(self):
        return package(self.root, self.work, make_plan(self.root, REPOSITORY))

    def test_first_release_packages_binaries_and_verifiable_checksums(self):
        receipt = self.published()
        self.assertTrue(receipt["video_rebuilt"])
        self.assertEqual(set(receipt["uploads"]), {MANUAL_ASSET, *VIDEO_ASSETS, RECEIPT_ASSET, CHECKSUM_ASSET})
        self.assertEqual(checked_package(self.work / "publish"), receipt)

    def test_version_only_release_reuses_original_video_and_rebuilds_manual(self):
        previous = self.published()
        self.set_version("0.9.1")
        plan = make_plan(self.root, REPOSITORY, previous)
        self.assertEqual(plan["video_action"], "reuse")
        self.build_receipts()
        receipt = package(self.root, self.work, plan)
        self.assertEqual(receipt["manual"]["version"], "0.9.1")
        self.assertEqual(receipt["video"]["version"], "0.9.0")
        self.assertNotIn(VIDEO_ASSETS[0], receipt["uploads"])
        self.assertIn("/v0.9.0/", receipt["video"]["assets"][0]["url"])
        self.assertFalse((self.work / "publish" / VIDEO_ASSETS[0]).exists())

    def test_application_change_requires_new_capture_and_video(self):
        previous = self.published()
        (self.root / "src/ComPort_Zone/app.py").write_text("changed behavior\n")
        self.assertEqual(make_plan(self.root, REPOSITORY, previous)["video_action"], "rebuild")

    def test_dependency_change_invalidates_recording_but_version_metadata_does_not(self):
        previous = self.published()
        path = self.root / "pyproject.toml"
        path.write_text(path.read_text().replace('version="0.9.0"', 'version="0.9.1"'))
        self.assertEqual(make_plan(self.root, REPOSITORY, previous)["video_action"], "reuse")
        path.write_text(path.read_text().replace('dependencies=[]', 'dependencies=["PySide6>=6.8"]'))
        self.assertEqual(make_plan(self.root, REPOSITORY, previous)["video_action"], "rebuild")

    def test_manual_only_change_does_not_require_new_video_but_rejects_old_pdf(self):
        previous = self.published()
        with (self.root / "docs/USER_MANUAL.md").open("a") as stream:
            stream.write("\nCorrected instructions.\n")
        plan = make_plan(self.root, REPOSITORY, previous)
        self.assertEqual(plan["video_action"], "reuse")
        with self.assertRaisesRegex(ValueError, "Stale manual"):
            package(self.root, self.work, plan)

    def test_stale_manual_version_blocks_release(self):
        (self.root / "src/ComPort_Zone/VERSION").write_text("0.9.1\n")
        with self.assertRaisesRegex(ValueError, "Review and update"):
            make_plan(self.root, REPOSITORY)

    def test_changed_source_after_plan_cannot_reuse_old_video(self):
        plan = make_plan(self.root, REPOSITORY, self.published())
        (self.root / "examples/tutorial/check.cpz").write_text("changed check\n")
        with self.assertRaisesRegex(ValueError, "Video inputs changed"):
            package(self.root, self.work, plan)

    def test_modified_download_fails_package_integrity(self):
        self.published()
        (self.work / "publish" / VIDEO_ASSETS[0]).write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            checked_package(self.work / "publish")

    def test_previous_manifest_cannot_redirect_to_another_repository(self):
        previous = self.published()
        previous["video"]["assets"][0]["url"] = "https://example.com/video.mp4"
        with self.assertRaisesRegex(ValueError, "URL"):
            validate_previous(previous, REPOSITORY)

    def test_media_notes_preserve_release_prose_and_are_idempotent(self):
        receipt = self.published()
        original = "# Release highlights\n\nUsers can run a new check.\n"
        once = updated_notes(original, receipt)
        self.assertTrue(once.startswith(original))
        self.assertEqual(updated_notes(once, receipt), once)
        self.assertIn("recorded for v0.9.0", once)

    def test_reused_video_is_verified_on_its_original_release(self):
        previous = self.published()
        self.set_version("0.9.1")
        self.build_receipts()
        receipt = package(self.root, self.work, make_plan(self.root, REPOSITORY, previous))
        staging = self.work / "publish"
        current = {"assets": [{"name": n, "size": (staging / n).stat().st_size,
                               "digest": "sha256:" + sha256(staging / n)} for n in receipt["uploads"]]}
        old = {"assets": [{"name": a["name"], "size": a["bytes"], "digest": "sha256:" + a["sha256"]}
                           for a in previous["video"]["assets"]]}
        with mock.patch("tools.media.release_media.remote_release", side_effect=lambda _, tag: current if tag == "v0.9.1" else old) as remote:
            self.assertEqual(verify(staging, "v0.9.1"), current)
            self.assertEqual(remote.call_count, 2)
            old["assets"] = old["assets"][1:]
            with self.assertRaisesRegex(ValueError, "Missing/wrong-sized"):
                verify(staging, "v0.9.1")


class DocumentationPolicyTests(unittest.TestCase):
    def test_user_facing_pr_requires_actual_user_documentation_changes(self):
        body = "- [x] User manual reviewed\nManual impact: updated\nManual review notes: Updated the connection steps."
        self.assertTrue(review_errors(body, ["src/ComPort_Zone/app.py"]))
        self.assertEqual(review_errors(body, ["src/ComPort_Zone/app.py", "docs/USER_MANUAL.md"]), [])

    def test_internal_pr_can_explain_why_the_manual_stays_unchanged(self):
        body = "- [x] User manual reviewed\nManual impact: none\nManual review notes: Changes internal CI logging only; user behavior is unchanged."
        self.assertEqual(review_errors(body, [".github/workflows/ci.yml"]), [])

    def test_template_comments_and_placeholders_do_not_count_as_review(self):
        body = "<!-- - [x] User manual reviewed -->\nManual impact: none\nManual review notes: <explain why behavior is unchanged>"
        self.assertGreaterEqual(len(review_errors(body, [])), 2)

    def test_binaries_are_blocked_without_blocking_manual_images_or_app_audio(self):
        for name in ("docs/media/guide.mp4", "docs/media/comport-zone-user-manual.pdf", "models/kokoro.onnx"):
            self.assertTrue(forbidden_asset(name), name)
        for name in ("docs/media/tutorial-terminal.png", "src/ComPort_Zone/assets/alert.wav", "tools/media/storyboard.json"):
            self.assertFalse(forbidden_asset(name), name)


if __name__ == "__main__":
    unittest.main()
