"""Tests for the GENESYS+ SCPI/TCP simulator in ``tools/genesys_sim.py``.

The simulator is the project's bench-testing fake for TDK-Lambda GENESYS+
power supplies. It backs:

* the ``examples/tdk-genplus-control-panel.json`` panel sample,
* the LAN code path in :mod:`ComPort_Zone.lan_core`,
* manual bench-testing of the desktop app against a known-good fake.

These tests cover three layers:

1. ``Psu`` state physics + fault latching (no socket, no threading).
2. ``Handler.dispatch`` over the SCPI command surface (still in-process).
3. End-to-end TCP round-trip through ``serve_in_thread`` driven by the
   real :class:`ComPort_Zone.lan_core.LanClient`, including multi-line
   framing and the ``SOUR:`` subsystem prefix fallback the panel relies
   on.
"""

from __future__ import annotations

import importlib.util
import socket
import time
import unittest
from pathlib import Path
from queue import Empty, Queue

from ComPort_Zone.lan_core import LanClient
from ComPort_Zone.models import LanProfile
from ComPort_Zone.serial_core import SerialEvent

# The simulator lives at ``tools/genesys_sim.py`` — outside the installed
# ``ComPort_Zone`` package — so we load it by file path rather than touching
# ``sys.path``. Keeps the test self-contained and means we don't have to
# turn ``tools/`` into a Python package just for tests.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SIM_PATH = _REPO_ROOT / "tools" / "genesys_sim.py"


def _load_simulator():
    spec = importlib.util.spec_from_file_location("genesys_sim", _SIM_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load simulator from {_SIM_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


genesys_sim = _load_simulator()
Psu = genesys_sim.Psu
Handler = genesys_sim.Handler
serve_in_thread = genesys_sim.serve_in_thread
_normalize = genesys_sim._normalize
_short = genesys_sim._short


# ----------------------------------------------------------------------
# Layer 1: Psu state physics
# ----------------------------------------------------------------------


class PsuStateTests(unittest.TestCase):
    def test_defaults_match_expected_profile(self) -> None:
        psu = Psu()
        self.assertEqual(psu.address, 0)
        self.assertFalse(psu.output_on)
        self.assertAlmostEqual(psu.v_set, 12.0)
        self.assertAlmostEqual(psu.i_set, 1.0)
        self.assertEqual(psu.foldback_mode, "OFF")
        self.assertEqual(psu.questionable, 0)
        self.assertEqual(psu.questionable_injected, 0)

    def test_measured_values_are_zero_when_output_is_off(self) -> None:
        psu = Psu()
        psu.v_set = 5.0
        psu.i_set = 2.0
        self.assertEqual(psu._measured_v(), 0.0)
        self.assertEqual(psu._measured_i(), 0.0)
        self.assertEqual(psu._mode(), "OFF")
        self.assertEqual(psu._oper() & Psu.O_OUT_ON, 0)

    def test_cv_mode_when_load_does_not_saturate_current_limit(self) -> None:
        psu = Psu()
        psu.v_set = 5.0       # 5 V / 10 Ω = 0.5 A measured
        psu.i_set = 2.0       # well above 0.5 A
        psu.output_on = True
        self.assertEqual(psu._mode(), "CV")
        self.assertAlmostEqual(psu._measured_i(), 0.5)
        oper = psu._oper()
        self.assertTrue(oper & Psu.O_OUT_ON)
        self.assertTrue(oper & Psu.O_CV)
        self.assertFalse(oper & Psu.O_CC)

    def test_cc_mode_when_load_pulls_current_limit(self) -> None:
        psu = Psu()
        psu.v_set = 30.0      # would draw 3 A through 10 Ω
        psu.i_set = 1.0       # limit far below
        psu.output_on = True
        self.assertEqual(psu._mode(), "CC")
        self.assertAlmostEqual(psu._measured_i(), 1.0)
        self.assertTrue(psu._oper() & Psu.O_CC)
        self.assertFalse(psu._oper() & Psu.O_CV)

    def test_ovp_trip_latches_and_forces_output_off(self) -> None:
        psu = Psu()
        psu.ovp_level = 10.0
        psu.v_set = 11.0
        psu.output_on = True
        bits = psu._ques()
        self.assertTrue(bits & Psu.Q_OV)
        self.assertFalse(psu.output_on)
        # Latched — bit is still set even though output is off and the
        # trip condition is gone.
        psu.v_set = 5.0
        bits_again = psu._ques()
        self.assertTrue(bits_again & Psu.Q_OV)

    def test_uvp_trip_latches_and_forces_output_off(self) -> None:
        psu = Psu()
        psu.uvl_level = 5.0
        psu.v_set = 3.0
        psu.output_on = True
        bits = psu._ques()
        self.assertTrue(bits & Psu.Q_UV)
        self.assertFalse(psu.output_on)

    def test_injected_faults_appear_in_ques_but_survive_cls(self) -> None:
        psu = Psu()
        psu.inject_fault(Psu.Q_OT | Psu.Q_AC)
        bits = psu._ques()
        self.assertTrue(bits & Psu.Q_OT)
        self.assertTrue(bits & Psu.Q_AC)
        # *CLS doesn't clear injected faults — they're a separate channel.
        psu.questionable = 0
        self.assertTrue(psu._ques() & Psu.Q_OT)
        # clear_injected_faults() with a mask is selective.
        psu.clear_injected_faults(Psu.Q_OT)
        bits = psu._ques()
        self.assertFalse(bits & Psu.Q_OT)
        self.assertTrue(bits & Psu.Q_AC)
        # ...without a mask, clears everything injected.
        psu.clear_injected_faults()
        self.assertEqual(psu._ques(), 0)

    def test_ques_bits_match_panel_json_numbering(self) -> None:
        # The example panel at examples/tdk-genplus-control-panel.json maps
        # bit 3 to "Foldback" and bit 4 to "Over-voltage". Regression for
        # the duplicate Q_FOLD constant (10 vs 3) the simulator used to
        # carry — second definition silently overrode the first.
        self.assertEqual(Psu.Q_FOLD, 1 << 3)
        self.assertEqual(Psu.Q_OV, 1 << 4)
        self.assertEqual(Psu.Q_OT, 1 << 2)
        self.assertEqual(Psu.Q_UV, 1 << 9)

    def test_reset_rolls_state_back_to_defaults(self) -> None:
        psu = Psu()
        psu.v_set = 42.0
        psu.output_on = True
        psu.questionable = Psu.Q_OV
        psu.inject_fault(Psu.Q_AC)
        psu.errors.append("garbage")
        psu.reset()
        self.assertAlmostEqual(psu.v_set, 12.0)
        self.assertFalse(psu.output_on)
        self.assertEqual(psu.questionable, 0)
        self.assertEqual(psu.questionable_injected, 0)
        self.assertEqual(psu.errors, [])


# ----------------------------------------------------------------------
# Layer 2: SCPI normalization + dispatch (no socket)
# ----------------------------------------------------------------------


class ScpiNormalizeTests(unittest.TestCase):
    def test_short_form_collapses_lowercase_suffixes(self) -> None:
        self.assertEqual(_short("SOURce"), "SOUR")
        self.assertEqual(_short("VOLTage"), "VOLT")
        self.assertEqual(_short("PROTection"), "PROT")
        self.assertEqual(_short("LEVel"), "LEV")
        self.assertEqual(_short("ALREADYSHORT"), "ALREADYSHORT")

    def test_normalize_handles_full_and_short_paths(self) -> None:
        for raw, expected in [
            ("*IDN?", ("*IDN?", "")),
            ("SOURce:VOLTage 12.5", ("SOUR:VOLT", "12.5")),
            ("SOUR:VOLT 12.5", ("SOUR:VOLT", "12.5")),
            ("MEASure:VOLTage?", ("MEAS:VOLT?", "")),
            ("OUTPut:PROTection:LOW:LEVel 1.0", ("OUTP:PROT:LOW:LEV", "1.0")),
            ("STATus:QUEStionable:CONDition?", ("STAT:QUES:COND?", "")),
            ("OUTP ON", ("OUTP", "ON")),
            (" VOLT  3.3 ", ("VOLT", "3.3")),
            ("INST:NSEL 7;", ("INST:NSEL", "7")),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(_normalize(raw), expected)


class HandlerDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.psu = Psu()
        self.handler = Handler(self.psu)

    def reply(self, raw: str) -> str | None:
        return self.handler.dispatch(raw)

    def test_idn_string_identifies_a_tdk_lambda_unit(self) -> None:
        idn = self.reply("*IDN?")
        self.assertIsNotNone(idn)
        self.assertIn("TDK-LAMBDA", idn or "")
        # Four comma-separated fields per IEEE 488.2 *IDN? response.
        self.assertEqual(len((idn or "").split(",")), 4)

    def test_setpoints_round_trip_via_short_and_long_forms(self) -> None:
        self.assertIsNone(self.reply("SOURce:VOLTage 7.5"))
        self.assertEqual(self.reply("VOLT?"), "7.500")
        self.assertIsNone(self.reply("CURR 0.75"))
        self.assertEqual(self.reply("SOUR:CURR?"), "0.750")
        self.assertIsNone(self.reply("POW 250"))
        self.assertEqual(self.reply("SOUR:POW:LEV?"), "250.000")

    def test_setpoints_are_clamped_to_rated_envelope(self) -> None:
        self.reply("VOLT 9999")
        self.assertAlmostEqual(self.psu.v_set, Psu.V_MAX)
        self.reply("VOLT -1")
        self.assertEqual(self.psu.v_set, 0.0)
        self.reply("CURR 9999")
        self.assertAlmostEqual(self.psu.i_set, Psu.I_MAX)

    def test_output_state_toggles_on_off_and_meas_tracks_setpoint(self) -> None:
        self.reply("VOLT 5.0")
        self.reply("CURR 2.0")
        self.assertEqual(self.reply("MEAS:VOLT?"), "0.000")  # output off
        self.reply("OUTP ON")
        self.assertEqual(self.reply("OUTP?"), "1")
        self.assertEqual(self.reply("MEAS:VOLT?"), "5.000")
        # 5 V / 10 Ω = 0.5 A, well below the 2 A limit -> CV mode
        self.assertEqual(self.reply("MEAS:CURR?"), "0.500")
        self.assertEqual(self.reply("OUTP:MODE?"), "CV")
        # Measured power should be V * I
        self.assertEqual(self.reply("MEAS:POW?"), "2.500")
        self.reply("OUTP OFF")
        self.assertEqual(self.reply("OUTP:STAT?"), "0")
        self.assertEqual(self.reply("MEAS:VOLT?"), "0.000")

    def test_unknown_command_queues_syst_err(self) -> None:
        self.assertIsNone(self.reply("NOPE:NOTHING 1"))
        err = self.reply("SYST:ERR?")
        self.assertIsNotNone(err)
        self.assertIn("-113", err or "")
        # Queue empties after read.
        self.assertEqual(self.reply("SYST:ERR?"), '0,"No error"')

    def test_sour_subsystem_prefix_is_implicit(self) -> None:
        # Regression for the SOUR-prefix-fallback added to support the
        # panel JSON, which sends ``VOLT:PROT:LEV`` without ``SOUR:``.
        self.assertIsNone(self.reply("VOLT:PROT:LEV 12.5"))
        self.assertAlmostEqual(self.psu.ovp_level, 12.5)
        self.assertEqual(self.reply("VOLT:PROT:LEV?"), "12.500")
        self.assertIsNone(self.reply("VOLT:PROT:LOW:LEV 1.5"))
        self.assertAlmostEqual(self.psu.uvl_level, 1.5)
        self.assertEqual(self.reply("VOLT:PROT:LOW:LEV?"), "1.500")
        self.assertIsNone(self.reply("VOLT:SLEW:UP 4.2"))
        self.assertAlmostEqual(self.psu.v_slew_up, 4.2)
        self.assertEqual(self.reply("CURR:SLEW:DOWN?"), "1.000")

    def test_instrument_address_round_trip_and_clamping(self) -> None:
        self.assertIsNone(self.reply("INST:NSEL 7"))
        self.assertEqual(self.reply("INST:NSEL?"), "7")
        # Out of range — silently ignored, address stays at last good value.
        self.reply("INST:NSEL 50")
        self.assertEqual(self.psu.address, 7)
        self.reply("INST:NSEL -1")
        self.assertEqual(self.psu.address, 7)

    def test_foldback_round_trips_and_rejects_garbage(self) -> None:
        for mode in ("OFF", "CC", "CV"):
            self.reply(f"OUTP:PROT:FOLD {mode}")
            self.assertEqual(self.reply("OUTP:PROT:FOLD?"), mode)
        # Garbage doesn't change the current setting.
        self.reply("OUTP:PROT:FOLD BOGUS")
        self.assertEqual(self.psu.foldback_mode, "CV")

    def test_ieee_488_stubs_and_syst_vers(self) -> None:
        self.assertEqual(self.reply("*OPC?"), "1")
        self.assertIsNone(self.reply("*OPC"))
        self.assertIsNone(self.reply("*WAI"))
        self.assertEqual(self.reply("*TST?"), "0")
        self.assertEqual(self.reply("SYST:VERS?"), "1999.0")

    def test_rst_clears_output_and_questionable_register(self) -> None:
        self.reply("OUTP ON")
        self.psu.questionable = Psu.Q_OT
        self.reply("*RST")
        self.assertFalse(self.psu.output_on)
        self.assertEqual(self.psu.questionable, 0)


# ----------------------------------------------------------------------
# Layer 2b: Fault paths + status registers
# ----------------------------------------------------------------------


class HandlerFaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.psu = Psu()
        self.handler = Handler(self.psu)

    def test_ques_register_reports_injected_bits(self) -> None:
        self.psu.inject_fault(Psu.Q_OT)
        self.assertEqual(self.handler.dispatch("STAT:QUES:COND?"), str(Psu.Q_OT))

    def test_cls_clears_latched_register_but_not_injected_bits(self) -> None:
        self.psu.questionable = Psu.Q_OV
        self.psu.inject_fault(Psu.Q_OT)
        self.handler.dispatch("*CLS")
        # Latched OV cleared, OT (injected) still asserted.
        bits = int(self.handler.dispatch("STAT:QUES:COND?") or "0")
        self.assertFalse(bits & Psu.Q_OV)
        self.assertTrue(bits & Psu.Q_OT)

    def test_outp_prot_cle_clears_latched_register(self) -> None:
        self.psu.questionable = Psu.Q_OV | Psu.Q_UV
        self.handler.dispatch("OUTP:PROT:CLE")
        bits = int(self.handler.dispatch("STAT:QUES:COND?") or "0")
        self.assertEqual(bits, 0)

    def test_ovp_drive_via_scpi_trips_and_latches(self) -> None:
        self.handler.dispatch("VOLT:PROT:LEV 5.0")
        self.handler.dispatch("VOLT 7.0")
        self.handler.dispatch("OUTP ON")
        bits = int(self.handler.dispatch("STAT:QUES:COND?") or "0")
        self.assertTrue(bits & Psu.Q_OV)
        self.assertEqual(self.handler.dispatch("OUTP?"), "0")
        # Even after lowering V back below OVP and turning output on again,
        # the latched bit survives until *CLS.
        self.handler.dispatch("VOLT 3.0")
        bits = int(self.handler.dispatch("STAT:QUES:COND?") or "0")
        self.assertTrue(bits & Psu.Q_OV)
        self.handler.dispatch("*CLS")
        bits = int(self.handler.dispatch("STAT:QUES:COND?") or "0")
        self.assertFalse(bits & Psu.Q_OV)

    def test_oper_register_tracks_output_and_mode(self) -> None:
        # Output off -> register clear
        self.assertEqual(self.handler.dispatch("STAT:OPER:COND?"), "0")
        self.handler.dispatch("VOLT 5.0")
        self.handler.dispatch("CURR 5.0")  # well above 0.5 A measured -> CV
        self.handler.dispatch("OUTP ON")
        bits = int(self.handler.dispatch("STAT:OPER:COND?") or "0")
        self.assertTrue(bits & Psu.O_OUT_ON)
        self.assertTrue(bits & Psu.O_CV)
        self.assertFalse(bits & Psu.O_CC)


# ----------------------------------------------------------------------
# Layer 3: end-to-end TCP, driven by the project's LanClient
# ----------------------------------------------------------------------


class _RxLineReader:
    """Pull ``\\r\\n``-terminated lines off an RX event queue.

    Keeps an inter-call residual buffer so that two replies arriving in
    one TCP recv (common on localhost) still yield two separate lines
    across consecutive ``readline`` calls.
    """

    def __init__(self, events: Queue[SerialEvent]) -> None:
        self.events = events
        self._buf = ""

    def readline(self, timeout: float = 2.0) -> str:
        deadline = time.monotonic() + timeout
        while True:
            if "\r\n" in self._buf:
                line, self._buf = self._buf.split("\r\n", 1)
                return line
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(
                    f"Timed out waiting for RX line (residual {self._buf!r})"
                )
            try:
                event = self.events.get(timeout=min(remaining, 0.05))
            except Empty:
                continue
            if event.kind == "rx":
                self._buf += event.message


class SimulatorTcpTests(unittest.TestCase):
    """End-to-end smoke tests through a live TCP socket.

    The :meth:`tearDown` shuts the server down so each test gets a fresh
    Psu/Handler, and the TCP port is OS-assigned so two runs never
    collide on port 8003 or on a CI matrix.
    """

    def setUp(self) -> None:
        self.server, self.thread = serve_in_thread(host="127.0.0.1", port=0)
        self.port: int = self.server.server_address[1]
        self.psu: Psu = self.server.psu  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)

    def _connected_client(self) -> tuple[LanClient, _RxLineReader]:
        client = LanClient()
        events = client.subscribe_events()
        ok = client.connect(
            LanProfile(
                host="127.0.0.1",
                port=self.port,
                line_ending="CRLF",
                timeout_ms=500,
                auto_reconnect=False,
            )
        )
        self.assertTrue(ok, "Initial TCP connect to simulator failed")
        return client, _RxLineReader(events)

    def test_idn_round_trip_over_tcp(self) -> None:
        client, rx = self._connected_client()
        try:
            client.send_text("*IDN?")
            self.assertIn("TDK-LAMBDA", rx.readline())
        finally:
            client.disconnect()

    def test_setpoint_and_measurement_round_trip(self) -> None:
        client, rx = self._connected_client()
        try:
            client.send_text("VOLT 4.2")
            client.send_text("CURR 2.5")
            client.send_text("OUTP ON")
            client.send_text("MEAS:VOLT?")
            self.assertEqual(rx.readline(), "4.200")
            client.send_text("MEAS:CURR?")
            self.assertEqual(rx.readline(), "0.420")  # 4.2 V / 10 Ω
            client.send_text("OUTP:MODE?")
            self.assertEqual(rx.readline(), "CV")
        finally:
            client.disconnect()

    def test_injected_fault_visible_over_tcp_and_clearable(self) -> None:
        # Inject from the test thread before the firmware-side polls.
        self.psu.inject_fault(Psu.Q_OT)
        client, rx = self._connected_client()
        try:
            client.send_text("STAT:QUES:COND?")
            self.assertEqual(int(rx.readline()), Psu.Q_OT)
            # *CLS doesn't clear injected (per Psu semantics)...
            client.send_text("*CLS")
            client.send_text("STAT:QUES:COND?")
            self.assertEqual(int(rx.readline()), Psu.Q_OT)
            # ...but the test can.
            self.psu.clear_injected_faults()
            client.send_text("STAT:QUES:COND?")
            self.assertEqual(int(rx.readline()), 0)
        finally:
            client.disconnect()

    def test_multiple_commands_in_one_frame_are_split(self) -> None:
        # The handler's line splitter accepts \r\n, \n, and \r — send a
        # raw frame mixing terminators and confirm every reply lands.
        client, rx = self._connected_client()
        try:
            # send_bytes bypasses LanClient's CRLF appending, so we can put
            # whatever terminators we want on the wire.
            client.send_bytes(b"*IDN?\nVOLT 3.3\rVOLT?\r\n")
            # Expect two response lines in order: IDN, then 3.300.
            self.assertIn("TDK-LAMBDA", rx.readline())
            self.assertEqual(rx.readline(), "3.300")
            self.assertAlmostEqual(self.psu.v_set, 3.3)
        finally:
            client.disconnect()

    def test_panel_style_sour_omitted_command_succeeds_over_tcp(self) -> None:
        # The example panel sends ``VOLT:PROT:LEV {value}`` without
        # ``SOUR:`` — the SOUR-fallback in dispatch() should let this
        # land in the OVP setter.
        client, rx = self._connected_client()
        try:
            client.send_text("VOLT:PROT:LEV 25.5")
            client.send_text("VOLT:PROT:LEV?")
            self.assertEqual(rx.readline(), "25.500")
            self.assertAlmostEqual(self.psu.ovp_level, 25.5)
        finally:
            client.disconnect()


# ----------------------------------------------------------------------
# Layer 3b: raw socket smoke for framing edge cases
# ----------------------------------------------------------------------


class SimulatorRawSocketTests(unittest.TestCase):
    """Drive the server with a bare TCP socket — useful for framing checks
    that don't fit LanClient's line-oriented send_text API."""

    def setUp(self) -> None:
        self.server, self.thread = serve_in_thread(host="127.0.0.1", port=0)
        self.port: int = self.server.server_address[1]
        self.psu: Psu = self.server.psu  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)

    def _connect(self) -> socket.socket:
        s = socket.create_connection(("127.0.0.1", self.port), timeout=2.0)
        s.settimeout(2.0)
        return s

    @staticmethod
    def _recv_until_crlf(sock: socket.socket, expected_lines: int) -> list[str]:
        buf = b""
        lines: list[str] = []
        deadline = time.monotonic() + 2.0
        while len(lines) < expected_lines and time.monotonic() < deadline:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                break
            buf += chunk
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                lines.append(line.decode("ascii", errors="replace"))
        return lines

    def test_empty_lines_are_skipped(self) -> None:
        sock = self._connect()
        try:
            sock.sendall(b"\r\n\r\n*IDN?\r\n")
            lines = self._recv_until_crlf(sock, 1)
            self.assertEqual(len(lines), 1)
            self.assertIn("TDK-LAMBDA", lines[0])
        finally:
            sock.close()

    def test_mixed_line_endings_in_one_packet(self) -> None:
        sock = self._connect()
        try:
            sock.sendall(b"VOLT 9.0\n*IDN?\rVOLT?\r\n")
            lines = self._recv_until_crlf(sock, 2)
            self.assertEqual(len(lines), 2)
            self.assertIn("TDK-LAMBDA", lines[0])
            self.assertEqual(lines[1], "9.000")
        finally:
            sock.close()

    def test_write_only_command_emits_no_reply(self) -> None:
        sock = self._connect()
        try:
            sock.sendall(b"VOLT 1.1\r\n")
            # Quick deadline — no reply should be in flight.
            sock.settimeout(0.3)
            with self.assertRaises(socket.timeout):
                sock.recv(64)
            self.assertAlmostEqual(self.psu.v_set, 1.1)
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
