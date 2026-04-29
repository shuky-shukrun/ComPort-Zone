import unittest

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from ComPort_Zone.models import SerialProfile, TerminalSessionState
from ComPort_Zone.ui.tab_workspace import TabWorkspaceController


class FakeTextBuffer:
    def __init__(self, text: str) -> None:
        self._text = text

    def toPlainText(self) -> str:
        return self._text


class FakeLineEdit:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class FakeComboBox:
    def __init__(self, text: str) -> None:
        self._text = text

    def currentText(self) -> str:
        return self._text


class FakeTerminalTab(QWidget):
    def __init__(self, title: str = "DUT") -> None:
        super().__init__()
        self.profile = SerialProfile(port="COM7", baudrate=57600, line_ending="LF")
        self.terminal = FakeTextBuffer("boot ok")
        self.command_input = FakeLineEdit("status")
        self.mode_combo = FakeComboBox("Hex Bytes")
        self._title = title
        self.shutdown_called = False

    @property
    def tab_title(self) -> str:
        return self._title

    def shutdown(self) -> None:
        self.shutdown_called = True


class FakeCommandFileTab(QWidget):
    pass


class TabWorkspaceControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def make_controller(self, tabs: QTabWidget):
        added_sessions: list[tuple[TerminalSessionState | None, bool]] = []
        save_calls: list[str] = []
        confirm_calls: list[QWidget] = []

        def add_session(
            state: TerminalSessionState | None = None,
            *,
            prompt_settings: bool = True,
        ) -> object:
            added_sessions.append((state, prompt_settings))
            return object()

        def confirm_close(widget: QWidget) -> bool:
            confirm_calls.append(widget)
            return True

        controller = TabWorkspaceController(
            tabs,
            terminal_type=FakeTerminalTab,
            command_file_type=FakeCommandFileTab,
            add_session=add_session,
            confirm_close_command_file_tab=confirm_close,
            save_settings=lambda: save_calls.append("save"),
        )
        return controller, added_sessions, save_calls, confirm_calls

    def test_lookup_helpers_return_typed_tabs(self) -> None:
        tabs = QTabWidget()
        controller, *_ = self.make_controller(tabs)
        terminal = FakeTerminalTab("DUT")
        editor = FakeCommandFileTab()
        tabs.addTab(terminal, "Terminal")
        tabs.addTab(editor, "Editor")

        tabs.setCurrentIndex(0)
        self.assertIs(controller.current_session(), terminal)
        self.assertIsNone(controller.current_command_file_editor())
        tabs.setCurrentIndex(1)
        self.assertIs(controller.current_command_file_editor(), editor)
        self.assertIsNone(controller.current_session())
        self.assertIs(controller.session_at(0), terminal)
        self.assertIs(controller.command_file_editor_at(1), editor)
        self.assertEqual(controller.iter_sessions(), [terminal])
        self.assertEqual(controller.iter_command_file_editors(), [editor])
        self.assertEqual(controller.workspace_tab_count(), 2)

        tabs.deleteLater()
        terminal.deleteLater()
        editor.deleteLater()

    def test_duplicate_session_uses_terminal_snapshot(self) -> None:
        tabs = QTabWidget()
        controller, added_sessions, *_ = self.make_controller(tabs)
        terminal = FakeTerminalTab("DUT")
        tabs.addTab(terminal, "Terminal")

        controller.duplicate_session(0)

        self.assertEqual(len(added_sessions), 1)
        state, prompt_settings = added_sessions[0]
        self.assertFalse(prompt_settings)
        self.assertEqual(state.title, "DUT Copy")
        self.assertTrue(state.title_is_custom)
        self.assertEqual(state.serial.port, "COM7")
        self.assertEqual(state.serial.baudrate, 57600)
        self.assertEqual(state.terminal_text, "boot ok")
        self.assertEqual(state.command_draft, "status")
        self.assertEqual(state.send_mode, "Hex Bytes")

        tabs.deleteLater()
        terminal.deleteLater()

    def test_close_session_shutdowns_terminal_and_adds_default_when_empty(self) -> None:
        tabs = QTabWidget()
        controller, added_sessions, save_calls, _ = self.make_controller(tabs)
        terminal = FakeTerminalTab("DUT")
        tabs.addTab(terminal, "Terminal")

        self.assertTrue(controller.close_session(0))

        self.assertTrue(terminal.shutdown_called)
        self.assertEqual(tabs.count(), 0)
        self.assertEqual(added_sessions, [(None, True)])
        self.assertEqual(save_calls, ["save"])

        tabs.deleteLater()
        terminal.deleteLater()

    def test_close_command_file_respects_confirmation(self) -> None:
        tabs = QTabWidget()
        editor = FakeCommandFileTab()
        tabs.addTab(editor, "Editor")
        save_calls: list[str] = []

        controller = TabWorkspaceController(
            tabs,
            terminal_type=FakeTerminalTab,
            command_file_type=FakeCommandFileTab,
            add_session=lambda *args, **kwargs: object(),
            confirm_close_command_file_tab=lambda widget: False,
            save_settings=lambda: save_calls.append("save"),
        )

        self.assertFalse(controller.close_session(0))
        self.assertEqual(tabs.count(), 1)
        self.assertEqual(save_calls, [])

        tabs.deleteLater()
        editor.deleteLater()

    def test_close_other_sessions_keeps_target_selected(self) -> None:
        tabs = QTabWidget()
        controller, _, save_calls, _ = self.make_controller(tabs)
        left = FakeTerminalTab("Left")
        target = FakeTerminalTab("Target")
        right = FakeTerminalTab("Right")
        tabs.addTab(left, "Left")
        tabs.addTab(target, "Target")
        tabs.addTab(right, "Right")

        controller.close_other_sessions(1)

        self.assertEqual(tabs.count(), 1)
        self.assertIs(tabs.currentWidget(), target)
        self.assertTrue(left.shutdown_called)
        self.assertFalse(target.shutdown_called)
        self.assertTrue(right.shutdown_called)
        self.assertGreaterEqual(len(save_calls), 1)

        tabs.deleteLater()
        left.deleteLater()
        target.deleteLater()
        right.deleteLater()


if __name__ == "__main__":
    unittest.main()
