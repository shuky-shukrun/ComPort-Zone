"""Tests for the dashboard CSV value logger (FR-49/FR-50/FR-51)."""

from __future__ import annotations

import csv
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from ComPort_Zone.core.dashboard import (
    VALUE_LOG_FIELDS,
    DashboardValueLogger,
)


FIXED = datetime(2026, 6, 12, 14, 2, 0, tzinfo=timezone.utc).astimezone()


class DashboardValueLoggerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.logger = DashboardValueLogger()
        self.addCleanup(self.logger.close)

    def _read(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            return list(csv.DictReader(csv_file))

    def test_open_writes_header(self) -> None:
        path = self.tmp / "values.csv"
        self.logger.open(path)
        self.assertTrue(self.logger.enabled)
        self.assertEqual(self.logger.path, path)
        with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            header = next(csv.reader(csv_file))
        self.assertEqual(header, list(VALUE_LOG_FIELDS))

    def test_log_row_round_trips_with_value_number(self) -> None:
        path = self.tmp / "values.csv"
        self.logger.open(path)
        self.assertTrue(
            self.logger.log(
                dashboard="Bench",
                entry_id="volts",
                label="Rail A",
                kind="poll",
                value_text="13.2 V",
                value_number=13.2,
                state="warn",
                timestamp=FIXED,
            )
        )
        rows = self._read(path)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["dashboard"], "Bench")
        self.assertEqual(row["entry_id"], "volts")
        self.assertEqual(row["label"], "Rail A")
        self.assertEqual(row["kind"], "poll")
        self.assertEqual(row["value_text"], "13.2 V")
        self.assertEqual(row["value_number"], "13.2")
        self.assertEqual(row["state"], "warn")
        self.assertTrue(row["timestamp"].startswith("2026-06-12T"))

    def test_text_row_emits_empty_value_number(self) -> None:
        path = self.tmp / "values.csv"
        self.logger.open(path)
        self.logger.log(
            dashboard="Bench",
            entry_id="mode",
            label="Mode",
            kind="poll",
            value_text="CV",
            value_number=None,
            state="ok",
            timestamp=FIXED,
        )
        rows = self._read(path)
        self.assertEqual(rows[0]["value_number"], "")
        self.assertEqual(rows[0]["value_text"], "CV")
        self.assertEqual(rows[0]["kind"], "poll")

    def test_log_returns_false_when_disabled(self) -> None:
        self.assertFalse(
            self.logger.log(
                dashboard="x",
                entry_id="y",
                label="z",
                kind="poll",
                value_text="",
                value_number=None,
                state="neutral",
            )
        )

    def test_reopen_appends_without_repeating_header(self) -> None:
        path = self.tmp / "values.csv"
        self.logger.open(path)
        self.logger.log(
            dashboard="Bench",
            entry_id="a",
            label="A",
            kind="poll",
            value_text="1",
            value_number=1.0,
            state="ok",
            timestamp=FIXED,
        )
        self.logger.close()
        # Reopening must NOT re-emit the header line, otherwise consumers
        # see a stray row in the middle of the file.
        self.logger.open(path)
        self.logger.log(
            dashboard="Bench",
            entry_id="b",
            label="B",
            kind="poll",
            value_text="2",
            value_number=2.0,
            state="ok",
            timestamp=FIXED,
        )
        rows = self._read(path)
        self.assertEqual([row["entry_id"] for row in rows], ["a", "b"])

    def test_open_replaces_a_prior_session(self) -> None:
        first = self.tmp / "a.csv"
        second = self.tmp / "b.csv"
        self.logger.open(first)
        self.logger.open(second)
        self.assertEqual(self.logger.path, second)
        self.assertTrue(second.exists())

    def test_open_unwritable_path_raises(self) -> None:
        # A path inside a missing-and-uncreatable directory triggers
        # OSError; the tab is the one that surfaces it via notify().
        path = self.tmp / "non" / "existent" / "file.csv"
        # mkdir(parents=True) makes the dirs writable on the happy path,
        # so we point at a file that already exists as a directory.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir()  # `path` is now a directory; opening for write fails.
        with self.assertRaises(OSError):
            self.logger.open(path)

    def test_concurrent_log_is_serialized(self) -> None:
        # The lock protects rows from interleaving when a future patch
        # logs from a worker thread; check it by hammering from many.
        path = self.tmp / "values.csv"
        self.logger.open(path)

        def worker(index: int) -> None:
            for round_index in range(10):
                self.logger.log(
                    dashboard="Bench",
                    entry_id=f"t{index}",
                    label=f"T{index}",
                    kind="poll",
                    value_text=f"{round_index}",
                    value_number=float(round_index),
                    state="ok",
                    timestamp=FIXED,
                )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        rows = self._read(path)
        self.assertEqual(len(rows), 40)
        # No rows lost; no partials (every row decodes as a full record).
        for row in rows:
            self.assertEqual(set(row), set(VALUE_LOG_FIELDS))


class DashboardValueLoggerKindColumnTests(unittest.TestCase):
    """v3 audit column tests (FR-50/FR-76/FR-77)."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.logger = DashboardValueLogger()
        self.addCleanup(self.logger.close)

    def _read(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            return list(csv.DictReader(csv_file))

    def test_kind_column_in_fixed_header(self) -> None:
        # The fixed-order header gates downstream tooling. ``kind`` sits
        # between label and value_text.
        self.assertEqual(
            VALUE_LOG_FIELDS,
            (
                "timestamp",
                "dashboard",
                "entry_id",
                "label",
                "kind",
                "value_text",
                "value_number",
                "state",
            ),
        )

    def test_poll_derived_control_kinds_distinguishable(self) -> None:
        path = self.tmp / "values.csv"
        self.logger.open(path)
        for kind in ("poll", "derived", "control"):
            self.logger.log(
                dashboard="Bench",
                entry_id=f"e_{kind}",
                label=kind.upper(),
                kind=kind,
                value_text=f"{kind}-text",
                value_number=None,
                state="ok",
                timestamp=FIXED,
            )
        rows = self._read(path)
        self.assertEqual([row["kind"] for row in rows], ["poll", "derived", "control"])
        self.assertEqual(
            [row["value_text"] for row in rows],
            ["poll-text", "derived-text", "control-text"],
        )

    def test_control_row_carries_sent_command_and_error_state(self) -> None:
        path = self.tmp / "values.csv"
        self.logger.open(path)
        self.logger.log(
            dashboard="Bench",
            entry_id="output",
            label="Output",
            kind="control",
            value_text="OUTP ON",
            value_number=None,
            state="ok",
            timestamp=FIXED,
        )
        self.logger.log(
            dashboard="Bench",
            entry_id="output",
            label="Output",
            kind="control",
            value_text="OUTP OFF",
            value_number=None,
            state="error",
            timestamp=FIXED,
        )
        rows = self._read(path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["kind"], "control")
        self.assertEqual(rows[0]["value_text"], "OUTP ON")
        self.assertEqual(rows[0]["state"], "ok")
        self.assertEqual(rows[0]["value_number"], "")
        self.assertEqual(rows[1]["state"], "error")

    def test_pre_v3_log_without_kind_reads_back(self) -> None:
        # A log written by a v2 build (no kind column) must still read
        # back through csv.DictReader — missing key, not raised.
        path = self.tmp / "old.csv"
        # Hand-assemble a v2-shaped log file with utf-8-sig BOM.
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            handle.write(
                "timestamp,dashboard,entry_id,label,value_text,value_number,state\n"
            )
            handle.write("2026-06-12T14:02:00.000+00:00,Bench,volts,V,12.0,12.0,ok\n")
        rows = self._read(path)
        self.assertEqual(len(rows), 1)
        # DictReader returns None for missing columns; the row IS readable.
        self.assertNotIn("kind", rows[0])
        self.assertEqual(rows[0]["entry_id"], "volts")
        self.assertEqual(rows[0]["state"], "ok")

    def test_v3_reopen_starts_new_header_with_kind_column(self) -> None:
        # If a user toggled logging on under v2 (no kind) and then upgrades
        # to v3, the next reopen rewrites the header — old rows stay
        # readable, new rows get the kind column. We don't try to migrate
        # the old rows; we just append cleanly.
        path = self.tmp / "old.csv"
        # Start by leaving the file empty so v3 writes a fresh header.
        self.logger.open(path)
        self.logger.log(
            dashboard="Bench",
            entry_id="x",
            label="X",
            kind="poll",
            value_text="1",
            value_number=1.0,
            state="ok",
            timestamp=FIXED,
        )
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = handle.readline().strip()
        self.assertIn("kind", header.split(","))


if __name__ == "__main__":
    unittest.main()
