from __future__ import annotations

from typing import Protocol

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QPushButton, QStyle, QTabWidget, QWidget

from ..icons import connection_state_icon, set_button_icon, standard_icon
from ..themes import ThemePalette
from ..widgets import set_button_role, set_widget_state


class TerminalStatusTab(Protocol):
    @property
    def tab_title(self) -> str:
        ...

    def connection_state(self) -> str:
        ...

    def connection_status_text(self) -> str:
        ...

    def connection_tooltip(self) -> str:
        ...

    def connection_action_text(self) -> str:
        ...


class CommandFileStatusTab(Protocol):
    def tab_title(self) -> str:
        ...

    def status_summary(self) -> str:
        ...

    def is_dirty(self) -> bool:
        ...

    def validation_errors(self) -> list[object]:
        ...


def connection_state_color(state: str, theme: ThemePalette) -> str:
    if state == "connected":
        return theme.rx
    if state == "retrying":
        return theme.status
    if state == "missing":
        return theme.error
    if state == "no-port":
        return theme.muted
    return theme.text


class WorkspaceStatusPresenter:
    def __init__(
        self,
        tabs: QTabWidget,
        *,
        terminal_type: type[QWidget],
        command_file_type: type[QWidget],
        connection_status_label: QLabel,
        connection_action_button: QPushButton,
        footer: QLabel,
    ) -> None:
        self.tabs = tabs
        self.terminal_type = terminal_type
        self.command_file_type = command_file_type
        self.connection_status_label = connection_status_label
        self.connection_action_button = connection_action_button
        self.footer = footer

    def set_status(self, text: str) -> None:
        self.footer.setText(text)

    def update_tab_titles(self, theme: ThemePalette) -> None:
        refs = getattr(self.tabs, "iter_tab_refs", lambda: [])()
        if refs:
            for ref in refs:
                if isinstance(ref.widget, self.terminal_type):
                    self._update_terminal_tab(ref.global_index, ref.widget, theme)
                elif isinstance(ref.widget, self.command_file_type):
                    self._update_command_file_tab(ref.global_index, ref.widget, theme)
            return
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, self.terminal_type):
                self._update_terminal_tab(index, widget, theme)
            elif isinstance(widget, self.command_file_type):
                self._update_command_file_tab(index, widget, theme)

    def sync_from_current(self, theme: ThemePalette) -> None:
        widget = self.tabs.currentWidget()
        if isinstance(widget, self.terminal_type):
            self.update_connection_status(widget, theme)
            return
        if isinstance(widget, self.command_file_type):
            self._show_command_file_status(widget)
            return
        self.connection_status_label.setText("No tab")
        self.connection_action_button.setEnabled(False)

    def update_connection_status(self, session: QWidget | None, theme: ThemePalette) -> None:
        if session is None:
            self.connection_status_label.setText("No session")
            self.connection_action_button.setEnabled(False)
            return
        state = session.connection_state()
        self.connection_status_label.setText(session.connection_status_text())
        self.connection_status_label.setToolTip(
            f"{session.connection_tooltip()}\nDouble-click to open Connection Settings."
        )
        set_widget_state(self.connection_status_label, state)
        self.connection_action_button.setEnabled(True)
        self.connection_action_button.setText(session.connection_action_text())
        self.connection_action_button.setToolTip(session.connection_tooltip())
        set_button_icon(self.connection_action_button, connection_state_icon(state), 15)
        set_button_role(self.connection_action_button, state)

    def _update_terminal_tab(self, index: int, tab: TerminalStatusTab, theme: ThemePalette) -> None:
        self.tabs.setTabText(index, tab.tab_title)
        state = tab.connection_state()
        color = connection_state_color(state, theme)
        icon = QStyle.StandardPixmap.SP_BrowserReload if state == "retrying" else QStyle.StandardPixmap.SP_ComputerIcon
        self.tabs.setTabIcon(index, standard_icon(icon, 18, color))
        self.tabs.setTabToolTip(index, tab.connection_status_text())
        self._tab_bar_for(index).setTabTextColor(self._local_index_for(index), QColor(color))

    def _update_command_file_tab(self, index: int, tab: CommandFileStatusTab, theme: ThemePalette) -> None:
        color = theme.status if tab.is_dirty() else theme.text
        if tab.validation_errors():
            color = theme.error
        self.tabs.setTabText(index, tab.tab_title())
        self.tabs.setTabIcon(index, standard_icon(QStyle.StandardPixmap.SP_FileIcon, 18, color))
        self.tabs.setTabToolTip(index, tab.status_summary())
        self._tab_bar_for(index).setTabTextColor(self._local_index_for(index), QColor(color))

    def _tab_bar_for(self, index: int):
        tab_ref = getattr(self.tabs, "tab_ref", lambda _index: None)(index)
        return tab_ref.pane.tabBar() if tab_ref is not None else self.tabs.tabBar()

    def _local_index_for(self, index: int) -> int:
        tab_ref = getattr(self.tabs, "tab_ref", lambda _index: None)(index)
        return tab_ref.local_index if tab_ref is not None else index

    def _show_command_file_status(self, tab: CommandFileStatusTab) -> None:
        # The shared connection chip/button are hidden for editor tabs (see
        # MainWindow.update_workspace_split_chrome); the footer carries the status.
        self.set_status(tab.status_summary())
