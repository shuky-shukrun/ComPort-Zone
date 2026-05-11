from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QStyle, QTabBar, QTabWidget, QToolButton, QWidget

from ..icons import set_button_icon
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


class TerminalTabWidget(QTabWidget):
    newTabRequested = Signal()
    newTabMenuRequested = Signal(QPoint)
    _NEW_TAB_BUTTON_GAP = 8
    _NEW_TAB_BUTTON_SIDE_MARGIN = 4

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.new_tab_button = QToolButton(self)
        self.new_tab_button.setObjectName("newTabButton")
        set_button_icon(self.new_tab_button, QStyle.StandardPixmap.SP_FileDialogNewFolder, 17)
        self.new_tab_button.setToolTip("New tab")
        self.new_tab_button.setAutoRaise(True)
        self.new_tab_button.setFixedSize(32, 28)
        self.new_tab_button.clicked.connect(self.newTabRequested.emit)
        self.new_tab_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.new_tab_button.customContextMenuRequested.connect(
            lambda position: self.newTabMenuRequested.emit(self.new_tab_button.mapToGlobal(position))
        )
        self.tabBar().installEventFilter(self)
        self.currentChanged.connect(lambda _: self._schedule_new_tab_button_position())

    def tabInserted(self, index: int) -> None:
        super().tabInserted(index)
        self._schedule_new_tab_button_position()

    def tabRemoved(self, index: int) -> None:
        super().tabRemoved(index)
        self._schedule_new_tab_button_position()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_tab_bar_width_limit()
        self._schedule_new_tab_button_position()

    def setTabText(self, index: int, text: str) -> None:
        super().setTabText(index, text)
        self._schedule_new_tab_button_position()

    def setTabIcon(self, index: int, icon) -> None:
        super().setTabIcon(index, icon)
        self._schedule_new_tab_button_position()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.tabBar() and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.LayoutRequest,
            QEvent.Type.Show,
            QEvent.Type.Move,
        }:
            self._schedule_new_tab_button_position()
        return super().eventFilter(watched, event)

    def _schedule_new_tab_button_position(self) -> None:
        QTimer.singleShot(0, self._position_new_tab_button)

    def _sync_tab_bar_width_limit(self) -> None:
        reserved_width = (
            self.new_tab_button.width()
            + self._NEW_TAB_BUTTON_GAP
            + self._NEW_TAB_BUTTON_SIDE_MARGIN
        )
        self.tabBar().setMaximumWidth(max(1, self.width() - reserved_width))

    def _position_new_tab_button(self) -> None:
        bar = self.tabBar()
        self._sync_tab_bar_width_limit()
        bar_origin = bar.mapTo(self, QPoint(0, 0))
        if self.count() == 0:
            desired_x = bar_origin.x() + 6
        else:
            right_edge = max(bar.tabRect(index).right() for index in range(self.count()))
            desired_x = bar_origin.x() + min(right_edge, bar.width() - 1) + self._NEW_TAB_BUTTON_GAP
        max_x = max(
            self._NEW_TAB_BUTTON_SIDE_MARGIN,
            self.width() - self.new_tab_button.width() - self._NEW_TAB_BUTTON_SIDE_MARGIN,
        )
        x = max(self._NEW_TAB_BUTTON_SIDE_MARGIN, min(desired_x, max_x))
        y = bar_origin.y() + max(2, int((bar.height() - self.new_tab_button.height()) / 2))
        self.new_tab_button.move(x, y)
        self.new_tab_button.raise_()


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

    def attach_tab_close_button(self, index: int, widget: QWidget) -> None:
        close_button = QToolButton(self.tabs.tabBar())
        close_button.setObjectName("tabCloseButton")
        close_button.setAutoRaise(True)
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.setFixedSize(22, 22)
        close_button.setToolTip(f"Close {self.tab_display_title(widget)}")
        set_button_icon(close_button, QStyle.StandardPixmap.SP_DialogCloseButton, 13)
        close_button.clicked.connect(
            lambda _checked=False, target=widget: self.close_session(self.tabs.indexOf(target))
        )
        self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, close_button)

    def tab_display_title(self, widget: QWidget | None) -> str:
        if widget is None:
            return "Tab"
        tab_title = getattr(widget, "tab_title", None)
        if callable(tab_title):
            return str(tab_title())
        if tab_title:
            return str(tab_title)
        return "Tab"

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

    def with_current_session(self, callback: Callable[[QWidget], object]) -> bool:
        session = self.current_session()
        if session is None:
            return False
        callback(session)
        return True

    def activate_session(self, index: int, callback: Callable[[QWidget], object]) -> bool:
        session = self.session_at(index)
        if session is None:
            return False
        self.tabs.setCurrentIndex(index)
        callback(session)
        return True

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
