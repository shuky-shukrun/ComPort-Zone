from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtWidgets import QTabWidget, QWidget

from ..models import SerialProfile, TerminalSessionState


class TextBufferLike(Protocol):
    def toPlainText(self) -> str:
        ...


class LineEditLike(Protocol):
    def text(self) -> str:
        ...


class ComboBoxLike(Protocol):
    def currentText(self) -> str:
        ...


class TerminalTabLike(Protocol):
    profile: SerialProfile
    terminal: TextBufferLike
    command_input: LineEditLike
    mode_combo: ComboBoxLike

    @property
    def tab_title(self) -> str:
        ...

    def shutdown(self) -> None:
        ...


class TabWorkspaceController:
    def __init__(
        self,
        tabs: QTabWidget,
        *,
        terminal_type: type[QWidget],
        command_file_type: type[QWidget],
        add_session: Callable[..., object],
        confirm_close_command_file_tab: Callable[[QWidget], bool],
        save_settings: Callable[[], None],
    ) -> None:
        self.tabs = tabs
        self.terminal_type = terminal_type
        self.command_file_type = command_file_type
        self._add_session = add_session
        self._confirm_close_command_file_tab = confirm_close_command_file_tab
        self._save_settings = save_settings

    def current_session(self) -> QWidget | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, self.terminal_type) else None

    def current_command_file_editor(self) -> QWidget | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, self.command_file_type) else None

    def session_at(self, index: int) -> QWidget | None:
        widget = self.tabs.widget(index)
        return widget if isinstance(widget, self.terminal_type) else None

    def command_file_editor_at(self, index: int) -> QWidget | None:
        widget = self.tabs.widget(index)
        return widget if isinstance(widget, self.command_file_type) else None

    def iter_sessions(self) -> list[QWidget]:
        return [
            widget
            for widget in self._widgets()
            if isinstance(widget, self.terminal_type)
        ]

    def iter_command_file_editors(self) -> list[QWidget]:
        return [
            widget
            for widget in self._widgets()
            if isinstance(widget, self.command_file_type)
        ]

    def workspace_tab_count(self) -> int:
        return self.tabs.count()

    def duplicate_current_session(self) -> None:
        self.duplicate_session(self.tabs.currentIndex())

    def duplicate_session(self, index: int) -> None:
        session = self.session_at(index)
        if session is None:
            self._add_session()
            return
        self._add_session(self._duplicate_state(session), prompt_settings=False)

    def close_current_session(self) -> None:
        index = self.tabs.currentIndex()
        if index >= 0:
            self.close_session(index)

    def close_session(self, index: int) -> bool:
        if index < 0 or index >= self.tabs.count():
            return False
        widget = self.tabs.widget(index)
        if isinstance(widget, self.command_file_type) and not self._confirm_close_command_file_tab(widget):
            return False
        if isinstance(widget, self.terminal_type):
            widget.shutdown()
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()
        if self.tabs.count() == 0:
            self._add_session()
        self._save_settings()
        return True

    def close_other_sessions(self, index: int) -> None:
        target = self.tabs.widget(index) if 0 <= index < self.tabs.count() else None
        if target is None:
            return
        for tab_index in range(self.tabs.count() - 1, -1, -1):
            if self.tabs.widget(tab_index) is not target:
                if not self.close_session(tab_index):
                    break
        current_index = self.tabs.indexOf(target)
        if current_index >= 0:
            self.tabs.setCurrentIndex(current_index)
        self._save_settings()

    def close_sessions_to_right(self, index: int) -> None:
        if index < 0 or index >= self.tabs.count() - 1:
            return
        for tab_index in range(self.tabs.count() - 1, index, -1):
            if not self.close_session(tab_index):
                break
        self.tabs.setCurrentIndex(min(index, self.tabs.count() - 1))
        self._save_settings()

    def _widgets(self) -> list[QWidget]:
        widgets: list[QWidget] = []
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if widget is not None:
                widgets.append(widget)
        return widgets

    def _duplicate_state(self, session: TerminalTabLike) -> TerminalSessionState:
        return TerminalSessionState(
            title=f"{session.tab_title} Copy",
            title_is_custom=True,
            serial=SerialProfile.from_dict(session.profile.to_dict()),
            connected_on_launch=False,
            terminal_text=session.terminal.toPlainText(),
            command_draft=session.command_input.text(),
            send_mode=session.mode_combo.currentText(),
        )
