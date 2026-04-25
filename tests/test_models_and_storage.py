import unittest
from unittest.mock import Mock

from ComPort_Zone.models import (
    AppSettings,
    QuickCommand,
    SerialProfile,
    TerminalSessionState,
    apply_line_ending,
)
from ComPort_Zone.storage import SettingsStore


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
            quick_snippets=["status", "reboot"],
            quick_commands=[
                QuickCommand(
                    id="cmd-1",
                    label="Read ID",
                    command="id?",
                    send_mode="Text",
                    group="Factory",
                    line_ending_override="LF",
                )
            ],
            restored_tabs=[
                TerminalSessionState(
                    title="DUT A",
                    profile_name="Bench",
                    serial=SerialProfile(port="COM9", baudrate=921600, line_ending="None"),
                    connected_on_launch=True,
                    terminal_text="boot ok",
                    command_draft="55 AA",
                    send_mode="Hex Bytes",
                ),
                TerminalSessionState(title="DUT B", profile_name="Bench"),
            ],
            theme="Scope Amber",
            timestamps_enabled=False,
            terminal_font_size=13,
            terminal_font_family="Cascadia Mono",
            line_wrap_enabled=True,
            scrollback_size=20000,
            receive_display_mode="Text + Hex",
            drawer_collapsed=False,
            drawer_width=340,
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
        self.assertEqual(loaded.profiles["Bench"].serial.port, "COM7")
        self.assertEqual(loaded.command_history, ["status", "reset"])
        self.assertEqual(loaded.quick_snippets, ["status", "reboot"])
        self.assertEqual(len(loaded.quick_commands), 1)
        self.assertEqual(loaded.quick_commands[0].label, "Read ID")
        self.assertEqual(loaded.quick_commands[0].line_ending_override, "LF")
        self.assertEqual([tab.title for tab in loaded.restored_tabs], ["DUT A", "DUT B"])
        self.assertEqual(loaded.restored_tabs[0].serial.port, "COM9")
        self.assertEqual(loaded.restored_tabs[0].serial.baudrate, 921600)
        self.assertEqual(loaded.restored_tabs[0].serial.line_ending, "None")
        self.assertTrue(loaded.restored_tabs[0].connected_on_launch)
        self.assertEqual(loaded.restored_tabs[0].terminal_text, "boot ok")
        self.assertEqual(loaded.restored_tabs[0].command_draft, "55 AA")
        self.assertEqual(loaded.restored_tabs[0].send_mode, "Hex Bytes")
        self.assertEqual(loaded.theme, "Scope Amber")
        self.assertFalse(loaded.timestamps_enabled)
        self.assertEqual(loaded.terminal_font_size, 13)
        self.assertEqual(loaded.terminal_font_family, "Cascadia Mono")
        self.assertTrue(loaded.line_wrap_enabled)
        self.assertEqual(loaded.scrollback_size, 20000)
        self.assertEqual(loaded.receive_display_mode, "Text + Hex")
        self.assertFalse(loaded.drawer_collapsed)
        self.assertEqual(loaded.drawer_width, 340)

    def test_legacy_quick_snippets_become_quick_commands(self) -> None:
        settings = AppSettings.from_dict({"quick_snippets": ["status", "reset"]})

        self.assertEqual([command.command for command in settings.quick_commands], ["status", "reset"])
        self.assertEqual([command.label for command in settings.quick_commands], ["status", "reset"])

    def test_legacy_workshop_theme_maps_to_vs_code_dark(self) -> None:
        settings = AppSettings.from_dict({"theme": "Workshop Dark"})

        self.assertEqual(settings.theme, "VS Code Dark")

    def test_active_profile_applies_saved_preferences(self) -> None:
        settings = AppSettings.from_dict(
            {
                "active_profile": "Lab",
                "profiles": {
                    "Lab": {
                        "serial": {"port": "COM12", "baudrate": 9600},
                        "theme": "Scope Amber",
                        "terminal_font_size": 15,
                        "receive_display_mode": "Hex",
                        "quick_commands": [
                            {
                                "id": "cmd-2",
                                "label": "Version",
                                "command": "version",
                            }
                        ],
                    }
                },
                "theme": "VS Code Dark",
                "terminal_font_size": 10,
            }
        )

        self.assertEqual(settings.theme, "Scope Amber")
        self.assertEqual(settings.terminal_font_size, 15)
        self.assertEqual(settings.receive_display_mode, "Hex")
        self.assertEqual(settings.profiles["Lab"].serial.port, "COM12")
        self.assertEqual(settings.quick_commands[0].command, "version")

    def test_default_profile_can_capture_all_preferences(self) -> None:
        settings = AppSettings(
            active_profile="Default",
            theme="Bench Light",
            terminal_font_size=14,
            receive_display_mode="Text + Hex",
            quick_commands=[QuickCommand(label="Errors", command="ERRORS")],
        )

        settings.profiles["Default"] = settings.capture_user_profile(
            SerialProfile(port="COM4", baudrate=230400)
        )
        restored = AppSettings.from_dict(settings.to_dict())

        self.assertEqual(restored.theme, "Bench Light")
        self.assertEqual(restored.terminal_font_size, 14)
        self.assertEqual(restored.receive_display_mode, "Text + Hex")
        self.assertEqual(restored.quick_commands[0].command, "ERRORS")
        self.assertEqual(restored.profiles["Default"].serial.port, "COM4")


if __name__ == "__main__":
    unittest.main()
