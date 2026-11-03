"""Live recording integrity, camera bounds and caption synchronization."""
from __future__ import annotations

import copy
import unittest

from tools.media.live_timing import camera_rect, ease, frame_count, rebased_captions, recording_errors


class LiveTimingTests(unittest.TestCase):
    def test_camera_stays_inside_source_at_all_corners(self):
        for zoom in (1, 1.1, 1.3, 2):
            for px, py in ((0, 0), (1600, 0), (0, 820), (1600, 820), (800, 410)):
                x, y, w, h = camera_rect(1600, 820, zoom, px, py)
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + w, 1600)
                self.assertLessEqual(y + h, 820)
                self.assertAlmostEqual(w / h, 1600 / 820)

    def test_camera_never_enlarges_beyond_source(self):
        self.assertEqual(camera_rect(1600, 820, 0.5, 20, 30), (0, 0, 1600, 820))

    def test_easing_is_independent_of_timer_frequency(self):
        value = 0
        for _ in range(30):
            value = ease(value, 100, 1 / 30)
        self.assertAlmostEqual(value, ease(0, 100, 1))
        self.assertGreater(value, 0)
        self.assertLess(value, 100)

    def test_frame_rounding_does_not_drop_fractional_audio_tail(self):
        self.assertEqual(frame_count(1, 30), 30)
        self.assertEqual(frame_count(1.001, 30), 31)
        self.assertEqual(frame_count(0, 30), 0)

    def test_captions_follow_actual_start_after_slow_interaction(self):
        scene = {"start": 20, "captions": [{"start": 20.6, "end": 23.4, "text": "Click Run."}]}
        original = copy.deepcopy(scene)
        result = rebased_captions(scene, 27)
        self.assertAlmostEqual(result[0]["start"], 27.6)
        self.assertAlmostEqual(result[0]["end"], 30.4)
        self.assertEqual(result[0]["text"], "Click Run.")
        self.assertEqual(scene, original)

    def recording(self):
        return {"version": "0.9.0", "source_fingerprint": "source", "narration_sha256": "voice",
                "steps": [{"id": "connect", "start": 0, "duration": 2},
                          {"id": "send", "start": 2.02, "duration": 3}],
                "fps": 30, "frames": 151, "duration": 151 / 30, "errors": []}

    def errors(self, record):
        return recording_errors(record, ["connect", "send"], "0.9.0", "source", "voice")

    def test_valid_recording(self):
        self.assertEqual(self.errors(self.recording()), [])

    def test_rejects_stale_source_voice_or_version(self):
        for field in ("version", "source_fingerprint", "narration_sha256"):
            record = self.recording()
            record[field] = "changed"
            with self.subTest(field=field):
                self.assertTrue(self.errors(record))

    def test_rejects_missing_or_reordered_steps(self):
        for steps in ([self.recording()["steps"][0]], list(reversed(self.recording()["steps"]))):
            record = self.recording()
            record["steps"] = steps
            self.assertTrue(self.errors(record))

    def test_rejects_overlapping_steps_and_truncated_recording(self):
        record = self.recording()
        record["steps"][1]["start"] = 1
        self.assertTrue(self.errors(record))
        record = self.recording()
        record["duration"] = 4
        self.assertTrue(self.errors(record))

    def test_assertion_failures_and_missing_footage_block_assembly(self):
        record = self.recording()
        record["errors"] = ["Expected device response did not arrive"]
        self.assertIn(record["errors"][0], self.errors(record))
        for changes in ({"frames": 0}, {"fps": 12}):
            record = self.recording()
            record.update(changes)
            self.assertTrue(self.errors(record))


if __name__ == "__main__":
    unittest.main()
