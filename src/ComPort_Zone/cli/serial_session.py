"""High-level helpers for opening / using a serial port from a CLI command.

Encapsulates two things the per-command code would otherwise duplicate:

* Mapping a connect failure to the correct exit code (``PORT_NOT_FOUND``
  when the port is not in pyserial's list, ``PORT_BUSY`` when it is but
  ``SerialClient.connect`` returns ``False``). Distinguishing the two
  requires consulting ``list_ports.comports()`` before connecting.
* Implementing ``--wait <seconds>`` as exponential-backoff retry around
  the connect call, returning ``PORT_BUSY`` if the deadline is reached.

The helpers do NOT depend on Click - they just raise typed exceptions
that the command layer translates to ``ctx.exit(...)``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..core.models import SerialProfile
from ..core.transports import SerialTransportAdapter
from .exit_codes import ExitCode


class SerialSessionError(Exception):
    """Base class - every subclass carries an ``ExitCode``."""

    exit_code: ExitCode = ExitCode.GENERIC_ERROR


class PortNotFoundError(SerialSessionError):
    exit_code = ExitCode.PORT_NOT_FOUND


class PortBusyError(SerialSessionError):
    exit_code = ExitCode.PORT_BUSY


# ----------------------------------------------------------- port-list helpers

def list_available_ports(transport: SerialTransportAdapter) -> list[dict[str, str]]:
    """Snapshot of currently-visible serial ports as plain dicts."""
    return transport.list_ports()


def port_is_present(transport: SerialTransportAdapter, port_name: str) -> bool:
    """Case-insensitive presence check - Windows COM names are case-insensitive."""
    needle = port_name.upper()
    return any(item.get("device", "").upper() == needle for item in transport.list_ports())


# ---------------------------------------------------------------- open w/ wait

@dataclass(slots=True)
class _WaitClock:
    deadline: float
    delay: float = 0.1
    max_delay: float = 2.0

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def expired(self) -> bool:
        return time.monotonic() >= self.deadline

    def sleep_and_backoff(self) -> None:
        time.sleep(min(self.delay, self.remaining()))
        self.delay = min(self.delay * 2, self.max_delay)


def open_serial(
    transport: SerialTransportAdapter,
    profile: SerialProfile,
    *,
    wait_seconds: float = 0.0,
) -> None:
    """Connect ``transport`` to ``profile.port``, retrying for up to
    ``wait_seconds`` if the port is busy.

    Raises:
        :class:`PortNotFoundError`: the requested port is not in pyserial's
            list (so connect would always fail).
        :class:`PortBusyError`: the port exists but ``connect`` returned
            False (or kept returning False until ``wait_seconds`` expired).
    """
    if not profile.port:
        raise PortNotFoundError("No serial port specified.")

    if not port_is_present(transport, profile.port):
        raise PortNotFoundError(
            f"Port {profile.port} is not present on this system."
        )

    if transport.connect(profile):
        return

    if wait_seconds <= 0:
        raise PortBusyError(
            f"Port {profile.port} is in use by another process. "
            "Disconnect from the GUI or terminate the other CLI session first."
        )

    clock = _WaitClock(deadline=time.monotonic() + wait_seconds)
    while not clock.expired():
        clock.sleep_and_backoff()
        if not port_is_present(transport, profile.port):
            raise PortNotFoundError(
                f"Port {profile.port} disappeared while waiting."
            )
        if transport.connect(profile):
            return

    raise PortBusyError(
        f"Port {profile.port} was still busy after waiting {wait_seconds:.1f}s."
    )


# ---------------------------------------------------------- describe / inspect

def port_details(transport: SerialTransportAdapter, port_name: str) -> dict[str, str] | None:
    """Return all known metadata for ``port_name`` (case-insensitive), or
    ``None`` if the port is not present.
    """
    needle = port_name.upper()
    for endpoint in transport.list_endpoints():
        if endpoint.id.upper() != needle:
            continue
        meta = dict(endpoint.metadata)
        meta.setdefault("device", endpoint.id)
        meta.setdefault("description", endpoint.description)
        return meta
    return None


