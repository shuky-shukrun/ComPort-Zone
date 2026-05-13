import unittest

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTabWidget, QWidget

from ComPort_Zone.themes import THEMES
from ComPort_Zone.ui.workspace_status import WorkspaceStatusPresenter, connection_state_color


class FakeTerminalStatusTab(QWidget):
    def __init__(self, title: str = "COM7", state: str = "connected") -> None:
        super().__init__()
        self._title = title
        self._state = state

    @property
    def tab_title(self) -> str:
        return self._title

    def connection_state(self) -> str:
        return self._state

    def connection_status_text(self) -> str:
        return f"{self._state.title()} | {self._title}"

    def connection_tooltip(self) -> str:
        return f"Tooltip {self._title}"

    def connection_action_text(self) -> str:
        return "Disconnect" if self._state == "connected" else "Connect"


class FakeCommandFileStatusTab(QWidget):
    def __init__(self, *, dirty: bool = False, invalid: bool = False) -> None:
        super().__init__()
        self.dirty = dirty
        self.invalid = invalid

    def tab_title(self) -> str:
        return "Untitled*"

    def status_summary(self) -> str:
        return "Command file | Untitled | Dirty"

    def is_dirty(self) -> bool:
        return self.dirty

    def validation_errors(self) -> list[object]:
        return ["issue"] if self.invalid else []


class WorkspaceStatusPresenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def make_presenter(self) -> tuple[WorkspaceStatusPresenter, QTabWidget, QLabel, QPushButton, QLabel]:
        tabs = QTabWidget()
        status_label = QLabel()
        action_button = QPushButton()
        footer = QLabel()
        presenter = WorkspaceStatusPresenter(
            tabs,
            terminal_type=FakeTerminalStatusTab,
            command_file_type=FakeCommandFileStatusTab,
            connection_status_label=status_label,
            connection_action_button=action_button,
            footer=footer,
        )
        return presenter, tabs, status_label, action_button, footer

    def test_update_tab_titles_applies_terminal_and_editor_status(self) -> None:
        presenter, tabs, *_ = self.make_presenter()
        theme = THEMES["VS Code Dark"]
        terminal = FakeTerminalStatusTab("COM9", "retrying")
        editor = FakeCommandFileStatusTab(dirty=True)
        tabs.addTab(terminal, "old terminal")
        tabs.addTab(editor, "old editor")

        presenter.update_tab_titles(theme)

        self.assertEqual(tabs.tabText(0), "COM9")
        self.assertEqual(tabs.tabText(1), "Untitled*")
        self.assertEqual(tabs.tabToolTip(0), "Retrying | COM9")
        self.assertEqual(tabs.tabToolTip(1), "Command file | Untitled | Dirty")
        self.assertEqual(tabs.tabBar().tabTextColor(0).name().lower(), theme.status.lower())
        self.assertEqual(tabs.tabBar().tabTextColor(1).name().lower(), theme.status.lower())

    def test_sync_from_current_terminal_and_editor_updates_footer_action(self) -> None:
        presenter, tabs, status_label, action_button, footer = self.make_presenter()
        theme = THEMES["VS Code Dark"]
        terminal = FakeTerminalStatusTab("COM1", "connected")
        editor = FakeCommandFileStatusTab()
        tabs.addTab(terminal, "terminal")
        tabs.addTab(editor, "editor")

        tabs.setCurrentWidget(terminal)
        presenter.sync_from_current(theme)

        self.assertEqual(status_label.text(), "Connected | COM1")
        self.assertEqual(action_button.text(), "Disconnect")
        self.assertTrue(action_button.isEnabled())
        self.assertIn("Double-click to open Connection Settings.", status_label.toolTip())

        tabs.setCurrentWidget(editor)
        presenter.sync_from_current(theme)

        self.assertEqual(status_label.text(), "Command file | Untitled | Dirty")
        self.assertEqual(action_button.text(), "Terminal only")
        self.assertFalse(action_button.isEnabled())
        self.assertEqual(footer.text(), "Command file | Untitled | Dirty")

    def test_connection_state_color_maps_states_to_theme(self) -> None:
        theme = THEMES["VS Code Dark"]

        self.assertEqual(connection_state_color("connected", theme), theme.rx)
        self.assertEqual(connection_state_color("retrying", theme), theme.status)
        self.assertEqual(connection_state_color("missing", theme), theme.error)
        self.assertEqual(connection_state_color("no-port", theme), theme.muted)
        self.assertEqual(connection_state_color("closed", theme), theme.text)


if __name__ == "__main__":
    unittest.main()
