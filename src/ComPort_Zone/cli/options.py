"""Reusable Click option decorators.

The CLI shares a fairly large set of serial-related flags across the
``send`` / ``hex`` / ``listen`` / ``repl`` / ``run`` subcommands. Defining
them once here keeps the per-command signatures readable and the spec
exactly aligned. Values are NOT defaulted - ``None`` means "user did not
specify"; precedence resolution happens in :mod:`config_resolver`.
"""

from __future__ import annotations

from typing import Callable, TypeVar

import click

F = TypeVar("F", bound=Callable)


# ---------------------------------------------------------------- shared flags

def serial_flags(func: F) -> F:
    """Attach the full serial transport flag set to a Click command.

    Order matches the requirements doc so ``--help`` reads top-to-bottom in
    the same order users see in the spec.
    """
    decorators = [
        click.option("--port", "port", metavar="COM", help="COM port (e.g. COM3)."),
        click.option("--baud", "baud", type=int, help="Baud rate."),
        click.option(
            "--data-bits",
            "data_bits",
            type=click.Choice(["5", "6", "7", "8"]),
            help="Data bits.",
        ),
        click.option(
            "--parity",
            "parity",
            type=click.Choice(["N", "E", "O", "M", "S"], case_sensitive=False),
            help="Parity.",
        ),
        click.option(
            "--stop-bits",
            "stop_bits",
            type=click.Choice(["1", "1.5", "2"]),
            help="Stop bits.",
        ),
        click.option(
            "--flow-control",
            "flow_control",
            type=click.Choice(["none", "xonxoff", "rtscts", "dsrdtr"], case_sensitive=False),
            help="Flow control.",
        ),
        click.option(
            "--line-ending",
            "line_ending",
            type=click.Choice(["none", "CR", "LF", "CRLF"], case_sensitive=False),
            help="Line ending for text mode.",
        ),
        click.option(
            "--dtr",
            "dtr",
            type=click.Choice(["on", "off"], case_sensitive=False),
            help="DTR control line.",
        ),
        click.option(
            "--rts",
            "rts",
            type=click.Choice(["on", "off"], case_sensitive=False),
            help="RTS control line.",
        ),
        click.option(
            "--auto-reconnect/--no-auto-reconnect",
            "auto_reconnect",
            default=None,
            help="Re-open the port on transient disconnect.",
        ),
        click.option(
            "--wait",
            "wait_seconds",
            type=float,
            default=0.0,
            show_default=True,
            help="Retry-with-backoff for this many seconds when the port is busy.",
        ),
    ]
    for decorator in reversed(decorators):
        func = decorator(func)
    return func
