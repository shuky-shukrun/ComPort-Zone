import unittest
from unittest.mock import Mock

from serial_terminal.models import AppSettings, SerialProfile, apply_line_ending
from serial_terminal.storage import SettingsStore


class ModelsAndStorageTests(unittest.TestCase):
    def test_apply_line_ending_respects_profile_setting(self) -> None:
        self.assertEqual(apply_line_ending("ping", "CRLF"), b"ping\r\n")
        self.assertEqual(apply_line_ending("ping", "None"), b"ping")

    def test_settings_store_round_trip(self) -> None:
        settings = AppSettings(
            active_profile="Bench",
            profiles={
                "Bench": SerialProfile(port="COM7", baudrate=57600, line_ending="LF"),
            },
            command_history=["status", "reset"],
            theme="Scope Amber",
            timestamps_enabled=False,
        )
        payload: dict[str, str] = {}
        fake_parent = Mock()
        fake_path = Mock()
        fake_path.parent = fake_parent
        fake_path.exists.return_value = True
        fake_path.write_text.side_effect = lambda text, encoding="utf-8": payload.setdefault(
            "json", text
        )
        fake_path.read_text.side_effect = lambda encoding="utf-8": payload["json"]

        store = SettingsStore(fake_path)
        store.save(settings)
        loaded = store.load()

        fake_parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        fake_path.write_text.assert_called_once()
        fake_path.read_text.assert_called_once()
        self.assertEqual(loaded.active_profile, "Bench")
        self.assertEqual(loaded.profiles["Bench"].port, "COM7")
        self.assertEqual(loaded.command_history, ["status", "reset"])
        self.assertEqual(loaded.theme, "Scope Amber")
        self.assertFalse(loaded.timestamps_enabled)


if __name__ == "__main__":
    unittest.main()
