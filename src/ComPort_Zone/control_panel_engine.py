"""Polling engine for control_panel entries.

Two cooperating pieces, mirroring the proven BatchRunner topology
(thread + ``Queue[SerialEvent]`` subscriber + GUI timer drain):

- :class:`ControlPanelPollScheduler` — pure scheduling policy. Lives on the
  GUI thread inside a control_panel tab, driven by a ~100 ms tick. Decides
  *when* each entry is due, enforces one-outstanding-per-entry, and
  models pausing as a set of reasons (user/connection/unbound/batch).
  No Qt, no threads, injectable clock — deterministic under test.

- :class:`SessionPollDispatcher` — per-bound-session worker thread that
  submits poll transactions to the session's
  :class:`~ComPort_Zone.port_channel.PortChannel` one at a time (FIFO). The
  channel serializes the wire and correlates each reply to its request, so
  the dispatcher no longer owns an RX queue or races the terminal's drain.
  All control_panels bound to one session share one dispatcher (via the run
  coordinator), which orders their commands on the wire (FR-21).

Requirements: docs/control_panel-view-requirements.md (FR-20..FR-23, FR-27,
NFR-1..NFR-5).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

from .batch import parse_hex_payload
from .control_panel_models import ControlPanelEntry
from .control_panel_parse import (
    MAX_RX_WINDOW_CHARS,
    CompiledParseRule,
    ParseOutcome,
    parse_response,
)
from .port_channel import (
    CANCELLED,
    CLOSED,
    OK,
    TIMEOUT,
    RegexMatcher,
    decode_serial_bytes,
)

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
# Granularity for awaiting a transaction's result future, so stop() stays
# responsive while a poll is open and for the readback pre-delay sleep.
RX_POLL_CHUNK_S = 0.05
# Idle wait on the request queue; just bounds how fast the worker notices
# stop() / a newly submitted request.
IDLE_DRAIN_TIMEOUT_S = 0.1

DISPATCHER_THREAD_NAME = "control_panel-dispatch"

# TX origin tag for control_panel sends (SerialEvent.source) — lets the bound
# terminal recognize and hide background-poll traffic.
CONTROL_PANEL_TX_SOURCE = "control_panel"

Clock = Callable[[], float]


@dataclass(slots=True)
class PollRequest:
    """One scheduled transaction, handed from a tab to its dispatcher."""

    control_panel_id: str
    entry: ControlPanelEntry
    compiled: CompiledParseRule
    result_queue: Queue["PollResult"]
    submitted_at: float = 0.0


@dataclass(slots=True)
class PollResult:
    """Outcome of one transaction, delivered back to the owning tab."""

    control_panel_id: str
    entry_id: str
    status: str
    outcome: ParseOutcome | None = None
    raw_window: str = ""
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0


@dataclass(slots=True)
class ReadbackRequest:
    """A readback transaction for a writing tile.

    The entry may be a real polled entry ("follow another tile") or a
    synthetic readback entry built from the writing tile's own readback
    command. owner_entry_id is the writing tile that requested it.
    """

    control_panel_id: str
    owner_entry_id: str
    entry: ControlPanelEntry
    compiled: CompiledParseRule
    result_queue: Queue["ReadbackResult"]
    delay_ms: int = 0
    seed_setpoint_value: bool = False
    submitted_at: float = 0.0


@dataclass(slots=True)
class ReadbackResult:
    """Outcome of one readback transaction."""

    control_panel_id: str
    owner_entry_id: str
    entry_id: str
    status: str
    outcome: ParseOutcome | None = None
    raw_window: str = ""
    error: str = ""
    seed_setpoint_value: bool = False
    started_at: float = 0.0
    finished_at: float = 0.0


@dataclass(slots=True)
class ControlRequest:
    """A control-tile send (v2, FR-60): fire the command, no RX window.

    Flows through the same per-session FIFO as poll requests, so control
    sends never interleave with control_panel polls on the wire.
    """

    control_panel_id: str
    entry_id: str
    command: str
    send_mode: str = "Text"
    line_ending_override: str = ""
    readback: ReadbackRequest | None = None
    result_queue: Queue = None  # type: ignore[assignment]  # tab's shared queue
    submitted_at: float = 0.0


@dataclass(slots=True)
class ControlResult:
    """Ack for one control send (ok / send_error / cancelled)."""

    control_panel_id: str
    entry_id: str
    status: str
    error: str = ""
    finished_at: float = 0.0


@dataclass(slots=True)
class _EntrySlot:
    entry: ControlPanelEntry
    next_due: float
    in_flight: bool = False


class ControlPanelPollScheduler:
    """Pure due-time bookkeeping for one control_panel tab.

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

    def configure(self, entries: Iterable[ControlPanelEntry]) -> None:
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

    def collect_due(self) -> list[ControlPanelEntry]:
        """Entries due now, marked in-flight so they are not re-issued
        until :meth:`complete`/:meth:`skip`."""
        if self._paused:
            return []
        now = self._clock()
        due: list[ControlPanelEntry] = []
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
    """Serializes control_panel transactions on one terminal session.

    Each poll/control/readback is submitted to the session's
    :class:`~ComPort_Zone.port_channel.PortChannel` as a single transaction
    (``query``/``send``) at NORMAL priority. The channel guarantees one
    request on the wire at a time and correlates each reply to its request,
    so this class no longer owns an RX subscriber, a stale-RX drain, a
    wall-clock filter, or a traffic journal — all of that collapsed into the
    channel. A manual terminal send pre-empts queued polls via the channel's
    INTERACTIVE priority, but never interrupts a transaction mid-wire (FR-21).

    ``transport`` is any :class:`~ComPort_Zone.transports.TransportAdapter`
    (duck-typed: ``send_text``/``send_bytes``/``query_text``/``query_bytes``).
    """

    def __init__(self, *, transport, clock: Clock = time.monotonic) -> None:
        self._transport = transport
        self._clock = clock
        self._requests: Queue[PollRequest | ReadbackRequest | ControlRequest] = Queue(
            maxsize=REQUEST_QUEUE_LIMIT
        )
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._lock = Lock()
        self._cancelled: set[str] = set()

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
        self._thread = Thread(target=self._run, daemon=True, name=DISPATCHER_THREAD_NAME)
        self._thread.start()

    def submit(self, request: PollRequest) -> bool:
        """Queue a transaction; False when stopped or the queue is full
        (caller should ``skip`` the entry and retry next tick)."""
        return self._enqueue(request)

    def submit_control(self, request: ControlRequest) -> bool:
        """Queue a control send (FR-60). Shares the poll FIFO, so it can
        never interleave with this session's control_panel traffic."""
        return self._enqueue(request)

    def submit_readback(self, request: ReadbackRequest) -> bool:
        """Queue a readback transaction. Used for connect-time and periodic
        readbacks; post-write readbacks can be attached to ControlRequest
        to keep them adjacent to the write."""
        return self._enqueue(request)

    def _enqueue(self, request: "PollRequest | ReadbackRequest | ControlRequest") -> bool:
        if not self.is_running or self._stop_event.is_set():
            return False
        request.submitted_at = self._clock()
        try:
            self._requests.put_nowait(request)
        except Full:
            return False
        return True

    def cancel_control_panel(self, control_panel_id: str) -> None:
        """Drop queued (not yet executing) requests of one control_panel;
        each is answered with a "cancelled" result."""
        with self._lock:
            self._cancelled.add(control_panel_id)

    def stop(self, timeout: float = 1.5) -> None:
        """Stop the worker and answer queued requests with "cancelled"."""
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        self._flush_requests_cancelled()

    def _is_cancelled(self, control_panel_id: str) -> bool:
        with self._lock:
            return control_panel_id in self._cancelled

    def _flush_requests_cancelled(self) -> None:
        while True:
            try:
                request = self._requests.get_nowait()
            except Empty:
                return
            self._answer_cancelled(request)

    def _answer_cancelled(self, request: "PollRequest | ReadbackRequest | ControlRequest") -> None:
        now = self._clock()
        if isinstance(request, ControlRequest):
            request.result_queue.put(
                ControlResult(
                    control_panel_id=request.control_panel_id,
                    entry_id=request.entry_id,
                    status=POLL_CANCELLED,
                    finished_at=now,
                )
            )
            return
        if isinstance(request, ReadbackRequest):
            request.result_queue.put(
                ReadbackResult(
                    control_panel_id=request.control_panel_id,
                    owner_entry_id=request.owner_entry_id,
                    entry_id=request.entry.id,
                    status=POLL_CANCELLED,
                    seed_setpoint_value=request.seed_setpoint_value,
                    started_at=now,
                    finished_at=now,
                )
            )
            return
        request.result_queue.put(
            PollResult(
                control_panel_id=request.control_panel_id,
                entry_id=request.entry.id,
                status=POLL_CANCELLED,
                started_at=now,
                finished_at=now,
            )
        )

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                request = self._requests.get(timeout=IDLE_DRAIN_TIMEOUT_S)
            except Empty:
                continue
            if self._is_cancelled(request.control_panel_id):
                self._answer_cancelled(request)
                continue
            if isinstance(request, ControlRequest):
                request.result_queue.put(self._execute_control(request))
                continue
            if isinstance(request, ReadbackRequest):
                request.result_queue.put(self._execute_readback(request))
                continue
            result = self._execute_transaction(request)
            request.result_queue.put(result)

    def _execute_control(self, request: ControlRequest) -> ControlResult:
        """Fire one control command (fire-and-forget). An inline readback runs
        as a follow-up query after an optional delay — each is its own channel
        transaction, so the readback's reply correlates to its own READ command
        rather than the control write's echo. Both are submitted back-to-back by
        this one dispatcher thread, so this session's own traffic stays ordered.

        When a readback follows, the control send opens a quiet-read window equal
        to the readback's settle delay: it doubles as the settle AND consumes any
        ack/echo the SET produced, so the readback query reads its own reply."""
        readback = request.readback
        quiet_read = readback.delay_ms / 1000 if readback is not None else 0.0
        try:
            future = self._send(
                request.command,
                request.send_mode,
                request.line_ending_override,
                quiet_read=quiet_read,
            )
        except Exception as exc:
            if readback is not None:
                request.result_queue.put(self._cancelled_readback(readback, POLL_SEND_ERROR, str(exc)))
            return ControlResult(
                control_panel_id=request.control_panel_id,
                entry_id=request.entry_id,
                status=POLL_SEND_ERROR,
                error=str(exc),
                finished_at=self._clock(),
            )
        control_result = self._control_result_from_tx(request, self._await(future))
        if readback is None:
            return control_result
        if control_result.status != POLL_OK:
            request.result_queue.put(
                self._cancelled_readback(readback, control_result.status, control_result.error)
            )
            return control_result
        request.result_queue.put(self._execute_readback(readback, already_delayed=True))
        return control_result

    def _cancelled_readback(
        self, readback: ReadbackRequest, status: str, error: str = ""
    ) -> ReadbackResult:
        now = self._clock()
        return ReadbackResult(
            control_panel_id=readback.control_panel_id,
            owner_entry_id=readback.owner_entry_id,
            entry_id=readback.entry.id,
            status=status,
            error=error,
            seed_setpoint_value=readback.seed_setpoint_value,
            started_at=now,
            finished_at=now,
        )

    def _wait_delay(self, delay_ms: int) -> bool:
        """Sleep for a readback delay, waking early if the worker stops."""
        if delay_ms <= 0:
            return not self._stop_event.is_set()
        deadline = self._clock() + delay_ms / 1000
        while not self._stop_event.is_set():
            remaining = deadline - self._clock()
            if remaining <= 0:
                return True
            time.sleep(min(remaining, RX_POLL_CHUNK_S))
        return False

    def _execute_readback(
        self, request: ReadbackRequest, *, already_delayed: bool = False
    ) -> ReadbackResult:
        # Standalone (periodic/connect) readback: the inter-poll delay runs
        # off the wire here, unlike an inline readback whose delay is part of
        # the held transaction via pre_read_delay.
        if not already_delayed and not self._wait_delay(request.delay_ms):
            now = self._clock()
            return ReadbackResult(
                control_panel_id=request.control_panel_id,
                owner_entry_id=request.owner_entry_id,
                entry_id=request.entry.id,
                status=POLL_CANCELLED,
                seed_setpoint_value=request.seed_setpoint_value,
                started_at=now,
                finished_at=now,
            )
        try:
            future = self._query(
                request.entry.command,
                request.entry.send_mode,
                request.entry.line_ending_override,
                matcher=self._matcher_for(request.compiled),
                timeout=request.entry.timeout_ms / 1000,
            )
        except Exception as exc:
            now = self._clock()
            return ReadbackResult(
                control_panel_id=request.control_panel_id,
                owner_entry_id=request.owner_entry_id,
                entry_id=request.entry.id,
                status=POLL_SEND_ERROR,
                error=str(exc),
                seed_setpoint_value=request.seed_setpoint_value,
                started_at=now,
                finished_at=now,
            )
        return self._readback_result_from_tx(request, self._await(future))

    # -- channel plumbing ---------------------------------------------------

    def _matcher_for(self, compiled: CompiledParseRule):
        if compiled.rule.kind == "regex" and compiled.pattern is not None:
            return RegexMatcher(compiled.pattern)
        # No explicit rule: let the transport decide how a reply is framed —
        # a line for serial/TCP, a whole datagram for UDP.
        return self._transport.default_matcher()

    def _send(
        self,
        command: str,
        send_mode: str,
        line_ending_override: str,
        *,
        quiet_read: float = 0.0,
    ):
        if send_mode == "Hex Bytes":
            return self._transport.send_bytes(
                parse_hex_payload(command),
                source=CONTROL_PANEL_TX_SOURCE,
                quiet_read=quiet_read,
            )
        return self._transport.send_text(
            command,
            line_ending_override or None,
            source=CONTROL_PANEL_TX_SOURCE,
            quiet_read=quiet_read,
        )

    def _query(
        self,
        command: str,
        send_mode: str,
        line_ending_override: str,
        *,
        matcher,
        timeout: float,
        pre_read_delay: float = 0.0,
    ):
        if send_mode == "Hex Bytes":
            return self._transport.query_bytes(
                parse_hex_payload(command),
                matcher=matcher,
                timeout=timeout,
                source=CONTROL_PANEL_TX_SOURCE,
                pre_read_delay=pre_read_delay,
            )
        return self._transport.query_text(
            command,
            line_ending_override or None,
            matcher=matcher,
            timeout=timeout,
            source=CONTROL_PANEL_TX_SOURCE,
            pre_read_delay=pre_read_delay,
        )

    def _await(self, future):
        """Block until the channel resolves ``future`` (bounded by the query
        timeout) or the worker is stopped (returns None)."""
        while not self._stop_event.is_set():
            try:
                return future.result(timeout=RX_POLL_CHUNK_S)
            except FutureTimeout:
                continue
        return None

    def _interpret(self, compiled: CompiledParseRule, tx):
        """Map a finished TxResult to (poll-status, outcome, raw window)."""
        window = decode_serial_bytes(tx.response)
        # Bound regex input / memory on a flood (NFR-3); the meaningful reply
        # for line and regex rules is at the tail of the window.
        if len(window) > MAX_RX_WINDOW_CHARS:
            window = window[-MAX_RX_WINDOW_CHARS:]
        if tx.status == OK:
            outcome = parse_response(compiled, window)
            return (POLL_OK if outcome is not None else POLL_TIMEOUT, outcome, window)
        if tx.status == TIMEOUT:
            return (POLL_TIMEOUT, None, window)
        if tx.status == CANCELLED:
            return (POLL_CANCELLED, None, window)
        return (POLL_SEND_ERROR, None, window)  # CLOSED / send error

    def _poll_result_from_tx(self, request: "PollRequest | ReadbackRequest", tx) -> PollResult:
        entry = request.entry
        if tx is None:
            now = self._clock()
            return PollResult(
                control_panel_id=request.control_panel_id,
                entry_id=entry.id,
                status=POLL_CANCELLED,
                started_at=now,
                finished_at=now,
            )
        status, outcome, window = self._interpret(request.compiled, tx)
        return PollResult(
            control_panel_id=request.control_panel_id,
            entry_id=entry.id,
            status=status,
            outcome=outcome,
            raw_window=window,
            error=tx.error,
            started_at=tx.started_at,
            finished_at=tx.finished_at,
        )

    def _readback_result_from_tx(self, request: ReadbackRequest, tx) -> ReadbackResult:
        if tx is None:
            now = self._clock()
            return ReadbackResult(
                control_panel_id=request.control_panel_id,
                owner_entry_id=request.owner_entry_id,
                entry_id=request.entry.id,
                status=POLL_CANCELLED,
                seed_setpoint_value=request.seed_setpoint_value,
                started_at=now,
                finished_at=now,
            )
        status, outcome, window = self._interpret(request.compiled, tx)
        return ReadbackResult(
            control_panel_id=request.control_panel_id,
            owner_entry_id=request.owner_entry_id,
            entry_id=request.entry.id,
            status=status,
            outcome=outcome,
            raw_window=window,
            error=tx.error,
            seed_setpoint_value=request.seed_setpoint_value,
            started_at=tx.started_at,
            finished_at=tx.finished_at,
        )

    def _control_result_from_tx(self, request: ControlRequest, tx) -> ControlResult:
        now = self._clock()
        if tx is None:
            return ControlResult(
                control_panel_id=request.control_panel_id,
                entry_id=request.entry_id,
                status=POLL_CANCELLED,
                finished_at=now,
            )
        if tx.status == CLOSED:
            return ControlResult(
                control_panel_id=request.control_panel_id,
                entry_id=request.entry_id,
                status=POLL_SEND_ERROR,
                error=tx.error,
                finished_at=tx.finished_at or now,
            )
        if tx.status == CANCELLED:
            return ControlResult(
                control_panel_id=request.control_panel_id,
                entry_id=request.entry_id,
                status=POLL_CANCELLED,
                finished_at=tx.finished_at or now,
            )
        # OK or TIMEOUT: the write itself reached the wire.
        return ControlResult(
            control_panel_id=request.control_panel_id,
            entry_id=request.entry_id,
            status=POLL_OK,
            finished_at=tx.finished_at or now,
        )

    def _execute_transaction(self, request: "PollRequest | ReadbackRequest") -> PollResult:
        """One poll: submit a single query to the channel and map its result.

        The channel serializes the send + reply window and hands back exactly
        the bytes that arrived for this request, so there is no stale-RX drain,
        wall-clock filter, or wire lock here anymore — correlation is
        structural. Factored out so tests can drive it synchronously.
        """
        entry = request.entry
        try:
            future = self._query(
                entry.command,
                entry.send_mode,
                entry.line_ending_override,
                matcher=self._matcher_for(request.compiled),
                timeout=entry.timeout_ms / 1000,
            )
        except Exception as exc:
            now = self._clock()
            return PollResult(
                control_panel_id=request.control_panel_id,
                entry_id=entry.id,
                status=POLL_SEND_ERROR,
                error=str(exc),
                started_at=now,
                finished_at=now,
            )
        return self._poll_result_from_tx(request, self._await(future))
