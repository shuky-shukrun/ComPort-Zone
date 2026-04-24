from __future__ import annotations

from datetime import datetime
from pathlib import Path
from queue import Empty

from PySide6.QtCore import QEvent, Qt, QStringListModel, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QFontDatabase, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QCompleter,
)

from .batch import BatchParseError, BatchRunner, load_batch_file, parse_hex_payload
from .history import HistoryStore
from .models import (
    AppSettings,
    FLOW_CONTROL_OPTIONS,
    LINE_ENDINGS,
    QuickCommand,
    SerialProfile,
    TerminalSessionState,
    THEME_OPTIONS,
    utc_now_iso,
)
from .serial_core import SerialClient, SerialEvent
from .session_log import SessionLogger
from .storage import SettingsStore, default_config_path
from .themes import THEMES, ThemePalette
from .widgets import ChevronComboBox, HistoryLineEdit

COMMON_BAUD_RATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]
SEND_MODES = ("Text", "Hex Bytes")
TERMINAL_FONT_MIN = 8
TERMINAL_FONT_MAX = 24
DRAWER_COLLAPSED_WIDTH = 48


def clone_profile(profile: SerialProfile) -> SerialProfile:
    return SerialProfile.from_dict(profile.to_dict())


def set_button_role(button: QPushButton, role: str) -> None:
    button.setProperty("role", role)
    button.style().unpolish(button)
    button.style().polish(button)
    button.update()


def pick_ui_font() -> QFont:
    families = {family.casefold(): family for family in QFontDatabase.families()}
    for candidate in ("Segoe UI Variable Text", "Segoe UI", "Inter"):
        if family := families.get(candidate.casefold()):
            return QFont(family, 10)
    return QApplication.font()


def pick_mono_font(point_size: int, family_name: str = "") -> QFont:
    families = {family.casefold(): family for family in QFontDatabase.families()}
    candidates = [family_name, "Cascadia Mono", "Cascadia Code", "Consolas", "JetBrains Mono"]
    for candidate in candidates:
        if candidate and (family := families.get(candidate.casefold())):
            return QFont(family, point_size)
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(point_size)
    return font


def short_label(text: str, limit: int = 40) -> str:
    text = text.strip()
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


class TerminalTabWidget(QTabWidget):
    newTabRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.new_tab_button = QToolButton(self.tabBar())
        self.new_tab_button.setObjectName("newTabButton")
        self.new_tab_button.setText("+")
        self.new_tab_button.setToolTip("New tab")
        self.new_tab_button.setAutoRaise(True)
        self.new_tab_button.setFixedSize(32, 28)
        self.new_tab_button.clicked.connect(self.newTabRequested.emit)
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
        self._position_new_tab_button()

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

    def _position_new_tab_button(self) -> None:
        bar = self.tabBar()
        if self.count() == 0:
            x = 6
        else:
            right_edge = max(bar.tabRect(index).right() for index in range(self.count()))
            x = right_edge + 8
        x = max(4, min(x, bar.width() - self.new_tab_button.width() - 4))
        y = max(2, int((bar.height() - self.new_tab_button.height()) / 2))
        self.new_tab_button.move(x, y)
        self.new_tab_button.raise_()


class ConnectionSettingsDialog(QDialog):
    def __init__(self, profile: SerialProfile, ports: list[dict[str, str]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Serial Settings")
        self.setMinimumWidth(420)

        self.port_combo = ChevronComboBox(self)
        self.port_combo.setEditable(True)
        for port in ports:
            self.port_combo.addItem(f"{port['device']} - {port['description']}", port["device"])
        if profile.port:
            index = self.port_combo.findData(profile.port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
            else:
                self.port_combo.setEditText(profile.port)

        self.baud_combo = ChevronComboBox(self)
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(COMMON_BAUD_RATES)
        self.baud_combo.setCurrentText(str(profile.baudrate))

        self.bytesize_combo = ChevronComboBox(self)
        self.bytesize_combo.addItems(["5", "6", "7", "8"])
        self.bytesize_combo.setCurrentText(str(profile.bytesize))

        self.parity_combo = ChevronComboBox(self)
        self.parity_combo.addItems(["N", "E", "O", "M", "S"])
        self.parity_combo.setCurrentText(profile.parity)

        self.stopbits_combo = ChevronComboBox(self)
        self.stopbits_combo.addItems(["1", "1.5", "2"])
        self.stopbits_combo.setCurrentText(str(profile.stopbits).rstrip("0").rstrip("."))

        self.flow_combo = ChevronComboBox(self)
        self.flow_combo.addItems(FLOW_CONTROL_OPTIONS)
        self.flow_combo.setCurrentText(profile.flow_control)

        self.line_ending_combo = ChevronComboBox(self)
        self.line_ending_combo.addItems(LINE_ENDINGS.keys())
        self.line_ending_combo.setCurrentText(profile.line_ending)

        self.auto_reconnect = QCheckBox("Auto-reconnect", self)
        self.auto_reconnect.setChecked(profile.auto_reconnect)
        self.dtr = QCheckBox("DTR", self)
        self.dtr.setChecked(profile.dtr)
        self.rts = QCheckBox("RTS", self)
        self.rts.setChecked(profile.rts)

        form = QFormLayout()
        form.addRow("Port", self.port_combo)
        form.addRow("Baud rate", self.baud_combo)
        form.addRow("Data bits", self.bytesize_combo)
        form.addRow("Parity", self.parity_combo)
        form.addRow("Stop bits", self.stopbits_combo)
        form.addRow("Flow control", self.flow_combo)
        form.addRow("Line ending", self.line_ending_combo)
        form.addRow("", self.auto_reconnect)
        form.addRow("", self.dtr)
        form.addRow("", self.rts)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def profile(self) -> SerialProfile:
        port_value = self.port_combo.currentData()
        port = str(port_value or self.port_combo.currentText()).split(" - ", 1)[0].strip()
        return SerialProfile(
            port=port,
            baudrate=int(self.baud_combo.currentText()),
            bytesize=int(self.bytesize_combo.currentText()),
            parity=self.parity_combo.currentText(),
            stopbits=float(self.stopbits_combo.currentText()),
            flow_control=self.flow_combo.currentText(),
            line_ending=self.line_ending_combo.currentText(),
            auto_reconnect=self.auto_reconnect.isChecked(),
            dtr=self.dtr.isChecked(),
            rts=self.rts.isChecked(),
        )


class QuickCommandDialog(QDialog):
    def __init__(self, command: QuickCommand | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quick Command")
        self.setMinimumWidth(420)
        command = command or QuickCommand()

        self.label_input = QLineEdit(command.label, self)
        self.command_input = QLineEdit(command.command, self)
        self.group_input = QLineEdit(command.group, self)
        self.mode_combo = ChevronComboBox(self)
        self.mode_combo.addItems(SEND_MODES)
        self.mode_combo.setCurrentText(command.send_mode if command.send_mode in SEND_MODES else "Text")
        self.line_ending_combo = ChevronComboBox(self)
        self.line_ending_combo.addItem("Use session setting", "")
        for name in LINE_ENDINGS:
            self.line_ending_combo.addItem(name, name)
        if command.line_ending_override:
            self.line_ending_combo.setCurrentText(command.line_ending_override)
        self._original = command

        form = QFormLayout()
        form.addRow("Label", self.label_input)
        form.addRow("Command", self.command_input)
        form.addRow("Group", self.group_input)
        form.addRow("Send mode", self.mode_combo)
        form.addRow("Line ending", self.line_ending_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def quick_command(self) -> QuickCommand:
        now = utc_now_iso()
        return QuickCommand(
            id=self._original.id,
            label=self.label_input.text().strip() or self.command_input.text().strip(),
            command=self.command_input.text().strip(),
            send_mode=self.mode_combo.currentText(),
            group=self.group_input.text().strip() or "General",
            line_ending_override=str(self.line_ending_combo.currentData() or ""),
            created_at=self._original.created_at or now,
            updated_at=now,
        )


class TerminalSessionWidget(QWidget):
    def __init__(self, host: "MainWindow", session_id: int, state: TerminalSessionState) -> None:
        super().__init__(host)
        self.host = host
        self.session_id = session_id
        self.title = state.title or f"Terminal {session_id}"
        self.profile_name = state.profile_name if state.profile_name in host.settings.profiles else host.settings.active_profile
        self.profile = host.get_profile(self.profile_name)
        self.serial_client = SerialClient()
        self.history_store = HistoryStore(host.history_catalog.all_commands())
        self.logger = SessionLogger()
        self.batch_runner = BatchRunner(
            event_queue=self.serial_client.events,
            send_text=self.serial_client.send_text,
            send_bytes=self.serial_client.send_bytes,
            connected_supplier=lambda: self.serial_client.is_connected,
        )
        self.paused = False
        self.pending_events: list[SerialEvent] = []
        self._connected = False
        self._status_text = "Disconnected"

        self._build_ui()
        self.refresh_ports()
        self.refresh_quick_commands()
        self.refresh_profiles()
        self.apply_settings()
        self.apply_drawer_state(host.settings.drawer_collapsed, host.settings.drawer_width)
        self._update_connection_ui(False)

        self.event_timer = QTimer(self)
        self.event_timer.timeout.connect(self._drain_events)
        self.event_timer.start(50)

    @property
    def tab_title(self) -> str:
        marker = " *" if self._connected else ""
        return f"{self.title}{marker}"

    def to_state(self) -> TerminalSessionState:
        return TerminalSessionState(title=self.title, profile_name=self.profile_name)

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(3)
        self.splitter.splitterMoved.connect(self._drawer_resized)

        self.drawer = QFrame(self)
        self.drawer.setObjectName("drawer")
        drawer_layout = QHBoxLayout(self.drawer)
        drawer_layout.setContentsMargins(0, 0, 0, 0)
        drawer_layout.setSpacing(0)

        self.drawer_rail = QFrame(self.drawer)
        self.drawer_rail.setObjectName("drawerRail")
        self.drawer_rail.setFixedWidth(DRAWER_COLLAPSED_WIDTH)
        rail_layout = QVBoxLayout(self.drawer_rail)
        rail_layout.setContentsMargins(6, 6, 6, 6)
        rail_layout.setSpacing(8)

        self.drawer_toggle = QPushButton(">", self.drawer_rail)
        self.drawer_toggle.setToolTip("Toggle command drawer")
        self.drawer_toggle.clicked.connect(self.host.toggle_drawer)
        rail_layout.addWidget(self.drawer_toggle)
        for label, tooltip, callback in (
            ("Q", "Quick commands", lambda: self._select_drawer_page(0)),
            ("S", "Scripts", lambda: self._select_drawer_page(1)),
            ("P", "Profiles", lambda: self._select_drawer_page(2)),
        ):
            button = QPushButton(label, self.drawer_rail)
            button.setToolTip(tooltip)
            button.clicked.connect(callback)
            rail_layout.addWidget(button)
        rail_layout.addStretch(1)

        self.drawer_panel = QFrame(self.drawer)
        self.drawer_panel.setObjectName("drawerPanel")
        panel_layout = QVBoxLayout(self.drawer_panel)
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(8)

        self.drawer_pages = QStackedWidget(self.drawer_panel)
        self.drawer_pages.addWidget(self._build_quick_page())
        self.drawer_pages.addWidget(self._build_scripts_page())
        self.drawer_pages.addWidget(self._build_profiles_page())
        panel_layout.addWidget(self.drawer_pages, 1)

        drawer_layout.addWidget(self.drawer_rail)
        drawer_layout.addWidget(self.drawer_panel, 1)

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
        prev_button.clicked.connect(self.find_previous)
        next_button = QPushButton("Next", self.search_bar)
        next_button.clicked.connect(self.find_next)
        close_search = QPushButton("X", self.search_bar)
        close_search.clicked.connect(self.hide_search)
        self.search_count = QLabel("0", self.search_bar)
        search_layout.addWidget(self.search_input, 1)
        search_layout.addWidget(prev_button)
        search_layout.addWidget(next_button)
        search_layout.addWidget(self.search_count)
        search_layout.addWidget(close_search)
        self.search_bar.hide()

        self.terminal = QTextEdit(terminal_column)
        self.terminal.setObjectName("terminal")
        self.terminal.setReadOnly(True)
        self.terminal.setAcceptRichText(False)
        self.terminal.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

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
        self.command_input = HistoryLineEdit(self.command_bar)
        self.command_input.setPlaceholderText("Send command")
        self.command_input.returnPressed.connect(self.send_from_input)
        self.command_input.historyRequested.connect(self._navigate_history)
        self.command_input.autocompleteRequested.connect(self._show_completion_popup)
        self.command_input.textEdited.connect(self._on_command_edited)
        self.completion_model = QStringListModel(self)
        completer = QCompleter(self.completion_model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.activated.connect(self._apply_completion)
        self.command_input.setCompleter(completer)
        send_button = QPushButton("Send", self.command_bar)
        set_button_role(send_button, "accent")
        send_button.clicked.connect(self.send_from_input)
        self.line_ending_label = QLabel("", self.command_bar)
        self.log_label = QLabel("Log off", self.command_bar)
        self.pause_label = QLabel("", self.command_bar)
        font_down = QPushButton("-", self.command_bar)
        font_down.setFixedWidth(30)
        font_down.setToolTip("Decrease terminal font")
        font_down.clicked.connect(lambda: self.host.change_font_size(-1))
        font_up = QPushButton("+", self.command_bar)
        font_up.setFixedWidth(30)
        font_up.setToolTip("Increase terminal font")
        font_up.clicked.connect(lambda: self.host.change_font_size(1))

        command_layout.addWidget(self.mode_combo)
        command_layout.addWidget(self.command_input, 1)
        command_layout.addWidget(send_button)
        command_layout.addWidget(self.line_ending_label)
        command_layout.addWidget(self.log_label)
        command_layout.addWidget(self.pause_label)
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

    def _build_quick_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel("Quick Send", page)
        title.setObjectName("drawerTitle")
        self.quick_list = QListWidget(page)
        self.quick_list.itemDoubleClicked.connect(lambda _: self.send_selected_quick_command())
        send = QPushButton("Send", page)
        send.clicked.connect(self.send_selected_quick_command)
        add = QPushButton("Add", page)
        add.clicked.connect(self.host.add_quick_command)
        edit = QPushButton("Edit", page)
        edit.clicked.connect(lambda: self.host.edit_quick_command(self.selected_quick_command_id()))
        delete = QPushButton("Delete", page)
        delete.clicked.connect(lambda: self.host.delete_quick_command(self.selected_quick_command_id()))
        up = QPushButton("Up", page)
        up.clicked.connect(lambda: self.host.move_quick_command(self.selected_quick_command_id(), -1))
        down = QPushButton("Down", page)
        down.clicked.connect(lambda: self.host.move_quick_command(self.selected_quick_command_id(), 1))
        layout.addWidget(title)
        layout.addWidget(self.quick_list, 1)
        for row in ((send, add), (edit, delete), (up, down)):
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            for button in row:
                line.addWidget(button)
            layout.addLayout(line)
        return page

    def _build_scripts_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel("Shortcuts", page)
        title.setObjectName("drawerTitle")
        connect = QPushButton("Connect / Disconnect", page)
        connect.clicked.connect(self.toggle_connection)
        settings = QPushButton("Serial Settings", page)
        settings.clicked.connect(lambda: self.open_connection_settings())
        run = QPushButton("Run Command File", page)
        run.clicked.connect(self.run_script)
        stop = QPushButton("Stop Command File", page)
        stop.clicked.connect(self.stop_script)
        log = QPushButton("Start / Stop Log", page)
        log.clicked.connect(self.toggle_logging)
        clear = QPushButton("Clear Terminal", page)
        clear.clicked.connect(self.clear_terminal)
        pause = QPushButton("Pause / Resume Output", page)
        pause.clicked.connect(self.toggle_pause)
        save = QPushButton("Save Current Input", page)
        save.clicked.connect(self.save_current_input_as_quick_command)
        layout.addWidget(title)
        for button in (connect, settings, run, stop, log, clear, pause, save):
            layout.addWidget(button)
        layout.addStretch(1)
        return page

    def _build_profiles_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel("Profiles", page)
        title.setObjectName("drawerTitle")
        self.profile_list = QListWidget(page)
        self.profile_list.itemDoubleClicked.connect(lambda _: self.apply_selected_profile())
        apply = QPushButton("Apply Profile", page)
        apply.clicked.connect(self.apply_selected_profile)
        save = QPushButton("Save Current As Profile", page)
        save.clicked.connect(self.save_current_profile)
        layout.addWidget(title)
        layout.addWidget(self.profile_list, 1)
        layout.addWidget(apply)
        layout.addWidget(save)
        return page

    def _select_drawer_page(self, index: int) -> None:
        self.drawer_pages.setCurrentIndex(index)
        if self.host.settings.drawer_collapsed:
            self.host.set_drawer_collapsed(False)

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
        self._update_line_ending_label()

    def apply_drawer_state(self, collapsed: bool, width: int) -> None:
        self.drawer_panel.setVisible(not collapsed)
        self.drawer_toggle.setText(">" if collapsed else "<")
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
            self.host.set_drawer_width(sizes[0])

    def selected_quick_command_id(self) -> str:
        item = self.quick_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""

    def refresh_quick_commands(self) -> None:
        self.quick_list.clear()
        for command in self.host.settings.quick_commands:
            item = QListWidgetItem(f"{command.group}  |  {command.display_label()}")
            item.setData(Qt.ItemDataRole.UserRole, command.id)
            item.setToolTip(command.command)
            self.quick_list.addItem(item)
        self._update_completion_model()

    def refresh_profiles(self) -> None:
        self.profile_list.clear()
        for name in self.host.settings.profiles:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.profile_list.addItem(item)

    def refresh_ports(self) -> None:
        self._ports = self.serial_client.list_ports()
        self.host.set_status(f"{len(self._ports)} serial port(s) detected.")

    def apply_selected_profile(self) -> None:
        item = self.profile_list.currentItem()
        if not item:
            return
        self.profile_name = str(item.data(Qt.ItemDataRole.UserRole))
        self.profile = self.host.get_profile(self.profile_name)
        self._update_line_ending_label()
        self.host.update_tab_titles()
        self.host.save_settings()

    def save_current_profile(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save Profile", "Profile name", text=self.profile_name)
        if not accepted or not name.strip():
            return
        self.profile_name = name.strip()
        self.host.settings.profiles[self.profile_name] = clone_profile(self.profile)
        self.host.settings.active_profile = self.profile_name
        self.host.refresh_profiles_everywhere()
        self.host.save_settings()

    def open_connection_settings(self, *, connect_after_accept: bool = True) -> bool:
        dialog = ConnectionSettingsDialog(self.profile, self.serial_client.list_ports(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            self.profile = dialog.profile()
        except ValueError as exc:
            QMessageBox.warning(self, "Serial Settings", str(exc))
            return False
        self.host.settings.profiles[self.profile_name] = clone_profile(self.profile)
        self._update_line_ending_label()
        self._update_connection_ui(self.serial_client.is_connected)
        if connect_after_accept and self.profile.port:
            if self.serial_client.is_connected:
                self.serial_client.disconnect()
            self.host.set_status(f"Connecting to {self.profile.port}...")
            self.serial_client.connect(self.profile)
        self.host.save_settings()
        return True

    def toggle_connection(self) -> None:
        if self.serial_client.is_connected:
            self.serial_client.disconnect()
            return
        if not self.profile.port:
            self.open_connection_settings(connect_after_accept=True)
            return
        self.serial_client.connect(self.profile)
        self.host.save_settings()

    def send_from_input(self) -> None:
        raw = self.command_input.text()
        if not raw.strip():
            return
        try:
            self._send_payload(raw, self.mode_combo.currentText())
        except Exception as exc:
            QMessageBox.warning(self, "Send", str(exc))
            return
        self.host.record_command(raw.strip())
        self.command_input.clear()

    def _send_payload(self, raw: str, mode: str) -> None:
        if mode == "Hex Bytes":
            self.serial_client.send_bytes(parse_hex_payload(raw))
            return
        lines = raw.splitlines() if "\n" in raw or "\r" in raw else [raw]
        for line in lines:
            if line.strip():
                self.serial_client.send_text(line.strip())

    def send_selected_quick_command(self) -> None:
        command = self.host.quick_command_by_id(self.selected_quick_command_id())
        if not command:
            return
        try:
            if command.send_mode == "Hex Bytes":
                self.serial_client.send_bytes(parse_hex_payload(command.command))
            else:
                self.serial_client.send_text(
                    command.command,
                    command.line_ending_override or None,
                )
        except Exception as exc:
            QMessageBox.warning(self, "Quick Send", str(exc))
            return
        self.host.record_command(command.command)

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
        try:
            steps = load_batch_file(path)
        except (BatchParseError, OSError) as exc:
            QMessageBox.critical(self, "Run Command File", str(exc))
            return
        self.host.settings.last_script_path = str(Path(path).parent)
        self.batch_runner.start(steps)
        self.host.save_settings()

    def stop_script(self) -> None:
        self.batch_runner.stop()

    def toggle_logging(self) -> None:
        if self.logger.enabled:
            path = self.logger.path
            self.logger.close()
            self.log_label.setText("Log off")
            self._append_status(f"Logging stopped: {path}" if path else "Logging stopped.")
            return
        default_dir = Path(self.host.settings.log_path).parent if self.host.settings.log_path else Path.cwd()
        default_name = f"comport-zone-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        path, _ = QFileDialog.getSaveFileName(self, "Choose Log File", str(default_dir / default_name), "Log Files (*.log *.txt);;All Files (*)")
        if not path:
            return
        self.logger.open(path)
        self.host.settings.log_path = path
        self.log_label.setText("Logging")
        self._append_status(f"Logging to {path}")
        self.host.save_settings()

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.pause_label.setText("Paused" if self.paused else "")
        if not self.paused:
            for event in self.pending_events:
                self._render_event(event)
            self.pending_events.clear()

    def clear_terminal(self) -> None:
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

    def _find_in_terminal(self, *, backward: bool) -> None:
        query = self.search_input.text().strip()
        if not query:
            return
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if self.terminal.find(query, flags):
            return
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
        self.terminal.setTextCursor(cursor)
        self.terminal.find(query, flags)

    def _refresh_search_highlights(self, text: str) -> None:
        query = text.strip()
        selections: list[QTextEdit.ExtraSelection] = []
        if query:
            cursor = self.terminal.document().find(query)
            while not cursor.isNull():
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                fmt = QTextCharFormat()
                fmt.setBackground(QColor(self.host.theme.search_highlight))
                fmt.setForeground(QColor("#ffffff"))
                selection.format = fmt
                selections.append(selection)
                cursor = self.terminal.document().find(query, cursor)
        self.terminal.setExtraSelections(selections)
        self.search_count.setText(str(len(selections)))

    def _navigate_history(self, direction: int) -> None:
        text = self.history_store.navigate(direction, self.command_input.text())
        self.command_input.setText(text)
        self.command_input.setCursorPosition(len(text))

    def _on_command_edited(self, text: str) -> None:
        self.history_store.reset_navigation()
        self._update_completion_model(text)

    def _update_completion_model(self, prefix: str | None = None) -> None:
        text = prefix if prefix is not None else self.command_input.text()
        suggestions = self.history_store.suggestions(text)
        suggestions.extend(
            command.command
            for command in self.host.settings.quick_commands
            if command.command not in suggestions and text.casefold() in command.command.casefold()
        )
        self.completion_model.setStringList(suggestions[:30])

    def _show_completion_popup(self) -> None:
        self._update_completion_model()
        if self.completion_model.rowCount() > 0 and self.command_input.completer():
            self.command_input.completer().complete()

    def _apply_completion(self, value: str) -> None:
        self.command_input.setText(value)
        self.command_input.setCursorPosition(len(value))

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.serial_client.events.get_nowait()
            except Empty:
                break
            self._handle_event(event)

    def _handle_event(self, event: SerialEvent) -> None:
        if event.kind == "connection":
            if self.logger.enabled:
                self.logger.log_event(event)
            connected = event.message == "connected"
            self._update_connection_ui(connected)
            self.batch_runner.notify_connection_state(connected)
            return
        if self.paused and event.kind == "rx":
            self.pending_events.append(event)
            self.pause_label.setText(f"Paused ({len(self.pending_events)})")
            return
        self._render_event(event)
        if self.logger.enabled:
            self.logger.log_event(event)

    def _render_event(self, event: SerialEvent) -> None:
        colors = {
            "rx": self.host.theme.rx,
            "tx": self.host.theme.tx,
            "status": self.host.theme.status,
            "error": self.host.theme.error,
        }
        prefixes = {
            "rx": "",
            "tx": "TX> ",
            "status": "SYS ",
            "error": "ERR ",
        }
        message = event.message.replace("\r\n", "\n").replace("\r", "\n")
        if self.host.settings.timestamps_enabled:
            stamp = event.timestamp.astimezone().strftime("%H:%M:%S.%f")[:-3]
            rendered = "".join(f"[{stamp}] {prefixes.get(event.kind, '')}{line}\n" for line in message.split("\n") if line != "")
        else:
            rendered = "".join(f"{prefixes.get(event.kind, '')}{line}\n" for line in message.split("\n") if line != "")
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(colors.get(event.kind, "#d4d4d4")))
        cursor.insertText(rendered, fmt)
        self.terminal.setTextCursor(cursor)
        self.terminal.ensureCursorVisible()
        if self.search_bar.isVisible():
            self._refresh_search_highlights(self.search_input.text())

    def _append_status(self, message: str) -> None:
        self._render_event(SerialEvent(kind="status", message=message))

    def _update_connection_ui(self, connected: bool) -> None:
        self._connected = connected
        self._status_text = "Connected" if connected else "Disconnected"
        profile_text = f"{self.profile.port or 'No port'} {self.profile.baudrate} {self.profile.bytesize}{self.profile.parity}{self.profile.stopbits:g}"
        self.status_label.setText(f"{self._status_text} | {profile_text}")
        self.host.update_tab_titles()
        self.host.set_status(self.status_label.text())

    def _update_line_ending_label(self) -> None:
        self.line_ending_label.setText(self.profile.line_ending)

    def shutdown(self) -> None:
        self.event_timer.stop()
        self.batch_runner.stop(emit_message=False)
        self.serial_client.disconnect()
        self.logger.close()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings_store = SettingsStore(default_config_path())
        self.settings = self.settings_store.load()
        self.settings.ensure_active_profile()
        self.history_catalog = HistoryStore(self.settings.command_history)
        self.theme = THEMES.get(self.settings.theme, THEMES["VS Code Dark"])
        self._session_counter = 0
        self._loading = True

        self.setWindowTitle("ComPort Zone")
        self.setFont(pick_ui_font())
        self.resize(self.settings.window_width, self.settings.window_height)
        self._build_ui()
        self._build_menus()
        self.apply_theme(self.theme.name)
        self.restore_sessions()
        self._loading = False
        self.set_status("Ready")

    def _build_ui(self) -> None:
        self.tabs = TerminalTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.newTabRequested.connect(lambda: self.add_session(prompt_settings=True))
        self.tabs.tabCloseRequested.connect(self.close_session)
        self.tabs.currentChanged.connect(lambda _: self.sync_status_from_current_session())
        self.setCentralWidget(self.tabs)

        self.footer = QLabel("Ready", self)
        self.footer.setObjectName("footer")
        self.statusBar().addPermanentWidget(self.footer, 1)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        self._add_action(file_menu, "New Tab", "Ctrl+T", lambda: self.add_session(prompt_settings=True))
        self._add_action(file_menu, "Duplicate Tab", "Ctrl+Shift+T", self.duplicate_current_session)
        self._add_action(file_menu, "Close Tab", "Ctrl+W", self.close_current_session)
        file_menu.addSeparator()
        self._add_action(file_menu, "Run Command File", "Ctrl+R", lambda: self.with_session(lambda s: s.run_script()))
        self._add_action(file_menu, "Start / Stop Log", "Ctrl+L", lambda: self.with_session(lambda s: s.toggle_logging()))
        file_menu.addSeparator()
        self._add_action(file_menu, "Exit", "", self.close)

        edit_menu = self.menuBar().addMenu("Edit")
        self._add_action(edit_menu, "Copy", "Ctrl+Shift+C", lambda: self.with_session(lambda s: s.copy_selection()))
        self._add_action(edit_menu, "Select All", "Ctrl+A", lambda: self.with_session(lambda s: s.select_all()))
        self._add_action(edit_menu, "Clear Terminal", "Ctrl+K", lambda: self.with_session(lambda s: s.clear_terminal()))
        self._add_action(edit_menu, "Search", "Ctrl+F", lambda: self.with_session(lambda s: s.show_search()))

        view_menu = self.menuBar().addMenu("View")
        self._add_action(view_menu, "Toggle Drawer", "Ctrl+B", self.toggle_drawer)
        self._add_action(view_menu, "Increase Font", "Ctrl+=", lambda: self.change_font_size(1))
        self._add_action(view_menu, "Decrease Font", "Ctrl+-", lambda: self.change_font_size(-1))
        self.timestamps_action = self._add_action(view_menu, "Show Timestamps", "", self.toggle_timestamps, checkable=True)
        self.timestamps_action.setChecked(self.settings.timestamps_enabled)
        self.wrap_action = self._add_action(view_menu, "Line Wrap", "", self.toggle_line_wrap, checkable=True)
        self.wrap_action.setChecked(self.settings.line_wrap_enabled)
        theme_menu = view_menu.addMenu("Theme")
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        for theme_name in THEME_OPTIONS:
            action = QAction(theme_name, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, name=theme_name: self.apply_theme(name))
            self.theme_group.addAction(action)
            theme_menu.addAction(action)
            self.theme_actions[theme_name] = action

        session_menu = self.menuBar().addMenu("Session")
        self._add_action(session_menu, "Rename Tab", "F2", self.rename_current_session)
        self._add_action(session_menu, "Connect / Disconnect", "Ctrl+Enter", lambda: self.with_session(lambda s: s.toggle_connection()))
        self._add_action(session_menu, "Pause / Resume Output", "Ctrl+P", lambda: self.with_session(lambda s: s.toggle_pause()))

        serial_menu = self.menuBar().addMenu("Serial")
        self._add_action(serial_menu, "Serial Settings", "Ctrl+,", lambda: self.with_session(lambda s: s.open_connection_settings()))
        self._add_action(serial_menu, "Refresh Ports", "F5", lambda: self.with_session(lambda s: s.refresh_ports()))
        self._add_action(serial_menu, "Save Profile", "", lambda: self.with_session(lambda s: s.save_current_profile()))
        self._add_action(serial_menu, "Import Profiles", "", self.import_profiles)
        self._add_action(serial_menu, "Export Profiles", "", self.export_profiles)

        tools_menu = self.menuBar().addMenu("Tools")
        self._add_action(tools_menu, "Add Quick Command", "", self.add_quick_command)
        self._add_action(tools_menu, "Edit Selected Quick Command", "", lambda: self.with_session(lambda s: self.edit_quick_command(s.selected_quick_command_id())))
        self._add_action(tools_menu, "Delete Selected Quick Command", "", lambda: self.with_session(lambda s: self.delete_quick_command(s.selected_quick_command_id())))

        help_menu = self.menuBar().addMenu("Help")
        self._add_action(help_menu, "About", "", self.show_about)

    def _add_action(self, menu, text: str, shortcut: str, callback, *, checkable: bool = False) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.setCheckable(checkable)
        action.triggered.connect(lambda _checked=False: callback())
        menu.addAction(action)
        return action

    def restore_sessions(self) -> None:
        states = self.settings.restored_tabs or [TerminalSessionState(title="Terminal 1", profile_name=self.settings.active_profile)]
        for state in states:
            self.add_session(state, prompt_settings=False)
        if self.tabs.count() == 0:
            self.add_session(prompt_settings=False)
        self.prompt_current_session_settings()

    def add_session(self, state: TerminalSessionState | None = None, *, prompt_settings: bool = True) -> None:
        self._session_counter += 1
        state = state or TerminalSessionState(title=f"Terminal {self._session_counter}", profile_name=self.settings.active_profile)
        session = TerminalSessionWidget(self, self._session_counter, state)
        index = self.tabs.addTab(session, session.tab_title)
        self.tabs.setCurrentIndex(index)
        self.update_tab_titles()
        if prompt_settings:
            self.prompt_session_settings(session)

    def prompt_current_session_settings(self) -> None:
        session = self.current_session()
        if session:
            self.prompt_session_settings(session)

    def prompt_session_settings(self, session: TerminalSessionWidget) -> None:
        QTimer.singleShot(0, lambda: self._open_prompted_session_settings(session))

    def _open_prompted_session_settings(self, session: TerminalSessionWidget) -> None:
        if self.tabs.indexOf(session) < 0:
            return
        self.tabs.setCurrentWidget(session)
        session.open_connection_settings(connect_after_accept=True)

    def duplicate_current_session(self) -> None:
        session = self.current_session()
        if not session:
            self.add_session()
            return
        self.add_session(
            TerminalSessionState(title=f"{session.title} Copy", profile_name=session.profile_name),
            prompt_settings=False,
        )

    def close_current_session(self) -> None:
        index = self.tabs.currentIndex()
        if index >= 0:
            self.close_session(index)

    def close_session(self, index: int) -> None:
        session = self.tabs.widget(index)
        if isinstance(session, TerminalSessionWidget):
            session.shutdown()
        self.tabs.removeTab(index)
        if session:
            session.deleteLater()
        if self.tabs.count() == 0:
            self.add_session()
        self.save_settings()

    def rename_current_session(self) -> None:
        session = self.current_session()
        if not session:
            return
        title, accepted = QInputDialog.getText(self, "Rename Tab", "Tab name", text=session.title)
        if accepted and title.strip():
            session.title = title.strip()
            self.update_tab_titles()
            self.save_settings()

    def current_session(self) -> TerminalSessionWidget | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, TerminalSessionWidget) else None

    def iter_sessions(self) -> list[TerminalSessionWidget]:
        sessions: list[TerminalSessionWidget] = []
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, TerminalSessionWidget):
                sessions.append(widget)
        return sessions

    def with_session(self, callback) -> None:
        session = self.current_session()
        if session:
            callback(session)

    def update_tab_titles(self) -> None:
        for index, session in enumerate(self.iter_sessions()):
            self.tabs.setTabText(index, session.tab_title)

    def sync_status_from_current_session(self) -> None:
        session = self.current_session()
        if session:
            self.set_status(session.status_label.text())

    def set_status(self, text: str) -> None:
        self.footer.setText(text)

    def toggle_drawer(self) -> None:
        self.set_drawer_collapsed(not self.settings.drawer_collapsed)

    def set_drawer_collapsed(self, collapsed: bool) -> None:
        self.settings.drawer_collapsed = collapsed
        for session in self.iter_sessions():
            session.apply_drawer_state(collapsed, self.settings.drawer_width)
        self.save_settings()

    def set_drawer_width(self, width: int) -> None:
        self.settings.drawer_width = max(220, min(width, 520))
        if not self._loading:
            self.save_settings()

    def change_font_size(self, delta: int) -> None:
        self.settings.terminal_font_size = max(
            TERMINAL_FONT_MIN,
            min(self.settings.terminal_font_size + delta, TERMINAL_FONT_MAX),
        )
        for session in self.iter_sessions():
            session.apply_settings()
        self.save_settings()

    def toggle_timestamps(self) -> None:
        self.settings.timestamps_enabled = self.timestamps_action.isChecked()
        self.save_settings()

    def toggle_line_wrap(self) -> None:
        self.settings.line_wrap_enabled = self.wrap_action.isChecked()
        for session in self.iter_sessions():
            session.apply_settings()
        self.save_settings()

    def get_profile(self, name: str) -> SerialProfile:
        return clone_profile(self.settings.profiles.get(name) or next(iter(self.settings.profiles.values())))

    def refresh_profiles_everywhere(self) -> None:
        for session in self.iter_sessions():
            session.refresh_profiles()

    def quick_command_by_id(self, command_id: str) -> QuickCommand | None:
        return next((command for command in self.settings.quick_commands if command.id == command_id), None)

    def add_quick_command(self, command: QuickCommand | None = None) -> None:
        if command is None or isinstance(command, bool):
            dialog = QuickCommandDialog(parent=self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            command = dialog.quick_command()
        if not command.command:
            return
        self.settings.quick_commands.append(command)
        self.refresh_quick_commands_everywhere()
        self.save_settings()

    def edit_quick_command(self, command_id: str) -> None:
        command = self.quick_command_by_id(command_id)
        if not command:
            return
        dialog = QuickCommandDialog(command, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.quick_command()
        for index, existing in enumerate(self.settings.quick_commands):
            if existing.id == updated.id:
                self.settings.quick_commands[index] = updated
                break
        self.refresh_quick_commands_everywhere()
        self.save_settings()

    def delete_quick_command(self, command_id: str) -> None:
        if not command_id:
            return
        self.settings.quick_commands = [command for command in self.settings.quick_commands if command.id != command_id]
        self.refresh_quick_commands_everywhere()
        self.save_settings()

    def move_quick_command(self, command_id: str, direction: int) -> None:
        commands = self.settings.quick_commands
        index = next((i for i, command in enumerate(commands) if command.id == command_id), -1)
        target = index + direction
        if index < 0 or target < 0 or target >= len(commands):
            return
        commands[index], commands[target] = commands[target], commands[index]
        self.refresh_quick_commands_everywhere()
        self.save_settings()

    def refresh_quick_commands_everywhere(self) -> None:
        for session in self.iter_sessions():
            session.refresh_quick_commands()

    def record_command(self, command: str) -> None:
        self.history_catalog.add(command)
        for session in self.iter_sessions():
            session.history_store.add(command)
            session._update_completion_model()
        self.save_settings()

    def import_profiles(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Profiles", str(Path.cwd()), "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        try:
            import json

            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            profiles = payload.get("profiles", payload)
            for name, data in profiles.items():
                self.settings.profiles[str(name)] = SerialProfile.from_dict(data)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Import Profiles", str(exc))
            return
        self.refresh_profiles_everywhere()
        self.save_settings()

    def export_profiles(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Profiles", str(Path.cwd() / "comport-zone-profiles.json"), "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        try:
            import json

            payload = {"profiles": {name: profile.to_dict() for name, profile in self.settings.profiles.items()}}
            Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Export Profiles", str(exc))

    def show_about(self) -> None:
        QMessageBox.information(self, "About ComPort Zone", "ComPort Zone\nSerial terminal for Windows COM-port workflows.")

    def apply_theme(self, name: str) -> None:
        self.theme = THEMES.get(name, THEMES["VS Code Dark"])
        self.settings.theme = self.theme.name
        self.setStyleSheet(self._stylesheet(self.theme))
        for theme_name, action in getattr(self, "theme_actions", {}).items():
            action.setChecked(theme_name == self.theme.name)
        self.save_settings()

    def _stylesheet(self, theme: ThemePalette) -> str:
        terminal_background = "#0c0c0c" if theme.name in {"VS Code Dark", "Windows Terminal"} else theme.field
        return f"""
        QMainWindow, QWidget {{
            background: {theme.window};
            color: {theme.text};
        }}
        QMenuBar {{
            background: {theme.window};
            color: {theme.text};
            border-bottom: 1px solid {theme.border};
        }}
        QMenuBar::item {{
            padding: 5px 10px;
        }}
        QMenuBar::item:selected, QMenu {{
            background: {theme.surface_alt};
        }}
        QMenu {{
            border: 1px solid {theme.border};
            padding: 4px;
        }}
        QMenu::item {{
            padding: 6px 28px 6px 20px;
        }}
        QMenu::item:selected {{
            background: {theme.accent_soft};
        }}
        QTabWidget::pane {{
            border: none;
        }}
        QTabBar::tab {{
            background: {theme.surface_alt};
            color: {theme.text};
            padding: 8px 14px;
            min-width: 130px;
            border-right: 1px solid {theme.window};
        }}
        QTabBar::tab:selected {{
            background: {theme.window};
            border-top: 2px solid {theme.accent};
        }}
        QToolButton#newTabButton {{
            background: {theme.surface_alt};
            color: {theme.text};
            border: 1px solid {theme.border};
            border-radius: 0;
            font-size: 13pt;
            padding: 0;
        }}
        QToolButton#newTabButton:hover {{
            background: {theme.surface};
            border-color: {theme.accent};
        }}
        QFrame#drawer {{
            background: {theme.window_alt};
            border-right: 1px solid {theme.border};
        }}
        QFrame#drawerRail {{
            background: {theme.surface_alt};
        }}
        QFrame#drawerPanel {{
            background: {theme.window_alt};
        }}
        QLabel#drawerTitle {{
            font-weight: 650;
            color: {theme.text};
        }}
        QFrame#terminalColumn, QTextEdit#terminal {{
            background: {terminal_background};
            color: {theme.text};
        }}
        QFrame#commandBar, QFrame#searchBar {{
            background: {theme.window};
            border-top: 1px solid {theme.border};
        }}
        QLineEdit, QComboBox, QListWidget {{
            background: {theme.field};
            color: {theme.text};
            border: 1px solid {theme.border};
            padding: 6px;
            selection-background-color: {theme.search_highlight};
        }}
        QComboBox {{
            padding-right: 28px;
        }}
        QComboBox::drop-down {{
            width: 26px;
            border-left: 1px solid {theme.border};
            background: {theme.surface_alt};
        }}
        QPushButton {{
            background: {theme.surface_alt};
            color: {theme.text};
            border: 1px solid {theme.border};
            padding: 6px 10px;
        }}
        QPushButton:hover {{
            background: {theme.surface};
            border-color: {theme.accent};
        }}
        QPushButton[role="accent"] {{
            background: {theme.accent};
            color: #ffffff;
            border-color: {theme.accent};
        }}
        QStatusBar {{
            background: {theme.accent};
            color: #ffffff;
        }}
        """

    def save_settings(self) -> None:
        if self._loading:
            return
        session = self.current_session()
        if session:
            self.settings.active_profile = session.profile_name
        self.settings.command_history = self.history_catalog.all_commands()
        self.settings.window_width = self.width()
        self.settings.window_height = self.height()
        self.settings.restored_tabs = [session.to_state() for session in self.iter_sessions()]
        if not self.settings_store.save(self.settings):
            self.set_status("Could not save settings to disk.")

    def closeEvent(self, event) -> None:
        for session in self.iter_sessions():
            session.shutdown()
        self.save_settings()
        super().closeEvent(event)


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("ComPort Zone")
    app.setFont(pick_ui_font())
    window = MainWindow()
    window.show()
    return app.exec()
