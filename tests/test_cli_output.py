"""Direct unit tests for ``ComPort_Zone.cli.output.CliOutput``.

The class is exercised indirectly by every subcommand test, but a subtle
bug in event routing / JSON shape / quiet-mode handling would surface
across many surfaces at once. These tests pin the behaviour at the
source.
"""

from __future__ import annotations

import io
import json
import unittest

from ComPort_Zone.cli.exit_codes import ExitCode
from ComPort_Zone.cli.output import CliOutput


def _make_output(**kwargs) -> tuple[CliOutput, io.StringIO, io.StringIO]:
    """Build a ``CliOutput`` whose stdout/stderr are in-memory streams."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    return (
        CliOutput(stdout=stdout, stderr=stderr, color=False, **kwargs),
        stdout,
        stderr,
    )


class StatusTests(unittest.TestCase):
    def test_plain_status_writes_to_stdout(self) -> None:
        output, stdout, stderr = _make_output()
        output.status("hello")
        self.assertEqual(stdout.getvalue().strip(), "hello")
        self.assertEqual(stderr.getvalue(), "")

    def test_quiet_suppresses_status(self) -> None:
        output, stdout, stderr = _make_output(quiet=True)
        output.status("hidden")
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_json_status_emits_event_object(self) -> None:
        output, stdout, _ = _make_output(json_mode=True)
        output.status("connected")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload, {"type": "status", "message": "connected"})


class DebugTests(unittest.TestCase):
    def test_debug_suppressed_without_verbose(self) -> None:
        output, stdout, stderr = _make_output()
        output.debug("trace")
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_debug_plain_goes_to_stderr_under_verbose(self) -> None:
        output, stdout, stderr = _make_output(verbose=True)
        output.debug("trace")
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("trace", stderr.getvalue())

    def test_debug_json_emits_event_on_stdout(self) -> None:
        output, stdout, _ = _make_output(verbose=True, json_mode=True)
        output.debug("trace")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload, {"type": "debug", "message": "trace"})


class ErrorTests(unittest.TestCase):
    def test_error_always_written_to_stderr_even_with_quiet(self) -> None:
        output, stdout, stderr = _make_output(quiet=True)
        output.error("boom", code=ExitCode.GENERIC_ERROR)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("boom", stderr.getvalue())
        self.assertIn("GENERIC_ERROR", stderr.getvalue())

    def test_error_without_code_omits_code_in_label(self) -> None:
        output, _, stderr = _make_output()
        output.error("plain message")
        text = stderr.getvalue()
        self.assertIn("plain message", text)
        # Just "Error:" prefix, not "Error (...)"
        self.assertIn("Error:", text)
        self.assertNotIn("Error (", text)

    def test_error_json_includes_code_string(self) -> None:
        output, stdout, stderr = _make_output(json_mode=True)
        output.error("boom", code=ExitCode.PORT_BUSY)
        # JSON errors go on stderr (so stdout stays clean for piping).
        payload = json.loads(stderr.getvalue())
        self.assertEqual(
            payload,
            {"type": "error", "message": "boom", "code": "PORT_BUSY"},
        )
        self.assertEqual(stdout.getvalue(), "")


class EventTests(unittest.TestCase):
    def test_rx_event_plain_prints_decoded_data(self) -> None:
        output, stdout, _ = _make_output()
        output.event("rx", data="hello\r\n", display="hello", hex="68656c6c6f0d0a")
        self.assertEqual(stdout.getvalue().strip(), "hello")

    def test_tx_event_plain_prefixes_with_arrow(self) -> None:
        output, stdout, _ = _make_output()
        output.event("tx", display="ping", mode="text")
        self.assertIn("TX>", stdout.getvalue())
        self.assertIn("ping", stdout.getvalue())

    def test_expect_event_renders_matched_marker(self) -> None:
        output, stdout, _ = _make_output()
        output.event("expect", pattern="OK", matched=True, after_ms=42)
        line = stdout.getvalue()
        self.assertIn("matched", line)
        self.assertIn("OK", line)
        self.assertIn("42", line)

    def test_unknown_kind_in_plain_mode_is_dropped(self) -> None:
        # Drop silently rather than printing raw — JSON mode is the
        # source of truth for "weird" event types.
        output, stdout, _ = _make_output()
        output.event("custom", foo="bar")
        self.assertEqual(stdout.getvalue(), "")

    def test_json_event_includes_timestamp_and_passes_through_fields(self) -> None:
        output, stdout, _ = _make_output(json_mode=True)
        output.event("rx", data="hi", hex="6869", port="COM3")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["type"], "rx")
        self.assertEqual(payload["data"], "hi")
        self.assertEqual(payload["hex"], "6869")
        self.assertEqual(payload["port"], "COM3")
        self.assertIn("ts", payload)


class ObjectTests(unittest.TestCase):
    def test_plain_object_renders_key_colon_value_per_line(self) -> None:
        output, stdout, _ = _make_output()
        output.object({"a": 1, "b": "two"})
        lines = stdout.getvalue().strip().splitlines()
        self.assertEqual(set(lines), {"a: 1", "b: two"})

    def test_json_object_is_pretty_printed_and_sorted(self) -> None:
        output, stdout, _ = _make_output(json_mode=True)
        output.object({"b": 2, "a": 1})
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload, {"a": 1, "b": 2})
        # sort_keys is on — verify a is before b in the raw text.
        raw = stdout.getvalue()
        self.assertLess(raw.find('"a"'), raw.find('"b"'))


class TableTests(unittest.TestCase):
    def test_empty_table_plain_prints_placeholder(self) -> None:
        output, stdout, _ = _make_output()
        output.table([], columns=["name", "value"])
        self.assertIn("(no entries)", stdout.getvalue())

    def test_empty_table_json_emits_empty_array(self) -> None:
        output, stdout, _ = _make_output(json_mode=True)
        output.table([], columns=["name"])
        self.assertEqual(json.loads(stdout.getvalue()), [])

    def test_plain_table_aligns_columns(self) -> None:
        output, stdout, _ = _make_output()
        output.table(
            [{"name": "short", "value": 1}, {"name": "much-longer", "value": 22}],
            columns=["name", "value"],
        )
        lines = stdout.getvalue().splitlines()
        # header, rule, row1, row2 — 4 lines
        self.assertEqual(len(lines), 4)
        # Every row's "name" column starts at the same offset.
        name_offsets = [line.find("short") if "short" in line else line.find("much-longer") for line in lines[2:]]
        self.assertEqual(name_offsets[0], name_offsets[1])

    def test_json_table_passes_full_row_dicts(self) -> None:
        output, stdout, _ = _make_output(json_mode=True)
        output.table(
            [{"name": "a", "value": 1, "extra": "kept"}],
            columns=["name", "value"],
        )
        payload = json.loads(stdout.getvalue())
        # JSON keeps every key — column list only controls the plain table.
        self.assertEqual(payload, [{"name": "a", "value": 1, "extra": "kept"}])


if __name__ == "__main__":
    unittest.main()
