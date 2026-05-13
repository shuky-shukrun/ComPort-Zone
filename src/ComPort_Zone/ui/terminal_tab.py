from __future__ import annotations

from datetime import datetime
from pathlib import Path
from queue import Empty

from PySide6.QtCore import QSize, Qt, QStringListModel, QTimer
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
    QVBoxLayout,
    QWidget,
)

from ..batch import BatchParseError, parse_hex_payload
from ..icons import set_button_icon
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
    row_for_item_id,
    selected_item_id,
)
from ..quick_actions_sidebar import QuickActionsSidebar, QuickActionsSidebarActions
from ..serial_core import SerialEvent, decode_serial_bytes, format_hex_bytes
from ..terminal_session_controller import ConnectionProfile, TerminalRenderPlan, TerminalSessionController
from ..terminal_view import TerminalView
from ..transports import SerialTransportAdapter
from ..widgets import ChevronComboBox, IntegratedTerminalEdit
from .dialogs import BatchParameterPromptBridge, CommandFileParametersDialog, ConnectionSettingsDialog
from .fonts import TERMINAL_FONT_MAX, TERMINAL_FONT_MIN, pick_mono_font

DRAWER_COLLAPSED_WIDTH = 48


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
        self.splitter.setHandleWidth(3)
        self.splitter.splitterMoved.connect(self._drawer_resized)

        self.drawer = self._build_quick_actions_sidebar()
        self.drawer_rail = self.drawer.rail
        self.drawer_panel = self.drawer.panel
        self.drawer_pages = self.drawer.pages

        terminal_column = QFrame(self)
        terminal_column.setObjectName("terminalColumn")
        terminal_layout = QVBoxLayout(terminal_column)
        terminal_layout.setContentsMargins(0, 0, 0, 0)
        terminal_layout.setSpacing(0)

        self.search_bar = QFrame(terminal_column)
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
        prev_button.clicked.connect(self.find_previous)
        next_button = QPushButton("Next", self.search_bar)
        set_button_icon(next_button, QStyle.StandardPixmap.SP_ArrowForward)
        next_button.clicked.connect(self.find_next)
        close_search = QPushButton("", self.search_bar)
        set_button_icon(close_search, QStyle.StandardPixmap.SP_DialogCloseButton)
        close_search.clicked.connect(self.hide_search)
        self.search_count = QLabel("0", self.search_bar)
        search_layout.addWidget(self.search_input, 1)
        search_layout.addWidget(prev_button)
        search_layout.addWidget(next_button)
        search_layout.addWidget(self.search_count)
        search_layout.addWidget(close_search)
        self.search_bar.hide()

        self.terminal = IntegratedTerminalEdit(terminal_column)
        self.terminal.setObjectName("terminal")
        self.terminal.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.terminal.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.terminal.customContextMenuRequested.connect(self.show_terminal_context_menu)
        self.terminal_view = TerminalView(self.terminal, self.search_count)
        self.command_input = self.terminal
        self.terminal.set_font_zoom_callback(lambda delta: self.host.change_font_size(delta))

        self.command_bar = QFrame(terminal_column)
        self.command_bar.setObjectName("commandBar")
        command_layout = QHBoxLayout(self.command_bar)
        command_layout.setContentsMargins(8, 6, 8, 6)
        command_layout.setSpacing(6)

        self.status_label = QLabel("Disconnected", self)
        self.status_label.hide()
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
        self.log_label = QLabel("Log off", self.command_bar)
        self.pause_label = QLabel("", self.command_bar)
        terminal_font_label = QLabel("Font", self.command_bar)
        terminal_font_label.setObjectName("terminalFontControlsLabel")
        terminal_font_label.setToolTip("Terminal font size")
        font_down = QPushButton("-", self.command_bar)
        font_down.setObjectName("terminalFontSizeButton")
        font_down.setFixedSize(QSize(38, 34))
        font_down.setToolTip("Decrease terminal font size")
        font_down.setAccessibleName("Decrease terminal font size")
        font_down.clicked.connect(lambda: self.host.change_font_size(-1))
        font_up = QPushButton("+", self.command_bar)
        font_up.setObjectName("terminalFontSizeButton")
        font_up.setFixedSize(QSize(38, 34))
        font_up.setToolTip("Increase terminal font size")
        font_up.setAccessibleName("Increase terminal font size")
        font_up.clicked.connect(lambda: self.host.change_font_size(1))

        command_layout.addWidget(self.mode_combo)
        command_layout.addWidget(self.rx_display_combo)
        command_layout.addWidget(self.line_ending_label)
        command_layout.addWidget(self.log_label)
        command_layout.addWidget(self.pause_label)
        command_layout.addWidget(terminal_font_label)
        command_layout.addWidget(font_down)
        command_layout.addWidget(font_up)

        terminal_layout.addWidget(self.search_bar)
        terminal_layout.addWidget(self.terminal, 1)
        terminal_layout.addWidget(self.command_bar)

        self.splitter.addWidget(self.drawer)
        self.splitter.addWidget(terminal_column)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        root.addWidget(self.splitter)

    def _build_quick_actions_sidebar(self) -> QuickActionsSidebar:
        sidebar = QuickActionsSidebar(
            actions=QuickActionsSidebarActions(
                command_primary=self.send_selected_quick_command,
                file_primary=self.run_selected_quick_file,
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
            command_double_clicked=self.send_selected_quick_command,
            file_double_clicked=self.run_selected_quick_file,
            command_context_menu_requested=self.show_quick_command_context_menu,
            file_context_menu_requested=self.show_quick_file_context_menu,
            command_sort_changed=self._quick_sort_changed,
            file_sort_changed=self._quick_file_sort_changed,
            command_order_changed=self.persist_quick_command_order,
            file_order_changed=self.persist_quick_file_order,
            on_page_requested=self._select_drawer_page,
            rail_width=DRAWER_COLLAPSED_WIDTH,
            parent=self,
        )
        self.quick_list = sidebar.quick_command_list
        self.quick_file_list = sidebar.quick_file_list
        self.quick_sort_combo = sidebar.quick_sort_combo
        self.quick_group_button = sidebar.quick_group_button
        self.quick_file_sort_combo = sidebar.quick_file_sort_combo
        self.quick_move_up_button = sidebar.quick_command_move_up_button
        self.quick_move_down_button = sidebar.quick_command_move_down_button
        self.quick_file_move_up_button = sidebar.quick_file_move_up_button
        self.quick_file_move_down_button = sidebar.quick_file_move_down_button
        return sidebar

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

    def apply_theme_palette(self) -> None:
        if hasattr(self.terminal, "set_terminal_colors"):
            self.terminal.set_terminal_colors(prompt=self.host.theme.tx, draft=self.host.theme.text)

    def _receive_display_mode_changed(self) -> None:
        mode = self.rx_display_combo.currentData()
        if mode:
            self.host.set_receive_display_mode(str(mode))

    def apply_drawer_state(self, collapsed: bool, width: int, page_index: int | None = None) -> None:
        if page_index is not None and self.drawer_pages.count() > 0:
            self.drawer_pages.setCurrentIndex(max(0, min(page_index, self.drawer_pages.count() - 1)))
        self.drawer_panel.setVisible(not collapsed)
        if collapsed:
            self.drawer.setMinimumWidth(DRAWER_COLLAPSED_WIDTH)
            self.drawer.setMaximumWidth(DRAWER_COLLAPSED_WIDTH)
            self.splitter.setSizes([DRAWER_COLLAPSED_WIDTH, max(700, self.width() - DRAWER_COLLAPSED_WIDTH)])
            return
        drawer_width = max(220, min(width, 520))
        self.drawer.setMinimumWidth(220)
        self.drawer.setMaximumWidth(520)
        self.splitter.setSizes([drawer_width, max(700, self.width() - drawer_width)])

    def _drawer_resized(self, pos: int, index: int) -> None:
        if self.host.settings.drawer_collapsed:
            return
        sizes = self.splitter.sizes()
        if sizes:
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
            "Send",
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
        self.terminal_view.render_plan(
            TerminalRenderPlan(
                event=SerialEvent(kind="tx", message=message),
                message=message,
                prefix="TX> ",
                color_role=color_role,
                ensure_line_break=True,
            ),
            colors={
                "tx": self.host.theme.tx,
                "error": self.host.theme.error,
                "default": self.host.theme.text,
            },
            timestamps_enabled=self.host.settings.timestamps_enabled,
            search_visible=self.search_bar.isVisible(),
            search_text=self.search_input.text(),
            search_highlight=self.host.theme.search_highlight,
        )

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
        path, _ = QFileDialog.getOpenFileName(self, "Run Command File", start_dir, "Text Files (*.txt *.cmd *.scr);;All Files (*)")
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
        if not result.started:
            return False
        self.host.set_status(result.status_text)
        self.host.save_settings()
        return True

    def _collect_parameter_values(self, parameter_occurrences) -> tuple[dict[str, str], set[str]] | None:
        dialog = CommandFileParametersDialog(parameter_occurrences, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.values()

    def stop_script(self) -> None:
        self.controller.stop_script()

    def toggle_logging(self) -> None:
        if self.logger.enabled:
            path = self.controller.stop_logging()
            self.log_label.setText("Log off")
            self.host.update_connection_status(self)
            self._append_status(f"Logging stopped: {path}" if path else "Logging stopped.")
            return
        default_dir = Path(self.host.settings.log_path).parent if self.host.settings.log_path else Path.cwd()
        default_name = f"comport-zone-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        path, _ = QFileDialog.getSaveFileName(self, "Choose Log File", str(default_dir / default_name), "Log Files (*.log *.txt);;All Files (*)")
        if not path:
            return
        self.controller.start_logging(path)
        self.host.settings.log_path = path
        self.log_label.setText("Logging")
        self.host.update_connection_status(self)
        self._append_status(f"Logging to {path}")
        self.host.save_settings()

    def toggle_pause(self) -> None:
        paused, pending_events = self.controller.toggle_pause()
        self.pause_label.setText("Paused" if paused else "")
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
        self.terminal_view.refresh_search_highlights(text, self.host.theme.search_highlight)

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

    def _handle_event(self, event: SerialEvent) -> None:
        if event.kind == "tx" and self._consume_suppressed_tx_echo(event.message):
            return
        decision = self.controller.handle_event(event)
        if decision.paused_count is not None:
            self.pause_label.setText(f"Paused ({decision.paused_count})")
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
        plan = self.controller.render_plan(event, self.host.settings.receive_display_mode)
        self.terminal_view.render_plan(
            plan,
            colors={
                "rx": self.host.theme.rx,
                "tx": self.host.theme.tx,
                "status": self.host.theme.status,
                "error": self.host.theme.error,
                "default": self.host.theme.text,
            },
            timestamps_enabled=self.host.settings.timestamps_enabled,
            search_visible=self.search_bar.isVisible(),
            search_text=self.search_input.text(),
            search_highlight=self.host.theme.search_highlight,
        )

    def display_message_for_event(self, event: SerialEvent) -> str:
        return self.controller.display_message_for_event(event, self.host.settings.receive_display_mode)

    def _append_status(self, message: str) -> None:
        self._render_event(SerialEvent(kind="status", message=message))

    def _update_connection_ui(self, connected: bool, *, update_footer: bool = True) -> None:
        self._connected = connected
        self._status_text = self.connection_state_label()
        status_text = self.connection_status_text()
        self.status_label.setText(status_text)
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
