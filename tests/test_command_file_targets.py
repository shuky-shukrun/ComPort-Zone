import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMenu

from ComPort_Zone.command_run_targets import CommandRunRequest, CommandRunTarget
from ComPort_Zone.ui.command_file_targets import CommandFileRunCoordinator


class FakeSerialClient:
    def __init__(self, connected: bool = True) -> None:
        self.is_connected = connected


class FakeSession:
    def __init__(self, session_id: int = 42, *, connected: bool = True) -> None:
        self.session_id = session_id
        self.tab_title = f"COM{session_id}"
        self.serial_client = FakeSerialClient(connected)
        self.started: list[tuple[str, str, Path | None]] = []

    def connection_status_text(self) -> str:
        return f"Connected | COM{self.session_id}"

    def run_script_text(
        self,
        text: str,
        source_label: str = "Editor buffer",
        source_path: Path | None = None,
    ) -> None:
        self.started.append((text, source_label, source_path))


class FakeEditor:
    def __init__(self, text: str = "SEND *IDN?\n", *, errors: list[str] | None = None) -> None:
        self.path: Path | None = None
        self._text = text
        self._errors = errors or []
        self.refresh_count = 0
        self.validation_updates = 0

    def display_name(self) -> str:
        return "Untitled"

    def refresh_run_targets(self) -> None:
        self.refresh_count += 1

    def text(self) -> str:
        return self._text

    def update_validation_status(self) -> None:
        self.validation_updates += 1

    def validation_errors(self) -> list[str]:
        return self._errors


class CommandFileRunCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def make_coordinator(
        self,
        *,
        sessions: list[FakeSession],
        editors: list[FakeEditor],
        current_editor: FakeEditor | None,
        statuses: list[str],
    ) -> CommandFileRunCoordinator:
        return CommandFileRunCoordinator(
            sessions_supplier=lambda: sessions,
            editors_supplier=lambda: editors,
            current_editor_supplier=lambda: current_editor,
            is_widget_open=lambda _widget: True,
            set_status=statuses.append,
            target_icon_color=lambda: "#9cdcfe",
        )

    def test_run_targets_include_only_connected_sessions(self) -> None:
        statuses: list[str] = []
        coordinator = self.make_coordinator(
            sessions=[FakeSession(1, connected=True), FakeSession(2, connected=False)],
            editors=[],
            current_editor=None,
            statuses=statuses,
        )

        self.assertEqual(coordinator.run_targets(), [CommandRunTarget(1, "Connected | COM1")])

    def test_populate_run_menu_runs_editor_in_target(self) -> None:
        session = FakeSession(88)
        editor = FakeEditor()
        statuses: list[str] = []
        coordinator = self.make_coordinator(
            sessions=[session],
            editors=[editor],
            current_editor=editor,
            statuses=statuses,
        )
        menu = QMenu()
        try:
            coordinator.populate_run_menu(menu)
            actions = menu.actions()

            self.assertEqual(len(actions), 1)
            self.assertIn("COM88", actions[0].text())

            actions[0].trigger()

            self.assertEqual(session.started, [("SEND *IDN?\n", "Untitled", None)])
            self.assertEqual(statuses, ["Running Untitled in COM88."])
        finally:
            menu.deleteLater()

    def test_populate_run_menu_reports_missing_targets(self) -> None:
        statuses: list[str] = []
        coordinator = self.make_coordinator(
            sessions=[FakeSession(7, connected=False)],
            editors=[FakeEditor()],
            current_editor=FakeEditor(),
            statuses=statuses,
        )
        menu = QMenu()
        try:
            coordinator.populate_run_menu(menu)
            actions = menu.actions()

            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0].text(), "No connected terminals")
            self.assertFalse(actions[0].isEnabled())
        finally:
            menu.deleteLater()

    def test_refresh_editor_targets_updates_all_editors(self) -> None:
        editor_a = FakeEditor()
        editor_b = FakeEditor()
        coordinator = self.make_coordinator(
            sessions=[],
            editors=[editor_a, editor_b],
            current_editor=None,
            statuses=[],
        )

        coordinator.refresh_editor_targets()

        self.assertEqual(editor_a.refresh_count, 1)
        self.assertEqual(editor_b.refresh_count, 1)

    def test_target_service_runs_command_request_by_id(self) -> None:
        session = FakeSession(5)
        statuses: list[str] = []
        coordinator = self.make_coordinator(
            sessions=[session],
            editors=[],
            current_editor=None,
            statuses=statuses,
        )

        self.assertTrue(coordinator.target_service.run(CommandRunRequest("SEND *RST"), 5))

        self.assertEqual(session.started, [("SEND *RST", "Untitled", None)])
        self.assertEqual(statuses, ["Running Untitled in COM5."])


if __name__ == "__main__":
    unittest.main()
