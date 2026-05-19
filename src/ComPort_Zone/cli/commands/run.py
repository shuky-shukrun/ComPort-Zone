"""`comport-zone run <file>` — execute a command file."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, TextIO

import click

from ...core.batch import (
    BatchParameterOccurrence,
    BatchTemplateStep,
    find_batch_parameters,
    parse_batch_template,
)
from ..command_file_runner import (
    FAILURE_EXPECT,
    FAILURE_INTERRUPTED,
    FAILURE_PARAM,
    FAILURE_PARSE,
    FAILURE_SEND,
    RunOutcome,
    run_command_file,
)
from ..config_resolver import load_app_settings, resolve_serial_profile
from ..exit_codes import ExitCode
from ..options import serial_flags
from ..output import CliOutput
from ..serial_session import SerialSessionError, open_serial
from ..transports import make_serial_transport


_FAILURE_TO_EXIT: dict[str, ExitCode] = {
    FAILURE_PARSE: ExitCode.PARSE_ERROR,
    FAILURE_PARAM: ExitCode.MISSING_PARAM,
    FAILURE_EXPECT: ExitCode.EXPECT_FAILED,
    FAILURE_SEND: ExitCode.GENERIC_ERROR,
    FAILURE_INTERRUPTED: ExitCode.INTERRUPTED,
}


def _parse_param_flag(raw: str) -> tuple[str, str]:
    """Parse a single ``KEY=VALUE`` flag into a pair."""
    if "=" not in raw:
        raise click.BadParameter(
            f"--param {raw!r}: expected KEY=VALUE.",
            param_hint="--param",
        )
    key, _, value = raw.partition("=")
    key = key.strip()
    if not key:
        raise click.BadParameter(
            f"--param {raw!r}: empty key.",
            param_hint="--param",
        )
    return key, value


def _gather_param_values(
    occurrences: list[BatchParameterOccurrence],
    flag_values: dict[str, str],
    *,
    interactive: bool,
    output: CliOutput,
) -> dict[str, str] | None:
    """Resolve every required parameter to a concrete value.

    Returns ``None`` when a required parameter is missing under
    ``--non-interactive`` — the caller emits a MISSING_PARAM exit.
    """
    values: dict[str, str] = dict(flag_values)
    missing: list[BatchParameterOccurrence] = []
    for occurrence in occurrences:
        if occurrence.name in values:
            continue
        if occurrence.default is not None:
            values.setdefault(occurrence.name, occurrence.default)
            continue
        missing.append(occurrence)

    if not missing:
        return values

    if not interactive:
        first = missing[0]
        output.error(
            f"Required parameter {first.name!r} on line {first.line_number} "
            "was not supplied. Use --param NAME=VALUE.",
            code=ExitCode.MISSING_PARAM,
        )
        return None

    for occurrence in missing:
        if occurrence.name in values:
            continue
        prompt = f"Parameter {occurrence.name} (line {occurrence.line_number}): "
        try:
            values[occurrence.name] = input(prompt)
        except EOFError:
            output.error(
                f"stdin closed before {occurrence.name!r} was supplied.",
                code=ExitCode.MISSING_PARAM,
            )
            return None
    return values


def _emit_outcome_failure(output: CliOutput, outcome: RunOutcome) -> ExitCode:
    code = _FAILURE_TO_EXIT.get(outcome.failure_kind or "", ExitCode.GENERIC_ERROR)
    output.error(outcome.failure_message or "Command file run failed.", code=code)
    return code


def _format_event_for_log(kind: str, fields: dict[str, Any]) -> str | None:
    """Plain-text rendering used for the --log file (and only the log)."""
    if kind == "tx":
        return f"TX> {fields.get('display', '')}"
    if kind == "rx":
        return fields.get("data", "")
    if kind == "expect":
        tag = "matched" if fields.get("matched") else "no-match"
        return f"[expect:{tag}] {fields.get('pattern', '')!r} after {fields.get('after_ms')} ms"
    if kind == "status":
        return fields.get("message", "")
    if kind == "error":
        return f"Error: {fields.get('message', '')}"
    return None


def execute_run(
    ctx: click.Context,
    *,
    file_path: Path,
    param_specs: tuple[str, ...],
    non_interactive: bool,
    log_path: Path | None,
    stop_on_expect_fail: bool,
    expect_timeout_ms: int,
    serial_flag_values: dict[str, Any],
) -> None:
    """Shared executor used by ``run`` and ``files run``.

    Parses ``file_path``, gathers parameters, opens the configured port,
    streams the run through :func:`run_command_file`, and exits via
    ``ctx.exit`` on failure.
    """
    output: CliOutput = ctx.obj["output"]

    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        output.error(f"Could not read {file_path}: {exc}", code=ExitCode.GENERIC_ERROR)
        ctx.exit(int(ExitCode.GENERIC_ERROR))
        return

    template: list[BatchTemplateStep] = parse_batch_template(text)
    if not template:
        output.status(f"{file_path}: no runnable commands.")
        return

    occurrences = find_batch_parameters(text)
    flag_values: dict[str, str] = {}
    for raw in param_specs:
        key, value = _parse_param_flag(raw)
        flag_values[key] = value

    parameter_values = _gather_param_values(
        occurrences,
        flag_values,
        interactive=not non_interactive,
        output=output,
    )
    if parameter_values is None:
        ctx.exit(int(ExitCode.MISSING_PARAM))
        return

    settings = load_app_settings(ctx.obj.get("config_path"))
    profile = resolve_serial_profile(settings=settings, **{
        key: serial_flag_values[key]
        for key in (
            "port",
            "baud",
            "data_bits",
            "parity",
            "stop_bits",
            "flow_control",
            "line_ending",
            "dtr",
            "rts",
            "auto_reconnect",
        )
    })

    transport = make_serial_transport()
    try:
        open_serial(
            transport,
            profile,
            wait_seconds=serial_flag_values["wait_seconds"],
        )
    except SerialSessionError as exc:
        output.error(str(exc), code=exc.exit_code)
        ctx.exit(int(exc.exit_code))
        return

    log_handle: TextIO | None = None
    if log_path is not None:
        log_handle = open(log_path, "a", encoding="utf-8")

    def on_event(kind: str, fields: dict[str, Any]) -> None:
        if kind == "tx":
            output.event("tx", **fields)
        elif kind == "rx":
            output.event("rx", display=fields.get("data", ""), **fields)
        elif kind == "expect":
            output.event("expect", **fields)
        elif kind == "status":
            output.status(fields.get("message", ""))
        elif kind == "error":
            output.error(fields.get("message", ""))
        if log_handle is not None:
            rendered = _format_event_for_log(kind, fields)
            if rendered:
                log_handle.write(rendered + "\n")
                log_handle.flush()

    try:
        output.status(
            f"Running {file_path.name} against {profile.port} "
            f"({len(template)} step(s))."
        )
        outcome = run_command_file(
            transport,
            template,
            parameter_values,
            on_event=on_event,
            stop_on_expect_fail=stop_on_expect_fail,
            expect_timeout_ms=expect_timeout_ms,
        )
    finally:
        if log_handle is not None:
            log_handle.close()
        transport.disconnect()
        output.status("Disconnected.")

    if outcome.success:
        output.status(
            f"Run complete: {outcome.steps_run} step(s), "
            f"{outcome.expect_failures} EXPECT failure(s)."
        )
        return

    code = _emit_outcome_failure(output, outcome)
    ctx.exit(int(code))


@click.command("run")
@click.argument(
    "file_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    metavar="FILE",
)
@click.option(
    "--param",
    "param_specs",
    multiple=True,
    metavar="KEY=VALUE",
    help="Supply a value for a {{PARAM}} placeholder. Repeatable.",
)
@click.option(
    "--non-interactive",
    "non_interactive",
    is_flag=True,
    help="Never prompt; missing required params exit with code 12.",
)
@click.option(
    "--log",
    "log_path",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    help="Append rendered TX/RX/EXPECT lines to this file.",
)
@click.option(
    "--stop-on-expect-fail/--continue-on-expect-fail",
    "stop_on_expect_fail",
    default=True,
    show_default=True,
    help="Whether the run aborts on the first failed EXPECT.",
)
@click.option(
    "--expect-timeout",
    "expect_timeout_ms",
    type=int,
    default=1000,
    show_default=True,
    metavar="MS",
    help="Default timeout applied to every EXPECT step.",
)
@serial_flags
@click.pass_context
def run_command(
    ctx: click.Context,
    file_path: Path,
    param_specs: tuple[str, ...],
    non_interactive: bool,
    log_path: Path | None,
    stop_on_expect_fail: bool,
    expect_timeout_ms: int,
    **serial_flag_values: Any,
) -> None:
    """Execute a SEND/WAIT/HEX/EXPECT command file against a serial port."""
    execute_run(
        ctx,
        file_path=file_path,
        param_specs=param_specs,
        non_interactive=non_interactive,
        log_path=log_path,
        stop_on_expect_fail=stop_on_expect_fail,
        expect_timeout_ms=expect_timeout_ms,
        serial_flag_values=serial_flag_values,
    )
