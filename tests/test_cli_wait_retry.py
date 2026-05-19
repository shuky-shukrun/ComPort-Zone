"""Tests for ``--wait <seconds>`` exponential-backoff retry in
``ComPort_Zone.cli.serial_session.open_serial``.

When the requested port exists but the first connect attempt fails, the
helper sleeps with backoff up to the deadline and retries. We don't want
to slow CI down by waiting real seconds, so the tests configure short
deadlines and a transport that flips ``connect_returns`` after a few
attempts.
"""

from __future__ import annotations

import time
import unittest

from ComPort_Zone.cli.serial_session import (
    PortBusyError,
    PortNotFoundError,
    open_serial,
)
from ComPort_Zone.core.models import SerialProfile
from tests.fakes.fake_serial_transport import FakeSerialTransport


class FlakyTransport(FakeSerialTransport):
    """Transport that fails ``connect`` ``failure_count`` times then succeeds."""

    def __init__(self, failure_count: int) -> None:
        super().__init__()
        self._failures_remaining = failure_count

    def connect(self, profile):  # type: ignore[override]
        self.connect_calls.append(profile)
        if self._failures_remaining > 0:
            self._failures_remaining -= 1
            return False
        self._connected = True
        return True


class WaitSucceedsTests(unittest.TestCase):
    def test_connect_succeeds_after_backoff(self) -> None:
        transport = FlakyTransport(failure_count=2)
        transport.set_ports([{"device": "COM3"}])

        start = time.monotonic()
        # 2 failures × ~0.1s + jitter — 1 second deadline is plenty.
        open_serial(
            transport,
            SerialProfile(port="COM3"),
            wait_seconds=1.0,
        )
        elapsed = time.monotonic() - start
        self.assertTrue(transport.is_connected)
        # At least two connect calls + the first one, total 3.
        self.assertGreaterEqual(len(transport.connect_calls), 3)
        # Backoff is exponential from 0.1s; floor at ~0.1s for one sleep.
        self.assertGreater(elapsed, 0.05)


class WaitExhaustedTests(unittest.TestCase):
    def test_busy_beyond_deadline_raises_port_busy(self) -> None:
        # Always-failing transport — wait must give up with PortBusyError.
        transport = FakeSerialTransport()
        transport.set_ports([{"device": "COM3"}])
        transport.connect_returns = False

        with self.assertRaises(PortBusyError):
            open_serial(
                transport,
                SerialProfile(port="COM3"),
                wait_seconds=0.25,
            )
        # At least the initial attempt plus one retry should have run.
        self.assertGreaterEqual(len(transport.connect_calls), 2)


class WaitPortDisappearsTests(unittest.TestCase):
    def test_port_vanishing_during_wait_raises_port_not_found(self) -> None:
        # Transport that unplugs the port after the first failed attempt.
        class UnpluggingTransport(FakeSerialTransport):
            attempts = 0

            def connect(inner_self, profile):  # type: ignore[override]
                inner_self.connect_calls.append(profile)
                inner_self.attempts += 1
                if inner_self.attempts == 1:
                    # First connect fails AND the port is removed before
                    # the retry loop's next presence check runs.
                    inner_self.set_ports([])
                    return False
                return True

        transport = UnpluggingTransport()
        transport.set_ports([{"device": "COM3"}])

        with self.assertRaises(PortNotFoundError):
            open_serial(
                transport,
                SerialProfile(port="COM3"),
                wait_seconds=0.5,
            )


class ImmediateBusyTests(unittest.TestCase):
    def test_busy_with_zero_wait_raises_immediately(self) -> None:
        transport = FakeSerialTransport()
        transport.set_ports([{"device": "COM3"}])
        transport.connect_returns = False

        with self.assertRaises(PortBusyError):
            open_serial(transport, SerialProfile(port="COM3"), wait_seconds=0.0)
        # Exactly one connect attempt — no retry loop ran.
        self.assertEqual(len(transport.connect_calls), 1)


if __name__ == "__main__":
    unittest.main()
