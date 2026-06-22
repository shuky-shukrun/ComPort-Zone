"""Concurrency stress tests for the serialized port channel.

Transport-agnostic (a FakeRawTransport echoes per-payload tagged replies), so
these prove the Serial+LAN-shared correlation guarantee deterministically:
many concurrent senders hammering ONE channel each receive exactly their own
reply — zero drops, zero misroutes — including a block of repeated-identical
payloads (the original ``SYST:ERR:ALL?`` symptom) and backpressure.
"""

from __future__ import annotations

import itertools
import threading
import unittest

from ComPort_Zone.port_channel import INTERACTIVE, NORMAL, LineMatcher, PortChannel

from tests.fakes.fake_raw_transport import FakeRawTransport


class ChannelStressTests(unittest.TestCase):
    def _channel(self, responder, *, delay: float = 0.0) -> PortChannel:
        raw = FakeRawTransport(read_timeout=0.002)
        raw.open()
        raw.set_responder(responder, delay=delay)
        channel = PortChannel(raw)
        channel.start()
        self.addCleanup(channel.stop)
        return channel

    def test_many_senders_each_gets_own_correct_reply(self) -> None:
        # Echo a per-payload tag: Q{tid}:{seq}? -> R{tid}:{seq}
        def responder(payload: bytes) -> bytes:
            token = payload.decode().strip().lstrip("Q").rstrip("?")
            return f"R{token}\r\n".encode()

        channel = self._channel(responder)
        errors: list[tuple] = []
        lock = threading.Lock()

        def sender(tid: int, count: int, priority: int) -> None:
            for seq in range(count):
                payload = f"Q{tid}:{seq}?\r\n".encode()
                res = channel.query(
                    payload, matcher=LineMatcher(), timeout=2.0, priority=priority
                ).result(timeout=10.0)
                expected = f"R{tid}:{seq}"
                if not (res.ok and res.text().strip() == expected):
                    with lock:
                        errors.append((tid, seq, res.status, res.text().strip()))

        per = 200
        threads = [threading.Thread(target=sender, args=(100, per, INTERACTIVE))]  # terminal
        threads += [threading.Thread(target=sender, args=(t, per, NORMAL)) for t in range(8)]  # pollers
        threads.append(threading.Thread(target=sender, args=(200, per, NORMAL)))  # batch
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertEqual(errors, [], f"{len(errors)} misrouted/dropped (first 5: {errors[:5]})")

    def test_repeated_identical_payloads_no_drops_or_dupes(self) -> None:
        # The core bug: identical SYST:ERR:ALL? requests were indistinguishable
        # by timestamp. Each query must get exactly one distinct reply.
        counter = itertools.count()

        def responder(payload: bytes) -> bytes:
            return f"+{next(counter)}\r\n".encode()

        channel = self._channel(responder)
        received: list[str] = []
        lock = threading.Lock()
        total = 500

        def sender(count: int) -> None:
            for _ in range(count):
                res = channel.query(
                    b"SYST:ERR:ALL?\r\n", matcher=LineMatcher(), timeout=2.0
                ).result(timeout=10.0)
                with lock:
                    received.append(res.text().strip())

        threads = [threading.Thread(target=sender, args=(total // 2,)) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertEqual(len(received), total, "some queries never resolved")
        # No reply was delivered twice and none was dropped: the set of replies
        # is exactly the set the device generated.
        self.assertEqual(len(set(received)), total, "duplicate or stolen replies")

    def test_no_response_dropped_under_backpressure(self) -> None:
        # Replies lag behind submissions; every submitted query must still
        # resolve (ok), never silently lost.
        def responder(payload: bytes) -> bytes:
            return b"ack\r\n"

        channel = self._channel(responder, delay=0.003)
        futures = [
            channel.query(f"P{i}?\r\n".encode(), matcher=LineMatcher(), timeout=5.0)
            for i in range(300)
        ]
        results = [f.result(timeout=15.0) for f in futures]
        self.assertEqual(len(results), 300)
        self.assertTrue(all(r.ok for r in results), "a query was dropped under backpressure")


if __name__ == "__main__":
    unittest.main()
