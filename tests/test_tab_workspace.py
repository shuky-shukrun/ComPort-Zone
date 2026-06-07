import unittest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QTabBar, QTabWidget, QWidget

from ComPort_Zone.models import SerialProfile, TerminalSessionState
from ComPort_Zone.ui.tab_workspace import TabWorkspaceController, TerminalTabWidget


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
        self.actions: list[str] = []

    @property
    def tab_title(self) -> str:
        return self._title

    def shutdown(self) -> None:
        self.shutdown_called = True

    def mark_action(self, name: str) -> None:
        self.actions.append(name)


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

    def test_terminal_tab_widget_owns_new_tab_button(self) -> None:
        tabs = TerminalTabWidget()
        tabs.resize(400, 240)
        tabs.show()
        self.qt.processEvents()
        menu_points: list[QPoint] = []
        new_tabs: list[str] = []
        tabs.newTabMenuRequested.connect(menu_points.append)
        tabs.newTabRequested.connect(lambda: new_tabs.append("new"))

        self.assertEqual(tabs.new_tab_button.objectName(), "newTabButton")
        self.assertEqual(tabs.new_tab_button.toolTip(), "New tab (choose type)")
        self.assertIs(tabs.new_tab_button.parent(), tabs)
        self.assertEqual(
            tabs.new_tab_button.contextMenuPolicy(),
            Qt.ContextMenuPolicy.CustomContextMenu,
        )

        tabs.new_tab_button.click()

        # Clicking + opens the new-tab menu (the user picks the tab type) rather than
        # creating a terminal directly.
        self.assertEqual(len(menu_points), 1)
        self.assertEqual(new_tabs, [])
        tabs.deleteLater()

    def test_terminal_tab_widget_forwards_new_tab_button_context_menu(self) -> None:
        tabs = TerminalTabWidget()
        tabs.resize(400, 240)
        tabs.show()
        self.qt.processEvents()
        emitted: list[QPoint] = []
        tabs.newTabMenuRequested.connect(emitted.append)
        position = QPoint(3, 4)

        tabs.new_tab_button.customContextMenuRequested.emit(position)

        self.assertEqual(emitted, [tabs.new_tab_button.mapToGlobal(position)])
        tabs.deleteLater()

    def test_overflow_button_hidden_when_tabs_fit(self) -> None:
        tabs = TerminalTabWidget()
        tabs.resize(600, 240)
        for name in ("COM1", "COM2"):
            tabs.addTab(FakeTerminalTab(name), name)
        tabs.show()
        self.qt.processEvents()
        tabs._position_tab_buttons()

        # A roomy strip shows no overflow; the + button trails the last tab.
        self.assertTrue(tabs.overflow_button.isHidden())
        self.assertEqual(tabs.overflow_button.objectName(), "tabOverflowButton")
        self.assertFalse(tabs.new_tab_button.isHidden())
        tabs.deleteLater()

    def test_overflow_button_appears_when_tabs_crowded(self) -> None:
        tabs = TerminalTabWidget()
        tabs.resize(240, 240)  # deliberately too narrow for the tabs below
        for index in range(12):
            tabs.addTab(FakeTerminalTab(f"COM{index} Device"), f"COM{index} Device")
        tabs.show()
        self.qt.processEvents()
        tabs._position_tab_buttons()

        # A crowded strip reveals the ⋯ button, tucked just left of the + button,
        # and the tab bar is capped to leave room for both.
        self.assertFalse(tabs.overflow_button.isHidden())
        self.assertLess(
            tabs.overflow_button.x() + tabs.overflow_button.width(),
            tabs.new_tab_button.x() + 1,
        )
        self.assertLessEqual(
            tabs.tabBar().maximumWidth(),
            tabs.width()
            - tabs.new_tab_button.width()
            - tabs.overflow_button.width()
            - tabs._NEW_TAB_BUTTON_GAP,
        )
        tabs.deleteLater()

    def test_overflow_menu_lists_all_tabs_and_activates_selection(self) -> None:
        tabs = TerminalTabWidget()
        tabs.resize(240, 240)
        for index in range(8):
            tabs.addTab(FakeTerminalTab(f"COM{index}"), f"COM{index}")
        tabs.setCurrentIndex(0)
        tabs.show()
        self.qt.processEvents()

        tabs._build_overflow_menu()
        actions = tabs._overflow_menu.actions()
        self.assertEqual(len(actions), tabs.count())
        self.assertEqual([a.text() for a in actions], [f"COM{i}" for i in range(8)])
        # Exactly the current tab is checked.
        self.assertEqual([i for i, a in enumerate(actions) if a.isChecked()], [0])

        # Triggering an entry activates that tab (which scrolls it into view).
        actions[6].trigger()
        self.assertEqual(tabs.currentIndex(), 6)
        tabs.deleteLater()

    def test_new_tab_button_stays_clear_of_close_button_after_tab_rename(self) -> None:
        tabs = TerminalTabWidget()
        tabs.resize(600, 240)
        controller, *_ = self.make_controller(tabs)
        terminal = FakeTerminalTab("DUT")
        index = tabs.addTab(terminal, "COM1")
        controller.attach_tab_close_button(index, terminal)
        tabs.show()
        self.qt.processEvents()

        tabs.setTabText(index, "Renamed DUT with a much much longer tab title")
        self.qt.processEvents()
        self.qt.processEvents()

        close_button = tabs.tabBar().tabButton(index, QTabBar.ButtonPosition.RightSide)
        self.assertIsNotNone(close_button)
        close_right = close_button.mapTo(tabs, close_button.rect().topRight()).x()
        self.assertGreater(tabs.new_tab_button.x(), close_right)
        self.assertLessEqual(
            tabs.tabBar().width(),
            tabs.width() - tabs.new_tab_button.width() - tabs._NEW_TAB_BUTTON_GAP,
        )

        tabs.deleteLater()
        terminal.deleteLater()

    def test_attach_tab_close_button_owns_close_button_ui(self) -> None:
        tabs = QTabWidget()
        controller, _, save_calls, _ = self.make_controller(tabs)
        terminal = FakeTerminalTab("DUT")
        index = tabs.addTab(terminal, "Terminal")

        controller.attach_tab_close_button(index, terminal)
        close_button = tabs.tabBar().tabButton(index, QTabBar.ButtonPosition.RightSide)

        self.assertIsNotNone(close_button)
        self.assertEqual(close_button.objectName(), "tabCloseButton")
        self.assertEqual(close_button.toolTip(), "Close DUT")

        close_button.click()

        self.assertTrue(terminal.shutdown_called)
        self.assertEqual(tabs.count(), 0)
        self.assertEqual(save_calls, ["save"])
        tabs.deleteLater()
        terminal.deleteLater()

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

    def test_activate_session_selects_tab_and_invokes_callback(self) -> None:
        tabs = QTabWidget()
        controller, *_ = self.make_controller(tabs)
        editor = FakeCommandFileTab()
        terminal = FakeTerminalTab("DUT")
        tabs.addTab(editor, "Editor")
        tabs.addTab(terminal, "Terminal")
        tabs.setCurrentIndex(0)

        self.assertTrue(
            controller.activate_session(
                1,
                lambda session: session.mark_action("settings"),
            )
        )
        self.assertEqual(tabs.currentWidget(), terminal)
        self.assertEqual(terminal.actions, ["settings"])
        self.assertFalse(controller.activate_session(0, lambda session: session.mark_action("ignored")))

        tabs.deleteLater()
        terminal.deleteLater()
        editor.deleteLater()

    def test_with_current_session_invokes_only_terminal_tabs(self) -> None:
        tabs = QTabWidget()
        controller, *_ = self.make_controller(tabs)
        terminal = FakeTerminalTab("DUT")
        editor = FakeCommandFileTab()
        tabs.addTab(terminal, "Terminal")
        tabs.addTab(editor, "Editor")

        tabs.setCurrentIndex(0)
        self.assertTrue(controller.with_current_session(lambda session: session.mark_action("current")))
        self.assertEqual(terminal.actions, ["current"])

        tabs.setCurrentIndex(1)
        self.assertFalse(controller.with_current_session(lambda session: session.mark_action("ignored")))
        self.assertEqual(terminal.actions, ["current"])

        tabs.deleteLater()
        terminal.deleteLater()
        editor.deleteLater()

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
