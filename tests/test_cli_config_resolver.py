"""Tests for the flag > env > settings > fallback precedence in
``ComPort_Zone.cli.config_resolver.resolve_serial_profile``.

This is the resolver every connect-using subcommand relies on; a wrong
choice here makes every CLI invocation use the wrong port/baud silently.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from ComPort_Zone.cli.config_resolver import (
    load_app_settings,
    resolve_lan_profile,
    resolve_serial_profile,
)
from ComPort_Zone.core.models import AppSettings, LanProfile, SerialProfile


def _empty_settings() -> AppSettings:
    return AppSettings(serial=SerialProfile())


def _settings_with(**fields) -> AppSettings:
    return AppSettings(serial=SerialProfile(**fields))


def _scrub_env() -> dict[str, str]:
    """Build a clean env minus any COMPORTZONE_* leaks from the host."""
    return {k: v for k, v in os.environ.items() if not k.startswith("COMPORTZONE_")}


class FlagWinsTests(unittest.TestCase):
    def test_port_flag_overrides_env_and_settings(self) -> None:
        env = _scrub_env() | {"COMPORTZONE_PORT": "COM_env"}
        settings = _settings_with(port="COM_settings", baudrate=9600)
        with patch.dict(os.environ, env, clear=True):
            profile = resolve_serial_profile(settings=settings, port="COM_flag")
        self.assertEqual(profile.port, "COM_flag")

    def test_baud_flag_overrides_env_and_settings(self) -> None:
        env = _scrub_env() | {"COMPORTZONE_BAUD": "57600"}
        settings = _settings_with(baudrate=9600)
        with patch.dict(os.environ, env, clear=True):
            profile = resolve_serial_profile(settings=settings, baud=115200)
        self.assertEqual(profile.baudrate, 115200)

    def test_line_ending_flag_overrides_env_and_settings(self) -> None:
        env = _scrub_env() | {"COMPORTZONE_LINE_ENDING": "lf"}
        settings = _settings_with(line_ending="None")
        with patch.dict(os.environ, env, clear=True):
            profile = resolve_serial_profile(settings=settings, line_ending="CRLF")
        self.assertEqual(profile.line_ending, "CRLF")


class EnvWinsOverSettingsTests(unittest.TestCase):
    def test_env_port_used_when_flag_absent(self) -> None:
        env = _scrub_env() | {"COMPORTZONE_PORT": "COM_env"}
        settings = _settings_with(port="COM_settings")
        with patch.dict(os.environ, env, clear=True):
            profile = resolve_serial_profile(settings=settings)
        self.assertEqual(profile.port, "COM_env")

    def test_env_baud_used_when_flag_absent(self) -> None:
        env = _scrub_env() | {"COMPORTZONE_BAUD": "230400"}
        settings = _settings_with(baudrate=9600)
        with patch.dict(os.environ, env, clear=True):
            profile = resolve_serial_profile(settings=settings)
        self.assertEqual(profile.baudrate, 230400)

    def test_env_parity_normalized_to_upper(self) -> None:
        env = _scrub_env() | {"COMPORTZONE_PARITY": "e"}
        with patch.dict(os.environ, env, clear=True):
            profile = resolve_serial_profile(settings=_empty_settings())
        self.assertEqual(profile.parity, "E")


class SettingsUsedWhenNothingElseTests(unittest.TestCase):
    def test_settings_port_baud_used_without_flag_or_env(self) -> None:
        settings = _settings_with(port="COM_settings", baudrate=4800)
        with patch.dict(os.environ, _scrub_env(), clear=True):
            profile = resolve_serial_profile(settings=settings)
        self.assertEqual(profile.port, "COM_settings")
        self.assertEqual(profile.baudrate, 4800)

    def test_fallback_when_settings_empty(self) -> None:
        # AppSettings() yields a default SerialProfile() (baud 115200 etc).
        # No flags, no env, no overrides — the SerialProfile defaults win.
        with patch.dict(os.environ, _scrub_env(), clear=True):
            profile = resolve_serial_profile(settings=AppSettings())
        # Verify the resolver doesn't replace defaults with falsy values.
        self.assertEqual(profile.baudrate, 115200)
        self.assertEqual(profile.bytesize, 8)
        self.assertEqual(profile.parity, "N")


class NormalizationTests(unittest.TestCase):
    def test_flow_control_flag_normalized_to_internal_name(self) -> None:
        with patch.dict(os.environ, _scrub_env(), clear=True):
            for flag_value, expected in [
                ("none", "None"),
                ("rtscts", "RTS/CTS"),
                ("xonxoff", "XON/XOFF"),
                ("dsrdtr", "DSR/DTR"),
            ]:
                with self.subTest(flag=flag_value):
                    profile = resolve_serial_profile(
                        settings=_empty_settings(), flow_control=flag_value
                    )
                    self.assertEqual(profile.flow_control, expected)

    def test_line_ending_flag_normalized(self) -> None:
        with patch.dict(os.environ, _scrub_env(), clear=True):
            for flag_value, expected in [
                ("none", "None"),
                ("CR", "CR"),
                ("lf", "LF"),
                ("crlf", "CRLF"),
            ]:
                with self.subTest(flag=flag_value):
                    profile = resolve_serial_profile(
                        settings=_empty_settings(), line_ending=flag_value
                    )
                    self.assertEqual(profile.line_ending, expected)

    def test_dtr_rts_on_off_flags(self) -> None:
        with patch.dict(os.environ, _scrub_env(), clear=True):
            profile = resolve_serial_profile(
                settings=_empty_settings(), dtr="off", rts="on"
            )
        self.assertFalse(profile.dtr)
        self.assertTrue(profile.rts)

    def test_data_bits_and_stop_bits_coerced_to_numbers(self) -> None:
        with patch.dict(os.environ, _scrub_env(), clear=True):
            profile = resolve_serial_profile(
                settings=_empty_settings(), data_bits="7", stop_bits="1.5"
            )
        self.assertEqual(profile.bytesize, 7)
        self.assertEqual(profile.stopbits, 1.5)


class AutoReconnectTests(unittest.TestCase):
    def test_auto_reconnect_flag_overrides_settings(self) -> None:
        settings = _settings_with(auto_reconnect=False)
        with patch.dict(os.environ, _scrub_env(), clear=True):
            profile = resolve_serial_profile(settings=settings, auto_reconnect=True)
        self.assertTrue(profile.auto_reconnect)

    def test_auto_reconnect_env_used_when_flag_absent(self) -> None:
        env = _scrub_env() | {"COMPORTZONE_AUTO_RECONNECT": "0"}
        settings = _settings_with(auto_reconnect=True)
        with patch.dict(os.environ, env, clear=True):
            profile = resolve_serial_profile(settings=settings)
        # "0" is falsy via _env_bool's truthy-set membership.
        self.assertFalse(profile.auto_reconnect)


class LanProfileTests(unittest.TestCase):
    def test_tcp_flags_override_lan_settings(self) -> None:
        settings = AppSettings(
            transport_kind="lan",
            lan=LanProfile(host="settings.local", port=5025, line_ending="CRLF"),
        )
        with patch.dict(os.environ, _scrub_env(), clear=True):
            profile = resolve_lan_profile(
                settings=settings,
                host="127.0.0.1",
                tcp_port=7000,
                tcp_timeout_ms=250,
                line_ending="lf",
            )
        self.assertEqual(profile.host, "127.0.0.1")
        self.assertEqual(profile.port, 7000)
        self.assertEqual(profile.timeout_ms, 250)
        self.assertEqual(profile.line_ending, "LF")

    def test_tcp_env_used_when_flags_are_absent(self) -> None:
        env = _scrub_env() | {
            "COMPORTZONE_HOST": "echo.local",
            "COMPORTZONE_TCP_PORT": "9000",
            "COMPORTZONE_TCP_TIMEOUT_MS": "500",
        }
        with patch.dict(os.environ, env, clear=True):
            profile = resolve_lan_profile(settings=AppSettings())
        self.assertEqual(profile.host, "echo.local")
        self.assertEqual(profile.port, 9000)
        self.assertEqual(profile.timeout_ms, 500)


class LoadAppSettingsTests(unittest.TestCase):
    def test_missing_file_returns_fresh_app_settings(self) -> None:
        # ``load_app_settings(None)`` reads from %LOCALAPPDATA%; on a clean
        # system the file may be missing. We can simulate by pointing at a
        # path that definitely doesn't exist.
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nowhere.json"
            self.assertFalse(target.exists())
            settings = load_app_settings(target)
            # Default ``AppSettings()`` has a default SerialProfile.
            self.assertEqual(settings.serial.baudrate, 115200)


if __name__ == "__main__":
    unittest.main()
