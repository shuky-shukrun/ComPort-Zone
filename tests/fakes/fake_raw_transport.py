"""In-memory :class:`~ComPort_Zone.raw_transport.RawTransport` for tests.

Deterministic and thread-safe. Drives the channel without pyserial/sockets:

* ``feed_inbound(data)`` pushes unsolicited bytes the reader will return.
* ``set_responder(fn)`` makes each ``write`` synthesize a reply via
  ``fn(payload) -> bytes | None`` and feed it back — model a request/response
  device (including per-payload *tagged* replies for cross-talk assertions).
* ``writes`` records every payload written, in order, for invariants.
* ``fail_next_write()`` / ``drop_connection()`` inject ``ConnectionLost``.
"""

from __future__ import annotations

import time
from threading import Condition, Event, Lock, Thread
from typing import Callable

from ComPort_Zone.core.raw_transport import ConnectionLost


class FakeRawTransport:
    def __init__(self, *, read_timeout: float = 0.02) -> None:
        self._read_timeout = read_timeout
        self._cv = Condition(Lock())
        self._inbound = bytearray()
        self._open = False
        self.writes: list[bytes] = []
        self._responder: Callable[[bytes], bytes | None] | None = None
        self._reply_delay = 0.0
        self._fail_write = False
        self._fail_read = False
        self._closed = Event()

    # -- RawTransport surface ----------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False
        self._closed.set()
        with self._cv:
            self._cv.notify_all()

    def cancel_read(self) -> None:
        with self._cv:
            self._cv.notify_all()

    def write(self, data: bytes) -> None:
        if self._fail_write:
            self._fail_write = False
            raise ConnectionLost("simulated write failure")
        with self._cv:
            self.writes.append(bytes(data))
        responder = self._responder
        if responder is not None:
            reply = responder(bytes(data))
            if reply:
                if self._reply_delay > 0:
                    Thread(
                        target=self._delayed_feed,
                        args=(reply, self._reply_delay),
                        daemon=True,
                    ).start()
                else:
                    self.feed_inbound(reply)

    def read(self) -> bytes:
        with self._cv:
            if self._fail_read:
                raise ConnectionLost("simulated connection drop")
            if not self._inbound:
                self._cv.wait(self._read_timeout)
            if self._fail_read:
                raise ConnectionLost("simulated connection drop")
            if self._inbound:
                data = bytes(self._inbound)
                self._inbound.clear()
                return data
            return b""

    # -- test fixtures ------------------------------------------------------

    def feed_inbound(self, data: bytes) -> None:
        with self._cv:
            self._inbound += data
            self._cv.notify_all()

    def set_responder(
        self, fn: Callable[[bytes], bytes | None], *, delay: float = 0.0
    ) -> None:
        self._responder = fn
        self._reply_delay = delay

    def fail_next_write(self) -> None:
        self._fail_write = True

    def drop_connection(self) -> None:
        self._fail_read = True
        with self._cv:
            self._cv.notify_all()

    def _delayed_feed(self, reply: bytes, delay: float) -> None:
        time.sleep(delay)
        if self._open:
            self.feed_inbound(reply)
