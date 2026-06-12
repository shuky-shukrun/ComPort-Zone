"""Polling engine for dashboard entries.

Two cooperating pieces, mirroring the proven BatchRunner topology
(thread + ``Queue[SerialEvent]`` subscriber + GUI timer drain):

- :class:`DashboardPollScheduler` — pure scheduling policy. Lives on the
  GUI thread inside a dashboard tab, driven by a ~100 ms tick. Decides
  *when* each entry is due, enforces one-outstanding-per-entry, and
  models pausing as a set of reasons (user/connection/unbound/batch).
  No Qt, no threads, injectable clock — deterministic under test.

- :class:`SessionPollDispatcher` — per-bound-session worker thread that
  executes poll transactions strictly one at a time (FIFO). It owns its
  own RX subscriber queue from ``transport.subscribe_events()`` so it
  never races the terminal's own event drain, and it is the *only* place
  dashboard traffic touches the transport (NFR-1). All dashboards bound
  to one session share one dispatcher (via the run coordinator), which
  is what serializes their commands on the wire (FR-21).

Requirements: docs/dashboard-view-requirements.md (FR-20..FR-23, FR-27,
NFR-1..NFR-5).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

from .batch import parse_hex_payload
from .dashboard_models import DashboardEntry
from .dashboard_parse import (
    CompiledParseRule,
    ParseOutcome,
    append_to_window,
    parse_response,
)
from .serial_core import SerialEvent

PAUSE_REASONS = ("user", "connection", "unbound", "batch")

POLL_OK = "ok"
POLL_TIMEOUT = "timeout"
POLL_SEND_ERROR = "send_error"
POLL_CANCELLED = "cancelled"

# Spacing applied to freshly scheduled entries so a connect/restore never
# fires every entry's first poll in the same tick (thundering herd).
RESUME_STAGGER_S = 0.025
# Upper bound on queued-but-not-executed transactions per session. With
# one-outstanding-per-entry the queue depth is naturally <= entry count;
# the cap is a backstop, not a tuning knob (NFR-3).
REQUEST_QUEUE_LIMIT = 64
# Chunked RX waits keep stop() responsive while a transaction is open.
RX_POLL_CHUNK_S = 0.05
# Idle wait on the request queue; doubles as the cadence for discarding
# unsolicited RX so the subscriber queue stays bounded between polls.
IDLE_DRAIN_TIMEOUT_S = 0.1

DISPATCHER_THREAD_NAME = "dashboard-dispatch"

# TX origin tag for dashboard sends (SerialEvent.source) — lets the bound
# terminal recognize and hide background-poll traffic.
DASHBOARD_TX_SOURCE = "dashboard"

Clock = Callable[[], float]


class PollTrafficJournal:
    """Wall-clock windows of this session's poll transactions.

    The bound terminal consults it to keep background-poll RX out of its
    transcript: an RX event whose timestamp falls inside an open window
    (plus a short grace for late reply fragments) belongs to a dashboard
    poll, not to the user. TX needs no window — dashboard TX events carry
    ``source == DASHBOARD_TX_SOURCE``. Thread-safe: the dispatcher thread
    writes, the GUI thread reads.
    """

    GRACE_S = 0.35
    _KEEP_CLOSED = 16

    def __init__(self) -> None:
        self._lock = Lock()
        self._windows: list[list[datetime | None]] = []

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc).astimezone()

    def open_window(self) -> None:
        with self._lock:
            self._windows.append([self._now(), None])
            if len(self._windows) > self._KEEP_CLOSED:
                self._windows = self._windows[-self._KEEP_CLOSED:]

    def close_window(self) -> None:
        with self._lock:
            for window in reversed(self._windows):
                if window[1] is None:
                    window[1] = self._now()
                    return

    def covers(self, timestamp: datetime) -> bool:
        """True when ``timestamp`` falls inside any poll window (open
        windows extend to now; closed ones keep a grace tail)."""
        with self._lock:
            for start, end in self._windows:
                if start is None or timestamp < start:
                    continue
                if end is None:
                    return True
                if (timestamp - end).total_seconds() <= self.GRACE_S:
                    return True
        return False


@dataclass(slots=True)
class PollRequest:
    """One scheduled transaction, handed from a tab to its dispatcher."""

    dashboard_id: str
    entry: DashboardEntry
    compiled: CompiledParseRule
    result_queue: Queue["PollResult"]
    submitted_at: float = 0.0


@dataclass(slots=True)
class PollResult:
    """Outcome of one transaction, delivered back to the owning tab."""

    dashboard_id: str
    entry_id: str
    status: str
    outcome: ParseOutcome | None = None
    raw_window: str = ""
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0


@dataclass(slots=True)
class ControlRequest:
    """A control-tile send (v2, FR-60): fire the command, no RX window.

    Flows through the same per-session FIFO as poll requests, so control
    sends never interleave with dashboard polls on the wire.
    """

    dashboard_id: str
    entry_id: str
    command: str
    send_mode: str = "Text"
    line_ending_override: str = ""
    result_queue: Queue = None  # type: ignore[assignment]  # tab's shared queue
    submitted_at: float = 0.0


@dataclass(slots=True)
class ControlResult:
    """Ack for one control send (ok / send_error / cancelled)."""

    dashboard_id: str
    entry_id: str
    status: str
    error: str = ""
    finished_at: float = 0.0


@dataclass(slots=True)
class _EntrySlot:
    entry: DashboardEntry
    next_due: float
    in_flight: bool = False


class DashboardPollScheduler:
    """Pure due-time bookkeeping for one dashboard tab.

    Fixed-delay semantics: an entry's next poll is scheduled
    ``interval`` after :meth:`complete` is called, so slow devices
    degrade the effective rate instead of building a backlog (FR-20).
    """

    def __init__(self, *, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._slots: dict[str, _EntrySlot] = {}
        self._paused: set[str] = set()

    @property
    def paused_reasons(self) -> frozenset[str]:
        return frozenset(self._paused)

    @property
    def is_paused(self) -> bool:
        return bool(self._paused)

    def configure(self, entries: Iterable[DashboardEntry]) -> None:
        """Adopt the current entry list.

        Entries whose interval and poll mode are unchanged keep their due
        time and in-flight mark; changed or new entries are (re)staggered
        from now. ``on_connect`` entries are never time-due — the tab arms
        them via :meth:`trigger_now` on connect edges (FR-52). Removed
        entries are dropped.
        """
        now = self._clock()
        slots: dict[str, _EntrySlot] = {}
        fresh = 0
        for entry in entries:
            existing = self._slots.get(entry.id)
            unchanged = (
                existing is not None
                and existing.entry.interval_ms == entry.interval_ms
                and existing.entry.poll_mode == entry.poll_mode
            )
            if unchanged:
                slots[entry.id] = _EntrySlot(entry, existing.next_due, existing.in_flight)
                continue
            in_flight = existing.in_flight if existing is not None else False
            if entry.poll_mode == "on_connect":
                next_due = math.inf
            else:
                next_due = now + fresh * RESUME_STAGGER_S
                fresh += 1
            slots[entry.id] = _EntrySlot(entry, next_due, in_flight)
        self._slots = slots

    def set_paused(self, reason: str, paused: bool) -> None:
        """Add or clear one pause reason; polling runs only when none are
        active. Clearing the last reason re-staggers overdue entries so
        resume does not burst."""
        if reason not in PAUSE_REASONS:
            raise ValueError(f"Unknown pause reason: {reason!r}")
        was_paused = bool(self._paused)
        if paused:
            self._paused.add(reason)
        else:
            self._paused.discard(reason)
        if was_paused and not self._paused:
            self._restagger_overdue()

    def _restagger_overdue(self) -> None:
        self.restagger(self._slots.keys())

    def restagger(self, entry_ids: Iterable[str]) -> None:
        """Re-space the given entries' overdue polls at the resume stagger
        so a gate opening (reconnect, batch end) never bursts (FR-55)."""
        now = self._clock()
        index = 0
        for entry_id in entry_ids:
            slot = self._slots.get(entry_id)
            if slot is None or slot.in_flight:
                continue
            if slot.next_due < now:
                slot.next_due = now + index * RESUME_STAGGER_S
                index += 1

    def trigger_now(self, entry_id: str, *, delay_s: float = 0.0) -> bool:
        """Arm an immediate (or slightly delayed) poll for an entry —
        connect-edge triggers for ``on_connect`` entries and the Poll Now
        action for any entry (FR-52/FR-53). No-op while in flight."""
        slot = self._slots.get(entry_id)
        if slot is None or slot.in_flight or not slot.entry.enabled:
            return False
        slot.next_due = self._clock() + max(0.0, delay_s)
        return True

    def collect_due(self) -> list[DashboardEntry]:
        """Entries due now, marked in-flight so they are not re-issued
        until :meth:`complete`/:meth:`skip`."""
        if self._paused:
            return []
        now = self._clock()
        due: list[DashboardEntry] = []
        for slot in self._slots.values():
            if slot.entry.enabled and not slot.in_flight and slot.next_due <= now:
                slot.in_flight = True
                due.append(slot.entry)
        return due

    def complete(self, entry_id: str) -> None:
        """A transaction finished (any status): schedule the next poll
        ``interval`` from now (fixed delay). ``on_connect`` entries re-arm
        to "never" until the next connect edge or Poll Now."""
        slot = self._slots.get(entry_id)
        if slot is None:
            return
        slot.in_flight = False
        if slot.entry.poll_mode == "on_connect":
            slot.next_due = math.inf
        else:
            slot.next_due = self._clock() + slot.entry.interval_ms / 1000

    def skip(self, entry_id: str) -> None:
        """A submit failed before executing: clear in-flight without
        rescheduling, so the entry retries on the next tick."""
        slot = self._slots.get(entry_id)
        if slot is None:
            return
        slot.in_flight = False

    def release_all_in_flight(self) -> None:
        """Forget outstanding transactions (e.g. after switching to a new
        dispatcher on rebind) so entries are not wedged waiting for
        results that will never arrive."""
        for slot in self._slots.values():
            slot.in_flight = False


class SessionPollDispatcher:
    """Serializes dashboard poll transactions on one terminal session.

    ``transport`` is any :class:`~ComPort_Zone.transports.TransportAdapter`
    (duck-typed: ``send_text``/``send_bytes``/``subscribe_events``/
    ``unsubscribe_events``).
    """

    def __init__(self, *, transport, clock: Clock = time.monotonic) -> None:
        self._transport = transport
        self._clock = clock
        self._requests: Queue[PollRequest | ControlRequest] = Queue(maxsize=REQUEST_QUEUE_LIMIT)
        self._rx_queue: Queue[SerialEvent] | None = None
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._lock = Lock()
        self._cancelled: set[str] = set()
        # Shared with the bound terminal so it can filter poll traffic out
        # of its transcript (the coordinator wires it up on bind).
        self.traffic_journal = PollTrafficJournal()

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event = Event()
        with self._lock:
            self._cancelled.clear()
        self._rx_queue = self._transport.subscribe_events()
        self._thread = Thread(target=self._run, daemon=True, name=DISPATCHER_THREAD_NAME)
        self._thread.start()

    def submit(self, request: PollRequest) -> bool:
        """Queue a transaction; False when stopped or the queue is full
        (caller should ``skip`` the entry and retry next tick)."""
        return self._enqueue(request)

    def submit_control(self, request: ControlRequest) -> bool:
        """Queue a control send (FR-60). Shares the poll FIFO, so it can
        never interleave with this session's dashboard traffic."""
        return self._enqueue(request)

    def _enqueue(self, request: "PollRequest | ControlRequest") -> bool:
        if not self.is_running or self._stop_event.is_set():
            return False
        request.submitted_at = self._clock()
        try:
            self._requests.put_nowait(request)
        except Full:
            return False
        return True

    def cancel_dashboard(self, dashboard_id: str) -> None:
        """Drop queued (not yet executing) requests of one dashboard;
        each is answered with a "cancelled" result."""
        with self._lock:
            self._cancelled.add(dashboard_id)

    def stop(self, timeout: float = 1.5) -> None:
        """Stop the worker, answer queued requests with "cancelled", and
        unsubscribe from the transport's events."""
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        self._flush_requests_cancelled()
        rx_queue = self._rx_queue
        self._rx_queue = None
        if rx_queue is not None:
            try:
                self._transport.unsubscribe_events(rx_queue)
            except Exception:
                pass

    def _is_cancelled(self, dashboard_id: str) -> bool:
        with self._lock:
            return dashboard_id in self._cancelled

    def _flush_requests_cancelled(self) -> None:
        while True:
            try:
                request = self._requests.get_nowait()
            except Empty:
                return
            self._answer_cancelled(request)

    def _answer_cancelled(self, request: "PollRequest | ControlRequest") -> None:
        now = self._clock()
        if isinstance(request, ControlRequest):
            request.result_queue.put(
                ControlResult(
                    dashboard_id=request.dashboard_id,
                    entry_id=request.entry_id,
                    status=POLL_CANCELLED,
                    finished_at=now,
                )
            )
            return
        request.result_queue.put(
            PollResult(
                dashboard_id=request.dashboard_id,
                entry_id=request.entry.id,
                status=POLL_CANCELLED,
                started_at=now,
                finished_at=now,
            )
        )

    def _run(self) -> None:
        rx_queue = self._rx_queue
        if rx_queue is None:
            return
        while not self._stop_event.is_set():
            try:
                request = self._requests.get(timeout=IDLE_DRAIN_TIMEOUT_S)
            except Empty:
                self._drain(rx_queue)
                continue
            if self._is_cancelled(request.dashboard_id):
                self._answer_cancelled(request)
                continue
            if isinstance(request, ControlRequest):
                request.result_queue.put(self._execute_control(request))
                continue
            result = self._execute_transaction(request, rx_queue)
            request.result_queue.put(result)

    def _execute_control(self, request: ControlRequest) -> ControlResult:
        """Fire one control command: send only, no RX collection. The
        journal window covers the send so the device's ack/echo stays out
        of the bound terminal's transcript (FR-60)."""
        self.traffic_journal.open_window()
        try:
            try:
                if request.send_mode == "Hex Bytes":
                    self._transport.send_bytes(
                        parse_hex_payload(request.command), source=DASHBOARD_TX_SOURCE
                    )
                else:
                    self._transport.send_text(
                        request.command,
                        request.line_ending_override or None,
                        source=DASHBOARD_TX_SOURCE,
                    )
            except Exception as exc:
                return ControlResult(
                    dashboard_id=request.dashboard_id,
                    entry_id=request.entry_id,
                    status=POLL_SEND_ERROR,
                    error=str(exc),
                    finished_at=self._clock(),
                )
            return ControlResult(
                dashboard_id=request.dashboard_id,
                entry_id=request.entry_id,
                status=POLL_OK,
                finished_at=self._clock(),
            )
        finally:
            self.traffic_journal.close_window()

    @staticmethod
    def _drain(rx_queue: Queue[SerialEvent]) -> None:
        while True:
            try:
                rx_queue.get_nowait()
            except Empty:
                return

    def _execute_transaction(
        self, request: PollRequest, rx_queue: Queue[SerialEvent]
    ) -> PollResult:
        """One poll: discard stale RX, send, collect RX until the parse
        rule decides or the entry timeout elapses. Factored out of the
        thread loop so tests can drive it synchronously."""
        entry = request.entry
        started = self._clock()
        deadline = started + entry.timeout_ms / 1000
        self._drain(rx_queue)
        self.traffic_journal.open_window()
        try:
            try:
                if entry.send_mode == "Hex Bytes":
                    self._transport.send_bytes(
                        parse_hex_payload(entry.command), source=DASHBOARD_TX_SOURCE
                    )
                else:
                    self._transport.send_text(
                        entry.command,
                        entry.line_ending_override or None,
                        source=DASHBOARD_TX_SOURCE,
                    )
            except Exception as exc:
                now = self._clock()
                return PollResult(
                    dashboard_id=request.dashboard_id,
                    entry_id=entry.id,
                    status=POLL_SEND_ERROR,
                    error=str(exc),
                    started_at=started,
                    finished_at=now,
                )
            window = ""
            while True:
                if self._stop_event.is_set():
                    return PollResult(
                        dashboard_id=request.dashboard_id,
                        entry_id=entry.id,
                        status=POLL_CANCELLED,
                        raw_window=window,
                        started_at=started,
                        finished_at=self._clock(),
                    )
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return PollResult(
                        dashboard_id=request.dashboard_id,
                        entry_id=entry.id,
                        status=POLL_TIMEOUT,
                        raw_window=window,
                        started_at=started,
                        finished_at=self._clock(),
                    )
                try:
                    event = rx_queue.get(timeout=min(remaining, RX_POLL_CHUNK_S))
                except Empty:
                    continue
                if event.kind != "rx":
                    continue
                window = append_to_window(window, event.message)
                outcome = parse_response(request.compiled, window)
                if outcome is not None:
                    return PollResult(
                        dashboard_id=request.dashboard_id,
                        entry_id=entry.id,
                        status=POLL_OK,
                        outcome=outcome,
                        raw_window=window,
                        started_at=started,
                        finished_at=self._clock(),
                    )
        finally:
            self.traffic_journal.close_window()
