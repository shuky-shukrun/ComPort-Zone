"""Unit tests for the single serialized request/response channel.

These exercise the core of the concurrency fix: that each reply is
correlated to the exact in-flight transaction (even for identical
payloads), that interactive sends pre-empt queued polls, and that
connection loss / stop resolve every future instead of hanging.
"""

from __future__ import annotations

import itertools
import time
import unittest
from threading import Event

from ComPort_Zone.port_channel import (
    CANCELLED,
    CLOSED,
    INTERACTIVE,
    NORMAL,
    OK,
    SOURCE_UNSOLICITED,
    TIMEOUT,
    CountMatcher,
    DatagramMatcher,
    LineMatcher,
    PortChannel,
    RegexMatcher,
    SubstringMatcher,
)

from tests.fakes.fake_raw_transport import FakeRawTransport


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class ChannelTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = FakeRawTransport()
        self.raw.open()
        self.lost: list[str] = []
        self.channel = PortChannel(self.raw, on_connection_lost=self.lost.append)
        self.monitor = self.channel.subscribe_monitor()
        self.channel.start()

    def tearDown(self) -> None:
        self.channel.stop()

    def drain_monitor(self):
        events = []
        while True:
            try:
                events.append(self.monitor.get_nowait())
            except Exception:
                return events


class QueryCorrelationTests(ChannelTestBase):
    def test_query_returns_matched_line(self) -> None:
        self.raw.set_responder(lambda payload: b"4.200\r\n")
        result = self.channel.query(
            b"MEAS:VOLT?\n", matcher=LineMatcher(), timeout=1.0
        ).result(timeout=2.0)
        self.assertEqual(result.status, OK)
        self.assertEqual(result.text().strip(), "4.200")

    def test_identical_payloads_are_correlated_in_order(self) -> None:
        # The core bug: two identical SYST:ERR:ALL? queries used to be
        # indistinguishable by timestamp. Here each gets ITS OWN reply.
        counter = itertools.count()
        self.raw.set_responder(lambda payload: f"+{next(counter)}\r\n".encode())
        f1 = self.channel.query(b"SYST:ERR:ALL?\n", matcher=LineMatcher(), timeout=1.0)
        f2 = self.channel.query(b"SYST:ERR:ALL?\n", matcher=LineMatcher(), timeout=1.0)
        self.assertEqual(f1.result(timeout=2.0).text().strip(), "+0")
        self.assertEqual(f2.result(timeout=2.0).text().strip(), "+1")

    def test_query_times_out_when_no_reply_and_worker_survives(self) -> None:
        result = self.channel.query(
            b"NOPE?\n", matcher=LineMatcher(), timeout=0.1
        ).result(timeout=2.0)
        self.assertEqual(result.status, TIMEOUT)
        # Worker still alive: a subsequent query with a reply succeeds.
        self.raw.set_responder(lambda payload: b"ok\r\n")
        follow = self.channel.query(
            b"PING?\n", matcher=LineMatcher(), timeout=1.0
        ).result(timeout=2.0)
        self.assertEqual(follow.status, OK)

    def test_regex_matcher(self) -> None:
        self.raw.set_responder(lambda payload: b"VALUE=42 END\r\n")
        result = self.channel.query(
            b"Q?\n", matcher=RegexMatcher(r"VALUE=(\d+)"), timeout=1.0
        ).result(timeout=2.0)
        self.assertEqual(result.status, OK)
        self.assertIn("VALUE=42", result.text())

    def test_substring_matcher(self) -> None:
        self.raw.set_responder(lambda payload: b"...READY...\r\n")
        result = self.channel.query(
            b"GO\n", matcher=SubstringMatcher("READY"), timeout=1.0
        ).result(timeout=2.0)
        self.assertEqual(result.status, OK)

    def test_count_matcher(self) -> None:
        self.raw.set_responder(lambda payload: b"\x01\x02\x03\x04")
        result = self.channel.query(
            b"\xaa", matcher=CountMatcher(4), timeout=1.0
        ).result(timeout=2.0)
        self.assertEqual(result.status, OK)
        self.assertEqual(result.response, b"\x01\x02\x03\x04")

    def test_datagram_matcher_completes_without_a_terminator(self) -> None:
        self.raw.set_responder(lambda payload: b"12.345")
        result = self.channel.query(
            b"MEAS?", matcher=DatagramMatcher(), timeout=1.0
        ).result(timeout=2.0)
        self.assertEqual(result.status, OK)
        self.assertEqual(result.response, b"12.345")

    def test_datagram_matcher_ignores_an_empty_spool(self) -> None:
        self.assertIsNone(DatagramMatcher().find_complete(b""))
        self.assertEqual(DatagramMatcher().find_complete(b"x"), 1)


class DefaultMatcherTests(unittest.TestCase):
    def test_defaults_to_line_framing(self) -> None:
        raw = FakeRawTransport()
        raw.open()
        channel = PortChannel(raw)
        self.assertIsInstance(channel.default_matcher(), LineMatcher)

    def test_datagram_transports_supply_their_own_default(self) -> None:
        raw = FakeRawTransport()
        raw.open()
        channel = PortChannel(raw, default_matcher=DatagramMatcher)
        first = channel.default_matcher()
        self.assertIsInstance(first, DatagramMatcher)
        # A factory, not a shared instance: no state can leak between requests.
        self.assertIsNot(first, channel.default_matcher())


class WriteSemanticsTests(ChannelTestBase):
    def test_write_is_fire_and_forget(self) -> None:
        result = self.channel.write(b"OUTP ON\n").result(timeout=2.0)
        self.assertEqual(result.status, OK)
        self.assertIn(b"OUTP ON\n", self.raw.writes)

    def test_quiet_read_captures_immediate_reply(self) -> None:
        self.raw.set_responder(lambda payload: b"echo\r\n")
        result = self.channel.write(
            b"*IDN?\n", quiet_read=0.2
        ).result(timeout=2.0)
        self.assertEqual(result.status, OK)
        self.assertIn("echo", result.text())


class MonitorTaggingTests(ChannelTestBase):
    def test_unsolicited_inbound_while_idle_goes_to_monitor(self) -> None:
        self.raw.feed_inbound(b"SURPRISE\r\n")
        self.assertTrue(
            _wait_until(
                lambda: any(
                    e.kind == "rx" and "SURPRISE" in e.message
                    for e in self.drain_monitor()
                )
            )
        )

    def test_source_tag_propagates_to_tx_and_rx(self) -> None:
        self.raw.set_responder(lambda payload: b"0,\"No error\"\r\n")
        self.channel.query(
            b"SYST:ERR:ALL?\n",
            matcher=LineMatcher(),
            timeout=1.0,
            source="control_panel",
            display="SYST:ERR:ALL?",
        ).result(timeout=2.0)
        events = self.drain_monitor()
        tx = [e for e in events if e.kind == "tx"]
        rx = [e for e in events if e.kind == "rx"]
        self.assertTrue(tx and all(e.source == "control_panel" for e in tx))
        self.assertTrue(rx and all(e.source == "control_panel" for e in rx))

    def test_leftover_inbound_not_attributed_to_next_reply(self) -> None:
        self.raw.feed_inbound(b"STALE\r\n")
        # Let the reader spool + publish the stale bytes first.
        self.assertTrue(
            _wait_until(
                lambda: any("STALE" in e.message for e in self.drain_monitor())
            )
        )
        self.raw.set_responder(lambda payload: b"FRESH\r\n")
        result = self.channel.query(
            b"Q?\n", matcher=LineMatcher(), timeout=1.0
        ).result(timeout=2.0)
        self.assertEqual(result.text().strip(), "FRESH")


class PriorityTests(ChannelTestBase):
    def test_interactive_jumps_ahead_of_queued_normal(self) -> None:
        gate = Event()

        def responder(payload: bytes) -> bytes | None:
            if payload == b"BLOCK\n":
                gate.wait(2.0)
            return b"r\r\n"

        self.raw.set_responder(responder)
        f0 = self.channel.query(b"BLOCK\n", matcher=LineMatcher(), timeout=3.0)
        # Worker is now parked inside write(BLOCK).
        self.assertTrue(_wait_until(lambda: b"BLOCK\n" in self.raw.writes))
        fn = self.channel.write(b"NORMAL\n", priority=NORMAL)
        fi = self.channel.write(b"INTER\n", priority=INTERACTIVE)
        gate.set()
        f0.result(timeout=3.0)
        fn.result(timeout=3.0)
        fi.result(timeout=3.0)
        self.assertLess(
            self.raw.writes.index(b"INTER\n"),
            self.raw.writes.index(b"NORMAL\n"),
            "interactive send should pre-empt the queued NORMAL poll",
        )


class LifecycleTests(ChannelTestBase):
    def test_connection_lost_fails_inflight_and_queued(self) -> None:
        # No responder: the first query parks in the read window.
        f1 = self.channel.query(b"A\n", matcher=LineMatcher(), timeout=5.0)
        self.assertTrue(_wait_until(lambda: b"A\n" in self.raw.writes))
        f2 = self.channel.query(b"B\n", matcher=LineMatcher(), timeout=5.0)
        self.raw.drop_connection()
        self.assertEqual(f1.result(timeout=2.0).status, CLOSED)
        self.assertEqual(f2.result(timeout=2.0).status, CLOSED)
        self.assertTrue(_wait_until(lambda: bool(self.lost)))

    def test_stop_cancels_queued(self) -> None:
        f1 = self.channel.query(b"A\n", matcher=LineMatcher(), timeout=10.0)
        self.assertTrue(_wait_until(lambda: b"A\n" in self.raw.writes))
        f2 = self.channel.query(b"B\n", matcher=LineMatcher(), timeout=10.0)
        self.channel.stop()
        self.assertEqual(f2.result(timeout=2.0).status, CANCELLED)
        # The in-flight one resolves too (cancelled by stop), never hangs.
        self.assertEqual(f1.result(timeout=2.0).status, CANCELLED)

    def test_submit_after_stop_resolves_closed(self) -> None:
        self.channel.stop()
        result = self.channel.write(b"X\n").result(timeout=1.0)
        self.assertEqual(result.status, CLOSED)


class SingleWriterInvariantTests(ChannelTestBase):
    def test_concurrent_queries_each_get_own_reply(self) -> None:
        # Echo a per-payload tagged reply; assert every future gets exactly
        # the reply for its own payload — no interleaving, no misroute.
        def responder(payload: bytes) -> bytes:
            token = payload.strip().decode().removeprefix("Q:")
            return f"R:{token}\r\n".encode()

        self.raw.set_responder(responder)

        import threading

        results: dict[str, str] = {}
        lock = threading.Lock()

        def worker(tid: int) -> None:
            for seq in range(25):
                token = f"{tid}-{seq}"
                fut = self.channel.query(
                    f"Q:{token}\n".encode(), matcher=LineMatcher(), timeout=2.0
                )
                res = fut.result(timeout=3.0)
                with lock:
                    results[token] = res.text().strip()

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20.0)

        self.assertEqual(len(results), 6 * 25)
        for token, reply in results.items():
            self.assertEqual(reply, f"R:{token}", f"{token} got {reply!r}")


if __name__ == "__main__":
    unittest.main()
