"""The single serialized request/response owner of one connection.

A :class:`PortChannel` wraps a :class:`~ComPort_Zone.raw_transport.RawTransport`
and is the **only** code that touches the wire. It runs exactly two threads:

* a *reader* — the only caller of ``raw.read()``; it appends bytes to an
  inbound spool and republishes them to the monitor for display, and
* a *worker* — the only caller of ``raw.write()``; it pulls one
  :class:`Transaction` at a time from a priority queue and runs it to
  completion: discard stale inbound, write, then (for a query) read the
  spool until the transaction's :class:`Matcher` is satisfied or the timeout
  elapses, delivering the matched bytes to *that* transaction's
  :class:`~concurrent.futures.Future`.

Because one worker does drain→write→read for one transaction at a time,
the reply read during a transaction's window belongs to that transaction —
**structural** correlation, with no timestamps, settle sleeps, residual
drains, or traffic-window journals. Two identical commands issued by two
callers are two transactions executed back-to-back; each gets exactly the
bytes that arrive in its own window.

Interactive sends (terminal/REPL) submit at ``INTERACTIVE`` priority and so
jump ahead of queued background polls — but never interrupt a transaction
already on the wire, so a poll's reply can't be stolen mid-flight.

Qt-free by design (re-exported through ``core/port_channel.py``).
"""

from __future__ import annotations

import re
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, PriorityQueue, Queue
from threading import Condition, Event, Lock, Thread, current_thread
from itertools import count
from typing import Callable, Protocol

from .raw_transport import ConnectionLost, RawTransport

# ----- shared wire types/helpers (re-exported by serial_core for back-compat)

def decode_serial_bytes(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def format_hex_bytes(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)


@dataclass(slots=True)
class SerialEvent:
    """A display/log event on the monitor stream (TX echo, RX, status, …).

    Display-only: correlation never relies on these. ``source`` tags the
    originator ("" = user/terminal, "control_panel", "batch", "cli",
    "unsolicited") so the terminal can hide background-poll traffic by tag
    rather than by time-window.
    """

    kind: str
    message: str
    raw: bytes = b""
    source: str = ""
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).astimezone()
    )


# ----- transaction model ----------------------------------------------------

# Result statuses.
OK = "ok"
TIMEOUT = "timeout"
SEND_ERROR = "send_error"
CLOSED = "closed"
CANCELLED = "cancelled"

# Priorities (lower runs first). Interactive sends pre-empt queued polls.
INTERACTIVE = 0
NORMAL = 10

SOURCE_UNSOLICITED = "unsolicited"

# Granularity of the worker's blocking waits, so stop()/loss stay responsive.
WORKER_IDLE_TICK_S = 0.05
RX_WAIT_CHUNK_S = 0.05


class Matcher(Protocol):
    def find_complete(self, spool: bytes) -> int | None:
        """Return the number of leading bytes in ``spool`` that form one
        complete response, or ``None`` if not complete yet. The channel
        delivers ``spool[:n]`` as the response and keeps ``spool[n:]``."""


class LineMatcher:
    """First complete CR/LF-terminated non-blank line (default for SCPI)."""

    def find_complete(self, spool: bytes) -> int | None:
        i = 0
        n = len(spool)
        while i < n:
            j = i
            while j < n and spool[j] not in (0x0D, 0x0A):
                j += 1
            if j >= n:
                return None  # no terminator yet — keep collecting
            end = j + 1
            if spool[j] == 0x0D and end < n and spool[end] == 0x0A:
                end += 1  # consume the \r\n pair together
            if spool[i:j].strip():
                return end
            i = end  # blank line (CRLF echo artifact) — skip and continue
        return None


class RegexMatcher:
    """Complete once ``pattern`` matches the decoded window; consumes it all."""

    def __init__(self, pattern: "re.Pattern[str] | str") -> None:
        self._pattern = re.compile(pattern) if isinstance(pattern, str) else pattern

    def find_complete(self, spool: bytes) -> int | None:
        if self._pattern.search(decode_serial_bytes(spool)) is not None:
            return len(spool)
        return None


class SubstringMatcher:
    """Complete once ``needle`` appears in the decoded window (batch/CLI EXPECT)."""

    def __init__(self, needle: str) -> None:
        self._needle = needle

    def find_complete(self, spool: bytes) -> int | None:
        if self._needle and self._needle in decode_serial_bytes(spool):
            return len(spool)
        return None


class DatagramMatcher:
    """One whole datagram is one response (default on datagram transports).

    A datagram transport's ``read()`` returns exactly one datagram per call and
    the reader notifies once per non-empty read, so the first non-empty spool
    observation inside a transaction window is normally one datagram —
    terminator or not, which is the point: UDP devices often reply without
    CR/LF and ``LineMatcher`` would sit there until the timeout.

    Accepted v1 caveat: two replies arriving back-to-back can be delivered as
    one response if the worker is not scheduled between the reader's two
    notifications. A request/response device sends one reply per request, and
    the window closes on the first one.
    """

    def find_complete(self, spool: bytes) -> int | None:
        return len(spool) if spool else None


class CountMatcher:
    """Complete once at least ``count`` bytes have arrived (binary protocols)."""

    def __init__(self, count: int) -> None:
        self._count = max(int(count), 0)

    def find_complete(self, spool: bytes) -> int | None:
        return self._count if len(spool) >= self._count else None


@dataclass(frozen=True, slots=True)
class TxResult:
    status: str
    response: bytes = b""
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == OK

    def text(self) -> str:
        return decode_serial_bytes(self.response)


@dataclass(slots=True)
class Transaction:
    payload: bytes
    matcher: Matcher | None
    timeout: float
    pre_read_delay: float
    priority: int
    source: str
    display: str
    future: "Future[TxResult]" = field(default_factory=Future)


# ----- monitor fan-out ------------------------------------------------------

class MonitorHub:
    """Display-only fan-out of :class:`SerialEvent`. Lives on the owning
    client so subscriptions survive a channel rebuild across reconnects."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._subscribers: list[Queue[SerialEvent]] = []

    def subscribe(self) -> Queue[SerialEvent]:
        q: Queue[SerialEvent] = Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, queue: Queue[SerialEvent]) -> None:
        with self._lock:
            self._subscribers = [s for s in self._subscribers if s is not queue]

    def publish(self, event: SerialEvent) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(event)


# ----- the channel ----------------------------------------------------------

class PortChannel:
    def __init__(
        self,
        raw: RawTransport,
        *,
        hub: MonitorHub | None = None,
        on_connection_lost: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        default_matcher: Callable[[], Matcher] | None = None,
    ) -> None:
        self._raw = raw
        self._hub = hub or MonitorHub()
        self._on_connection_lost = on_connection_lost
        self._clock = clock
        # A factory, not an instance: callers get a fresh matcher per request
        # so a future stateful matcher cannot leak across transactions.
        self._default_matcher: Callable[[], Matcher] = default_matcher or LineMatcher

        self._queue: "PriorityQueue[tuple[int, int, Transaction]]" = PriorityQueue()
        self._seq = count()

        self._spool = bytearray()
        self._spool_cv = Condition(Lock())
        self._current_source = SOURCE_UNSOLICITED

        self._stop = Event()
        self._closed = Event()
        self._loss_lock = Lock()
        self._loss_emitted = False
        self._inflight: Transaction | None = None
        self._reader: Thread | None = None
        self._worker: Thread | None = None

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        self._stop.clear()
        self._closed.clear()
        with self._loss_lock:
            self._loss_emitted = False
        self._reader = Thread(target=self._reader_loop, daemon=True, name="channel-reader")
        self._worker = Thread(target=self._worker_loop, daemon=True, name="channel-worker")
        self._reader.start()
        self._worker.start()

    def stop(self, timeout: float = 1.5) -> None:
        self._stop.set()
        self._closed.set()
        with self._spool_cv:
            self._spool_cv.notify_all()
        try:
            self._raw.cancel_read()
        except Exception:
            pass
        for thread in (self._worker, self._reader):
            if thread and thread.is_alive() and thread is not current_thread():
                thread.join(timeout=timeout)
        self._worker = None
        self._reader = None
        self._fail_queued(CANCELLED)
        try:
            self._raw.close()
        except Exception:
            pass

    @property
    def is_open(self) -> bool:
        return not self._closed.is_set() and self._raw.is_open

    def default_matcher(self) -> Matcher:
        """A fresh matcher suited to this channel's transport, for callers that
        have no explicit framing rule of their own (see
        ``control_panel_engine._matcher_for``)."""
        return self._default_matcher()

    # -- monitor ------------------------------------------------------------

    def subscribe_monitor(self) -> Queue[SerialEvent]:
        return self._hub.subscribe()

    def unsubscribe_monitor(self, queue: Queue[SerialEvent]) -> None:
        self._hub.unsubscribe(queue)

    def publish_status(self, kind: str, message: str) -> None:
        """Let the owning client surface connection/status/error lines on the
        same monitor stream consumers already read."""
        self._publish(kind, message)

    # -- submission ---------------------------------------------------------

    def query(
        self,
        payload: bytes,
        *,
        matcher: Matcher,
        timeout: float,
        source: str = "",
        display: str = "",
        priority: int = NORMAL,
        pre_read_delay: float = 0.0,
    ) -> "Future[TxResult]":
        return self._submit(
            Transaction(
                payload=payload,
                matcher=matcher,
                timeout=max(timeout, 0.0),
                pre_read_delay=max(pre_read_delay, 0.0),
                priority=priority,
                source=source,
                display=display,
            )
        )

    def write(
        self,
        payload: bytes,
        *,
        source: str = "",
        display: str = "",
        priority: int = NORMAL,
        quiet_read: float = 0.0,
    ) -> "Future[TxResult]":
        # matcher=None means "no required reply": with quiet_read>0 we still
        # open a read window (so an immediate reply is captured in-order and
        # not eaten by the next transaction), ending in OK when it elapses.
        return self._submit(
            Transaction(
                payload=payload,
                matcher=None,
                timeout=max(quiet_read, 0.0),
                pre_read_delay=0.0,
                priority=priority,
                source=source,
                display=display,
            )
        )

    def _submit(self, txn: Transaction) -> "Future[TxResult]":
        if self._closed.is_set() or self._stop.is_set():
            txn.future.set_result(TxResult(status=CLOSED, error="channel is closed"))
            return txn.future
        self._queue.put((txn.priority, next(self._seq), txn))
        return txn.future

    # -- reader thread ------------------------------------------------------

    def _reader_loop(self) -> None:
        while not self._closed.is_set():
            try:
                data = self._raw.read()
            except ConnectionLost as exc:
                if self._closed.is_set():
                    return
                self._on_loss(str(exc))
                return
            except Exception as exc:  # defensive: never let the reader die silently
                if self._closed.is_set():
                    return
                self._on_loss(f"read error: {exc}")
                return
            if data:
                self._publish("rx", decode_serial_bytes(data), raw=data, source=self._current_source)
                with self._spool_cv:
                    self._spool += data
                    self._spool_cv.notify_all()

    # -- worker thread ------------------------------------------------------

    def _worker_loop(self) -> None:
        while not self._stop.is_set() and not self._closed.is_set():
            try:
                _, _, txn = self._queue.get(timeout=WORKER_IDLE_TICK_S)
            except Empty:
                self._drain_idle()
                continue
            self._inflight = txn
            alive = self._run_transaction(txn)
            self._inflight = None
            if not alive:
                return

    def _drain_idle(self) -> None:
        # Bytes that arrive while no transaction is in flight are unsolicited;
        # the reader already published them — just keep the spool bounded.
        with self._spool_cv:
            self._spool.clear()

    def _run_transaction(self, txn: Transaction) -> bool:
        """Run one transaction to completion. Returns False if the connection
        was lost (worker should exit)."""
        # 1. Discard stale inbound: anything in the spool arrived before our
        #    write, so by definition it is not our reply. (Already shown by
        #    the reader under its prior source.)
        with self._spool_cv:
            self._spool.clear()
        self._current_source = txn.source

        # 2. Write.
        started = self._clock()
        try:
            self._raw.write(txn.payload)
        except ConnectionLost as exc:
            self._current_source = SOURCE_UNSOLICITED
            self._resolve(
                txn,
                TxResult(status=CLOSED, error=str(exc), started_at=started, finished_at=self._clock()),
            )
            self._on_loss(str(exc))
            return False
        self._publish("tx", txn.display, source=txn.source)

        # 3. Fire-and-forget (no matcher, no quiet window).
        if txn.matcher is None and txn.timeout <= 0:
            self._current_source = SOURCE_UNSOLICITED
            self._resolve(txn, TxResult(status=OK, started_at=started, finished_at=self._clock()))
            return True

        # 4. Optional pre-read delay (post-write readback).
        if txn.pre_read_delay > 0 and not self._interruptible_sleep(txn.pre_read_delay):
            self._current_source = SOURCE_UNSOLICITED
            self._resolve(txn, TxResult(status=CANCELLED, started_at=started, finished_at=self._clock()))
            return not self._closed.is_set()

        # 5. Collect the reply window.
        deadline = self._clock() + txn.timeout
        response = b""
        status = TIMEOUT
        with self._spool_cv:
            while True:
                if self._closed.is_set():
                    status = CANCELLED if self._stop.is_set() else CLOSED
                    break
                if txn.matcher is not None:
                    offset = txn.matcher.find_complete(bytes(self._spool))
                    if offset is not None:
                        response = bytes(self._spool[:offset])
                        del self._spool[:offset]
                        status = OK
                        break
                remaining = deadline - self._clock()
                if remaining <= 0:
                    if txn.matcher is None:
                        # Quiet window elapsed normally — success, return
                        # whatever (if anything) the device volunteered.
                        response = bytes(self._spool)
                        self._spool.clear()
                        status = OK
                    else:
                        status = TIMEOUT
                    break
                self._spool_cv.wait(min(remaining, RX_WAIT_CHUNK_S))

        self._current_source = SOURCE_UNSOLICITED
        self._resolve(
            txn,
            TxResult(status=status, response=response, started_at=started, finished_at=self._clock()),
        )
        return status != CLOSED

    def _interruptible_sleep(self, duration: float) -> bool:
        deadline = self._clock() + duration
        while not self._stop.is_set() and not self._closed.is_set():
            remaining = deadline - self._clock()
            if remaining <= 0:
                return True
            time.sleep(min(remaining, RX_WAIT_CHUNK_S))
        return False

    # -- helpers ------------------------------------------------------------

    def _publish(self, kind: str, message: str, *, raw: bytes = b"", source: str = "") -> None:
        self._hub.publish(SerialEvent(kind=kind, message=message, raw=raw, source=source))

    @staticmethod
    def _resolve(txn: Transaction, result: TxResult) -> None:
        try:
            txn.future.set_result(result)
        except Exception:
            pass  # already resolved (e.g. cancelled during stop)

    def _fail_queued(self, status: str) -> None:
        while True:
            try:
                _, _, txn = self._queue.get_nowait()
            except Empty:
                return
            self._resolve(
                txn,
                TxResult(status=status, error="channel is closed" if status == CLOSED else ""),
            )

    def _on_loss(self, reason: str) -> None:
        with self._loss_lock:
            first = not self._loss_emitted
            self._loss_emitted = True
        self._closed.set()
        with self._spool_cv:
            self._spool_cv.notify_all()
        if not first:
            return
        self._publish("error", f"Connection lost: {reason}")
        self._publish("connection", "disconnected")
        self._fail_queued(CLOSED)
        if self._on_connection_lost is not None:
            try:
                self._on_connection_lost(reason)
            except Exception:
                pass
