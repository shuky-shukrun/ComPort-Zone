"""Synchronous command-file executor for the CLI.

The GUI uses :class:`ComPort_Zone.batch.BatchRunner`, a threaded runner
built around the GUI's pause/resume + connection-loss-recovery semantics.
The CLI has different needs:

* Sequential execution with deterministic exit-code mapping.
* No interactive pause/resume — Ctrl+C just stops.
* The caller (the ``run`` subcommand) wants a structured outcome it can
  translate into ``EXPECT_FAILED`` / ``PARSE_ERROR`` etc.

This module reuses every parser from :mod:`ComPort_Zone.batch` and only
re-implements the driving loop, keeping the SEND/HEX/WAIT/EXPECT
semantics exactly aligned with the GUI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from queue import Empty
from typing import Callable

from ..core.batch import (
    BatchParseError,
    BatchTemplateStep,
    RunSettings,
    parse_batch_line,
    parse_hex_payload,
    substitute_batch_parameters,
)
from ..core.serial_core import SerialEvent, decode_serial_bytes, format_hex_bytes
from ..core.transports import TransportAdapter


# Failure kinds emitted in :class:`RunOutcome`. Strings — not an enum — so
# the test assertions read naturally and so future kinds don't require an
# import-side schema change.
FAILURE_PARSE = "parse"
FAILURE_PARAM = "param"
FAILURE_EXPECT = "expect"
FAILURE_SEND = "send"
FAILURE_INTERRUPTED = "interrupted"


@dataclass(slots=True)
class RunOutcome:
    success: bool
    failure_kind: str | None = None
    failure_line: int | None = None
    failure_message: str = ""
    steps_run: int = 0
    expect_failures: int = 0


# Type of the per-event callback the caller passes in to receive
# TX / RX / status / error events as they happen. Kept narrow so the CLI's
# CliOutput integration stays simple.
EventSink = Callable[[str, dict], None]


def _drain_rx(
    event_queue,
    rx_buffer: bytearray,
    on_event: EventSink,
    *,
    block_timeout: float = 0.0,
) -> bool:
    """Consume queued events, mirroring RX bytes into ``rx_buffer`` and
    forwarding everything to ``on_event``. Returns True if any event was
    drained. ``block_timeout`` is the max time to wait for the FIRST event
    (subsequent events are pulled non-blocking).
    """
    drained = False
    deadline_first = True
    while True:
        try:
            if deadline_first and block_timeout > 0:
                event = event_queue.get(timeout=block_timeout)
            else:
                event = event_queue.get_nowait()
        except Empty:
            return drained
        deadline_first = False
        drained = True
        _dispatch_event(event, rx_buffer, on_event)


def _dispatch_event(
    event: SerialEvent, rx_buffer: bytearray, on_event: EventSink
) -> None:
    if event.kind == "rx":
        if event.raw:
            rx_buffer.extend(event.raw)
        on_event(
            "rx",
            {
                "data": decode_serial_bytes(event.raw) if event.raw else event.message,
                "hex": format_hex_bytes(event.raw) if event.raw else "",
            },
        )
    elif event.kind == "tx":
        on_event("tx", {"display": event.message})
    elif event.kind == "error":
        on_event("error", {"message": event.message})
    elif event.kind in {"status", "progress", "connection"}:
        on_event("status", {"message": event.message})


def _wait_for_expect(
    expected: str,
    *,
    event_queue,
    rx_buffer: bytearray,
    timeout_ms: int,
    on_event: EventSink,
) -> tuple[bool, int]:
    """Block until ``expected`` is seen in the decoded RX buffer or
    ``timeout_ms`` elapses. Returns ``(matched, elapsed_ms)``.
    """
    start = time.monotonic()
    deadline = start + max(timeout_ms, 1) / 1000.0

    def matched() -> bool:
        text = decode_serial_bytes(bytes(rx_buffer))
        index = text.find(expected)
        if index < 0:
            return False
        # Trim the buffer past the match so a subsequent EXPECT on the same
        # text doesn't re-match the prior occurrence.
        consumed_text = text[: index + len(expected)]
        consumed_bytes = consumed_text.encode("utf-8", "replace")
        del rx_buffer[: len(consumed_bytes)]
        return True

    if matched():
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return True, elapsed_ms

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, timeout_ms
        try:
            event = event_queue.get(timeout=min(remaining, 0.1))
        except Empty:
            continue
        _dispatch_event(event, rx_buffer, on_event)
        if event.kind == "rx" and matched():
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return True, elapsed_ms


def run_command_file(
    transport: TransportAdapter,
    steps: list[BatchTemplateStep],
    parameter_values: dict[str, str],
    *,
    on_event: EventSink,
    stop_on_expect_fail: bool = True,
    expect_timeout_ms: int = 1000,
) -> RunOutcome:
    """Drive ``steps`` to completion against ``transport``.

    Caller responsibilities:
      - The transport is already connected.
      - ``parameter_values`` contains every parameter the file needs
        (the ``run`` subcommand validates this before calling).
      - ``on_event`` routes events to whichever output sink fits
        (typically :class:`CliOutput`).
    """
    event_queue = transport.subscribe_monitor()
    rx_buffer = bytearray()
    expect_failures = 0
    steps_run = 0
    # Seed the run's @@settings from the CLI flags; @@ directives override them mid-run.
    settings = RunSettings(
        expect_timeout_ms=max(expect_timeout_ms, 1),
        stop_on_error=stop_on_expect_fail,
    )

    def _missing_param_prompt(name: str, line_number: int, line_text: str) -> str | None:
        # Reaching this means the resolver couldn't find a value AND the
        # template has no default. Validation should have prevented this;
        # treat it as a fatal parameter error.
        return None

    def _handle_send_failure(line_number: int, message: str) -> RunOutcome | None:
        # @@on-error stop -> return a fatal outcome; continue -> log and keep going.
        if settings.stop_on_error:
            return RunOutcome(
                success=False,
                failure_kind=FAILURE_SEND,
                failure_line=line_number,
                failure_message=message,
                steps_run=steps_run,
                expect_failures=expect_failures,
            )
        on_event("error", {"message": f"Line {line_number}: {message}"})
        return None

    try:
        for template_step in steps:
            try:
                resolved_line = substitute_batch_parameters(
                    template_step.line,
                    parameter_values,
                    _missing_param_prompt,
                    template_step.line_number,
                )
            except Exception as exc:  # pragma: no cover - defensive
                return RunOutcome(
                    success=False,
                    failure_kind=FAILURE_PARAM,
                    failure_line=template_step.line_number,
                    failure_message=f"Parameter substitution failed: {exc}",
                    steps_run=steps_run,
                    expect_failures=expect_failures,
                )
            if resolved_line is None:
                return RunOutcome(
                    success=False,
                    failure_kind=FAILURE_PARAM,
                    failure_line=template_step.line_number,
                    failure_message=(
                        f"Line {template_step.line_number}: required parameter not "
                        "supplied (use --param NAME=VALUE)."
                    ),
                    steps_run=steps_run,
                    expect_failures=expect_failures,
                )
            try:
                step = parse_batch_line(resolved_line, template_step.line_number)
            except BatchParseError as exc:
                return RunOutcome(
                    success=False,
                    failure_kind=FAILURE_PARSE,
                    failure_line=template_step.line_number,
                    failure_message=str(exc),
                    steps_run=steps_run,
                    expect_failures=expect_failures,
                )

            # Drain any pending RX before the new step so EXPECT buffers don't
            # leak across SEND boundaries.
            _drain_rx(event_queue, rx_buffer, on_event)

            steps_run += 1

            if step.kind == "setting":
                name, value = step.payload
                settings.apply(name, value)
                on_event("status", {"message": f"Setting @@{name} = {value}."})
                continue

            if step.kind == "wait":
                _interruptible_sleep(step.payload / 1000.0, event_queue, rx_buffer, on_event)
                continue

            # Persistent inter-command delay (@@wait) applies before each send/hex.
            if step.kind in ("send", "hex") and settings.wait_before_ms > 0:
                _interruptible_sleep(
                    settings.wait_before_ms / 1000.0, event_queue, rx_buffer, on_event
                )

            if step.kind == "send":
                if settings.send_mode == "hex":
                    try:
                        data = parse_hex_payload(str(step.payload))
                    except ValueError as exc:
                        outcome = _handle_send_failure(step.line_number, f"@@send-mode hex: {exc}")
                        if outcome is not None:
                            return outcome
                        continue
                    try:
                        transport.send_bytes(data)
                    except Exception as exc:
                        outcome = _handle_send_failure(step.line_number, f"SEND failed: {exc}")
                        if outcome is not None:
                            return outcome
                        continue
                    on_event(
                        "tx",
                        {"display": f"HEX {format_hex_bytes(data)}", "mode": "hex", "line_number": step.line_number},
                    )
                else:
                    try:
                        transport.send_text(str(step.payload))
                    except Exception as exc:
                        outcome = _handle_send_failure(step.line_number, f"SEND failed: {exc}")
                        if outcome is not None:
                            return outcome
                        continue
                    on_event(
                        "tx",
                        {"display": str(step.payload), "mode": "text", "line_number": step.line_number},
                    )
                # Reset the expectation buffer between sends so subsequent
                # EXPECT only sees post-send RX.
                rx_buffer.clear()
                continue

            if step.kind == "hex":
                try:
                    transport.send_bytes(step.payload)
                except Exception as exc:
                    outcome = _handle_send_failure(step.line_number, f"HEX send failed: {exc}")
                    if outcome is not None:
                        return outcome
                    continue
                on_event(
                    "tx",
                    {
                        "display": f"HEX {format_hex_bytes(step.payload)}",
                        "mode": "hex",
                        "line_number": step.line_number,
                    },
                )
                rx_buffer.clear()
                continue

            if step.kind == "expect":
                matched, elapsed_ms = _wait_for_expect(
                    str(step.payload),
                    event_queue=event_queue,
                    rx_buffer=rx_buffer,
                    timeout_ms=settings.expect_timeout_ms,
                    on_event=on_event,
                )
                on_event(
                    "expect",
                    {
                        "pattern": str(step.payload),
                        "matched": matched,
                        "after_ms": elapsed_ms,
                        "line_number": step.line_number,
                    },
                )
                if not matched:
                    expect_failures += 1
                    if settings.stop_on_error:
                        return RunOutcome(
                            success=False,
                            failure_kind=FAILURE_EXPECT,
                            failure_line=step.line_number,
                            failure_message=(
                                f"EXPECT timed out on line {step.line_number} "
                                f"after {settings.expect_timeout_ms} ms: {step.payload}"
                            ),
                            steps_run=steps_run,
                            expect_failures=expect_failures,
                        )
                continue

        # End of file — drain residual RX so trailing output isn't lost.
        _drain_rx(event_queue, rx_buffer, on_event)
        return RunOutcome(
            success=True,
            steps_run=steps_run,
            expect_failures=expect_failures,
        )
    except KeyboardInterrupt:
        return RunOutcome(
            success=False,
            failure_kind=FAILURE_INTERRUPTED,
            failure_message="Interrupted.",
            steps_run=steps_run,
            expect_failures=expect_failures,
        )
    finally:
        transport.unsubscribe_monitor(event_queue)


def _interruptible_sleep(
    seconds: float,
    event_queue,
    rx_buffer: bytearray,
    on_event: EventSink,
) -> None:
    """Sleep ``seconds`` while continuing to drain RX events so the user
    still sees device output during long WAIT steps.
    """
    if seconds <= 0:
        return
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        _drain_rx(event_queue, rx_buffer, on_event, block_timeout=min(remaining, 0.1))
