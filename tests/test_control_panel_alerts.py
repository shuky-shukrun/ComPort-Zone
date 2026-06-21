"""Tests for alert transition detection and the bounded alert log."""

from __future__ import annotations

import unittest

from ComPort_Zone.control_panel_alerts import (
    ALERT_HISTORY_LIMIT,
    ALERT_KIND,
    RECOVERY_KIND,
    AlertLog,
    AlertRecord,
    detect_transition,
)

ALL_STATES = ("ok", "warn", "fail", "neutral", "stale", "error")


def make_record(kind: str, entry_id: str = "e1") -> AlertRecord:
    return AlertRecord(
        timestamp="12:00:00",
        entry_id=entry_id,
        entry_label="Volts",
        old_state="ok",
        new_state="fail",
        value_text="13.2 V",
        kind=kind,
    )


class DetectTransitionTests(unittest.TestCase):
    def test_exhaustive_matrix(self) -> None:
        alerting = {"fail", "error"}
        for prev in ALL_STATES:
            for new in ALL_STATES:
                expected = ""
                if new in alerting and prev not in alerting:
                    expected = ALERT_KIND
                elif prev in alerting and new not in alerting:
                    expected = RECOVERY_KIND
                with self.subTest(prev=prev, new=new):
                    self.assertEqual(detect_transition(prev, new), expected)

    def test_fail_to_error_does_not_refire(self) -> None:
        self.assertEqual(detect_transition("fail", "error"), "")
        self.assertEqual(detect_transition("error", "fail"), "")

    def test_stale_never_alerts(self) -> None:
        for prev in ("ok", "warn", "neutral"):
            self.assertEqual(detect_transition(prev, "stale"), "")


class AlertLogTests(unittest.TestCase):
    def test_append_counts_unseen_alerts_only(self) -> None:
        log = AlertLog()
        log.append(make_record(ALERT_KIND))
        log.append(make_record(RECOVERY_KIND))
        log.append(make_record(ALERT_KIND))
        self.assertEqual(log.unseen_count, 2)
        self.assertEqual(len(log), 3)

    def test_records_newest_first(self) -> None:
        log = AlertLog()
        log.append(make_record(ALERT_KIND, "first"))
        log.append(make_record(ALERT_KIND, "second"))
        self.assertEqual([record.entry_id for record in log.records()], ["second", "first"])

    def test_mark_seen(self) -> None:
        log = AlertLog()
        log.append(make_record(ALERT_KIND))
        log.mark_seen()
        self.assertEqual(log.unseen_count, 0)
        self.assertEqual(len(log), 1)  # history retained

    def test_bounded(self) -> None:
        log = AlertLog()
        for index in range(ALERT_HISTORY_LIMIT + 50):
            log.append(make_record(ALERT_KIND, f"e{index}"))
        self.assertEqual(len(log), ALERT_HISTORY_LIMIT)
        self.assertEqual(log.records()[0].entry_id, f"e{ALERT_HISTORY_LIMIT + 49}")

    def test_clear(self) -> None:
        log = AlertLog()
        log.append(make_record(ALERT_KIND))
        log.clear()
        self.assertEqual(len(log), 0)
        self.assertEqual(log.unseen_count, 0)


if __name__ == "__main__":
    unittest.main()
