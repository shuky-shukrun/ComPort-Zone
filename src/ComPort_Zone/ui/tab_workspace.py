from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QMenu, QStyle, QTabBar, QTabWidget, QToolButton, QWidget

from ..icons import set_button_icon
from ..models import LanProfile, SerialProfile, TerminalSessionState


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
    profile: SerialProfile | LanProfile
    terminal: TextBufferLike
    command_input: LineEditLike
    mode_combo: ComboBoxLike

    @property
    def tab_title(self) -> str:
        ...

    def shutdown(self) -> None:
        ...

    def to_state(self) -> TerminalSessionState:
        ...


class TerminalTabWidget(QTabWidget):
    newTabRequested = Signal()
    newTabMenuRequested = Signal(QPoint)
    _NEW_TAB_BUTTON_GAP = 8
    _NEW_TAB_BUTTON_SIDE_MARGIN = 4
    _OVERFLOW_BUTTON_GAP = 4

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Named so the QSS can hide the native scroll arrows (QTabBar::scroller) for
        # just this tab strip — overflow is surfaced through the ⋯ menu instead.
        self.setObjectName("sessionTabs")
        # Scroll buttons keep the tab bar's minimum width tiny (≈ one tab) regardless
        # of tab count, so a crowded strip never forces the window wider. The native
        # arrows themselves are hidden in QSS; the ⋯ overflow menu replaces them.
        self.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.new_tab_button = QToolButton(self)
        self.new_tab_button.setObjectName("newTabButton")
        set_button_icon(self.new_tab_button, QStyle.StandardPixmap.SP_FileDialogNewFolder, 17)
        self.new_tab_button.setToolTip("New Terminal")
        self.new_tab_button.setAutoRaise(True)
        self.new_tab_button.setFixedSize(32, 28)
        # Clicking + opens the new-tab menu (New Terminal / New Command File) rather
        # than creating a terminal outright, so the user picks the tab type.
        self.new_tab_button.setToolTip("New tab (choose type)")
        self.new_tab_button.clicked.connect(self._open_new_tab_menu)
        self.new_tab_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.new_tab_button.customContextMenuRequested.connect(
            lambda position: self.newTabMenuRequested.emit(self.new_tab_button.mapToGlobal(position))
        )
        # ⋯ overflow: appears only when the tabs don't all fit. Its menu lists every
        # tab (icon + title, current one checked) so any tab — including ones scrolled
        # out of view — is one click away. Selecting one scrolls it back into view.
        self.overflow_button = QToolButton(self)
        self.overflow_button.setObjectName("tabOverflowButton")
        self.overflow_button.setText("⋯")  # ⋯ horizontal ellipsis
        self.overflow_button.setToolTip("Show all tabs")
        self.overflow_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.overflow_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.overflow_button.setFixedSize(30, 28)
        self.overflow_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._overflow_menu = QMenu(self.overflow_button)
        self._overflow_menu.aboutToShow.connect(self._build_overflow_menu)
        self.overflow_button.setMenu(self._overflow_menu)
        self.overflow_button.hide()
        self.tabBar().installEventFilter(self)
        self.currentChanged.connect(lambda _: self._schedule_tab_button_layout())

    def tabInserted(self, index: int) -> None:
        super().tabInserted(index)
        self._schedule_tab_button_layout()

    def tabRemoved(self, index: int) -> None:
        super().tabRemoved(index)
        self._schedule_tab_button_layout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_tab_bar_width_limit()
        self._schedule_tab_button_layout()

    def setTabText(self, index: int, text: str) -> None:
        super().setTabText(index, text)
        self._schedule_tab_button_layout()

    def setTabIcon(self, index: int, icon) -> None:
        super().setTabIcon(index, icon)
        self._schedule_tab_button_layout()

    def _open_new_tab_menu(self) -> None:
        button = self.new_tab_button
        self.newTabMenuRequested.emit(button.mapToGlobal(button.rect().bottomLeft()))

    def eventFilter(self, watched, event) -> bool:
        if watched is self.tabBar() and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.LayoutRequest,
            QEvent.Type.Show,
            QEvent.Type.Move,
        }:
            self._schedule_tab_button_layout()
        return super().eventFilter(watched, event)

    def _schedule_tab_button_layout(self) -> None:
        QTimer.singleShot(0, self._position_tab_buttons)

    def _tabs_overflowing(self) -> bool:
        """True when the tabs' natural width exceeds the room left after the + button.

        Uses the tab bar's (unconstrained) size hint, so it stays correct even though
        ``_sync_tab_bar_width_limit`` caps the bar's actual width. Reserving the extra
        ⋯ width only once overflow is already true gives a little hysteresis that stops
        the button flickering on/off right at the threshold.
        """
        if self.count() == 0:
            return False
        base_reserved = (
            self.new_tab_button.width()
            + self._NEW_TAB_BUTTON_GAP
            + self._NEW_TAB_BUTTON_SIDE_MARGIN
        )
        return self.tabBar().sizeHint().width() > self.width() - base_reserved

    def _sync_tab_bar_width_limit(self) -> bool:
        """Cap the tab bar so the +/⋯ buttons always have room; return overflow state."""
        overflowing = self._tabs_overflowing()
        reserved = (
            self.new_tab_button.width()
            + self._NEW_TAB_BUTTON_GAP
            + self._NEW_TAB_BUTTON_SIDE_MARGIN
        )
        if overflowing:
            reserved += self.overflow_button.width() + self._OVERFLOW_BUTTON_GAP
        self.tabBar().setMaximumWidth(max(1, self.width() - reserved))
        return overflowing

    def _position_tab_buttons(self) -> None:
        bar = self.tabBar()
        overflowing = self._sync_tab_bar_width_limit()
        bar_origin = bar.mapTo(self, QPoint(0, 0))

        def centered_y(widget: QToolButton) -> int:
            return bar_origin.y() + max(2, int((bar.height() - widget.height()) / 2))

        if overflowing:
            # Crowded strip: pin + to the far right and tuck ⋯ just left of it; the
            # capped tab bar ends one gap before the ⋯ button.
            new_tab_x = max(
                self._NEW_TAB_BUTTON_SIDE_MARGIN,
                self.width() - self.new_tab_button.width() - self._NEW_TAB_BUTTON_SIDE_MARGIN,
            )
            overflow_x = max(
                self._NEW_TAB_BUTTON_SIDE_MARGIN,
                new_tab_x - self._OVERFLOW_BUTTON_GAP - self.overflow_button.width(),
            )
            self.overflow_button.move(overflow_x, centered_y(self.overflow_button))
            self.overflow_button.show()
            self.overflow_button.raise_()
            self.new_tab_button.move(new_tab_x, centered_y(self.new_tab_button))
            self.new_tab_button.raise_()
            return

        # Everything fits: hide ⋯ and let + trail the last tab (or sit at the start
        # of an empty strip).
        self.overflow_button.hide()
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
        self.new_tab_button.move(x, centered_y(self.new_tab_button))
        self.new_tab_button.raise_()

    def _build_overflow_menu(self) -> None:
        menu = self._overflow_menu
        menu.clear()
        current = self.currentIndex()
        for index in range(self.count()):
            title = self.tabText(index).strip() or f"Tab {index + 1}"
            action = menu.addAction(self.tabIcon(index), title)
            action.setCheckable(True)
            action.setChecked(index == current)
            tooltip = self.tabToolTip(index)
            if tooltip:
                action.setToolTip(tooltip)
            widget = self.widget(index)
            action.triggered.connect(
                lambda _checked=False, target=widget: self._activate_overflow_tab(target)
            )

    def _activate_overflow_tab(self, widget: QWidget | None) -> None:
        if widget is None:
            return
        index = self.indexOf(widget)
        if index >= 0:
            # Drives QTabBar.setCurrentIndex -> makeVisible, scrolling the picked tab
            # back on-screen even when the native scroll arrows are hidden.
            self.setCurrentIndex(index)


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
        dashboard_type: type[QWidget] | None = None,
    ) -> None:
        self.tabs = tabs
        self.terminal_type = terminal_type
        self.command_file_type = command_file_type
        self.dashboard_type = dashboard_type
        self._add_session = add_session
        self._confirm_close_command_file_tab = confirm_close_command_file_tab
        self._save_settings = save_settings

    def _is_dashboard(self, widget: QWidget | None) -> bool:
        return self.dashboard_type is not None and isinstance(widget, self.dashboard_type)

    def attach_tab_close_button(self, index: int, widget: QWidget) -> None:
        tab_ref = getattr(self.tabs, "tab_ref", lambda _index: None)(index)
        tab_bar = tab_ref.pane.tabBar() if tab_ref is not None else self.tabs.tabBar()
        local_index = tab_ref.local_index if tab_ref is not None else index
        close_button = QToolButton(tab_bar)
        close_button.setObjectName("tabCloseButton")
        close_button.setAutoRaise(True)
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.setFixedSize(22, 22)
        close_button.setToolTip(f"Close {self.tab_display_title(widget)}")
        set_button_icon(close_button, QStyle.StandardPixmap.SP_DialogCloseButton, 13)
        close_button.clicked.connect(
            lambda _checked=False, target=widget: self.close_session(self.tabs.indexOf(target))
        )
        tab_bar.setTabButton(local_index, QTabBar.ButtonPosition.RightSide, close_button)

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

    def current_dashboard(self) -> QWidget | None:
        widget = self.tabs.currentWidget()
        return widget if self._is_dashboard(widget) else None

    def session_at(self, index: int) -> QWidget | None:
        widget = self.tabs.widget(index)
        return widget if isinstance(widget, self.terminal_type) else None

    def command_file_editor_at(self, index: int) -> QWidget | None:
        widget = self.tabs.widget(index)
        return widget if isinstance(widget, self.command_file_type) else None

    def dashboard_at(self, index: int) -> QWidget | None:
        widget = self.tabs.widget(index)
        return widget if self._is_dashboard(widget) else None

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

    def iter_dashboards(self) -> list[QWidget]:
        return [widget for widget in self._widgets() if self._is_dashboard(widget)]

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
        # Terminals and dashboards own background resources (reader threads,
        # poll dispatchers); dashboards live-save so no confirmation is needed.
        if isinstance(widget, self.terminal_type) or self._is_dashboard(widget):
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
        tab_ref = getattr(self.tabs, "tab_ref", lambda _index: None)(index)
        if tab_ref is not None:
            pane = tab_ref.pane
            if tab_ref.local_index >= pane.count() - 1:
                return
            for local_index in range(pane.count() - 1, tab_ref.local_index, -1):
                widget = pane.widget(local_index)
                global_index = self.tabs.indexOf(widget) if widget is not None else -1
                if not self.close_session(global_index):
                    break
            current_index = self.tabs.indexOf(tab_ref.widget)
            if current_index >= 0:
                self.tabs.setCurrentIndex(current_index)
            self._save_settings()
            return
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
        to_state = getattr(session, "to_state", None)
        if callable(to_state):
            state = to_state()
        else:
            state = TerminalSessionState(
                serial=SerialProfile.from_dict(session.profile.to_dict()),
                terminal_text=session.terminal.toPlainText(),
                command_draft=session.command_input.text(),
                send_mode=session.mode_combo.currentText(),
            )
        state.title = f"{session.tab_title} Copy"
        state.title_is_custom = True
        state.connected_on_launch = False
        return state
