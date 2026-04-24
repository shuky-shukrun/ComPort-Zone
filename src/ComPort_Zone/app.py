from __future__ import annotations

from datetime import datetime
from pathlib import Path
from queue import Empty

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QStringListModel, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap, QTextCharFormat, QTextCursor, QTextDocument
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
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QStyle,
    QVBoxLayout,
    QWidget,
    QCompleter,
)
from PySide6.QtSvg import QSvgRenderer

from .batch import BatchParseError, BatchRunner, load_batch_file, parse_hex_payload
from .history import HistoryStore
from .models import (
    AppSettings,
    DEFAULT_PROFILE_NAME,
    FLOW_CONTROL_OPTIONS,
    LINE_ENDINGS,
    QuickCommand,
    SerialProfile,
    TerminalSessionState,
    THEME_OPTIONS,
    UserProfile,
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

TABLER_ICON_PATHS = {
    "arrow-left": '<path d="M5 12l14 0" /><path d="M5 12l6 6" /><path d="M5 12l6 -6" />',
    "arrow-right": '<path d="M5 12l14 0" /><path d="M13 18l6 -6" /><path d="M13 6l6 6" />',
    "check": '<path d="M5 12l5 5l10 -10" />',
    "chevron-down": '<path d="M6 9l6 6l6 -6" />',
    "chevron-up": '<path d="M6 15l6 -6l6 6" />',
    "clock": '<path d="M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0" /><path d="M12 7v5l3 3" />',
    "clipboard-list": '<path d="M9 5h-2a2 2 0 0 0 -2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-12a2 2 0 0 0 -2 -2h-2" /><path d="M9 5a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2a2 2 0 0 1 -2 2h-2a2 2 0 0 1 -2 -2" /><path d="M9 12l.01 0" /><path d="M13 12l2 0" /><path d="M9 16l.01 0" /><path d="M13 16l2 0" />',
    "command": '<path d="M7 9a2 2 0 1 1 2 -2v10a2 2 0 1 1 -2 -2h10a2 2 0 1 1 -2 2v-10a2 2 0 1 1 2 2h-10" />',
    "copy": '<path d="M7 9.667a2.667 2.667 0 0 1 2.667 -2.667h8.666a2.667 2.667 0 0 1 2.667 2.667v8.666a2.667 2.667 0 0 1 -2.667 2.667h-8.666a2.667 2.667 0 0 1 -2.667 -2.667l0 -8.666" /><path d="M4.012 16.737a2.005 2.005 0 0 1 -1.012 -1.737v-10c0 -1.1 .9 -2 2 -2h10c.75 0 1.158 .385 1.5 1" />',
    "database": '<path d="M4 6a8 3 0 1 0 16 0a8 3 0 1 0 -16 0" /><path d="M4 6v6a8 3 0 0 0 16 0v-6" /><path d="M4 12v6a8 3 0 0 0 16 0v-6" />',
    "device-floppy": '<path d="M6 4h10l4 4v10a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2v-12a2 2 0 0 1 2 -2" /><path d="M10 14a2 2 0 1 0 4 0a2 2 0 1 0 -4 0" /><path d="M14 4l0 4l-6 0l0 -4" />',
    "file-export": '<path d="M14 3v4a1 1 0 0 0 1 1h4" /><path d="M11.5 21h-4.5a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v5m-5 6h7m-3 -3l3 3l-3 3" />',
    "file-import": '<path d="M14 3v4a1 1 0 0 0 1 1h4" /><path d="M5 13v-8a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2h-5.5m-9.5 -2h7m-3 -3l3 3l-3 3" />',
    "folder-open": '<path d="M5 19l2.757 -7.351a1 1 0 0 1 .936 -.649h12.307a1 1 0 0 1 .986 1.164l-.996 5.211a2 2 0 0 1 -1.964 1.625h-14.026a2 2 0 0 1 -2 -2v-11a2 2 0 0 1 2 -2h4l3 3h7a2 2 0 0 1 2 2v2" />',
    "info-circle": '<path d="M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0" /><path d="M12 9h.01" /><path d="M11 12h1v4h1" />',
    "list": '<path d="M9 6l11 0" /><path d="M9 12l11 0" /><path d="M9 18l11 0" /><path d="M5 6l0 .01" /><path d="M5 12l0 .01" /><path d="M5 18l0 .01" />',
    "pencil": '<path d="M4 20h4l10.5 -10.5a2.828 2.828 0 1 0 -4 -4l-10.5 10.5v4" /><path d="M13.5 6.5l4 4" />',
    "player-pause": '<path d="M6 6a1 1 0 0 1 1 -1h2a1 1 0 0 1 1 1v12a1 1 0 0 1 -1 1h-2a1 1 0 0 1 -1 -1l0 -12" /><path d="M14 6a1 1 0 0 1 1 -1h2a1 1 0 0 1 1 1v12a1 1 0 0 1 -1 1h-2a1 1 0 0 1 -1 -1l0 -12" />',
    "player-play": '<path d="M7 4v16l13 -8l-13 -8" />',
    "player-stop": '<path d="M5 7a2 2 0 0 1 2 -2h10a2 2 0 0 1 2 2v10a2 2 0 0 1 -2 2h-10a2 2 0 0 1 -2 -2l0 -10" />',
    "plus": '<path d="M12 5l0 14" /><path d="M5 12l14 0" />',
    "refresh": '<path d="M20 11a8.1 8.1 0 0 0 -15.5 -2m-.5 -4v4h4" /><path d="M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4" />',
    "search": '<path d="M3 10a7 7 0 1 0 14 0a7 7 0 1 0 -14 0" /><path d="M21 21l-6 -6" />',
    "send": '<path d="M10 14l11 -11" /><path d="M21 3l-6.5 18a.55 .55 0 0 1 -1 0l-3.5 -7l-7 -3.5a.55 .55 0 0 1 0 -1l18 -6.5" />',
    "settings": '<path d="M10.325 4.317c.426 -1.756 2.924 -1.756 3.35 0a1.724 1.724 0 0 0 2.573 1.066c1.543 -.94 3.31 .826 2.37 2.37a1.724 1.724 0 0 0 1.065 2.572c1.756 .426 1.756 2.924 0 3.35a1.724 1.724 0 0 0 -1.066 2.573c.94 1.543 -.826 3.31 -2.37 2.37a1.724 1.724 0 0 0 -2.572 1.065c-.426 1.756 -2.924 1.756 -3.35 0a1.724 1.724 0 0 0 -2.573 -1.066c-1.543 .94 -3.31 -.826 -2.37 -2.37a1.724 1.724 0 0 0 -1.065 -2.572c-1.756 -.426 -1.756 -2.924 0 -3.35a1.724 1.724 0 0 0 1.066 -2.573c-.94 -1.543 .826 -3.31 2.37 -2.37c1 .608 2.296 .07 2.572 -1.065" /><path d="M9 12a3 3 0 1 0 6 0a3 3 0 0 0 -6 0" />',
    "terminal-2": '<path d="M8 9l3 3l-3 3" /><path d="M13 15l3 0" /><path d="M3 6a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2l0 -12" />',
    "trash": '<path d="M4 7l16 0" /><path d="M10 11l0 6" /><path d="M14 11l0 6" /><path d="M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2 -2l1 -12" /><path d="M9 7v-3a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v3" />',
    "x": '<path d="M18 6l-12 12" /><path d="M6 6l12 12" />',
}

STYLE_ICON_MAP = {
    QStyle.StandardPixmap.SP_ArrowBack: "arrow-left",
    QStyle.StandardPixmap.SP_ArrowDown: "chevron-down",
    QStyle.StandardPixmap.SP_ArrowForward: "arrow-right",
    QStyle.StandardPixmap.SP_ArrowLeft: "arrow-left",
    QStyle.StandardPixmap.SP_ArrowRight: "arrow-right",
    QStyle.StandardPixmap.SP_ArrowUp: "chevron-up",
    QStyle.StandardPixmap.SP_BrowserReload: "refresh",
    QStyle.StandardPixmap.SP_CommandLink: "command",
    QStyle.StandardPixmap.SP_ComputerIcon: "terminal-2",
    QStyle.StandardPixmap.SP_DialogApplyButton: "check",
    QStyle.StandardPixmap.SP_DialogCloseButton: "x",
    QStyle.StandardPixmap.SP_DialogOpenButton: "file-import",
    QStyle.StandardPixmap.SP_DialogSaveButton: "device-floppy",
    QStyle.StandardPixmap.SP_DirOpenIcon: "folder-open",
    QStyle.StandardPixmap.SP_DriveHDIcon: "database",
    QStyle.StandardPixmap.SP_FileDialogContentsView: "search",
    QStyle.StandardPixmap.SP_FileDialogDetailedView: "settings",
    QStyle.StandardPixmap.SP_FileDialogInfoView: "clock",
    QStyle.StandardPixmap.SP_FileDialogListView: "list",
    QStyle.StandardPixmap.SP_FileDialogNewFolder: "plus",
    QStyle.StandardPixmap.SP_FileIcon: "copy",
    QStyle.StandardPixmap.SP_MediaPause: "player-pause",
    QStyle.StandardPixmap.SP_MediaPlay: "player-play",
    QStyle.StandardPixmap.SP_MediaStop: "player-stop",
    QStyle.StandardPixmap.SP_MessageBoxInformation: "info-circle",
    QStyle.StandardPixmap.SP_TitleBarCloseButton: "x",
    QStyle.StandardPixmap.SP_TrashIcon: "trash",
}


def clone_profile(profile: SerialProfile) -> SerialProfile:
    return SerialProfile.from_dict(profile.to_dict())


def set_button_role(button: QPushButton, role: str) -> None:
    button.setProperty("role", role)
    button.style().unpolish(button)
    button.style().polish(button)
    button.update()


def standard_icon(
    pixmap: QStyle.StandardPixmap,
    size: int = 18,
    color: str = "#d4d4d4",
) -> QIcon:
    icon_name = STYLE_ICON_MAP.get(pixmap, "info-circle")
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
        <path stroke="none" d="M0 0h24v24H0z" fill="none" />
        {TABLER_ICON_PATHS[icon_name]}
    </svg>
    """
    pixmap_icon = QPixmap(size, size)
    pixmap_icon.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    painter = QPainter(pixmap_icon)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap_icon)


def set_button_icon(button, pixmap: QStyle.StandardPixmap, size: int = 16) -> None:
    button.setIcon(standard_icon(pixmap, size))
    button.setIconSize(QSize(size, size))


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
        set_button_icon(self.new_tab_button, QStyle.StandardPixmap.SP_FileDialogNewFolder, 17)
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

        for icon, tooltip, callback in (
            (QStyle.StandardPixmap.SP_CommandLink, "Quick commands", lambda: self._select_drawer_page(0)),
            (QStyle.StandardPixmap.SP_MediaPlay, "Scripts and shortcuts", lambda: self._select_drawer_page(1)),
            (QStyle.StandardPixmap.SP_DriveHDIcon, "Profiles", lambda: self._select_drawer_page(2)),
        ):
            button = QToolButton(self.drawer_rail)
            button.setObjectName("railButton")
            button.setFixedSize(36, 36)
            set_button_icon(button, icon, 18)
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
        set_button_icon(prev_button, QStyle.StandardPixmap.SP_ArrowBack)
        prev_button.clicked.connect(self.find_previous)
        next_button = QPushButton("Next", self.search_bar)
        set_button_icon(next_button, QStyle.StandardPixmap.SP_ArrowForward)
        next_button.clicked.connect(self.find_next)
        close_search = QPushButton("X", self.search_bar)
        set_button_icon(close_search, QStyle.StandardPixmap.SP_DialogCloseButton)
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
        set_button_icon(send_button, QStyle.StandardPixmap.SP_ArrowForward)
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

    def _drawer_title(self, text: str, parent: QWidget) -> QLabel:
        title = QLabel(text, parent)
        title.setObjectName("drawerTitle")
        return title

    def _drawer_section(self, text: str, parent: QWidget) -> QLabel:
        section = QLabel(text.upper(), parent)
        section.setObjectName("drawerSection")
        return section

    def _drawer_action(
        self,
        text: str,
        icon: QStyle.StandardPixmap,
        callback,
        parent: QWidget,
        *,
        role: str = "drawerAction",
    ) -> QPushButton:
        button = QPushButton(text, parent)
        button.setObjectName("drawerActionButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        set_button_icon(button, icon)
        set_button_role(button, role)
        button.clicked.connect(callback)
        return button

    def _build_quick_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = self._drawer_title("Quick Send", page)
        self.quick_list = QListWidget(page)
        self.quick_list.itemDoubleClicked.connect(lambda _: self.send_selected_quick_command())
        send = self._drawer_action("Send Selected", QStyle.StandardPixmap.SP_ArrowForward, self.send_selected_quick_command, page, role="drawerPrimary")
        add = self._drawer_action("Add", QStyle.StandardPixmap.SP_FileDialogNewFolder, self.host.add_quick_command, page)
        edit = self._drawer_action("Edit", QStyle.StandardPixmap.SP_FileDialogDetailedView, lambda: self.host.edit_quick_command(self.selected_quick_command_id()), page)
        delete = self._drawer_action("Delete", QStyle.StandardPixmap.SP_TrashIcon, lambda: self.host.delete_quick_command(self.selected_quick_command_id()), page, role="drawerDanger")
        up = self._drawer_action("Move Up", QStyle.StandardPixmap.SP_ArrowUp, lambda: self.host.move_quick_command(self.selected_quick_command_id(), -1), page)
        down = self._drawer_action("Move Down", QStyle.StandardPixmap.SP_ArrowDown, lambda: self.host.move_quick_command(self.selected_quick_command_id(), 1), page)
        layout.addWidget(title)
        layout.addWidget(self._drawer_section("Saved Commands", page))
        layout.addWidget(self.quick_list, 1)
        for row in ((send, add), (edit, delete), (up, down)):
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            for button in row:
                line.addWidget(button)
            layout.addLayout(line)
        return page

    def _build_scripts_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        title = self._drawer_title("Shortcuts", page)
        connect = self._drawer_action("Connect / Disconnect", QStyle.StandardPixmap.SP_ComputerIcon, self.toggle_connection, page, role="drawerPrimary")
        settings = self._drawer_action("Serial Settings", QStyle.StandardPixmap.SP_FileDialogDetailedView, lambda: self.open_connection_settings(), page)
        run = self._drawer_action("Run Command File", QStyle.StandardPixmap.SP_MediaPlay, self.run_script, page)
        stop = self._drawer_action("Stop Command File", QStyle.StandardPixmap.SP_MediaStop, self.stop_script, page)
        log = self._drawer_action("Start / Stop Log", QStyle.StandardPixmap.SP_DialogSaveButton, self.toggle_logging, page)
        clear = self._drawer_action("Clear Terminal", QStyle.StandardPixmap.SP_TrashIcon, self.clear_terminal, page, role="drawerDanger")
        pause = self._drawer_action("Pause / Resume Output", QStyle.StandardPixmap.SP_MediaPause, self.toggle_pause, page)
        save = self._drawer_action("Save Current Input", QStyle.StandardPixmap.SP_DialogSaveButton, self.save_current_input_as_quick_command, page)
        layout.addWidget(title)
        layout.addWidget(self._drawer_section("Session", page))
        layout.addWidget(connect)
        layout.addWidget(settings)
        layout.addSpacing(5)
        layout.addWidget(self._drawer_section("Scripts & Logs", page))
        layout.addWidget(run)
        layout.addWidget(stop)
        layout.addWidget(log)
        layout.addSpacing(5)
        layout.addWidget(self._drawer_section("Terminal", page))
        layout.addWidget(clear)
        layout.addWidget(pause)
        layout.addWidget(save)
        layout.addStretch(1)
        return page

    def _build_profiles_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = self._drawer_title("Profiles", page)
        self.profile_list = QListWidget(page)
        self.profile_list.itemDoubleClicked.connect(lambda _: self.apply_selected_profile())
        apply = self._drawer_action("Apply Profile", QStyle.StandardPixmap.SP_DialogApplyButton, self.apply_selected_profile, page, role="drawerPrimary")
        save = self._drawer_action("Save Current As Profile", QStyle.StandardPixmap.SP_DialogSaveButton, self.save_current_profile, page)
        rename = self._drawer_action("Rename", QStyle.StandardPixmap.SP_FileDialogDetailedView, lambda: self.host.rename_profile(self.selected_profile_name()), page)
        delete = self._drawer_action("Delete", QStyle.StandardPixmap.SP_TrashIcon, lambda: self.host.delete_profile(self.selected_profile_name()), page, role="drawerDanger")
        layout.addWidget(title)
        layout.addWidget(self._drawer_section("Available Profiles", page))
        layout.addWidget(self.profile_list, 1)
        layout.addWidget(apply)
        layout.addWidget(save)
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        line.addWidget(rename)
        line.addWidget(delete)
        layout.addLayout(line)
        return page

    def _select_drawer_page(self, index: int) -> None:
        if (
            not self.host.settings.drawer_collapsed
            and self.drawer_pages.currentIndex() == index
        ):
            self.host.set_drawer_collapsed(True)
            return
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

    def selected_profile_name(self) -> str:
        item = self.profile_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else self.profile_name

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
        selected_row = -1
        for name in self.host.settings.profiles:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.profile_list.addItem(item)
            if name == self.profile_name:
                selected_row = self.profile_list.count() - 1
        if selected_row >= 0:
            self.profile_list.setCurrentRow(selected_row)

    def refresh_ports(self) -> None:
        self._ports = self.serial_client.list_ports()
        self.host.set_status(f"{len(self._ports)} serial port(s) detected.")

    def apply_selected_profile(self) -> None:
        item = self.profile_list.currentItem()
        if not item:
            return
        profile_name = str(item.data(Qt.ItemDataRole.UserRole))
        self.host.activate_profile(profile_name, self)

    def save_current_profile(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save Profile", "Profile name", text=self.profile_name)
        if not accepted or not name.strip():
            return
        self.host.save_profile_as(name.strip(), self)

    def open_connection_settings(self, *, connect_after_accept: bool = True) -> bool:
        dialog = ConnectionSettingsDialog(self.profile, self.serial_client.list_ports(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            self.profile = dialog.profile()
        except ValueError as exc:
            QMessageBox.warning(self, "Serial Settings", str(exc))
            return False
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
        self._profile_dirty = False

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
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.show_tab_context_menu)
        self.setCentralWidget(self.tabs)

        self.footer = QLabel("Ready", self)
        self.footer.setObjectName("footer")
        self.statusBar().addPermanentWidget(self.footer, 1)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        self._add_action(file_menu, "New Tab", "Ctrl+T", lambda: self.add_session(prompt_settings=True), icon=QStyle.StandardPixmap.SP_FileDialogNewFolder)
        self._add_action(file_menu, "Duplicate Tab", "Ctrl+Shift+T", self.duplicate_current_session, icon=QStyle.StandardPixmap.SP_FileIcon)
        self._add_action(file_menu, "Close Tab", "Ctrl+W", self.close_current_session, icon=QStyle.StandardPixmap.SP_DialogCloseButton)
        file_menu.addSeparator()
        self._add_action(file_menu, "Run Command File", "Ctrl+R", lambda: self.with_session(lambda s: s.run_script()), icon=QStyle.StandardPixmap.SP_MediaPlay)
        self._add_action(file_menu, "Start / Stop Log", "Ctrl+L", lambda: self.with_session(lambda s: s.toggle_logging()), icon=QStyle.StandardPixmap.SP_DialogSaveButton)
        file_menu.addSeparator()
        self._add_action(file_menu, "Exit", "", self.close, icon=QStyle.StandardPixmap.SP_TitleBarCloseButton)

        edit_menu = self.menuBar().addMenu("Edit")
        self._add_action(edit_menu, "Copy", "Ctrl+Shift+C", lambda: self.with_session(lambda s: s.copy_selection()), icon=QStyle.StandardPixmap.SP_FileIcon)
        self._add_action(edit_menu, "Select All", "Ctrl+A", lambda: self.with_session(lambda s: s.select_all()), icon=QStyle.StandardPixmap.SP_FileDialogListView)
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Clear Terminal", "Ctrl+K", lambda: self.with_session(lambda s: s.clear_terminal()), icon=QStyle.StandardPixmap.SP_TrashIcon)
        self._add_action(edit_menu, "Search", "Ctrl+F", lambda: self.with_session(lambda s: s.show_search()), icon=QStyle.StandardPixmap.SP_FileDialogContentsView)

        view_menu = self.menuBar().addMenu("View")
        self._add_action(view_menu, "Toggle Drawer", "Ctrl+B", self.toggle_drawer, icon=QStyle.StandardPixmap.SP_FileDialogDetailedView)
        view_menu.addSeparator()
        self._add_action(view_menu, "Increase Font", "Ctrl+=", lambda: self.change_font_size(1), icon=QStyle.StandardPixmap.SP_ArrowUp)
        self._add_action(view_menu, "Decrease Font", "Ctrl+-", lambda: self.change_font_size(-1), icon=QStyle.StandardPixmap.SP_ArrowDown)
        view_menu.addSeparator()
        self.timestamps_action = self._add_action(view_menu, "Show Timestamps", "", self.toggle_timestamps, checkable=True, icon=QStyle.StandardPixmap.SP_FileDialogInfoView)
        self.timestamps_action.setChecked(self.settings.timestamps_enabled)
        self.wrap_action = self._add_action(view_menu, "Line Wrap", "", self.toggle_line_wrap, checkable=True, icon=QStyle.StandardPixmap.SP_FileDialogListView)
        self.wrap_action.setChecked(self.settings.line_wrap_enabled)
        view_menu.addSeparator()
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
        self._add_action(session_menu, "Rename Tab", "F2", self.rename_current_session, icon=QStyle.StandardPixmap.SP_FileDialogDetailedView)
        session_menu.addSeparator()
        self._add_action(session_menu, "Connect / Disconnect", "Ctrl+Enter", lambda: self.with_session(lambda s: s.toggle_connection()), icon=QStyle.StandardPixmap.SP_ComputerIcon)
        self._add_action(session_menu, "Pause / Resume Output", "Ctrl+P", lambda: self.with_session(lambda s: s.toggle_pause()), icon=QStyle.StandardPixmap.SP_MediaPause)

        serial_menu = self.menuBar().addMenu("Serial")
        self._add_action(serial_menu, "Serial Settings", "Ctrl+,", lambda: self.with_session(lambda s: s.open_connection_settings()), icon=QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self._add_action(serial_menu, "Refresh Ports", "F5", lambda: self.with_session(lambda s: s.refresh_ports()), icon=QStyle.StandardPixmap.SP_BrowserReload)
        serial_menu.addSeparator()
        self._add_action(serial_menu, "Save Profile", "", lambda: self.with_session(lambda s: s.save_current_profile()), icon=QStyle.StandardPixmap.SP_DialogSaveButton)
        self._add_action(serial_menu, "Rename Profile", "", lambda: self.with_session(lambda s: self.rename_profile(s.selected_profile_name())), icon=QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self._add_action(serial_menu, "Delete Profile", "", lambda: self.with_session(lambda s: self.delete_profile(s.selected_profile_name())), icon=QStyle.StandardPixmap.SP_TrashIcon)
        serial_menu.addSeparator()
        self._add_action(serial_menu, "Import Profiles", "", self.import_profiles, icon=QStyle.StandardPixmap.SP_DialogOpenButton)
        self._add_action(serial_menu, "Export Profiles", "", self.export_profiles, icon=QStyle.StandardPixmap.SP_DialogSaveButton)

        tools_menu = self.menuBar().addMenu("Tools")
        self._add_action(tools_menu, "Send Selected Quick Command", "", lambda: self.with_session(lambda s: s.send_selected_quick_command()), icon=QStyle.StandardPixmap.SP_ArrowForward)
        tools_menu.addSeparator()
        self._add_action(tools_menu, "Add Quick Command", "", self.add_quick_command, icon=QStyle.StandardPixmap.SP_FileDialogNewFolder)
        self._add_action(tools_menu, "Edit Selected Quick Command", "", lambda: self.with_session(lambda s: self.edit_quick_command(s.selected_quick_command_id())), icon=QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self._add_action(tools_menu, "Delete Selected Quick Command", "", lambda: self.with_session(lambda s: self.delete_quick_command(s.selected_quick_command_id())), icon=QStyle.StandardPixmap.SP_TrashIcon)

        help_menu = self.menuBar().addMenu("Help")
        self._add_action(help_menu, "About", "", self.show_about, icon=QStyle.StandardPixmap.SP_MessageBoxInformation)

    def _add_action(
        self,
        menu,
        text: str,
        shortcut: str,
        callback,
        *,
        checkable: bool = False,
        icon: QStyle.StandardPixmap | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if icon is not None:
            action.setIcon(standard_icon(icon))
        if shortcut:
            action.setShortcut(shortcut)
        action.setCheckable(checkable)
        action.triggered.connect(lambda _checked=False: callback())
        menu.addAction(action)
        return action

    def _add_context_action(
        self,
        menu: QMenu,
        text: str,
        callback,
        *,
        icon: QStyle.StandardPixmap | None = None,
        enabled: bool = True,
    ) -> QAction:
        action = QAction(text, self)
        if icon is not None:
            action.setIcon(standard_icon(icon))
        action.setEnabled(enabled)
        action.triggered.connect(lambda _checked=False: callback())
        menu.addAction(action)
        return action

    def show_tab_context_menu(self, position) -> None:
        tab_bar = self.tabs.tabBar()
        index = tab_bar.tabAt(position)
        menu = self.build_tab_context_menu(index)
        menu.exec(tab_bar.mapToGlobal(position))

    def build_tab_context_menu(self, index: int) -> QMenu:
        menu = QMenu(self)
        if index < 0:
            self._add_context_action(
                menu,
                "New Tab",
                lambda: self.add_session(prompt_settings=True),
                icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
            )
            return menu

        session = self.session_at(index)
        is_connected = bool(session and session.serial_client.is_connected)
        menu.setTitle(session.title if session else self.tabs.tabText(index))
        self._add_context_action(
            menu,
            "New Tab",
            lambda: self.add_session(prompt_settings=True),
            icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
        )
        self._add_context_action(
            menu,
            "Duplicate Tab",
            lambda tab_index=index: self.duplicate_session(tab_index),
            icon=QStyle.StandardPixmap.SP_FileIcon,
        )
        self._add_context_action(
            menu,
            "Rename Tab",
            lambda tab_index=index: self.rename_session(tab_index),
            icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
        )
        menu.addSeparator()
        self._add_context_action(
            menu,
            "Serial Settings",
            lambda tab_index=index: self.open_session_settings(tab_index),
            icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
            enabled=session is not None,
        )
        self._add_context_action(
            menu,
            "Disconnect" if is_connected else "Connect",
            lambda tab_index=index: self.toggle_session_connection(tab_index),
            icon=QStyle.StandardPixmap.SP_ComputerIcon,
            enabled=session is not None,
        )
        self._add_context_action(
            menu,
            "Search",
            lambda tab_index=index: self.show_session_search(tab_index),
            icon=QStyle.StandardPixmap.SP_FileDialogContentsView,
            enabled=session is not None,
        )
        self._add_context_action(
            menu,
            "Clear Terminal",
            lambda tab_index=index: self.clear_session_terminal(tab_index),
            icon=QStyle.StandardPixmap.SP_TrashIcon,
            enabled=session is not None,
        )
        menu.addSeparator()
        self._add_context_action(
            menu,
            "Close Tab",
            lambda tab_index=index: self.close_session(tab_index),
            icon=QStyle.StandardPixmap.SP_DialogCloseButton,
        )
        self._add_context_action(
            menu,
            "Close Other Tabs",
            lambda tab_index=index: self.close_other_sessions(tab_index),
            icon=QStyle.StandardPixmap.SP_TitleBarCloseButton,
            enabled=self.tabs.count() > 1,
        )
        self._add_context_action(
            menu,
            "Close Tabs to the Right",
            lambda tab_index=index: self.close_sessions_to_right(tab_index),
            icon=QStyle.StandardPixmap.SP_ArrowRight,
            enabled=index < self.tabs.count() - 1,
        )
        return menu

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
        index = self.tabs.addTab(
            session,
            standard_icon(QStyle.StandardPixmap.SP_ComputerIcon),
            session.tab_title,
        )
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
        self.duplicate_session(self.tabs.currentIndex())

    def duplicate_session(self, index: int) -> None:
        session = self.session_at(index)
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
        if index < 0 or index >= self.tabs.count():
            return
        session = self.tabs.widget(index)
        if isinstance(session, TerminalSessionWidget):
            session.shutdown()
        self.tabs.removeTab(index)
        if session:
            session.deleteLater()
        if self.tabs.count() == 0:
            self.add_session()
        self.save_settings()

    def close_other_sessions(self, index: int) -> None:
        target = self.session_at(index)
        if not target:
            return
        for tab_index in range(self.tabs.count() - 1, -1, -1):
            if self.tabs.widget(tab_index) is not target:
                self.close_session(tab_index)
        current_index = self.tabs.indexOf(target)
        if current_index >= 0:
            self.tabs.setCurrentIndex(current_index)
        self.save_settings()

    def close_sessions_to_right(self, index: int) -> None:
        if index < 0 or index >= self.tabs.count() - 1:
            return
        for tab_index in range(self.tabs.count() - 1, index, -1):
            self.close_session(tab_index)
        self.tabs.setCurrentIndex(min(index, self.tabs.count() - 1))
        self.save_settings()

    def rename_current_session(self) -> None:
        self.rename_session(self.tabs.currentIndex())

    def rename_session(self, index: int) -> None:
        session = self.session_at(index)
        if not session:
            return
        self.tabs.setCurrentIndex(index)
        title, accepted = QInputDialog.getText(self, "Rename Tab", "Tab name", text=session.title)
        if accepted and title.strip():
            session.title = title.strip()
            self.update_tab_titles()
            self.save_settings()

    def current_session(self) -> TerminalSessionWidget | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, TerminalSessionWidget) else None

    def session_at(self, index: int) -> TerminalSessionWidget | None:
        widget = self.tabs.widget(index)
        return widget if isinstance(widget, TerminalSessionWidget) else None

    def open_session_settings(self, index: int) -> None:
        session = self.session_at(index)
        if session:
            self.tabs.setCurrentIndex(index)
            session.open_connection_settings(connect_after_accept=True)

    def toggle_session_connection(self, index: int) -> None:
        session = self.session_at(index)
        if session:
            self.tabs.setCurrentIndex(index)
            session.toggle_connection()

    def show_session_search(self, index: int) -> None:
        session = self.session_at(index)
        if session:
            self.tabs.setCurrentIndex(index)
            session.show_search()

    def clear_session_terminal(self, index: int) -> None:
        session = self.session_at(index)
        if session:
            self.tabs.setCurrentIndex(index)
            session.clear_terminal()

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
        profile = self.settings.profiles.get(name)
        if not profile:
            profile = next(iter(self.settings.profiles.values()))
        return clone_profile(profile.serial)

    def active_profile_snapshot(self, serial: SerialProfile | None = None) -> UserProfile:
        return self.settings.capture_user_profile(serial)

    def save_profile_as(self, name: str, session: TerminalSessionWidget) -> None:
        session.profile_name = name
        self.settings.active_profile = name
        self.settings.profiles[name] = self.active_profile_snapshot(session.profile)
        self._profile_dirty = False
        self.refresh_profiles_everywhere()
        self.update_tab_titles()
        self.save_settings(profile_sync=False)

    def rename_profile(self, old_name: str) -> None:
        old_name = old_name.strip()
        if not old_name or old_name not in self.settings.profiles:
            return
        if old_name == DEFAULT_PROFILE_NAME:
            QMessageBox.information(
                self,
                "Rename Profile",
                "The Default profile cannot be renamed.",
            )
            return
        new_name, accepted = QInputDialog.getText(
            self,
            "Rename Profile",
            "Profile name",
            text=old_name,
        )
        new_name = new_name.strip()
        if not accepted or not new_name or new_name == old_name:
            return
        if new_name in self.settings.profiles:
            QMessageBox.warning(
                self,
                "Rename Profile",
                f"A profile named '{new_name}' already exists.",
            )
            return
        self.settings.profiles[new_name] = self.settings.profiles.pop(old_name)
        if self.settings.active_profile == old_name:
            self.settings.active_profile = new_name
        for session in self.iter_sessions():
            if session.profile_name == old_name:
                session.profile_name = new_name
        self.refresh_profiles_everywhere()
        self.update_tab_titles()
        self.save_settings(profile_sync=False)

    def delete_profile(self, name: str) -> None:
        name = name.strip()
        if not name or name not in self.settings.profiles:
            return
        if name == DEFAULT_PROFILE_NAME:
            QMessageBox.information(
                self,
                "Delete Profile",
                "The Default profile cannot be deleted.",
            )
            return
        result = QMessageBox.question(
            self,
            "Delete Profile",
            f"Delete profile '{name}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        was_active = self.settings.active_profile == name
        self.settings.profiles.pop(name)
        for session in self.iter_sessions():
            if session.profile_name == name:
                session.profile_name = DEFAULT_PROFILE_NAME
        self._profile_dirty = False
        if was_active:
            self.activate_profile(DEFAULT_PROFILE_NAME)
        else:
            self.refresh_profiles_everywhere()
            self.save_settings(profile_sync=False)

    def save_active_profile_changes(self) -> None:
        session = self.current_session()
        serial = session.profile if session else None
        self.settings.profiles[self.settings.active_profile] = self.active_profile_snapshot(serial)
        self._profile_dirty = False
        self.refresh_profiles_everywhere()
        self.save_settings(profile_sync=False)

    def activate_profile(self, name: str, session: TerminalSessionWidget | None = None) -> None:
        if name not in self.settings.profiles:
            return
        if not self.confirm_unsaved_profile_changes():
            return
        target = session or self.current_session()
        profile = self.settings.profiles[name]
        self.settings.apply_user_profile(name)
        self.history_catalog = HistoryStore(self.settings.command_history)
        if target:
            target.profile_name = name
            target.profile = clone_profile(profile.serial)
            target._update_line_ending_label()
            target._update_connection_ui(target.serial_client.is_connected)
        self.apply_profile_preferences_to_ui()
        self._profile_dirty = False
        self.save_settings(profile_sync=False)

    def apply_profile_preferences_to_ui(self) -> None:
        self.apply_theme(self.settings.theme, save=False)
        if hasattr(self, "timestamps_action"):
            self.timestamps_action.setChecked(self.settings.timestamps_enabled)
        if hasattr(self, "wrap_action"):
            self.wrap_action.setChecked(self.settings.line_wrap_enabled)
        for session in self.iter_sessions():
            session.history_store = HistoryStore(self.history_catalog.all_commands())
            session.apply_settings()
            session.apply_drawer_state(
                self.settings.drawer_collapsed,
                self.settings.drawer_width,
            )
            session.refresh_quick_commands()
            session.refresh_profiles()
        self.update_tab_titles()
        self.sync_status_from_current_session()

    def update_profile_state(self, serial: SerialProfile | None = None) -> None:
        snapshot = self.active_profile_snapshot(serial)
        if self.settings.active_profile == DEFAULT_PROFILE_NAME:
            self.settings.profiles[DEFAULT_PROFILE_NAME] = snapshot
            self._profile_dirty = False
            return
        stored = self.settings.profiles.get(self.settings.active_profile)
        self._profile_dirty = stored is not None and snapshot.to_dict() != stored.to_dict()

    def confirm_unsaved_profile_changes(self) -> bool:
        if not self._profile_dirty or self.settings.active_profile == DEFAULT_PROFILE_NAME:
            return True
        result = QMessageBox.question(
            self,
            "Save Profile Changes?",
            f"Save changes to profile '{self.settings.active_profile}'?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Save:
            self.save_active_profile_changes()
        else:
            self._profile_dirty = False
        return True

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
            fallback = self.active_profile_snapshot(self.current_session().profile if self.current_session() else None)
            for name, data in profiles.items():
                self.settings.profiles[str(name)] = UserProfile.from_dict(data, fallback)
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Import Profiles", str(exc))
            return
        self.refresh_profiles_everywhere()
        self.save_settings(profile_sync=False)

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
        QMessageBox.information(self, "About ComPort Zone", "ComPort Zone\nCOM-port terminal for Windows device workflows.")

    def apply_theme(self, name: str, *, save: bool = True) -> None:
        self.theme = THEMES.get(name, THEMES["VS Code Dark"])
        self.settings.theme = self.theme.name
        self.setStyleSheet(self._stylesheet(self.theme))
        for theme_name, action in getattr(self, "theme_actions", {}).items():
            action.setChecked(theme_name == self.theme.name)
        if save:
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
            padding-left: 4px;
        }}
        QMenuBar::item {{
            padding: 6px 11px;
            border-radius: 6px;
        }}
        QMenuBar::item:selected, QMenu {{
            background: {theme.surface_alt};
        }}
        QMenu {{
            border: 1px solid {theme.border};
            border-radius: 8px;
            padding: 6px;
        }}
        QMenu::item {{
            padding: 7px 30px 7px 24px;
            border-radius: 6px;
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
            padding: 8px 16px;
            min-width: 130px;
            border: 1px solid transparent;
            border-top-left-radius: 9px;
            border-top-right-radius: 9px;
            margin: 5px 2px 0 2px;
        }}
        QTabBar::tab:selected {{
            background: {theme.window};
            border-top: 2px solid {theme.accent};
            border-left: 1px solid {theme.border};
            border-right: 1px solid {theme.border};
        }}
        QTabBar::tab:hover:!selected {{
            background: {theme.surface};
        }}
        QToolButton#newTabButton {{
            background: {theme.surface_alt};
            color: {theme.text};
            border: 1px solid {theme.border};
            border-radius: 8px;
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
            border-right: 1px solid {theme.border};
        }}
        QToolButton#railButton {{
            background: transparent;
            color: {theme.text};
            border: 1px solid transparent;
            border-radius: 10px;
        }}
        QToolButton#railButton:hover {{
            background: {theme.surface};
            border-color: {theme.border};
        }}
        QToolButton#railButton:pressed {{
            background: {theme.accent_soft};
            border-color: {theme.accent};
        }}
        QFrame#drawerPanel {{
            background: {theme.window_alt};
        }}
        QLabel#drawerTitle {{
            font-weight: 650;
            color: {theme.text};
            padding: 1px 2px 4px 2px;
        }}
        QLabel#drawerSection {{
            color: {theme.muted};
            font-size: 8pt;
            font-weight: 700;
            padding: 9px 3px 1px 3px;
        }}
        QFrame#terminalColumn, QTextEdit#terminal {{
            background: {terminal_background};
            color: {theme.text};
            border: none;
        }}
        QFrame#commandBar, QFrame#searchBar {{
            background: {theme.window};
            border-top: 1px solid {theme.border};
        }}
        QLineEdit, QComboBox, QListWidget {{
            background: {theme.field};
            color: {theme.text};
            border: 1px solid {theme.border};
            border-radius: 8px;
            padding: 7px 9px;
            selection-background-color: {theme.search_highlight};
        }}
        QLineEdit:focus, QComboBox:focus, QListWidget:focus {{
            border-color: {theme.accent};
        }}
        QListWidget {{
            outline: none;
        }}
        QListWidget::item {{
            border-radius: 7px;
            padding: 7px 8px;
            margin: 2px;
        }}
        QListWidget::item:hover {{
            background: {theme.surface};
        }}
        QListWidget::item:selected {{
            background: {theme.accent_soft};
            color: {theme.text};
        }}
        QComboBox {{
            padding-right: 28px;
        }}
        QComboBox::drop-down {{
            width: 26px;
            border-left: 1px solid {theme.border};
            background: {theme.surface_alt};
            border-top-right-radius: 8px;
            border-bottom-right-radius: 8px;
        }}
        QPushButton {{
            background: {theme.surface_alt};
            color: {theme.text};
            border: 1px solid {theme.border};
            border-radius: 8px;
            padding: 7px 11px;
        }}
        QPushButton:hover {{
            background: {theme.surface};
            border-color: {theme.accent};
        }}
        QPushButton:pressed {{
            background: {theme.accent_soft};
        }}
        QPushButton[role="accent"] {{
            background: {theme.accent};
            color: #ffffff;
            border-color: {theme.accent};
        }}
        QPushButton#drawerActionButton {{
            text-align: left;
            border-radius: 9px;
            padding: 8px 10px;
        }}
        QPushButton#drawerActionButton[role="drawerPrimary"] {{
            background: {theme.chip};
            border-color: {theme.accent_soft};
        }}
        QPushButton#drawerActionButton[role="drawerPrimary"]:hover {{
            background: {theme.accent_soft};
            border-color: {theme.accent};
        }}
        QPushButton#drawerActionButton[role="drawerDanger"]:hover {{
            background: {theme.surface};
            border-color: {theme.error};
        }}
        QSplitter::handle {{
            background: {theme.border};
        }}
        QSplitter::handle:hover {{
            background: {theme.accent};
        }}
        QStatusBar {{
            background: {theme.accent};
            color: #ffffff;
        }}
        """

    def save_settings(self, *, profile_sync: bool = True) -> None:
        if self._loading:
            return
        session = self.current_session()
        if session:
            self.settings.active_profile = session.profile_name
        self.settings.command_history = self.history_catalog.all_commands()
        self.settings.window_width = self.width()
        self.settings.window_height = self.height()
        self.settings.restored_tabs = [session.to_state() for session in self.iter_sessions()]
        if profile_sync:
            self.update_profile_state(session.profile if session else None)
        if not self.settings_store.save(self.settings):
            self.set_status("Could not save settings to disk.")

    def closeEvent(self, event) -> None:
        if not self.confirm_unsaved_profile_changes():
            event.ignore()
            return
        for session in self.iter_sessions():
            session.shutdown()
        self.save_settings(profile_sync=False)
        super().closeEvent(event)


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("ComPort Zone")
    app.setFont(pick_ui_font())
    window = MainWindow()
    window.show()
    return app.exec()
