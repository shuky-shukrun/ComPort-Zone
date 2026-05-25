"""Output formatting for the CLI.

Two output modes:

* Plain text (default): human-readable. ANSI colors when stdout is a TTY
  and ``--no-color`` was not passed.
* ``--json``: machine-readable. Single-result commands emit one JSON object;
  streaming commands emit one JSON object per line (NDJSON).

The contract is intentionally narrow - all CLI commands route their output
through this module so toggling ``--json`` works uniformly.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import IO, Any

import click

from .exit_codes import EXIT_CODE_NAMES, ExitCode


@dataclass(slots=True)
class CliOutput:
    """Holds output settings and writes events / data accordingly."""

    json_mode: bool = False
    quiet: bool = False
    verbose: bool = False
    color: bool = True
    stdout: IO[str] | None = None
    stderr: IO[str] | None = None

    def _out(self) -> IO[str]:
        return self.stdout or sys.stdout

    def _err(self) -> IO[str]:
        return self.stderr or sys.stderr

    # ------------------------------------------------------------------ status

    def status(self, message: str) -> None:
        """Informational status (suppressed by ``--quiet``)."""
        if self.quiet:
            return
        if self.json_mode:
            self._emit_json_event(self._out(), {"type": "status", "message": message})
            return
        click.echo(self._style(message, fg="cyan"), file=self._out())

    def debug(self, message: str) -> None:
        """Diagnostics shown only with ``--verbose``."""
        if not self.verbose:
            return
        if self.json_mode:
            self._emit_json_event(self._out(), {"type": "debug", "message": message})
            return
        click.echo(self._style(f"[debug] {message}", fg="bright_black"), file=self._err())

    # ------------------------------------------------------------------- error

    def error(self, message: str, *, code: ExitCode | None = None) -> None:
        """Error message - always shown (never suppressed by ``--quiet``)."""
        if self.json_mode:
            payload: dict[str, Any] = {"type": "error", "message": message}
            if code is not None:
                payload["code"] = EXIT_CODE_NAMES[code]
            self._emit_json_event(self._err(), payload)
            return
        prefix = "Error"
        if code is not None:
            prefix = f"Error ({EXIT_CODE_NAMES[code]})"
        click.echo(self._style(f"{prefix}: {message}", fg="red", bold=True), file=self._err())

    # ----------------------------------------------------------- streaming TX/RX

    def event(self, kind: str, **fields: Any) -> None:
        """Emit a typed event - RX, TX, expect, etc.

        In JSON mode this is a single NDJSON line on stdout. In plain mode the
        formatter routes by ``kind`` so each event type prints sensibly. Fields
        the plain formatter doesn't know about are ignored - the JSON output
        is the source of truth.
        """
        if self.json_mode:
            payload = {"ts": _now_iso(), "type": kind, **fields}
            self._emit_json_event(self._out(), payload)
            return
        text = self._format_event_for_humans(kind, fields)
        if text is None:
            return
        click.echo(text, file=self._out())

    # ---------------------------------------------------------------- one-shot

    def object(self, payload: dict[str, Any]) -> None:
        """Single-result output for one-shot commands.

        JSON mode dumps the dict; plain mode prints ``key: value`` lines for
        readability (avoid bare JSON in the terminal where users skim).
        """
        if self.json_mode:
            click.echo(json.dumps(payload, indent=2, sort_keys=True), file=self._out())
            return
        for key, value in payload.items():
            click.echo(f"{key}: {value}", file=self._out())

    def table(self, rows: list[dict[str, Any]], *, columns: list[str]) -> None:
        """Render a list of records.

        JSON mode emits an array of objects; plain mode renders an aligned
        text table. Empty rows print ``(no entries)`` (or empty array in JSON)
        so callers don't need a separate empty-state path.
        """
        if self.json_mode:
            click.echo(json.dumps(rows, indent=2, sort_keys=True), file=self._out())
            return
        if not rows:
            click.echo("(no entries)", file=self._out())
            return
        widths = {col: len(col) for col in columns}
        for row in rows:
            for col in columns:
                widths[col] = max(widths[col], len(str(row.get(col, ""))))
        header = "  ".join(col.ljust(widths[col]) for col in columns)
        rule = "  ".join("-" * widths[col] for col in columns)
        click.echo(self._style(header, bold=True), file=self._out())
        click.echo(rule, file=self._out())
        for row in rows:
            line = "  ".join(str(row.get(col, "")).ljust(widths[col]) for col in columns)
            click.echo(line, file=self._out())

    # ---------------------------------------------------------------- internals

    def _emit_json_event(self, stream: IO[str], payload: dict[str, Any]) -> None:
        click.echo(json.dumps(payload, sort_keys=True), file=stream)

    def _style(self, text: str, **kwargs: Any) -> str:
        if not self.color:
            return text
        # click.style honours NO_COLOR / non-TTY via click.echo, but we can
        # still let users force colours off explicitly.
        return click.style(text, **kwargs)

    def _format_event_for_humans(self, kind: str, fields: dict[str, Any]) -> str | None:
        if kind == "rx":
            ts = fields.get("ts_local") or ""
            prefix = f"[{ts}] " if ts else ""
            data = fields.get("display") or fields.get("data") or ""
            return f"{prefix}{data}"
        if kind == "tx":
            data = fields.get("display") or fields.get("data") or ""
            return self._style(f"TX> {data}", fg="green")
        if kind == "expect":
            matched = fields.get("matched")
            pattern = fields.get("pattern", "")
            after = fields.get("after_ms")
            tag = "matched" if matched else "no-match"
            suffix = f" after {after} ms" if after is not None else ""
            return self._style(f"[expect:{tag}] {pattern!r}{suffix}", fg="magenta")
        if kind == "status":
            return self._style(str(fields.get("message", "")), fg="cyan")
        if kind == "error":
            code = fields.get("code")
            prefix = f"Error ({code})" if code else "Error"
            return self._style(f"{prefix}: {fields.get('message', '')}", fg="red", bold=True)
        # Unknown kinds: drop in plain mode (json mode already captured them).
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
