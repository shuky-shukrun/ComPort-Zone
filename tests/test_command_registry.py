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
                "Connection Settings",
                "Run Command File",
                "Pause / Resume Command File",
                "New Command File",
                "Open Command File Editor",
                "Stop Command File",
                "Run Selected Quick File",
                "Edit Selected Quick File",
                "Add Quick File",
                "Clear Terminal",
                "Clear Command History",
                "Find / Search",
                "Replace in Editor",
                "Terminal Font Settings",
                "Split Right",
                "Split Down",
                "Join Tabs",
                "Save Current Input as Quick Command",
                "App Settings Import / Export",
                "Import Quick Commands from CSV",
                "Export Quick Commands to CSV",
                "Delete All Quick Commands",
                "Import Quick Files from CSV",
                "Export Quick Files to CSV",
                "Delete All Quick Files",
                "New Control Panel",
                "Manage Control Panels",
                "Import Control Panels from JSON",
                "Export Control Panels to JSON",
                "Check for Updates",
            ],
        )

    def test_palette_commands_are_backed_by_specs(self) -> None:
        registry = CommandRegistry(FakeHost())

        # Every palette command resolves to a registered spec (some palette
        # commands now live only in the sidebar / builder submenus, so they are
        # no longer required to appear in a flat MENU_SECTIONS list).
        for command_id in registry.palette_command_ids():
            self.assertIsInstance(registry.spec(command_id).menu_label(), str)

        self.assertEqual(
            registry.menu_items("connection")[:3],
            (
                "serial.connect_disconnect",
                "serial.settings",
                "serial.refresh_ports",
            ),
        )
        self.assertIn("edit.find", registry.menu_command_ids("edit"))
        self.assertIn("connection.dtr", registry.menu_command_ids("connection"))

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
