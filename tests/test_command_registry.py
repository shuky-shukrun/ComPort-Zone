import unittest

from ComPort_Zone.command_registry import CommandRegistry


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def clear_terminal(self) -> None:
        self.calls.append("clear_terminal")


class FakeHost:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.session = FakeSession()

    def add_session(self, *, prompt_settings: bool = True) -> None:
        self.calls.append(("add_session", prompt_settings))

    def with_session(self, callback) -> None:
        self.calls.append("with_session")
        callback(self.session)

    def show_find_in_current_tab(self) -> None:
        self.calls.append("show_find_in_current_tab")

    def clear_command_history(self) -> None:
        self.calls.append("clear_command_history")

    def __getattr__(self, name: str):
        def record_call(*_args, **_kwargs) -> None:
            self.calls.append(name)

        return record_call


class CommandRegistryTests(unittest.TestCase):
    def test_palette_entries_keep_existing_static_order(self) -> None:
        registry = CommandRegistry(FakeHost())

        self.assertEqual(
            [entry.title for entry in registry.palette_entries()],
            [
                "Connect / Disconnect",
                "Serial Settings",
                "Run Command File",
                "New Command File",
                "Open Command File Editor",
                "Stop Command File",
                "Send Selected Quick File",
                "Edit Selected Quick File",
                "Add Quick File",
                "Clear Terminal",
                "Clear Command History",
                "Find / Search",
                "Replace in Editor",
                "Terminal Font Settings",
                "Save Current Input as Quick Command",
                "App Settings Import / Export",
                "Import Quick Commands from CSV",
                "Export Quick Commands to CSV",
                "Delete All Quick Commands",
                "Import Quick Files from CSV",
                "Export Quick Files to CSV",
                "Delete All Quick Files",
            ],
        )

    def test_palette_commands_are_backed_by_menu_command_specs(self) -> None:
        registry = CommandRegistry(FakeHost())

        self.assertLessEqual(
            set(registry.palette_command_ids()),
            set(registry.menu_command_ids()),
        )
        self.assertEqual(
            registry.menu_items("serial"),
            (
                "serial.connect_disconnect",
                "serial.settings",
                "serial.refresh_ports",
            ),
        )
        self.assertIn("edit.find", registry.menu_command_ids("edit"))
        self.assertIn("quick_files.edit_selected_content", registry.menu_command_ids("quick_files"))

    def test_registered_callbacks_call_main_window_or_active_session(self) -> None:
        host = FakeHost()
        registry = CommandRegistry(host)

        registry.spec("file.new_tab").callback(host)()
        registry.spec("edit.clear_terminal").callback(host)()
        registry.spec("edit.find").callback(host)()

        self.assertEqual(
            host.calls,
            [
                ("add_session", True),
                "with_session",
                "show_find_in_current_tab",
            ],
        )
        self.assertEqual(host.session.calls, ["clear_terminal"])


if __name__ == "__main__":
    unittest.main()
