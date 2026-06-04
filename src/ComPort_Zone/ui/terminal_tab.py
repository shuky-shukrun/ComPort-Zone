from __future__ import annotations

from datetime import datetime
from pathlib import Path
from queue import Empty

from PySide6.QtCore import QEvent, Qt, QStringListModel, QTimer, Signal
from PySide6.QtGui import QAction, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyle,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from ..batch import BatchParseError, parse_hex_payload
from ..icons import connection_state_icon, set_button_icon
from ..models import (
    LanProfile,
    QUICK_COMMAND_SORT_MODES,
    QUICK_FILE_SORT_MODES,
    RECEIVE_DISPLAY_MODES,
    QuickCommand,
    QuickFile,
    SerialProfile,
    TerminalSessionState,
)
from ..quick_actions import SEND_MODES, quick_file_display_text
from ..quick_actions_panel import (
    item_ids_in_order,
    populate_quick_command_list,
    populate_quick_file_list,
    populate_quick_history_list,
    row_for_item_id,
    selected_item_id,
)
from ..quick_actions_sidebar import QuickActionsSidebar, QuickActionsSidebarActions
from ..serial_core import SerialEvent, decode_serial_bytes, format_hex_bytes
from ..terminal_session_controller import ConnectionProfile, TerminalRenderPlan, TerminalSessionController
from ..terminal_view import TerminalView
from ..themes import mix_hex
from ..transports import SerialTransportAdapter
from ..widgets import ChevronComboBox, IntegratedTerminalEdit, set_button_role, set_widget_state
from .dialogs import BatchParameterPromptBridge, CommandFileParametersDialog, ConnectionSettingsDialog
from .fonts import TERMINAL_FONT_MAX, TERMINAL_FONT_MIN, pick_mono_font
from .tokens import DRAWER_COLLAPSE_AT, DRAWER_MAX_W, DRAWER_MIN_W, SPLITTER_HANDLE

DRAWER_COLLAPSED_WIDTH = 48
# Scrollback cap for the stored transcript that backs timestamp/hex re-rendering.
TRANSCRIPT_EVENT_CAP = 5000


class TerminalConnectionStatusLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:
        position = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(position):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def clone_profile(profile: SerialProfile) -> SerialProfile:
    return SerialProfile.from_dict(profile.to_dict())


def clone_lan_profile(profile: LanProfile) -> LanProfile:
    return LanProfile.from_dict(profile.to_dict())


def short_label(text: str, limit: int = 40) -> str:
    text = text.strip()
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


class TerminalSessionWidget(QWidget):
    def __init__(self, host: "MainWindow", session_id: int, state: TerminalSessionState) -> None:
        super().__init__(host)
        self.host = host
        self.session_id = session_id
        self.title = state.title or f"Terminal {session_id}"
        self.title_is_custom = state.title_is_custom or (
            bool(self.title)
            and not self.title.startswith("Terminal")
            and self.title not in {"No port", "No endpoint"}
        )
        self.transport_kind = state.transport_kind or "serial"
        self.profile: ConnectionProfile = self._profile_from_state(state)
        self.parameter_prompt_bridge = BatchParameterPromptBridge(self)
        self.controller = TerminalSessionController(
            self.profile,
            history_commands=host.history_catalog.all_commands(),
            parameter_prompt=self.parameter_prompt_bridge.prompt,
            transport_kind=self.transport_kind,
        )
        self.transport = self.controller.transport
        self.serial_client = self.controller.serial_client
        self.history_store = self.controller.history_store
        self.logger = self.controller.logger
        self.batch_runner = self.controller.batch_runner
        self._connected = False
        self._status_text = "Disconnected"
        self._quick_list_refreshing = False
        self._quick_file_list_refreshing = False
        self._suppressed_tx_echoes: list[str] = []
        # Stored transcript entries so timestamp/hex toggles re-render all history.
        self._transcript: list[tuple] = []
        self._replaying = False

        self._build_ui()
        self.refresh_ports()
        self.refresh_quick_commands()
        self.refresh_quick_files()
        self.apply_settings()
        if state.send_mode in SEND_MODES:
            self.mode_combo.setCurrentText(state.send_mode)
        if state.command_draft:
            self.command_input.setText(state.command_draft)
        if state.terminal_text:
            self.terminal.setPlainText(state.terminal_text)
            self.terminal.moveCursor(QTextCursor.MoveOperation.End)
        self.apply_drawer_state(
            host.settings.drawer_collapsed,
            host.settings.drawer_width,
            host.settings.drawer_page_index,
        )
        self._update_connection_ui(False)

        self.event_timer = QTimer(self)
        self.event_timer.timeout.connect(self._drain_events)
        self.event_timer.start(50)

    @property
    def tab_title(self) -> str:
        if self.title_is_custom:
            return self.title
        endpoint = self.connection_endpoint()
        if endpoint:
            return endpoint
        return "No endpoint" if self.transport_kind == "lan" else "No port"

    @property
    def paused(self) -> bool:
        return self.controller.paused

    @paused.setter
    def paused(self, value: bool) -> None:
        self.controller.paused = value

    @property
    def pending_events(self) -> list[SerialEvent]:
        return self.controller.pending_events

    def to_state(self) -> TerminalSessionState:
        transport_profile = self.profile.to_dict()
        serial_profile = clone_profile(self.profile) if isinstance(self.profile, SerialProfile) else None
        lan_profile = clone_lan_profile(self.profile) if isinstance(self.profile, LanProfile) else None
        return TerminalSessionState(
            title=self.title,
            title_is_custom=self.title_is_custom,
            transport_kind=self.transport_kind,
            transport_profile=transport_profile,
            serial=serial_profile,
            lan=lan_profile,
            connected_on_launch=self._connected or self.transport.is_connected,
            terminal_text=self.terminal.toPlainText(),
            command_draft=self.command_input.text(),
            send_mode=self.mode_combo.currentText(),
        )

    def _profile_from_state(self, state: TerminalSessionState) -> ConnectionProfile:
        if self.transport_kind == "lan":
            if state.lan is not None:
                return clone_lan_profile(state.lan)
            if state.transport_profile:
                return LanProfile.from_dict(state.transport_profile)
            return self.host.default_lan_profile()
        if state.serial is not None:
            return clone_profile(state.serial)
        if state.transport_profile:
            return SerialProfile.from_dict(state.transport_profile)
        return self.host.default_serial_profile()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(SPLITTER_HANDLE)
        self.splitter.splitterMoved.connect(self._drawer_resized)

        self.drawer = self._build_quick_actions_sidebar()
        self.drawer_rail = self.drawer.rail
        self.drawer_panel = self.drawer.panel
        self.drawer_pages = self.drawer.pages

        self.terminal_column = QFrame(self)
        self.terminal_column.setObjectName("terminalColumn")
        terminal_layout = QVBoxLayout(self.terminal_column)
        terminal_layout.setContentsMargins(0, 0, 0, 0)
        terminal_layout.setSpacing(0)

        self.search_bar = QFrame(self.terminal_column)
        self.search_bar.setObjectName("searchBar")
        search_layout = QHBoxLayout(self.search_bar)
        search_layout.setContentsMargins(8, 6, 8, 6)
        search_layout.setSpacing(6)
        self.search_input = QLineEdit(self.search_bar)
        self.search_input.setPlaceholderText("Search")
        self.search_input.textChanged.connect(self._refresh_search_highlights)
        self.search_input.returnPressed.connect(self.find_next)
        prev_button = QPushButton("Prev", self.search_bar)
        set_button_icon(prev_button, QStyle.StandardPixmap.SP_ArrowBack)
        prev_button.setToolTip("Previous match")
        prev_button.clicked.connect(self.find_previous)
        next_button = QPushButton("Next", self.search_bar)
        set_button_icon(next_button, QStyle.StandardPixmap.SP_ArrowForward)
        next_button.setToolTip("Next match (Enter)")
        next_button.clicked.connect(self.find_next)
        close_search = QPushButton("", self.search_bar)
        set_button_icon(close_search, QStyle.StandardPixmap.SP_DialogCloseButton)
        close_search.setToolTip("Close search (Esc)")
        close_search.setAccessibleName("Close search")
        close_search.clicked.connect(self.hide_search)
        self.search_count = QLabel("0", self.search_bar)
        search_layout.addWidget(self.search_input, 1)
        search_layout.addWidget(prev_button)
        search_layout.addWidget(next_button)
        search_layout.addWidget(self.search_count)
        search_layout.addWidget(close_search)
        self.search_bar.hide()

        self.terminal = IntegratedTerminalEdit(self.terminal_column)
        self.terminal.setObjectName("terminal")
        self.terminal.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.terminal.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.terminal.customContextMenuRequested.connect(self.show_terminal_context_menu)
        self.terminal_view = TerminalView(self.terminal, self.search_count)
        self.command_input = self.terminal
        self.terminal.set_font_zoom_callback(lambda delta: self.host.change_font_size(delta))

        self.command_bar = QFrame(self.terminal_column)
        self.command_bar.setObjectName("commandBar")
        command_layout = QHBoxLayout(self.command_bar)
        command_layout.setContentsMargins(8, 6, 8, 6)
        command_layout.setSpacing(6)

        self.status_label = TerminalConnectionStatusLabel("Disconnected", self.command_bar)
        self.status_label.setObjectName("terminalConnectionStatus")
        self.status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.status_label.setMaximumWidth(220)
        self.status_label.setToolTip("Click to open Connection Settings.")
        self.status_label.clicked.connect(self.open_connection_settings)
        self.connection_button = QPushButton("Connect", self.command_bar)
        self.connection_button.setObjectName("terminalConnectionActionButton")
        self.connection_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connection_button.clicked.connect(self.toggle_connection)
        self.script_pause_button = QPushButton("Pause", self.command_bar)
        self.script_pause_button.setObjectName("commandFilePauseButton")
        self.script_pause_button.setToolTip("Pause the running command file.")
        set_button_icon(self.script_pause_button, QStyle.StandardPixmap.SP_MediaPause, 15)
        self.script_pause_button.clicked.connect(self.pause_script)
        self.script_resume_button = QPushButton("Resume", self.command_bar)
        self.script_resume_button.setObjectName("commandFileResumeButton")
        self.script_resume_button.setToolTip("Resume the paused command file.")
        set_button_icon(self.script_resume_button, QStyle.StandardPixmap.SP_MediaPlay, 15)
        self.script_resume_button.clicked.connect(self.resume_script)
        self.script_stop_button = QPushButton("Stop", self.command_bar)
        self.script_stop_button.setObjectName("commandFileStopButton")
        self.script_stop_button.setToolTip("Stop the running command file.")
        set_button_icon(self.script_stop_button, QStyle.StandardPixmap.SP_MediaStop, 15)
        self.script_stop_button.clicked.connect(self.stop_script)
        self.script_status_label = QLabel("File idle", self.command_bar)
        self.script_status_label.setObjectName("commandFileStatusLabel")
        self.mode_combo = ChevronComboBox(self.command_bar)
        self.mode_combo.addItems(SEND_MODES)
        self.mode_combo.setFixedWidth(118)
        self.mode_combo.setToolTip("Send mode")
        self.rx_display_combo = ChevronComboBox(self.command_bar)
        for receive_mode in RECEIVE_DISPLAY_MODES:
            self.rx_display_combo.addItem(f"RX {receive_mode}", receive_mode)
        self.rx_display_combo.setFixedWidth(132)
        self.rx_display_combo.setToolTip("Receive display mode")
        self.rx_display_combo.currentIndexChanged.connect(self._receive_display_mode_changed)
        self.command_input.returnPressed.connect(self.send_from_input)
        self.command_input.historyRequested.connect(self._navigate_history)
        self.command_input.autocompleteRequested.connect(self._show_completion_popup)
        self.command_input.deleteHistoryRequested.connect(self._delete_current_input_from_history)
        self.command_input.textEdited.connect(self._on_command_edited)
        self.completion_model = QStringListModel(self)
        completer = QCompleter(self.completion_model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.activated.connect(self._apply_completion)
        self.command_input.setCompleter(completer)
        self.line_ending_label = QLabel("", self.command_bar)
        # Compact view/IO toggles that sit in the status area: timestamps, hex view,
        # and session logging. They stay visible even when the bar is narrow.
        self.timestamp_toggle = self._make_status_toggle(
            "clock", "Show timestamps on received lines", self._toggle_timestamps_clicked
        )
        self.hex_toggle = self._make_status_toggle(
            "hex", "Show received data as hex", self._toggle_hex_clicked
        )
        self.log_toggle = self._make_status_toggle(
            "save", "Log this session to a file", self._toggle_log_clicked
        )
        self.pause_label = QLabel("", self.command_bar)
        # Overflow for the IO controls: when the command bar is too narrow they
        # collapse into this "⋯" menu so the terminal can keep shrinking.
        self.command_overflow_button = QToolButton(self.command_bar)
        self.command_overflow_button.setObjectName("commandBarOverflow")
        self.command_overflow_button.setText("⋯")
        self.command_overflow_button.setToolTip("Send mode, receive display, line ending")
        self.command_overflow_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.command_overflow_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.command_overflow_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._command_overflow_menu = QMenu(self.command_overflow_button)
        self._command_overflow_menu.aboutToShow.connect(self._build_command_overflow_menu)
        self.command_overflow_button.setMenu(self._command_overflow_menu)
        self.command_overflow_button.hide()
        self._command_secondary = [
            self.mode_combo,
            self.rx_display_combo,
            self.line_ending_label,
        ]
        command_layout.addWidget(self.status_label)
        command_layout.addWidget(self.connection_button)
        command_layout.addWidget(self.script_pause_button)
        command_layout.addWidget(self.script_resume_button)
        command_layout.addWidget(self.script_stop_button)
        command_layout.addWidget(self.script_status_label)
        command_layout.addStretch(1)
        command_layout.addWidget(self.mode_combo)
        command_layout.addWidget(self.rx_display_combo)
        command_layout.addWidget(self.line_ending_label)
        command_layout.addWidget(self.command_overflow_button)
        command_layout.addWidget(self.timestamp_toggle)
        command_layout.addWidget(self.hex_toggle)
        command_layout.addWidget(self.log_toggle)
        command_layout.addWidget(self.pause_label)
        self.command_bar.installEventFilter(self)
        self._sync_status_toggles()

        terminal_layout.addWidget(self.search_bar)
        terminal_layout.addWidget(self.terminal, 1)
        terminal_layout.addWidget(self.command_bar)

        self.splitter.addWidget(self.drawer)
        self.splitter.addWidget(self.terminal_column)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        root.addWidget(self.splitter)
        self._refresh_script_controls()

    def eventFilter(self, obj, event):
        if obj is self.command_bar and event.type() == QEvent.Type.Resize:
            self._relayout_command_bar()
        return super().eventFilter(obj, event)

    def _relayout_command_bar(self) -> None:
        """Collapse the IO controls into the overflow menu when the bar is narrow."""
        if not hasattr(self, "command_overflow_button"):
            return
        layout = self.command_bar.layout()
        spacing = layout.spacing()
        margins = layout.contentsMargins()
        essentials = [
            self.status_label,
            self.connection_button,
            self.script_status_label,
            self.timestamp_toggle,
            self.hex_toggle,
            self.log_toggle,
        ]
        for button in (self.script_pause_button, self.script_resume_button, self.script_stop_button):
            if button.isVisible():
                essentials.append(button)
        needed = margins.left() + margins.right() + 16
        for widget in essentials + self._command_secondary:
            needed += widget.sizeHint().width() + spacing
        collapse = self.command_bar.width() < needed
        for widget in self._command_secondary:
            widget.setVisible(not collapse)
        self.command_overflow_button.setVisible(collapse)

    def _build_command_overflow_menu(self) -> None:
        menu = self._command_overflow_menu
        menu.clear()
        send_menu = menu.addMenu("Send mode")
        for index in range(self.mode_combo.count()):
            action = send_menu.addAction(self.mode_combo.itemText(index))
            action.setCheckable(True)
            action.setChecked(index == self.mode_combo.currentIndex())
            action.triggered.connect(lambda _checked=False, idx=index: self.mode_combo.setCurrentIndex(idx))
        receive_menu = menu.addMenu("Receive display")
        for index in range(self.rx_display_combo.count()):
            action = receive_menu.addAction(self.rx_display_combo.itemText(index))
            action.setCheckable(True)
            action.setChecked(index == self.rx_display_combo.currentIndex())
            action.triggered.connect(lambda _checked=False, idx=index: self.rx_display_combo.setCurrentIndex(idx))
        menu.addSeparator()
        line_ending = self.line_ending_label.text().strip()
        if line_ending:
            menu.addAction(line_ending).setEnabled(False)

    def _make_status_toggle(self, icon_name: str, tooltip: str, slot) -> QToolButton:
        """A compact checkable icon button for the command bar's status toggles."""
        button = QToolButton(self.command_bar)
        button.setObjectName("statusToggleButton")
        button.setCheckable(True)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setProperty("iconName", icon_name)
        button.clicked.connect(slot)
        return button

    def _toggle_timestamps_clicked(self, checked: bool) -> None:
        self.host.set_timestamps_enabled(checked)

    def _toggle_hex_clicked(self, checked: bool) -> None:
        self.host.set_receive_display_mode("Hex" if checked else "Text")

    def _toggle_log_clicked(self, _checked: bool = False) -> None:
        # Logging owns its real state (file dialog / logger); re-sync from it.
        self.toggle_logging()

    def _sync_status_toggles(self) -> None:
        """Reflect timestamp / hex / logging state on the command-bar toggles."""
        if not hasattr(self, "log_toggle"):
            return
        settings = self.host.settings
        theme = self.host.theme
        for button, on in (
            (self.timestamp_toggle, bool(settings.timestamps_enabled)),
            (self.hex_toggle, settings.receive_display_mode in ("Hex", "Text + Hex")),
            (self.log_toggle, bool(self.logger.enabled)),
        ):
            if button.isChecked() != on:
                button.blockSignals(True)
                button.setChecked(on)
                button.blockSignals(False)
            # SVG icons are pixmaps, so tint explicitly: accent when active, else muted.
            set_button_icon(button, str(button.property("iconName")), 15, theme.accent if on else theme.muted)

    def _build_quick_actions_sidebar(self) -> QuickActionsSidebar:
        sidebar = QuickActionsSidebar(
            actions=QuickActionsSidebarActions(
                command_primary=lambda: self.host.use_quick_command_from_sidebar(self),
                file_primary=lambda: self.host.use_quick_file_from_sidebar(self),
                add_command=self.host.add_quick_command,
                edit_command=lambda: self.host.edit_quick_command(self.selected_quick_command_id()),
                delete_command=lambda: self.host.delete_quick_command(self.selected_quick_command_id()),
                move_command_up=lambda: self.host.move_quick_command(self.selected_quick_command_id(), -1),
                move_command_down=lambda: self.host.move_quick_command(self.selected_quick_command_id(), 1),
                import_commands=self.host.import_quick_commands_csv,
                export_commands=self.host.export_quick_commands_csv,
                add_file=self.host.add_quick_file,
                edit_file=lambda: self.host.edit_quick_file(self.selected_quick_file_id()),
                delete_file=lambda: self.host.delete_quick_file(self.selected_quick_file_id()),
                move_file_up=lambda: self.move_selected_quick_file(-1),
                move_file_down=lambda: self.move_selected_quick_file(1),
                import_files=self.host.import_quick_files_csv,
                export_files=self.host.export_quick_files_csv,
            ),
            command_primary_label="Send",
            file_primary_label="Run",
            command_tooltip="Right-click a saved command for actions. Press and drag to reorder.",
            file_tooltip="Double-click a saved command file to run it. Press and drag to reorder.",
            command_double_clicked=lambda: self.host.use_quick_command_from_sidebar(self),
            file_double_clicked=lambda: self.host.use_quick_file_from_sidebar(self),
            command_context_menu_requested=self.show_quick_command_context_menu,
            file_context_menu_requested=self.show_quick_file_context_menu,
            command_sort_changed=self._quick_sort_changed,
            file_sort_changed=self._quick_file_sort_changed,
            command_order_changed=self.persist_quick_command_order,
            file_order_changed=self.persist_quick_file_order,
            include_history=True,
            history_primary=self._resend_history_command,
            settings_callback=self.host.show_command_palette,
            on_page_requested=self._select_drawer_page,
            rail_width=DRAWER_COLLAPSED_WIDTH,
            parent=self,
        )
        self.quick_list = sidebar.quick_command_list
        self.quick_file_list = sidebar.quick_file_list
        self.quick_history_list = sidebar.quick_history_list
        self.quick_sort_combo = sidebar.quick_sort_combo
        self.quick_group_button = sidebar.quick_group_button
        self.quick_file_sort_combo = sidebar.quick_file_sort_combo
        self.quick_move_up_button = sidebar.quick_command_move_up_button
        self.quick_move_down_button = sidebar.quick_command_move_down_button
        self.quick_file_move_up_button = sidebar.quick_file_move_up_button
        self.quick_file_move_down_button = sidebar.quick_file_move_down_button
        self.refresh_quick_history()
        return sidebar

    def _resend_history_command(self, command: str) -> None:
        text = command.strip()
        if not text:
            return
        self._send_integrated_input(text, self.mode_combo.currentText())

    def resend_command(self, command: str) -> None:
        """Send a previous command again (used by the shared History panel)."""
        self._resend_history_command(command)

    def refresh_quick_history(self) -> None:
        history = list(reversed(self.host.history_catalog.all_commands()))
        populate_quick_history_list(self.quick_history_list, history[:80])

    def _select_drawer_page(self, index: int) -> None:
        self.host.request_drawer_page(index)

    def apply_settings(self) -> None:
        self.terminal.document().setMaximumBlockCount(max(self.host.settings.scrollback_size, 1000))
        self.terminal.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth
            if self.host.settings.line_wrap_enabled
            else QTextEdit.LineWrapMode.NoWrap
        )
        terminal_font = pick_mono_font(
            max(TERMINAL_FONT_MIN, min(self.host.settings.terminal_font_size, TERMINAL_FONT_MAX)),
            self.host.settings.terminal_font_family,
        )
        self.terminal.setFont(terminal_font)
        self.terminal.document().setDefaultFont(terminal_font)
        if hasattr(self.terminal, "set_terminal_colors"):
            self.terminal.set_terminal_colors(prompt=self.host.theme.tx, draft=self.host.theme.text)
        receive_mode = (
            self.host.settings.receive_display_mode
            if self.host.settings.receive_display_mode in RECEIVE_DISPLAY_MODES
            else "Text"
        )
        self.rx_display_combo.blockSignals(True)
        receive_mode_index = self.rx_display_combo.findData(receive_mode)
        if receive_mode_index >= 0:
            self.rx_display_combo.setCurrentIndex(receive_mode_index)
        self.rx_display_combo.blockSignals(False)
        self._update_line_ending_label()
        self._sync_status_toggles()

    def apply_theme_palette(self) -> None:
        if hasattr(self.terminal, "set_terminal_colors"):
            self.terminal.set_terminal_colors(prompt=self.host.theme.tx, draft=self.host.theme.text)
        if hasattr(self, "drawer") and hasattr(self.drawer, "apply_theme_palette"):
            self.drawer.apply_theme_palette(self.host.theme)
        self._sync_status_toggles()

    def _receive_display_mode_changed(self) -> None:
        mode = self.rx_display_combo.currentData()
        if mode:
            self.host.set_receive_display_mode(str(mode))

    def apply_drawer_state(self, collapsed: bool, width: int, page_index: int | None = None) -> None:
        if page_index is not None and self.drawer_pages.count() > 0:
            self.drawer_pages.setCurrentIndex(max(0, min(page_index, self.drawer_pages.count() - 1)))
        self.drawer_panel.setVisible(not collapsed)
        if not collapsed and hasattr(self, "quick_history_list"):
            self.refresh_quick_history()
        if collapsed:
            self.drawer.setMinimumWidth(DRAWER_COLLAPSED_WIDTH)
            self.drawer.setMaximumWidth(DRAWER_COLLAPSED_WIDTH)
            self.splitter.setSizes([DRAWER_COLLAPSED_WIDTH, max(200, self.width() - DRAWER_COLLAPSED_WIDTH)])
            return
        drawer_width = max(DRAWER_MIN_W, min(width, DRAWER_MAX_W))
        self.drawer.setMinimumWidth(DRAWER_MIN_W)
        self.drawer.setMaximumWidth(DRAWER_MAX_W)
        self.splitter.setSizes([drawer_width, max(200, self.width() - drawer_width)])

    def set_workspace_drawer_visible(self, visible: bool) -> None:
        if visible:
            self.drawer.setVisible(True)
            self.apply_drawer_state(
                self.host.settings.drawer_collapsed,
                self.host.settings.drawer_width,
                self.host.settings.drawer_page_index,
            )
            return
        self.drawer.setVisible(False)
        self.drawer.setMinimumWidth(0)
        self.drawer.setMaximumWidth(0)
        self.splitter.setSizes([0, max(700, self.width())])

    def _drawer_resized(self, pos: int, index: int) -> None:
        if self.host.settings.drawer_collapsed:
            return
        sizes = self.splitter.sizes()
        if not sizes:
            return
        # Dragging the handle below the open-drawer floor auto-collapses to the rail
        # rather than clipping the rows' send/play affordance.
        if sizes[0] < DRAWER_COLLAPSE_AT:
            self.host.set_drawer_collapsed(True)
            return
        self.host.set_drawer_width(sizes[0], source=self)

    def _quick_sort_changed(self) -> None:
        mode = self.quick_sort_combo.currentData()
        if mode:
            self.host.set_quick_command_sort_mode(str(mode))

    def _quick_file_sort_changed(self) -> None:
        mode = self.quick_file_sort_combo.currentData()
        if mode:
            self.host.set_quick_file_sort_mode(str(mode))

    def quick_command_groups(self) -> list[str]:
        self.host._refresh_quick_actions_from_settings()
        return self.host.quick_actions.command_group_names()

    def visible_quick_commands(self) -> list[QuickCommand]:
        self.host._refresh_quick_actions_from_settings()
        return self.host.quick_actions.visible_commands()

    def can_manually_reorder_quick_commands(self) -> bool:
        self.host._refresh_quick_actions_from_settings()
        return self.host.quick_actions.can_manually_reorder_commands()

    def refresh_quick_command_controls(self) -> None:
        mode = (
            self.host.quick_actions.command_sort_mode
            if self.host.quick_actions.command_sort_mode in QUICK_COMMAND_SORT_MODES
            else "Custom"
        )
        self.quick_sort_combo.blockSignals(True)
        index = self.quick_sort_combo.findData(mode)
        if index >= 0:
            self.quick_sort_combo.setCurrentIndex(index)
        self.quick_sort_combo.blockSignals(False)

        groups = self.quick_command_groups()
        hidden = {group.casefold() for group in self.host.quick_actions.command_hidden_groups}
        visible_count = sum(1 for group in groups if group.casefold() not in hidden)
        total_count = len(groups)
        if total_count == 0:
            group_text = "Groups: None"
        elif visible_count == total_count:
            group_text = "Groups: All"
        elif visible_count == 0:
            group_text = "Groups: Hidden"
        else:
            group_text = f"Groups: {visible_count}/{total_count}"
        self.quick_group_button.setText(group_text)

        old_menu = self.quick_group_button.menu()
        if old_menu is not None:
            old_menu.deleteLater()
        menu = QMenu(self.quick_group_button)
        self.host._add_context_action(
            menu,
            "Show All Groups",
            self.host.show_all_quick_command_groups,
            icon=QStyle.StandardPixmap.SP_DialogApplyButton,
            enabled=total_count > 0 and visible_count < total_count,
        )
        self.host._add_context_action(
            menu,
            "Hide All Groups",
            self.host.hide_all_quick_command_groups,
            icon=QStyle.StandardPixmap.SP_TrashIcon,
            enabled=total_count > 0 and visible_count > 0,
        )
        if groups:
            menu.addSeparator()
            for group in groups:
                action = QAction(group, menu)
                action.setCheckable(True)
                action.setChecked(group.casefold() not in hidden)
                action.toggled.connect(
                    lambda checked, group=group: self.host.set_quick_command_group_visible(group, checked)
                )
                menu.addAction(action)
        else:
            action = QAction("No groups yet", menu)
            action.setEnabled(False)
            menu.addAction(action)
        self.quick_group_button.setMenu(menu)

        can_reorder = self.can_manually_reorder_quick_commands()
        self.quick_list.setDragEnabled(can_reorder)
        self.quick_list.setAcceptDrops(can_reorder)
        self.quick_list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
            if can_reorder
            else QAbstractItemView.DragDropMode.NoDragDrop
        )
        self.quick_move_up_button.setEnabled(can_reorder)
        self.quick_move_down_button.setEnabled(can_reorder)
        if can_reorder:
            self.quick_list.setToolTip("Right-click a saved command for actions. Press and drag to reorder.")
        else:
            self.quick_list.setToolTip("Reorder is available only in Custom order with all groups visible.")

    def visible_quick_files(self) -> list[QuickFile]:
        self.host._refresh_quick_actions_from_settings()
        return self.host.quick_actions.visible_files()

    def refresh_quick_file_controls(self) -> None:
        if not hasattr(self, "quick_file_sort_combo"):
            return
        mode = (
            self.host.quick_actions.file_sort_mode
            if self.host.quick_actions.file_sort_mode in QUICK_FILE_SORT_MODES
            else "Custom"
        )
        self.quick_file_sort_combo.blockSignals(True)
        index = self.quick_file_sort_combo.findData(mode)
        if index >= 0:
            self.quick_file_sort_combo.setCurrentIndex(index)
        self.quick_file_sort_combo.blockSignals(False)
        self.quick_file_list.setDragEnabled(True)
        self.quick_file_list.setAcceptDrops(True)
        self.quick_file_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        if hasattr(self, "quick_file_move_up_button"):
            self.quick_file_move_up_button.setEnabled(True)
        if hasattr(self, "quick_file_move_down_button"):
            self.quick_file_move_down_button.setEnabled(True)
        if mode == "Custom":
            self.quick_file_list.setToolTip("Double-click a saved command file to run it. Press and drag to reorder.")
        else:
            self.quick_file_list.setToolTip("Double-click to run. Dragging or moving a file switches this list to Custom order.")

    def selected_quick_command_id(self) -> str:
        return selected_item_id(self.quick_list)

    def quick_command_row(self, command_id: str) -> int:
        return row_for_item_id(self.quick_list, command_id)

    def quick_command_ids_in_list_order(self) -> list[str]:
        return item_ids_in_order(self.quick_list)

    def persist_quick_command_order(self) -> None:
        if self._quick_list_refreshing or not self.can_manually_reorder_quick_commands():
            return
        self.host.reorder_quick_commands(
            self.quick_command_ids_in_list_order(),
            selected_id=self.selected_quick_command_id(),
        )

    def show_quick_command_context_menu(self, position) -> None:
        item = self.quick_list.itemAt(position)
        command_id = ""
        if item:
            self.quick_list.setCurrentItem(item)
            command_id = str(item.data(Qt.ItemDataRole.UserRole))
        menu = self.build_quick_command_context_menu(command_id)
        menu.exec(self.quick_list.mapToGlobal(position))

    def build_quick_command_context_menu(self, command_id: str) -> QMenu:
        menu = QMenu(self)
        command = self.host.quick_command_by_id(command_id)
        if not command:
            self.host._add_context_action(
                menu,
                "Add New Command",
                self.host.add_quick_command,
                icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
            )
            self.host._add_context_action(
                menu,
                "Import from CSV",
                self.host.import_quick_commands_csv,
                icon=QStyle.StandardPixmap.SP_DialogOpenButton,
            )
            self.host._add_context_action(
                menu,
                "Export to CSV",
                self.host.export_quick_commands_csv,
                icon=QStyle.StandardPixmap.SP_DialogSaveButton,
                enabled=bool(self.host.quick_actions.quick_commands),
            )
            return menu

        row = self.quick_command_row(command_id)
        can_reorder = self.can_manually_reorder_quick_commands()
        menu.setTitle(command.display_label())
        self.host._add_context_action(
            menu,
            "Send",
            self.send_selected_quick_command,
            icon=QStyle.StandardPixmap.SP_ArrowForward,
        )
        menu.addSeparator()
        self.host._add_context_action(
            menu,
            "Add New Command",
            self.host.add_quick_command,
            icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
        )
        self.host._add_context_action(
            menu,
            "Edit",
            lambda command_id=command_id: self.host.edit_quick_command(command_id),
            icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
        )
        self.host._add_context_action(
            menu,
            "Duplicate",
            lambda command_id=command_id: self.host.duplicate_quick_command(command_id),
            icon=QStyle.StandardPixmap.SP_FileIcon,
        )
        self.host._add_context_action(
            menu,
            "Delete",
            lambda command_id=command_id: self.host.delete_quick_command(command_id),
            icon=QStyle.StandardPixmap.SP_TrashIcon,
        )
        menu.addSeparator()
        self.host._add_context_action(
            menu,
            "Copy Command Text",
            lambda command_id=command_id: self.host.copy_quick_command_text(command_id),
            icon=QStyle.StandardPixmap.SP_FileIcon,
        )
        self.host._add_context_action(
            menu,
            "Import from CSV",
            self.host.import_quick_commands_csv,
            icon=QStyle.StandardPixmap.SP_DialogOpenButton,
        )
        self.host._add_context_action(
            menu,
            "Export to CSV",
            self.host.export_quick_commands_csv,
            icon=QStyle.StandardPixmap.SP_DialogSaveButton,
            enabled=bool(self.host.quick_actions.quick_commands),
        )
        menu.addSeparator()
        self.host._add_context_action(
            menu,
            "Move Up",
            lambda command_id=command_id: self.host.move_quick_command(command_id, -1),
            icon=QStyle.StandardPixmap.SP_ArrowUp,
            enabled=can_reorder and row > 0,
        )
        self.host._add_context_action(
            menu,
            "Move Down",
            lambda command_id=command_id: self.host.move_quick_command(command_id, 1),
            icon=QStyle.StandardPixmap.SP_ArrowDown,
            enabled=can_reorder and 0 <= row < self.quick_list.count() - 1,
        )
        return menu

    def refresh_quick_commands(self, selected_id: str | None = None) -> None:
        selected_id = selected_id or self.selected_quick_command_id()
        self._quick_list_refreshing = True
        self.refresh_quick_command_controls()
        populate_quick_command_list(
            self.quick_list,
            self.visible_quick_commands(),
            selected_id=selected_id,
            label_limit=30,
            group_limit=10,
            draggable=True,
        )
        self._quick_list_refreshing = False
        self._update_completion_model()

    def selected_quick_file_id(self) -> str:
        return selected_item_id(self.quick_file_list)

    def quick_file_row(self, quick_file_id: str) -> int:
        return row_for_item_id(self.quick_file_list, quick_file_id)

    def quick_file_ids_in_list_order(self) -> list[str]:
        return item_ids_in_order(self.quick_file_list)

    def move_selected_quick_file(self, direction: int) -> None:
        quick_file_id = self.selected_quick_file_id()
        if not quick_file_id:
            self.host.set_status("Select a quick file to move.")
            return
        row = self.quick_file_row(quick_file_id)
        target = row + direction
        if row < 0 or target < 0 or target >= self.quick_file_list.count():
            return
        self.host.reorder_quick_files(
            self.quick_file_ids_in_list_order(),
            selected_id=quick_file_id,
            force_custom=True,
        )
        self.host.move_quick_file(quick_file_id, direction)

    def move_quick_file_from_visible(self, quick_file_id: str, direction: int) -> None:
        row = self.quick_file_row(quick_file_id)
        if row >= 0:
            self.quick_file_list.setCurrentRow(row)
        self.move_selected_quick_file(direction)

    def persist_quick_file_order(self) -> None:
        if self._quick_file_list_refreshing:
            return
        self.host.reorder_quick_files(
            self.quick_file_ids_in_list_order(),
            selected_id=self.selected_quick_file_id(),
            force_custom=True,
        )

    def show_quick_file_context_menu(self, position) -> None:
        item = self.quick_file_list.itemAt(position)
        quick_file_id = ""
        if item:
            self.quick_file_list.setCurrentItem(item)
            quick_file_id = str(item.data(Qt.ItemDataRole.UserRole))
        menu = self.build_quick_file_context_menu(quick_file_id)
        menu.exec(self.quick_file_list.mapToGlobal(position))

    def build_quick_file_context_menu(self, quick_file_id: str) -> QMenu:
        menu = QMenu(self)
        quick_file = self.host.quick_file_by_id(quick_file_id)
        if not quick_file:
            self.host._add_context_action(
                menu,
                "Add File",
                self.host.add_quick_file,
                icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
            )
            self.host._add_context_action(
                menu,
                "Import from CSV",
                self.host.import_quick_files_csv,
                icon=QStyle.StandardPixmap.SP_DialogOpenButton,
            )
            self.host._add_context_action(
                menu,
                "Export to CSV",
                self.host.export_quick_files_csv,
                icon=QStyle.StandardPixmap.SP_DialogSaveButton,
                enabled=bool(self.host.quick_actions.quick_files),
            )
            return menu

        menu.setTitle(quick_file_display_text(quick_file))
        row = self.quick_file_row(quick_file_id)
        self.host._add_context_action(
            menu,
            "Run",
            self.run_selected_quick_file,
            icon=QStyle.StandardPixmap.SP_ArrowForward,
        )
        self.host._add_context_action(
            menu,
            "Show in Explorer",
            lambda quick_file_id=quick_file_id: self.host.show_quick_file_in_explorer(quick_file_id),
            icon=QStyle.StandardPixmap.SP_DirOpenIcon,
        )
        self.host._add_context_action(
            menu,
            "Edit File",
            lambda quick_file_id=quick_file_id: self.host.open_quick_file_editor(quick_file_id),
            icon=QStyle.StandardPixmap.SP_FileDialogContentsView,
        )
        menu.addSeparator()
        self.host._add_context_action(
            menu,
            "Add File",
            self.host.add_quick_file,
            icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
        )
        self.host._add_context_action(
            menu,
            "Edit",
            lambda quick_file_id=quick_file_id: self.host.edit_quick_file(quick_file_id),
            icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
        )
        self.host._add_context_action(
            menu,
            "Delete",
            lambda quick_file_id=quick_file_id: self.host.delete_quick_file(quick_file_id),
            icon=QStyle.StandardPixmap.SP_TrashIcon,
        )
        menu.addSeparator()
        self.host._add_context_action(
            menu,
            "Move Up",
            lambda quick_file_id=quick_file_id: self.move_quick_file_from_visible(quick_file_id, -1),
            icon=QStyle.StandardPixmap.SP_ArrowUp,
            enabled=row > 0,
        )
        self.host._add_context_action(
            menu,
            "Move Down",
            lambda quick_file_id=quick_file_id: self.move_quick_file_from_visible(quick_file_id, 1),
            icon=QStyle.StandardPixmap.SP_ArrowDown,
            enabled=0 <= row < self.quick_file_list.count() - 1,
        )
        menu.addSeparator()
        self.host._add_context_action(
            menu,
            "Import from CSV",
            self.host.import_quick_files_csv,
            icon=QStyle.StandardPixmap.SP_DialogOpenButton,
        )
        self.host._add_context_action(
            menu,
            "Export to CSV",
            self.host.export_quick_files_csv,
            icon=QStyle.StandardPixmap.SP_DialogSaveButton,
            enabled=bool(self.host.quick_actions.quick_files),
        )
        return menu

    def refresh_quick_files(self, selected_id: str | None = None) -> None:
        if not hasattr(self, "quick_file_list"):
            return
        selected_id = selected_id or self.selected_quick_file_id()
        self._quick_file_list_refreshing = True
        self.refresh_quick_file_controls()
        populate_quick_file_list(
            self.quick_file_list,
            self.visible_quick_files(),
            selected_id=selected_id,
            label_limit=32,
            draggable=True,
        )
        self._quick_file_list_refreshing = False

    def run_selected_quick_file(self) -> None:
        quick_file = self.host.quick_file_by_id(self.selected_quick_file_id())
        if not quick_file:
            return
        self.run_script_path(Path(quick_file.path))

    def refresh_ports(self) -> None:
        if self.transport_kind != "serial":
            self._ports = []
            self.host.set_status("LAN endpoints are entered manually.")
            self._update_connection_ui(self.transport.is_connected, update_footer=False)
            return
        self._ports = self.list_ports_snapshot()
        self.host.set_status(f"{len(self._ports)} serial port(s) detected.")
        self._update_connection_ui(self.transport.is_connected, update_footer=False)

    def list_ports_snapshot(self) -> list[dict[str, str]]:
        if self.transport_kind != "serial" or not hasattr(self.transport, "list_ports"):
            self._ports = []
            self._update_connection_ui(self.transport.is_connected, update_footer=False)
            return self._ports
        self._ports = self.transport.list_ports()
        self._update_connection_ui(self.transport.is_connected, update_footer=False)
        return self._ports

    def serial_ports_snapshot(self) -> list[dict[str, str]]:
        if self.transport_kind == "serial":
            return self.list_ports_snapshot()
        self._ports = SerialTransportAdapter().list_ports()
        return self._ports

    def open_connection_settings(self, *, connect_after_accept: bool = True) -> bool:
        serial_ports_supplier = (
            self.list_ports_snapshot
            if self.transport_kind == "serial"
            else self.serial_ports_snapshot
        )
        dialog = ConnectionSettingsDialog(
            self.profile,
            serial_ports_supplier(),
            self,
            ports_supplier=serial_ports_supplier,
            transport_kind=self.transport_kind,
            serial_profile=(
                self.profile
                if isinstance(self.profile, SerialProfile)
                else self.host.default_serial_profile()
            ),
            lan_profile=(
                self.profile
                if isinstance(self.profile, LanProfile)
                else self.host.default_lan_profile()
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            new_kind = dialog.transport_kind()
            new_profile = dialog.profile()
        except ValueError as exc:
            QMessageBox.warning(self, "Connection Settings", str(exc))
            return False
        if new_kind != self.transport_kind:
            if self.transport.is_connected or self.transport.is_reconnecting:
                self.transport.disconnect()
            self._replace_controller(new_profile, new_kind)
        else:
            self.profile = new_profile
            self.controller.profile = self.profile
        self.controller.profile = self.profile
        self._update_line_ending_label()
        self._update_connection_ui(self.transport.is_connected)
        endpoint = self.connection_endpoint()
        if connect_after_accept and endpoint:
            if self.transport.is_connected:
                self.transport.disconnect()
            self.host.set_status(f"Connecting to {endpoint}...")
            self.transport.connect(self.profile)
            self._update_connection_ui(self.transport.is_connected)
        self.host.save_settings()
        return True

    def toggle_connection(self) -> None:
        self.controller.profile = self.profile
        self.controller.transport_kind = self.transport_kind
        self.controller.toggle_connection(
            open_connection_settings=self.open_connection_settings,
            set_status=self.host.set_status,
            update_connection_ui=self._update_connection_ui,
            append_status=self._append_status,
            save_settings=self.host.save_settings,
        )

    def _replace_controller(self, profile: ConnectionProfile, transport_kind: str) -> None:
        logger = self.logger
        self.batch_runner.stop(emit_message=False)
        self.profile = profile
        self.transport_kind = transport_kind
        self.controller = TerminalSessionController(
            self.profile,
            history_commands=self.host.history_catalog.all_commands(),
            parameter_prompt=self.parameter_prompt_bridge.prompt,
            transport_kind=self.transport_kind,
        )
        self.controller.logger = logger
        self.transport = self.controller.transport
        self.serial_client = self.controller.serial_client
        self.history_store = self.controller.history_store
        self.logger = self.controller.logger
        self.batch_runner = self.controller.batch_runner

    def send_from_input(self) -> None:
        raw = self.command_input.text()
        if not raw.strip():
            return
        if self._send_integrated_input(raw, self.mode_combo.currentText()):
            self._clear_command_input_after_send()

    def _send_payload(self, raw: str, mode: str) -> None:
        self.controller.send_payload(raw, mode)

    def _send_integrated_input(self, raw: str, mode: str) -> bool:
        if mode == "Hex Bytes":
            try:
                payload = parse_hex_payload(raw)
            except ValueError as exc:
                self._render_user_send(raw.strip(), color_role="error")
                self.host.set_status(str(exc))
                return True
            display = "HEX " + format_hex_bytes(payload)
            try:
                self.transport.send_bytes(payload)
            except Exception as exc:
                self._render_user_send(display, color_role="error")
                self.host.set_status(str(exc))
                return True
            self._suppress_tx_echo(display)
            self._render_user_send(display, color_role="tx")
            self.host.record_command(raw.strip())
            return True

        lines = [line.strip() for line in raw.splitlines()]
        sendable_lines = [line for line in lines if line]
        if not sendable_lines:
            return False
        sent_all = True
        failed_index: int | None = None
        for index, line in enumerate(sendable_lines):
            try:
                self.transport.send_text(line)
            except Exception as exc:
                failed_index = index
                self._render_user_send(line, color_role="error")
                self.host.set_status(str(exc))
                sent_all = False
                break
            self._suppress_tx_echo(line)
            self._render_user_send(line, color_role="tx")
        if failed_index is not None:
            for line in sendable_lines[failed_index + 1 :]:
                self._render_user_send(line, color_role="error")
        if sent_all:
            self.host.record_command(raw.strip())
        return True

    def _render_user_send(self, message: str, *, color_role: str) -> None:
        if not message:
            return
        plan = TerminalRenderPlan(
            event=SerialEvent(kind="tx", message=message),
            message=message,
            prefix="TX> ",
            direction="TX",
            color_role=color_role,
            ensure_line_break=True,
        )
        self._emit_plan(plan)
        self._store_transcript(("plan", plan))

    def _suppress_tx_echo(self, message: str) -> None:
        self._suppressed_tx_echoes.append(message)
        QTimer.singleShot(1000, self._clear_stale_suppressed_tx_echoes)

    def _clear_stale_suppressed_tx_echoes(self) -> None:
        self._suppressed_tx_echoes.clear()

    def _consume_suppressed_tx_echo(self, message: str) -> bool:
        if not self._suppressed_tx_echoes:
            return False
        if self._suppressed_tx_echoes[0] == message:
            self._suppressed_tx_echoes.pop(0)
            return True
        if message in self._suppressed_tx_echoes:
            self._suppressed_tx_echoes.remove(message)
            return True
        return False

    def send_selected_quick_command(self) -> None:
        command = self.host.quick_command_by_id(self.selected_quick_command_id())
        if not command:
            return
        self.send_quick_command(command)

    def send_quick_command(self, command: QuickCommand) -> None:
        try:
            self.controller.send_quick_command(command, record_command=self.host.record_command)
        except Exception as exc:
            QMessageBox.warning(self, "Quick Send", str(exc))
            return
        self._clear_command_input_after_send()

    def _clear_command_input_after_send(self) -> None:
        self.command_input.clear()
        # Completer activation can arrive after returnPressed; clear again after
        # the event loop settles so accepted history/snippet text does not stick.
        QTimer.singleShot(0, self.command_input.clear)

    def save_current_input_as_quick_command(self) -> None:
        value = self.command_input.text().strip()
        if not value:
            QMessageBox.information(self, "Quick Command", "Enter a command first.")
            return
        self.host.add_quick_command(QuickCommand(label=value, command=value, send_mode=self.mode_combo.currentText()))

    def run_script(self) -> None:
        start_dir = self.host.settings.last_script_path or str(Path.cwd())
        path, _ = QFileDialog.getOpenFileName(self, "Run Command File", start_dir, "Command Files (*.cpz *.txt *.cmd *.scr);;ComPort Zone Files (*.cpz);;All Files (*)")
        if not path:
            return
        self.run_script_path(Path(path))

    def run_script_path(self, path: Path) -> bool:
        try:
            script_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Run Command File", str(exc))
            return False
        return self.run_script_text(script_text, source_label=str(path), source_path=path)

    def run_script_text(self, script_text: str, *, source_label: str = "Editor buffer", source_path: Path | None = None) -> bool:
        try:
            result = self.controller.run_script_text(
                script_text,
                source_label=source_label,
                source_path=source_path,
                collect_parameter_values=self._collect_parameter_values,
                parameter_prompt=self.parameter_prompt_bridge.prompt,
                set_last_script_path=lambda path: setattr(self.host.settings, "last_script_path", str(path)),
            )
        except BatchParseError as exc:
            QMessageBox.critical(self, "Run Command File", str(exc))
            return False
        if result.empty:
            QMessageBox.information(self, "Run Command File", "Command file is empty.")
            return False
        if result.busy:
            self.host.set_status(result.status_text)
            QMessageBox.information(self, "Run Command File", result.status_text)
            self._refresh_script_controls()
            return False
        if not result.started:
            return False
        self.host.set_status(result.status_text)
        self.host.save_settings()
        self._refresh_script_controls()
        return True

    def _collect_parameter_values(self, parameter_occurrences) -> tuple[dict[str, str], set[str]] | None:
        dialog = CommandFileParametersDialog(parameter_occurrences, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.values()

    def stop_script(self) -> None:
        self.controller.stop_script()
        self._refresh_script_controls()

    def pause_script(self) -> None:
        if self.controller.pause_script():
            self._refresh_script_controls()

    def resume_script(self) -> None:
        if self.controller.resume_script():
            self._refresh_script_controls()

    def toggle_script_pause(self) -> None:
        snapshot = self.controller.script_snapshot()
        if snapshot.is_paused:
            self.resume_script()
            return
        self.pause_script()

    def _refresh_script_controls(self) -> None:
        if not hasattr(self, "script_status_label"):
            return
        snapshot = self.controller.script_snapshot()
        connected = self.transport.is_connected
        active = snapshot.is_running or snapshot.is_stopping
        paused = snapshot.is_paused
        stopping = snapshot.is_stopping
        self.script_pause_button.setVisible(active and not paused)
        self.script_pause_button.setEnabled(active and not stopping)
        self.script_resume_button.setVisible(active and paused)
        self.script_resume_button.setEnabled(snapshot.can_resume)
        self.script_stop_button.setVisible(active)
        self.script_stop_button.setEnabled(active and not stopping)
        if stopping:
            text = "File stopping"
            tooltip = "Command file is stopping."
        elif paused:
            text = "File paused"
            if snapshot.pause_reason == "connection":
                tooltip = "Command file is paused after disconnect. Reconnect, then click Resume."
            elif snapshot.pause_reason == "user+connection":
                tooltip = "Command file is paused and the connection is closed. Reconnect, then click Resume."
            else:
                tooltip = "Command file is paused. Click Resume to continue."
        elif active:
            text = "File running"
            tooltip = "Command file is running."
        else:
            text = "File idle"
            tooltip = "No command file is running."
        self.script_status_label.setText(text)
        self.script_status_label.setToolTip(tooltip)

    def toggle_logging(self) -> None:
        if self.logger.enabled:
            path = self.controller.stop_logging()
            self.host.update_connection_status(self)
            self._sync_status_toggles()
            self._append_status(f"Logging stopped: {path}" if path else "Logging stopped.")
            return
        default_dir = Path(self.host.settings.log_path).parent if self.host.settings.log_path else Path.cwd()
        default_name = f"comport-zone-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        path, _ = QFileDialog.getSaveFileName(self, "Choose Log File", str(default_dir / default_name), "Log Files (*.log *.txt);;All Files (*)")
        if not path:
            self._sync_status_toggles()  # user cancelled — revert the toggled button
            return
        self.controller.start_logging(path)
        self.host.settings.log_path = path
        self.host.update_connection_status(self)
        self._sync_status_toggles()
        self._append_status(f"Logging to {path}")
        self.host.save_settings()

    def toggle_pause(self) -> None:
        paused, pending_events = self.controller.toggle_pause()
        self.pause_label.setText("RX paused" if paused else "")
        if not paused:
            for event in pending_events:
                self._render_event(event)

    def clear_terminal(self) -> None:
        clear_transcript = getattr(self.terminal, "clear_transcript", None)
        if callable(clear_transcript):
            clear_transcript(clear_draft=True)
        else:
            self.terminal.clear()
        self._refresh_search_highlights(self.search_input.text())

    def show_search(self) -> None:
        self.search_bar.show()
        self.search_input.setFocus()
        self.search_input.selectAll()

    def hide_search(self) -> None:
        self.search_input.clear()
        self.search_bar.hide()
        self.command_input.setFocus()

    def find_next(self) -> None:
        self._find_in_terminal(backward=False)

    def find_previous(self) -> None:
        self._find_in_terminal(backward=True)

    def copy_selection(self) -> None:
        self.terminal.copy()

    def select_all(self) -> None:
        self.terminal.selectAll()

    def selected_terminal_text(self) -> str:
        return self.terminal.textCursor().selectedText().replace("\u2029", "\n")

    def show_terminal_context_menu(self, position) -> None:
        menu = self.build_terminal_context_menu(position)
        menu.exec(self.terminal.mapToGlobal(position))

    def build_terminal_context_menu(self, position) -> QMenu:
        menu = self.terminal.createStandardContextMenu(position)
        menu.addSeparator()
        self.host._add_context_command_action(
            menu,
            "edit.clear_terminal",
            callback=self.clear_terminal,
        )
        self._add_terminal_toggle_context_action(
            menu,
            text="Line Wrap",
            checked=self.host.settings.line_wrap_enabled,
            callback=self._set_line_wrap_enabled_from_context_menu,
        )
        self._add_terminal_toggle_context_action(
            menu,
            text="Show Timestamps",
            checked=self.host.settings.timestamps_enabled,
            callback=self._set_timestamps_enabled_from_context_menu,
        )
        selected_text = self.selected_terminal_text()
        if selected_text:
            menu.addSeparator()
            self.host._add_context_action(
                menu,
                "Show Selection as Hex",
                lambda text=selected_text: self.show_converted_selection("Selection as Hex", self.text_to_hex(text)),
                icon=QStyle.StandardPixmap.SP_FileDialogInfoView,
            )
            self.host._add_context_action(
                menu,
                "Show Hex Selection as Text",
                lambda text=selected_text: self.show_hex_selection_as_text(text),
                icon=QStyle.StandardPixmap.SP_FileDialogInfoView,
            )
            menu.addSeparator()
            self.host._add_context_action(
                menu,
                "Replace Selection with Hex",
                lambda text=selected_text: self.replace_terminal_selection(self.text_to_hex(text)),
                icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
            )
            self.host._add_context_action(
                menu,
                "Replace Hex Selection with Text",
                lambda text=selected_text: self.replace_hex_selection_with_text(text),
                icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
            )
        return menu

    def _add_terminal_toggle_context_action(
        self,
        menu: QMenu,
        *,
        text: str,
        checked: bool,
        callback,
    ) -> QAction:
        action = QAction(text, menu)
        action.setCheckable(True)
        action.setChecked(checked)
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def _set_host_action_checked(self, action_name: str, checked: bool) -> bool:
        action = getattr(self.host, action_name, None)
        if action is None:
            return False
        blocked = action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(blocked)
        return True

    def _set_line_wrap_enabled_from_context_menu(self, checked: bool) -> None:
        if self._set_host_action_checked("wrap_action", checked):
            self.host.toggle_line_wrap()
            return
        self.host.settings.line_wrap_enabled = checked
        if hasattr(self.host, "iter_sessions"):
            for session in self.host.iter_sessions():
                session.apply_settings()
        else:
            self.apply_settings()
        self.host.save_settings()

    def _set_timestamps_enabled_from_context_menu(self, checked: bool) -> None:
        if self._set_host_action_checked("timestamps_action", checked):
            self.host.toggle_timestamps()
            return
        self.host.settings.timestamps_enabled = checked
        self.host.save_settings()

    def text_to_hex(self, text: str) -> str:
        return format_hex_bytes(text.encode("utf-8"))

    def hex_to_text(self, text: str) -> str:
        return decode_serial_bytes(parse_hex_payload(text))

    def show_hex_selection_as_text(self, text: str) -> None:
        try:
            converted = self.hex_to_text(text)
        except ValueError as exc:
            QMessageBox.warning(self, "Convert Hex to Text", str(exc))
            return
        self.show_converted_selection("Hex Selection as Text", converted)

    def replace_hex_selection_with_text(self, text: str) -> None:
        try:
            converted = self.hex_to_text(text)
        except ValueError as exc:
            QMessageBox.warning(self, "Convert Hex to Text", str(exc))
            return
        self.replace_terminal_selection(converted)

    def replace_terminal_selection(self, replacement: str) -> None:
        replace_from_menu = getattr(self.terminal, "replace_selection_from_menu", None)
        if callable(replace_from_menu):
            if replace_from_menu(replacement) and self.search_bar.isVisible():
                self._refresh_search_highlights(self.search_input.text())
            return
        cursor = self.terminal.textCursor()
        if not cursor.hasSelection():
            return
        was_read_only = self.terminal.isReadOnly()
        self.terminal.setReadOnly(False)
        cursor.insertText(replacement)
        self.terminal.setReadOnly(was_read_only)
        self.terminal.setTextCursor(cursor)
        if self.search_bar.isVisible():
            self._refresh_search_highlights(self.search_input.text())

    def show_converted_selection(self, title: str, content: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(520, 320)
        layout = QVBoxLayout(dialog)
        output = QTextEdit(dialog)
        output.setReadOnly(True)
        output.setPlainText(content)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        copy_button = buttons.addButton("Copy", QDialogButtonBox.ButtonRole.ActionRole)
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(output.toPlainText()))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(output, 1)
        layout.addWidget(buttons)
        dialog.exec()

    def _find_in_terminal(self, *, backward: bool) -> None:
        self.terminal_view.find(self.search_input.text(), backward=backward)

    def _refresh_search_highlights(self, text: str) -> None:
        self.terminal_view.refresh_search_highlights(
            text, self.host.theme.search_highlight, self.host.theme.text
        )

    def _navigate_history(self, direction: int) -> None:
        text = self.history_store.navigate(direction, self.command_input.text())
        self.command_input.setText(text)
        self.command_input.setCursorPosition(len(text))

    def _on_command_edited(self, text: str) -> None:
        self.history_store.reset_navigation()
        token_under_cursor = getattr(self.command_input, "token_under_cursor", None)
        self._update_completion_model(token_under_cursor() if callable(token_under_cursor) else text)

    def _delete_current_input_from_history(self) -> None:
        command = self.command_input.text().strip()
        if not command:
            return
        if self.host.remove_command_from_history(command):
            self.command_input.clear()
            self.host.set_status(f"Removed '{short_label(command, 40)}' from command history.")
            return
        self.host.set_status(f"'{short_label(command, 40)}' is not in command history.")

    def _update_completion_model(self, prefix: str | None = None) -> None:
        text = prefix if prefix is not None else self.command_input.text()
        suggestions = self.history_store.suggestions(text)
        suggestions.extend(
            command.command
            for command in self.host.quick_actions.quick_commands
            if command.command not in suggestions and text.casefold() in command.command.casefold()
        )
        self.completion_model.setStringList(suggestions[:30])

    def _show_completion_popup(self) -> None:
        token_under_cursor = getattr(self.command_input, "token_under_cursor", None)
        self._update_completion_model(token_under_cursor() if callable(token_under_cursor) else None)
        if self.completion_model.rowCount() > 0 and self.command_input.completer():
            show_completions = getattr(self.command_input, "show_completions", None)
            if callable(show_completions):
                show_completions(forced=True)
            else:
                self.command_input.completer().complete()

    def _apply_completion(self, value: str) -> None:
        insert_completion = getattr(self.command_input, "insert_completion", None)
        if callable(insert_completion):
            insert_completion(value)
            return
        self.command_input.setText(value)
        self.command_input.setCursorPosition(len(value))

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.transport.events.get_nowait()
            except Empty:
                break
            self._handle_event(event)
        self._refresh_script_controls()

    def _handle_event(self, event: SerialEvent) -> None:
        if event.kind == "tx" and self._consume_suppressed_tx_echo(event.message):
            return
        decision = self.controller.handle_event(event)
        if decision.paused_count is not None:
            self.pause_label.setText(f"RX paused ({decision.paused_count})")
            return
        if decision.event_to_render is not None:
            self._render_event(decision.event_to_render)
        if decision.status_message and self.host.tabs.currentWidget() is self:
            self.host.set_status(decision.status_message)
        if decision.connection_state is not None:
            self._update_connection_ui(
                decision.connection_state,
                update_footer=decision.connection_update_footer,
            )

    def _render_event(self, event: SerialEvent) -> None:
        self._emit_plan(self.controller.render_plan(event, self.host.settings.receive_display_mode))
        self._store_transcript(("event", event))

    def _emit_plan(self, plan: TerminalRenderPlan) -> None:
        self.terminal_view.render_plan(
            plan,
            colors=self._terminal_colors(),
            timestamps_enabled=self.host.settings.timestamps_enabled,
            search_visible=self.search_bar.isVisible(),
            search_text=self.search_input.text(),
            search_highlight=self.host.theme.search_highlight,
        )

    def _terminal_colors(self) -> dict[str, str]:
        theme = self.host.theme
        text = theme.text
        faint = theme.text_faint or theme.muted
        timestamp = mix_hex(faint, theme.terminal_bg, 0.62)
        return {
            # direction-column colours
            "rx": theme.rx,
            "tx": theme.tx,
            "status": timestamp,  # SYS leader is faint, like the mockup
            "error": theme.error,
            "default": text,
            # message-body colours, softened toward the terminal ink
            "rx_body": mix_hex(theme.rx, text, 0.5),
            "tx_body": mix_hex(theme.tx, text, 0.58),
            "status_body": faint,
            "error_body": theme.error,
            "default_body": text,
            # detached timestamp column
            "timestamp": timestamp,
        }

    def _store_transcript(self, entry: tuple) -> None:
        if self._replaying:
            return
        self._transcript.append(entry)
        if len(self._transcript) > TRANSCRIPT_EVENT_CAP:
            del self._transcript[: len(self._transcript) - TRANSCRIPT_EVENT_CAP]

    def rerender_transcript(self) -> None:
        """Rebuild the transcript with the current settings (timestamp on/off,
        receive-display mode) so a toggle applies to all history — and restores."""
        self.terminal.clear_transcript()
        if not self._transcript:
            return
        self._replaying = True
        try:
            for kind, payload in self._transcript:
                if kind == "event":
                    self._emit_plan(self.controller.render_plan(payload, self.host.settings.receive_display_mode))
                else:
                    self._emit_plan(payload)
        finally:
            self._replaying = False

    def display_message_for_event(self, event: SerialEvent) -> str:
        return self.controller.display_message_for_event(event, self.host.settings.receive_display_mode)

    def _append_status(self, message: str) -> None:
        self._render_event(SerialEvent(kind="status", message=message))

    def _update_connection_ui(self, connected: bool, *, update_footer: bool = True) -> None:
        self._connected = connected
        self._status_text = self.connection_state_label()
        state = self.connection_state()
        # Command-bar chip stays compact (state + endpoint) so the terminal can be
        # narrow; the full profile lives in the shared status bar + this tooltip.
        self.status_label.setText(self.connection_chip_text())
        self.status_label.setToolTip(f"{self.connection_tooltip()}\nClick to open Connection Settings.")
        set_widget_state(self.status_label, state)
        self.connection_button.setText(self.connection_action_text())
        self.connection_button.setToolTip(self.connection_tooltip())
        set_button_icon(self.connection_button, connection_state_icon(state), 15)
        set_button_role(self.connection_button, state)
        self._refresh_script_controls()
        self.host.update_tab_titles()
        self.host.update_connection_status(self)
        if update_footer and self.host.tabs.currentWidget() is self:
            self.host.set_status(self._status_text)

    def connection_state(self) -> str:
        if self._connected or self.transport.is_connected:
            return "connected"
        if self.transport.is_reconnecting:
            return "retrying"
        if not self.connection_endpoint():
            return "no-port"
        if self._profile_port_missing():
            return "missing"
        return "closed"

    def connection_state_label(self) -> str:
        no_endpoint_label = "No endpoint" if self.transport_kind == "lan" else "No port"
        return {
            "connected": "Connected",
            "retrying": "Retrying",
            "missing": "Missing",
            "no-port": no_endpoint_label,
            "closed": "Closed",
        }[self.connection_state()]

    def connection_action_text(self) -> str:
        no_endpoint_action = "Set Endpoint" if self.transport_kind == "lan" else "Set Port"
        return {
            "connected": "Disconnect",
            "retrying": "Stop Retry",
            "missing": "Connect",
            "no-port": no_endpoint_action,
            "closed": "Connect",
        }[self.connection_state()]

    def connection_tooltip(self) -> str:
        state = self.connection_state()
        profile_text = self._profile_summary()
        if state == "connected":
            return f"Disconnect {profile_text}."
        if state == "retrying":
            return f"Stop auto-reconnect attempts for {profile_text}."
        if state == "missing":
            return f"{self.profile.port} is not currently detected. Try to connect anyway or open Connection Settings."
        if state == "no-port":
            return "Choose a LAN host and port." if self.transport_kind == "lan" else "Choose a COM port and connect."
        return f"Connect to {profile_text}."

    def connection_status_text(self) -> str:
        endpoint = self.connection_endpoint()
        if not endpoint:
            return "No endpoint selected" if self.transport_kind == "lan" else "No port selected"
        log_status = "Log on" if self.logger.enabled else "Log off"
        if isinstance(self.profile, LanProfile):
            return " | ".join(
                [
                    self.connection_state_label(),
                    f"LAN {endpoint}",
                    self.profile.line_ending,
                    log_status,
                ]
            )
        framing = f"{self.profile.bytesize}{self.profile.parity}{self.profile.stopbits:g}"
        return " | ".join(
            [
                self.connection_state_label(),
                self.profile.port,
                f"{self.profile.baudrate} {framing}",
                self.profile.line_ending,
                log_status,
            ]
        )

    def connection_chip_text(self) -> str:
        endpoint = self.connection_endpoint()
        label = self.connection_state_label()
        return f"{label} · {endpoint}" if endpoint else label

    def _profile_summary(self) -> str:
        endpoint = self.connection_endpoint()
        if not endpoint:
            return "No endpoint" if self.transport_kind == "lan" else "No port"
        if isinstance(self.profile, LanProfile):
            return f"LAN {endpoint}"
        framing = f"{self.profile.bytesize}{self.profile.parity}{self.profile.stopbits:g}"
        return f"{self.profile.port} {self.profile.baudrate} {framing}"

    def connection_endpoint(self) -> str:
        if isinstance(self.profile, LanProfile):
            return self.profile.endpoint()
        return self.profile.port

    def _profile_port_missing(self) -> bool:
        if self.transport_kind != "serial" or not isinstance(self.profile, SerialProfile):
            return False
        ports = getattr(self, "_ports", [])
        known_ports = {str(port.get("device", "")) for port in ports}
        return bool(self.profile.port and self.profile.port not in known_ports)

    def profile_port_missing(self) -> bool:
        return self._profile_port_missing()

    def _update_line_ending_label(self) -> None:
        self.line_ending_label.setText(self.profile.line_ending)
        self.host.update_connection_status(self)

    def shutdown(self) -> None:
        self.event_timer.stop()
        self.batch_runner.stop(emit_message=False)
        self.transport.disconnect()
        self.logger.close()
