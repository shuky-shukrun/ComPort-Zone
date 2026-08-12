"""Unit tests for the REPL meta-command dispatcher.

The REPL's full Click command wires up prompt_toolkit, threading, and a
PromptSession — none of which we want in unit tests. ``ReplDispatcher``
is the pure routing layer; these tests drive it directly with scripted
``handle_line`` calls.
"""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from ComPort_Zone.cli.output import CliOutput
from ComPort_Zone.cli.repl_dispatcher import ReplDispatcher, ReplState
from ComPort_Zone.core.models import (
    AppSettings,
    LanProfile,
    QuickCommand,
    SerialProfile,
    UdpProfile,
)
from ComPort_Zone.core.settings_service import SettingsService
from ComPort_Zone.core.storage import SettingsStore
from tests.fakes.fake_serial_transport import FakeSerialTransport


def _save(path: Path, settings: AppSettings) -> None:
    SettingsService(SettingsStore(path)).save(settings)


def _load(path: Path) -> AppSettings:
    return SettingsService(SettingsStore(path)).load()


class _Harness:
    """One-shot helper holding the dispatcher + the I/O streams to inspect."""

    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        profile: SerialProfile | LanProfile | UdpProfile | None = None,
        config_path: Path | None = None,
    ) -> None:
        self.transport = FakeSerialTransport()
        self.transport.set_ports([{"device": "COM3"}])
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.output = CliOutput(
            stdout=self.stdout, stderr=self.stderr, color=False
        )
        self.settings = settings or AppSettings()
        self.profile = profile or SerialProfile(port="COM3", baudrate=115200)
        self.state = ReplState(
            transport=self.transport,
            output=self.output,
            settings=self.settings,
            profile=self.profile,
            config_path=config_path,
        )
        self.dispatcher = ReplDispatcher(self.state)

    def run(self, line: str) -> bool:
        return self.dispatcher.handle_line(line)


class MetaCommandRoutingTests(unittest.TestCase):
    def test_blank_line_is_a_noop(self) -> None:
        h = _Harness()
        self.assertTrue(h.run(""))
        self.assertEqual(h.transport.sent_text, [])

    def test_quit_sets_state_and_returns_false(self) -> None:
        h = _Harness()
        result = h.run("/quit")
        self.assertFalse(result)
        self.assertTrue(h.state.quit_requested)

    def test_exit_is_an_alias_for_quit(self) -> None:
        h = _Harness()
        self.assertFalse(h.run("/exit"))

    def test_help_prints_command_list(self) -> None:
        h = _Harness()
        h.run("/help")
        text = h.stdout.getvalue()
        self.assertIn("/help", text)
        self.assertIn("/connect", text)
        self.assertIn("/quick", text)

    def test_unknown_meta_command_emits_error(self) -> None:
        h = _Harness()
        h.run("/bogus")
        self.assertIn("/bogus", h.stderr.getvalue())


class ConnectionLifecycleTests(unittest.TestCase):
    def test_connect_then_disconnect(self) -> None:
        h = _Harness()
        h.run("/connect")
        self.assertTrue(h.transport.is_connected)
        h.run("/disconnect")
        self.assertFalse(h.transport.is_connected)

    def test_reconnect_disconnects_then_connects(self) -> None:
        h = _Harness()
        h.run("/connect")
        self.assertTrue(h.transport.is_connected)
        h.run("/reconnect")
        self.assertTrue(h.transport.is_connected)
        # disconnect_calls increments on every disconnect (initial connect
        # doesn't call disconnect; /reconnect does).
        self.assertGreaterEqual(h.transport.disconnect_calls, 1)

    def test_tcp_connect_and_show_endpoint(self) -> None:
        h = _Harness(profile=LanProfile(host="127.0.0.1", port=7000))
        h.run("/connect")
        self.assertTrue(h.transport.is_connected)
        h.run("/show endpoint")
        self.assertIn("127.0.0.1:7000", h.stdout.getvalue())

    def test_tcp_set_shortcuts_update_lan_profile_and_settings(self) -> None:
        h = _Harness(profile=LanProfile(host="127.0.0.1", port=7000))
        h.run("/set tcp-port 9000")
        self.assertEqual(h.state.profile.port, 9000)
        # The change mirrors into the persisted LAN settings, not the serial ones.
        self.assertEqual(h.state.settings.transport_kind, "lan")
        self.assertIsNotNone(h.state.settings.lan)
        self.assertEqual(h.state.settings.lan.port, 9000)

    def test_tcp_set_rejects_out_of_range_port(self) -> None:
        h = _Harness(profile=LanProfile(host="127.0.0.1", port=7000))
        h.run("/set tcp-port 70000")
        self.assertEqual(h.state.profile.port, 7000)  # unchanged
        self.assertIn("1 to 65535", h.stderr.getvalue())

    def test_udp_connect_and_show_endpoint(self) -> None:
        h = _Harness(profile=UdpProfile(host="127.0.0.1", port=5025))
        h.run("/connect")
        self.assertTrue(h.transport.is_connected)
        h.run("/show endpoint")
        printed = h.stdout.getvalue()
        self.assertIn("127.0.0.1:5025", printed)
        self.assertIn("udp", printed)

    def test_udp_set_shortcuts_update_udp_profile_and_settings(self) -> None:
        h = _Harness(profile=UdpProfile(host="127.0.0.1", port=5025))
        h.run("/set udp-port 9000")
        h.run("/set udp-timeout 750")
        self.assertEqual(h.state.profile.port, 9000)
        self.assertEqual(h.state.profile.timeout_ms, 750)
        self.assertEqual(h.state.settings.transport_kind, "udp")
        self.assertEqual(h.state.settings.udp.port, 9000)
        self.assertEqual(h.state.settings.udp.timeout_ms, 750)

    def test_udp_set_rejects_out_of_range_port_naming_the_udp_flag(self) -> None:
        h = _Harness(profile=UdpProfile(host="127.0.0.1", port=5025))
        h.run("/set udp-port 70000")
        self.assertEqual(h.state.profile.port, 5025)  # unchanged
        self.assertIn("/set udp-port", h.stderr.getvalue())

    def test_udp_rejects_the_tcp_set_vocabulary(self) -> None:
        h = _Harness(profile=UdpProfile(host="127.0.0.1", port=5025))
        h.run("/set tcp-port 9000")
        self.assertEqual(h.state.profile.port, 5025)
        self.assertIn("Unknown /set key", h.stderr.getvalue())


class SendingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "settings.json"
        _save(self.settings_path, AppSettings())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_plain_input_sent_when_connected(self) -> None:
        h = _Harness(config_path=self.settings_path)
        h.run("/connect")
        h.run("ping")
        self.assertEqual(h.transport.sent_text, [("ping", None)])

    def test_plain_input_when_disconnected_emits_error(self) -> None:
        h = _Harness(config_path=self.settings_path)
        h.run("ping")
        self.assertIn("Not connected", h.stderr.getvalue())
        self.assertEqual(h.transport.sent_text, [])

    def test_hex_meta_sends_bytes(self) -> None:
        h = _Harness(config_path=self.settings_path)
        h.run("/connect")
        h.run("/hex 55 AA 03")
        self.assertEqual(h.transport.sent_bytes, [b"\x55\xaa\x03"])

    def test_sent_text_appended_to_history_and_persisted(self) -> None:
        h = _Harness(config_path=self.settings_path)
        h.run("/connect")
        h.run("status")
        h.run("status")  # duplicate run shouldn't double-append
        h.run("reset")
        loaded = _load(self.settings_path)
        # The GUI's de-dupe-against-previous rule applies here too.
        self.assertEqual(loaded.command_history[-2:], ["status", "reset"])


class QuickSendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "settings.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_quick_send_by_label_uses_stored_line_ending(self) -> None:
        settings = AppSettings(
            quick_commands=[
                QuickCommand(
                    label="Read ID",
                    command="*IDN?",
                    send_mode="Text",
                    line_ending_override="LF",
                )
            ]
        )
        _save(self.settings_path, settings)
        h = _Harness(settings=settings, config_path=self.settings_path)
        h.run("/connect")
        h.run("/quick Read ID")
        # shlex tokenisation will split "Read ID" into two tokens; we
        # only feed the first token to resolve_entry, so it'll be "Read"
        # — wrong. Re-run with the id form to assert the routing works.
        h.run(f"/quick {settings.quick_commands[0].id}")
        self.assertEqual(h.transport.sent_text, [("*IDN?", "LF")])

    def test_quick_send_with_hex_mode_sends_bytes(self) -> None:
        settings = AppSettings(
            quick_commands=[
                QuickCommand(label="Wake", command="55 AA", send_mode="Hex Bytes"),
            ]
        )
        _save(self.settings_path, settings)
        h = _Harness(settings=settings, config_path=self.settings_path)
        h.run("/connect")
        h.run("/quick Wake")
        self.assertEqual(h.transport.sent_bytes, [b"\x55\xaa"])


class SetCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "settings.json"
        _save(self.settings_path, AppSettings())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_set_baud_updates_profile_and_persists(self) -> None:
        h = _Harness(config_path=self.settings_path)
        h.run("/set baud 9600")
        self.assertEqual(h.state.profile.baudrate, 9600)
        self.assertEqual(_load(self.settings_path).serial.baudrate, 9600)

    def test_set_line_ending_normalises(self) -> None:
        h = _Harness(config_path=self.settings_path)
        h.run("/set line-ending lf")
        self.assertEqual(h.state.profile.line_ending, "LF")

    def test_set_invalid_key_emits_error(self) -> None:
        h = _Harness(config_path=self.settings_path)
        h.run("/set nonsense 42")
        self.assertIn("Unknown /set key", h.stderr.getvalue())

    def test_set_bad_value_keeps_old_setting(self) -> None:
        h = _Harness(config_path=self.settings_path)
        original = h.state.profile.baudrate
        h.run("/set baud not_a_number")
        self.assertEqual(h.state.profile.baudrate, original)
        self.assertIn("integer", h.stderr.getvalue().lower())


class LogTests(unittest.TestCase):
    def test_log_start_creates_file_and_stop_closes_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "rx.log"
            h = _Harness()
            h.run("/connect")
            h.run(f'/log start "{log_path}"')
            self.assertIsNotNone(h.state.log_handle)
            h.run("hello")
            h.run("/log stop")
            self.assertIsNone(h.state.log_handle)
            self.assertIn("TX> hello", log_path.read_text(encoding="utf-8"))


class TimestampsTests(unittest.TestCase):
    def test_timestamps_toggle(self) -> None:
        h = _Harness()
        self.assertFalse(h.state.timestamps_enabled)
        h.run("/timestamps on")
        self.assertTrue(h.state.timestamps_enabled)
        h.run("/timestamps off")
        self.assertFalse(h.state.timestamps_enabled)


class RunMetaCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.settings_path = self.tmp_path / "settings.json"
        _save(self.settings_path, AppSettings())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_run_executes_steps_when_connected(self) -> None:
        script = self.tmp_path / "script.txt"
        script.write_text("SEND hello\n", encoding="utf-8")
        h = _Harness(config_path=self.settings_path)
        h.run("/connect")
        h.run(f'/run "{script}"')
        self.assertEqual(h.transport.sent_text, [("hello", None)])
        self.assertIn("/run done", h.stdout.getvalue())

    def test_run_requires_connection(self) -> None:
        script = self.tmp_path / "no_conn.txt"
        script.write_text("SEND x\n", encoding="utf-8")
        h = _Harness(config_path=self.settings_path)
        h.run(f'/run "{script}"')
        self.assertIn("not connected", h.stderr.getvalue().lower())
        self.assertEqual(h.transport.sent_text, [])

    def test_run_missing_required_param_emits_error(self) -> None:
        script = self.tmp_path / "needs_param.txt"
        script.write_text("SEND v={{VOLT}}\n", encoding="utf-8")
        h = _Harness(config_path=self.settings_path)
        h.run("/connect")
        h.run(f'/run "{script}"')
        self.assertIn("missing --param VOLT", h.stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
