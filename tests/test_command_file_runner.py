"""Direct unit tests for ``ComPort_Zone.cli.command_file_runner``.

The runner is exercised end-to-end via ``test_cli_run.py``, but a few
internal semantics deserve targeted assertions:

* The EXPECT buffer is trimmed past the match so a subsequent EXPECT
  doesn't re-match the same bytes.
* ``--continue-on-expect-fail`` accumulates failures without aborting.
* Each ``FAILURE_*`` constant maps to a specific failure path.
"""

from __future__ import annotations

import time
import unittest

from ComPort_Zone.cli.command_file_runner import (
    FAILURE_EXPECT,
    FAILURE_PARAM,
    FAILURE_PARSE,
    FAILURE_SEND,
    RunOutcome,
    run_command_file,
)
from ComPort_Zone.core.batch import parse_batch_template
from tests.fakes.fake_serial_transport import FakeSerialTransport


def _steps(text: str):
    return parse_batch_template(text)


def _no_events_sink(kind: str, fields: dict) -> None:
    """Drop every event — most tests only assert on the RunOutcome."""


class RunOutcomeShapeTests(unittest.TestCase):
    def test_empty_steps_succeed_with_zero_run_count(self) -> None:
        fake = FakeSerialTransport()
        outcome = run_command_file(fake, [], {}, on_event=_no_events_sink)
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.steps_run, 0)

    def test_send_step_sets_steps_run_to_one(self) -> None:
        fake = FakeSerialTransport()
        outcome = run_command_file(
            fake, _steps("SEND ping\n"), {}, on_event=_no_events_sink
        )
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.steps_run, 1)
        self.assertEqual(fake.sent_text, [("ping", None)])

    def test_hex_step_sends_bytes(self) -> None:
        fake = FakeSerialTransport()
        outcome = run_command_file(
            fake, _steps("HEX 55 AA\n"), {}, on_event=_no_events_sink
        )
        self.assertTrue(outcome.success)
        self.assertEqual(fake.sent_bytes, [b"\x55\xaa"])


class ExpectBufferTrimTests(unittest.TestCase):
    def test_second_expect_does_not_match_first_response_again(self) -> None:
        """Each EXPECT must consume only its own bytes from the buffer.

        Without buffer trimming, the first ``EXPECT OK`` would leave "OK\\r\\n"
        in the buffer and the second ``EXPECT OK`` would match the same bytes
        immediately, masking a missing response from the device.
        """
        fake = FakeSerialTransport()
        fake.queue_response(b"OK\r\n")  # answer to step 1
        # No second response queued — step 2 must time out.
        outcome = run_command_file(
            fake,
            _steps(
                """\
SEND first
EXPECT OK
SEND second
EXPECT OK
"""
            ),
            {},
            on_event=_no_events_sink,
            expect_timeout_ms=50,
        )
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.failure_kind, FAILURE_EXPECT)
        # First EXPECT matched; second did not. expect_failures counts only
        # the unmatched ones, regardless of whether the run stopped.
        self.assertEqual(outcome.expect_failures, 1)


class ContinueOnExpectFailTests(unittest.TestCase):
    def test_continue_keeps_running_and_counts_failures(self) -> None:
        fake = FakeSerialTransport()
        outcome = run_command_file(
            fake,
            _steps(
                """\
SEND a
EXPECT NEVER
SEND b
EXPECT NEVER
SEND c
"""
            ),
            {},
            on_event=_no_events_sink,
            stop_on_expect_fail=False,
            expect_timeout_ms=30,
        )
        # No failure should abort the run — all three SENDs happen.
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.expect_failures, 2)
        self.assertEqual([text for text, _ in fake.sent_text], ["a", "b", "c"])


class SettingsDirectiveTests(unittest.TestCase):
    def test_send_mode_hex_sends_bare_lines_as_bytes(self) -> None:
        fake = FakeSerialTransport()
        outcome = run_command_file(
            fake, _steps("@@send-mode hex\n55 AA\n"), {}, on_event=_no_events_sink
        )
        self.assertTrue(outcome.success)
        self.assertEqual(fake.sent_bytes, [b"\x55\xaa"])

    def test_on_error_continue_overrides_default_stop(self) -> None:
        # Default is stop; the @@ directive flips it mid-run so SEND b still runs.
        fake = FakeSerialTransport()
        outcome = run_command_file(
            fake,
            _steps("SEND a\n@@on-error continue\nEXPECT NEVER\nSEND b\n"),
            {},
            on_event=_no_events_sink,
            expect_timeout_ms=20,
        )
        self.assertTrue(outcome.success)
        self.assertEqual([text for text, _ in fake.sent_text], ["a", "b"])

    def test_expect_timeout_setting_lowers_timeout(self) -> None:
        fake = FakeSerialTransport()
        outcome = run_command_file(
            fake,
            _steps("@@expect-timeout 20\nSEND x\nEXPECT NEVER\n"),
            {},
            on_event=_no_events_sink,
            expect_timeout_ms=1000,
        )
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.failure_kind, FAILURE_EXPECT)
        self.assertIn("after 20 ms", outcome.failure_message)


class ParameterTests(unittest.TestCase):
    def test_param_value_substituted_into_send(self) -> None:
        fake = FakeSerialTransport()
        outcome = run_command_file(
            fake,
            _steps("SEND v={{VOLT}}\n"),
            {"VOLT": "3.3"},
            on_event=_no_events_sink,
        )
        self.assertTrue(outcome.success)
        self.assertEqual(fake.sent_text, [("v=3.3", None)])

    def test_missing_param_returns_param_failure(self) -> None:
        fake = FakeSerialTransport()
        outcome = run_command_file(
            fake,
            _steps("SEND v={{VOLT}}\n"),
            {},  # no value for VOLT, no default in template
            on_event=_no_events_sink,
        )
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.failure_kind, FAILURE_PARAM)


class ParseErrorTests(unittest.TestCase):
    def test_malformed_hex_after_substitution_returns_parse_failure(self) -> None:
        fake = FakeSerialTransport()
        # Odd-nibble HEX triggers BatchParseError.
        outcome = run_command_file(
            fake, _steps("HEX 5\n"), {}, on_event=_no_events_sink
        )
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.failure_kind, FAILURE_PARSE)


class SendFailureTests(unittest.TestCase):
    def test_send_exception_returns_send_failure(self) -> None:
        fake = FakeSerialTransport()

        def explode(text: str, line_ending_override=None) -> None:
            raise RuntimeError("simulated write error")

        fake.send_text = explode  # type: ignore[assignment]
        outcome = run_command_file(
            fake, _steps("SEND ping\n"), {}, on_event=_no_events_sink
        )
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.failure_kind, FAILURE_SEND)


class EventSinkTests(unittest.TestCase):
    def test_event_sink_receives_tx_and_rx_and_expect(self) -> None:
        fake = FakeSerialTransport()
        fake.queue_response(b"OK\r\n")
        recorded: list[tuple[str, dict]] = []

        def sink(kind: str, fields: dict) -> None:
            recorded.append((kind, dict(fields)))

        outcome = run_command_file(
            fake,
            _steps("SEND ping\nEXPECT OK\n"),
            {},
            on_event=sink,
            expect_timeout_ms=200,
        )
        self.assertTrue(outcome.success)
        kinds = [kind for kind, _ in recorded]
        self.assertIn("tx", kinds)
        self.assertIn("rx", kinds)
        self.assertIn("expect", kinds)
        # The expect record should report matched=True.
        expect_payloads = [fields for kind, fields in recorded if kind == "expect"]
        self.assertTrue(expect_payloads[0]["matched"])


class WaitStepTests(unittest.TestCase):
    def test_wait_delays_at_least_specified_ms(self) -> None:
        fake = FakeSerialTransport()
        start = time.monotonic()
        outcome = run_command_file(
            fake, _steps("WAIT 80\n"), {}, on_event=_no_events_sink
        )
        elapsed = time.monotonic() - start
        self.assertTrue(outcome.success)
        # Allow a small scheduling slop on the lower bound.
        self.assertGreaterEqual(elapsed, 0.060)


if __name__ == "__main__":
    unittest.main()
