#!/usr/bin/env python3
"""
GENESYS+ TCP/SCPI Simulator for NextGenDisplay bench testing.

Listens on TCP/8003 and responds to the SCPI subset the v1 firmware emits,
so you can validate the board's LAN path end-to-end without a real
TDK-Lambda GENESYS+ PSU on the bench. Every command received and every
response sent is timestamped and printed, so you can see exactly what
the board is doing.

Run with `--help` for CLI options. See `tools/genesys_sim.md` for the
full setup walkthrough (PC static IP, firewall, board settings, etc.).

Quick reference -- supported SCPI commands (case-insensitive,
short/long forms accepted):

  *IDN?                                          query identification
  *CLS                                           clear status / fault bits
  *RST                                           reset
  INSTrument:NSELect <n>                         select address 0..31
  INSTrument:NSELect?
  MEASure:VOLTage?                               measured V
  MEASure:CURRent?                               measured I
  MEASure:POWer?                                 measured P
  SOURce:VOLTage <v>          /  SOURce:VOLTage?
  SOURce:CURRent <i>          /  SOURce:CURRent?
  SOURce:POWer:LEVel <w>      /  SOURce:POWer:LEVel?
  SOURce:VOLTage:PROTection:LEVel       (OVP)
  SOURce:VOLTage:PROTection:LOW:LEVel   (UVL)
  SOURce:VOLTage:SLEW:UP|DOWN <v/ms>
  SOURce:CURRent:SLEW:UP|DOWN <a/ms>
  OUTPut:STATe ON|OFF         /  OUTPut:STATe?
  OUTPut:MODE?                              -> CV | CC | CP | OFF
  OUTPut:PROTection:FOLDback OFF|CC|CV      /  ?
  OUTPut:PROTection:CLEar
  STATus:QUEStionable:CONDition?            -> 0..65535 (Table 6-1 bits:
                                                          1=AC, 2=OT, 3=FLD,
                                                          4=OVP, 5=SO, 7=ILC,
                                                          9=UVP)
  STATus:OPERation:CONDition?               -> 0..65535 (bit 8 = OUT.ON)
  SYSTem:ERRor?                             -> "0,\"No error\""
  SYSTem:VERSion?                           -> "1999.0"
  *OPC? / *OPC / *WAI / *TST?               IEEE 488.2 stubs

Tests / library use:
    from tools.genesys_sim import Psu, Handler, serve_in_thread
    server, _ = serve_in_thread(port=0)        # OS-assigned port
    port = server.server_address[1]
    # ... drive the simulator over a TCP socket ...
    server.shutdown(); server.server_close()

Or for in-process SCPI-dispatch tests (no socket needed):
    handler = Handler(Psu())
    assert handler.dispatch("*IDN?").startswith("TDK-LAMBDA")
"""

from __future__ import annotations

import argparse
import socket
import socketserver
import sys
import threading
from datetime import datetime
from typing import Callable

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

class C:
    RESET = "\033[0m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"
    enabled = True

def _c(text: str, color: str) -> str:
    return f"{color}{text}{C.RESET}" if C.enabled else text

def log(tag: str, msg: str, color: str = C.RESET) -> None:
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{_c(ts, C.DIM)} {_c(tag, color)} {msg}", flush=True)


# ----------------------------------------------------------------------
# Simulated PSU state
# ----------------------------------------------------------------------

class Psu:
    """Single in-process simulated GEN+ instrument."""

    # Approximate rated envelope of a mid-range GENESYS+ unit. Anything
    # the board pushes outside this range is clamped and a fault bit is
    # raised in STAT:QUES so you can see how the firmware reacts.
    V_MAX = 60.0
    I_MAX = 10.0
    LOAD_OHMS = 10.0   # simulated resistive load for current readback

    # STAT:QUES bits (per Genesys+ manual Table 6-1; same numbering used by
    # the example panel at examples/tdk-genplus-control-panel.json and by
    # the firmware's FaultBit in core/include/nextgen/app/DeviceState.hpp).
    Q_AC   = 1 << 1   # AC fail
    Q_OT   = 1 << 2   # over-temperature
    Q_FOLD = 1 << 3   # fold-back protection trip
    Q_OV   = 1 << 4   # over-voltage protection
    Q_SO   = 1 << 5   # shut-off (daisy)
    Q_ILC  = 1 << 7   # interlock
    Q_UV   = 1 << 9   # under-voltage protection

    # STAT:OPER bits (per Genesys+ manual Table 6-2)
    O_CV = 1 << 0
    O_CC = 1 << 1
    O_OUT_ON = 1 << 8

    def __init__(self) -> None:
        self.address = 0
        self.output_on = False
        self.v_set = 12.0
        self.i_set = 1.0
        self.p_limit = self.V_MAX * self.I_MAX
        self.ovp_level = self.V_MAX * 1.10
        self.uvl_level = 0.0
        self.foldback_mode = "OFF"  # OFF | CC | CV
        self.v_slew_up = 1.0
        self.v_slew_down = 1.0
        self.i_slew_up = 1.0
        self.i_slew_down = 1.0
        # Persistent fault bitmap (cleared by *CLS / OUTPut:PROT:CLE).
        self.questionable = 0
        # Per-tick fault injection requested via CLI / runtime poke.
        self.questionable_injected = 0
        self.errors: list[str] = []

    # ---- physics ------------------------------------------------------

    def _measured_v(self) -> float:
        return self.v_set if self.output_on else 0.0

    def _measured_i(self) -> float:
        if not self.output_on:
            return 0.0
        # Simple resistive-load model. Real PSU would current-limit.
        i = self._measured_v() / self.LOAD_OHMS
        return min(i, self.i_set)

    def _mode(self) -> str:
        if not self.output_on:
            return "OFF"
        i = self._measured_i()
        # Crude CV/CC classifier: if computed I hits I-limit, we're in CC.
        if i >= self.i_set - 1e-6:
            return "CC"
        return "CV"

    def _ques(self) -> int:
        # OVP latch: if setpoint exceeds OVP threshold while output is on,
        # raise the OV bit, force output off, and PERSIST the bit into
        # `questionable` so the firmware still sees the fault after the
        # output drops (mirrors a real PSU's latched OVP).
        if self.output_on and self.v_set > self.ovp_level:
            self.questionable |= self.Q_OV
            self.output_on = False
        # UVP latch: same idea for under-voltage limit.
        if self.output_on and self.v_set < self.uvl_level:
            self.questionable |= self.Q_UV
            self.output_on = False
        return (self.questionable | self.questionable_injected) & 0xFFFF

    # ---- runtime fault injection (test/debug helpers) ----------------

    def inject_fault(self, mask: int) -> None:
        """Assert the given STAT:QUES bits until cleared with
        :meth:`clear_injected_faults`. *Independent* of *CLS / OUTP:PROT:CLE
        — those clear the persistent ``questionable`` register only."""
        self.questionable_injected |= int(mask) & 0xFFFF

    def clear_injected_faults(self, mask: int | None = None) -> None:
        if mask is None:
            self.questionable_injected = 0
        else:
            self.questionable_injected &= ~int(mask) & 0xFFFF

    def reset(self) -> None:
        """Reinitialise PSU state. Equivalent to ``*RST`` plus injected-fault
        clear — useful between tests to share a single ``Psu`` instance."""
        self.__init__()

    def _oper(self) -> int:
        bits = 0
        if self.output_on:
            bits |= self.O_OUT_ON
            mode = self._mode()
            if mode == "CV":
                bits |= self.O_CV
            elif mode == "CC":
                bits |= self.O_CC
        return bits & 0xFFFF

    # ---- formatting helpers ------------------------------------------

    @staticmethod
    def _fmt_v(x: float) -> str:
        return f"{x:.3f}"

    @staticmethod
    def _fmt_i(x: float) -> str:
        return f"{x:.3f}"

    @staticmethod
    def _fmt_w(x: float) -> str:
        return f"{x:.3f}"


# ----------------------------------------------------------------------
# SCPI command dispatch
# ----------------------------------------------------------------------

# Normalise a SCPI keyword: collapse the lower-case "long suffix"
# letters and uppercase what remains, e.g. "SOURce:VOLTage" → "SOUR:VOLT",
# "OUTPut:PROTection:LOW:LEVel" → "OUTP:PROT:LOW:LEV". Genesys+ accepts
# both abbreviations, so the simulator should too. The trick: keep
# uppercase letters and digits, drop lower-case letters.

def _short(token: str) -> str:
    return "".join(ch for ch in token if not ch.islower()).upper()

def _normalize(cmd: str) -> tuple[str, str]:
    """
    Split into (head, arg). Strip any trailing '?'. Apply short-form
    normalisation per colon-separated component. Returns the bare
    short form of the command head and any whitespace-trimmed argument.
    """
    cmd = cmd.strip().rstrip(";")
    # Split head and argument on first whitespace.
    if " " in cmd:
        head, arg = cmd.split(" ", 1)
        arg = arg.strip()
    else:
        head, arg = cmd, ""
    head = head.strip()
    is_query = head.endswith("?")
    if is_query:
        head = head[:-1]
    parts = head.split(":")
    head_short = ":".join(_short(p) for p in parts)
    if is_query:
        head_short += "?"
    return head_short, arg


class Handler:
    """Dispatcher mapping normalised SCPI heads to PSU methods."""

    def __init__(self, psu: Psu) -> None:
        self.psu = psu
        # head (already normalised, short form, with trailing ? for queries)
        # → callable(arg) -> response_or_None
        self.table: dict[str, Callable[[str], str | None]] = {
            "*IDN?":  self._idn,
            "*CLS":   self._cls,
            "*RST":   self._rst,
            "*OPC?":  lambda _: "1",
            "*OPC":   lambda _: None,
            "*WAI":   lambda _: None,
            "*TST?":  lambda _: "0",
            "SYST:VERS?":  lambda _: "1999.0",
            "INST:NSEL":   self._set_addr,
            "INST:NSEL?":  self._get_addr,
            "MEAS:VOLT?":  lambda _: Psu._fmt_v(psu._measured_v()),
            "MEAS:CURR?":  lambda _: Psu._fmt_i(psu._measured_i()),
            "MEAS:POW?":   lambda _: Psu._fmt_w(psu._measured_v() * psu._measured_i()),
            "SOUR:VOLT":   self._set_v,
            "SOUR:VOLT?":  lambda _: Psu._fmt_v(psu.v_set),
            "SOUR:CURR":   self._set_i,
            "SOUR:CURR?":  lambda _: Psu._fmt_i(psu.i_set),
            "SOUR:POW:LEV":   self._set_p,
            "SOUR:POW:LEV?":  lambda _: Psu._fmt_w(psu.p_limit),
            "OUTP:STAT":   self._set_out,
            "OUTP:STAT?":  lambda _: "1" if psu.output_on else "0",
            "OUTP:MODE?":  lambda _: psu._mode(),
            # SCPI short-form aliases — Genesys+ accepts both long and
            # short forms; mirror that here so the v1 stack's short-form
            # codec (VOLT/CURR/POW/OUTP) hits the same handlers.
            "VOLT":    self._set_v,
            "VOLT?":   lambda _: Psu._fmt_v(psu.v_set),
            "CURR":    self._set_i,
            "CURR?":   lambda _: Psu._fmt_i(psu.i_set),
            "POW":     self._set_p,
            "POW?":    lambda _: Psu._fmt_w(psu.p_limit),
            "OUTP":    self._set_out,
            "OUTP?":   lambda _: "1" if psu.output_on else "0",
            "OUTP:PROT:FOLD":   self._set_fold,
            "OUTP:PROT:FOLD?":  lambda _: psu.foldback_mode,
            "OUTP:PROT:CLE":    self._clear_prot,
            "SOUR:VOLT:PROT:LEV":     self._set_ovp,
            "SOUR:VOLT:PROT:LEV?":    lambda _: Psu._fmt_v(psu.ovp_level),
            "SOUR:VOLT:PROT:LOW:LEV": self._set_uvl,
            "SOUR:VOLT:PROT:LOW:LEV?": lambda _: Psu._fmt_v(psu.uvl_level),
            "SOUR:VOLT:SLEW:UP":      self._set_v_slew_up,
            "SOUR:VOLT:SLEW:UP?":     lambda _: f"{psu.v_slew_up:.3f}",
            "SOUR:VOLT:SLEW:DOWN":    self._set_v_slew_down,
            "SOUR:VOLT:SLEW:DOWN?":   lambda _: f"{psu.v_slew_down:.3f}",
            "SOUR:CURR:SLEW:UP":      self._set_i_slew_up,
            "SOUR:CURR:SLEW:UP?":     lambda _: f"{psu.i_slew_up:.3f}",
            "SOUR:CURR:SLEW:DOWN":    self._set_i_slew_down,
            "SOUR:CURR:SLEW:DOWN?":   lambda _: f"{psu.i_slew_down:.3f}",
            "STAT:QUES:COND?":  lambda _: str(psu._ques()),
            "STAT:OPER:COND?":  lambda _: str(psu._oper()),
            "SYST:ERR?":        self._syst_err,
        }

    def dispatch(self, raw: str) -> str | None:
        head, arg = _normalize(raw)
        fn = self.table.get(head)
        if fn is None and head:
            # SCPI lets clients omit the default subsystem prefix; "SOURce"
            # is the implicit subsystem for all setpoint/protection/slew
            # commands. The example panel JSON at
            # examples/tdk-genplus-control-panel.json exercises this — it
            # sends e.g. ``VOLT:PROT:LEV 12.5`` rather than
            # ``SOUR:VOLT:PROT:LEV 12.5``. Try the SOUR: variant before
            # logging an undefined-header error.
            sour_head = (
                "SOUR:" + head[:-1] + "?" if head.endswith("?") else "SOUR:" + head
            )
            fn = self.table.get(sour_head)
        if fn is None:
            self.psu.errors.append(f"-113,\"Undefined header: {raw[:40]}\"")
            return None  # silently swallow unknown writes; queries get no
                         # reply, which mirrors typical PSU behaviour
        return fn(arg)

    # ---- per-command helpers -----------------------------------------

    def _idn(self, _: str) -> str:
        return "TDK-LAMBDA,G10-100,011B158-0001,G:02.122"

    def _cls(self, _: str) -> None:
        self.psu.questionable = 0
        self.psu.errors.clear()
        return None

    def _rst(self, _: str) -> None:
        self.psu.output_on = False
        self.psu.questionable = 0
        return None

    def _set_addr(self, arg: str) -> None:
        try:
            n = int(arg)
            if 0 <= n <= 31:
                self.psu.address = n
        except ValueError:
            pass
        return None

    def _get_addr(self, _: str) -> str:
        return str(self.psu.address)

    def _parse_float(self, arg: str) -> float | None:
        try:
            return float(arg)
        except ValueError:
            return None

    def _set_v(self, arg: str) -> None:
        v = self._parse_float(arg)
        if v is not None:
            self.psu.v_set = max(0.0, min(v, Psu.V_MAX))
        return None

    def _set_i(self, arg: str) -> None:
        i = self._parse_float(arg)
        if i is not None:
            self.psu.i_set = max(0.0, min(i, Psu.I_MAX))
        return None

    def _set_p(self, arg: str) -> None:
        p = self._parse_float(arg)
        if p is not None:
            self.psu.p_limit = max(0.0, p)
        return None

    def _set_out(self, arg: str) -> None:
        a = arg.strip().upper()
        if a in ("ON", "1"):
            self.psu.output_on = True
        elif a in ("OFF", "0"):
            self.psu.output_on = False
        return None

    def _set_fold(self, arg: str) -> None:
        a = arg.strip().upper()
        if a in ("OFF", "CC", "CV"):
            self.psu.foldback_mode = a
        return None

    def _clear_prot(self, _: str) -> None:
        self.psu.questionable = 0
        return None

    def _set_ovp(self, arg: str) -> None:
        v = self._parse_float(arg)
        if v is not None:
            self.psu.ovp_level = v
        return None

    def _set_uvl(self, arg: str) -> None:
        v = self._parse_float(arg)
        if v is not None:
            self.psu.uvl_level = v
        return None

    def _set_v_slew_up(self, arg: str) -> None:
        v = self._parse_float(arg)
        if v is not None:
            self.psu.v_slew_up = v
        return None

    def _set_v_slew_down(self, arg: str) -> None:
        v = self._parse_float(arg)
        if v is not None:
            self.psu.v_slew_down = v
        return None

    def _set_i_slew_up(self, arg: str) -> None:
        v = self._parse_float(arg)
        if v is not None:
            self.psu.i_slew_up = v
        return None

    def _set_i_slew_down(self, arg: str) -> None:
        v = self._parse_float(arg)
        if v is not None:
            self.psu.i_slew_down = v
        return None

    def _syst_err(self, _: str) -> str:
        if not self.psu.errors:
            return "0,\"No error\""
        return self.psu.errors.pop(0)


# ----------------------------------------------------------------------
# TCP server
# ----------------------------------------------------------------------

class ScpiTcpHandler(socketserver.BaseRequestHandler):
    """One instance per accepted TCP connection."""

    def handle(self) -> None:
        peer = f"{self.client_address[0]}:{self.client_address[1]}"
        log("CONN", f"open  <- {peer}", C.GREEN)
        self.request.settimeout(60.0)
        buf = bytearray()
        psu: Psu = self.server.psu          # type: ignore[attr-defined]
        handler: Handler = self.server.handler  # type: ignore[attr-defined]
        try:
            while True:
                try:
                    chunk = self.request.recv(1024)
                except socket.timeout:
                    # Real PSUs keep the socket open; keep waiting silently.
                    continue
                if not chunk:
                    break
                buf.extend(chunk)
                # SCPI line terminator is CRLF. Accept LF or CR too for
                # robustness against firmware framing changes.
                while True:
                    nl = -1
                    for sep in (b"\r\n", b"\n", b"\r"):
                        idx = buf.find(sep)
                        if idx >= 0 and (nl == -1 or idx < nl):
                            nl = idx
                            seplen = len(sep)
                    if nl < 0:
                        break
                    line = bytes(buf[:nl])
                    del buf[:nl + seplen]
                    text = line.decode("ascii", errors="replace").strip()
                    if not text:
                        continue
                    log("RX", f"{peer}  {text}", C.CYAN)
                    reply = handler.dispatch(text)
                    if reply is not None:
                        wire = (reply + "\r\n").encode("ascii")
                        try:
                            self.request.sendall(wire)
                            log("TX", f"{peer}  {reply}", C.YELLOW)
                        except OSError as exc:
                            log("ERR", f"{peer}  send failed: {exc}", C.RED)
                            return
        except (ConnectionResetError, ConnectionAbortedError, OSError) as exc:
            log("CONN", f"{peer}  closed: {exc.__class__.__name__}", C.MAGENTA)
        finally:
            log("CONN", f"close -> {peer}", C.MAGENTA)


class ThreadedTcpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


# ----------------------------------------------------------------------
# Library entry point: start the simulator in-process (for tests / embed)
# ----------------------------------------------------------------------

def build_server(
    host: str = "127.0.0.1",
    port: int = 0,
    psu: Psu | None = None,
) -> ThreadedTcpServer:
    """Build (but do not start) a ``ThreadedTcpServer`` bound to ``host:port``.

    Pass ``port=0`` to let the OS pick a free port — read it back from
    ``server.server_address[1]`` after binding. The returned server has
    ``server.psu`` and ``server.handler`` attributes attached so callers
    can drive PSU state from the test thread (e.g. inject faults).
    """
    psu = psu if psu is not None else Psu()
    handler = Handler(psu)
    server = ThreadedTcpServer((host, port), ScpiTcpHandler)
    server.psu = psu              # type: ignore[attr-defined]
    server.handler = handler      # type: ignore[attr-defined]
    return server


def serve_in_thread(
    host: str = "127.0.0.1",
    port: int = 0,
    psu: Psu | None = None,
) -> tuple[ThreadedTcpServer, threading.Thread]:
    """Start a simulator server in a background daemon thread.

    Returns ``(server, thread)``. The bound port lives at
    ``server.server_address[1]``; the simulated PSU instance lives at
    ``server.psu``. Call ``server.shutdown()`` then
    ``server.server_close()`` to stop.
    """
    server = build_server(host=host, port=port, psu=psu)
    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="genesys-sim",
    )
    thread.start()
    return server, thread


# ----------------------------------------------------------------------
# Serial responder (for manual serial-port testing via a com0com pair)
# ----------------------------------------------------------------------

def run_serial(port_name: str, baud: int, psu: Psu, handler: Handler) -> None:
    """Serve the same SCPI behaviour over a serial port instead of TCP.

    Point ComPort Zone at one end of a com0com virtual pair (or a real
    crossover) and run this on the other end. Frames on CR/LF/CRLF like the
    TCP handler and replies with ``<reply>\\r\\n``.
    """
    import serial  # local import: the TCP path doesn't need pyserial

    ser = serial.Serial(port_name, baudrate=baud, timeout=0.1)
    log("BOOT", f"GEN+ simulator on serial {port_name} @ {baud} baud", C.GREEN)
    log("BOOT", "Press Ctrl+C to stop.", C.DIM)
    buf = bytearray()
    try:
        while True:
            try:
                chunk = ser.read(ser.in_waiting or 1)
            except serial.SerialException as exc:
                log("ERR", f"{port_name}  read failed: {exc}", C.RED)
                break
            if not chunk:
                continue
            buf.extend(chunk)
            while True:
                nl = -1
                seplen = 1
                for sep in (b"\r\n", b"\n", b"\r"):
                    idx = buf.find(sep)
                    if idx >= 0 and (nl == -1 or idx < nl):
                        nl = idx
                        seplen = len(sep)
                if nl < 0:
                    break
                line = bytes(buf[:nl])
                del buf[:nl + seplen]
                text = line.decode("ascii", errors="replace").strip()
                if not text:
                    continue
                log("RX", f"{port_name}  {text}", C.CYAN)
                reply = handler.dispatch(text)
                if reply is not None:
                    ser.write((reply + "\r\n").encode("ascii"))
                    ser.flush()
                    log("TX", f"{port_name}  {reply}", C.YELLOW)
    except KeyboardInterrupt:
        log("BOOT", "Shutting down (Ctrl+C)", C.YELLOW)
    finally:
        ser.close()


# ----------------------------------------------------------------------
# CLI / entry point
# ----------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="GENESYS+ SCPI/TCP simulator for NextGenDisplay bench testing.",
    )
    p.add_argument("--host", default="0.0.0.0",
                   help="bind address (default: 0.0.0.0, all interfaces)")
    p.add_argument("--port", type=int, default=8003,
                   help="TCP port (default: 8003, matches firmware default)")
    p.add_argument("--serial", metavar="COMx",
                   help="serve over this serial port instead of TCP "
                        "(e.g. COM21, one end of a com0com pair)")
    p.add_argument("--baud", type=int, default=9600,
                   help="serial baud rate when --serial is used (default: 9600)")
    p.add_argument("--no-color", action="store_true",
                   help="disable ANSI colours in console output")
    p.add_argument("--inject-ov", action="store_true",
                   help="start with over-voltage fault bit asserted (STAT:QUES bit 4)")
    p.add_argument("--inject-ot", action="store_true",
                   help="start with over-temperature fault bit asserted (STAT:QUES bit 2)")
    args = p.parse_args(argv)

    if args.no_color or not sys.stdout.isatty():
        C.enabled = False

    psu = Psu()
    if args.inject_ov:
        psu.inject_fault(Psu.Q_OV)
    if args.inject_ot:
        psu.inject_fault(Psu.Q_OT)

    if args.serial:
        if args.inject_ov:
            log("BOOT", "Injected: OV fault bit asserted", C.RED)
        if args.inject_ot:
            log("BOOT", "Injected: OT fault bit asserted", C.RED)
        run_serial(args.serial, args.baud, psu, Handler(psu))
        return 0

    server = build_server(host=args.host, port=args.port, psu=psu)

    log("BOOT", f"GEN+ simulator listening on {args.host}:{args.port}", C.GREEN)
    log("BOOT", "Press Ctrl+C to stop. Every command/response will be logged below.",
        C.DIM)
    if args.inject_ov:
        log("BOOT", "Injected: OV fault bit asserted", C.RED)
    if args.inject_ot:
        log("BOOT", "Injected: OT fault bit asserted", C.RED)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("BOOT", "Shutting down (Ctrl+C)", C.YELLOW)
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
