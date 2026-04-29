from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from queue import Empty
from threading import Event
from typing import cast

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QStringListModel, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QSplashScreen,
    QTextEdit,
    QStyle,
    QVBoxLayout,
    QWidget,
    QCompleter,
)

from .batch import (
    BatchParseError,
    parse_hex_payload,
)
from .command_editor import CommandEditorQuickActionCallbacks, CommandEditorSources, CommandFileEditorDialog
from .command_registry import CommandPaletteEntry, CommandRegistry
from .history import HistoryStore
from .icons import STYLE_ICON_MAP, TABLER_ICON_PATHS, set_button_icon, standard_icon
from .command_run_targets import CommandRunRequest, CommandRunTarget, CommandRunTargetService
from . import __version__
from .models import (
    AppSettings,
    CommandFileTabState,
    FLOW_CONTROL_OPTIONS,
    LINE_ENDINGS,
    QuickCommand,
    QuickFile,
    QUICK_COMMAND_SORT_MODES,
    QUICK_FILE_SORT_MODES,
    RECEIVE_DISPLAY_MODES,
    SerialProfile,
    TerminalSessionState,
    THEME_OPTIONS,
    utc_now_iso,
)
from . import quick_actions as _quick_actions
from .quick_actions_panel import (
    item_ids_in_order,
    populate_quick_command_list,
    populate_quick_file_list,
    row_for_item_id,
    selected_item_id,
)
from .quick_actions_sidebar import QuickActionsSidebar, QuickActionsSidebarActions
from .serial_core import SerialClient, SerialEvent, decode_serial_bytes, format_hex_bytes
from .settings_service import SettingsService
from .storage import SettingsStore, default_config_path
from .terminal_session_controller import TerminalSessionController
from .terminal_view import TerminalView
from .themes import THEMES, ThemePalette
from .ui.tab_workspace import TabWorkspaceController, TerminalTabWidget
from .widgets import ChevronComboBox, HistoryLineEdit
from .workspace_state import WorkspaceStateService

COMMON_BAUD_RATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]
TERMINAL_FONT_MIN = 8
TERMINAL_FONT_MAX = 24
DRAWER_COLLAPSED_WIDTH = 48
APP_USER_MODEL_ID = "ComPortZone.Terminal"
APP_ICON_PATH = Path(__file__).resolve().parent / "assets" / "comport-zone-icon.png"
APP_SETTINGS_EXPLANATION = (
    "App Settings JSON includes serial defaults, restored tabs, theme, terminal font, "
    "terminal display preferences, drawer and window state, command history, and last "
    "log/script paths.\n\n"
    "Quick Commands and Quick Files are not included here. Manage them with their own "
    "CSV import/export actions from the Quick Send and Quick Files drawer pages."
)

def clone_profile(profile: SerialProfile) -> SerialProfile:
    return SerialProfile.from_dict(profile.to_dict())


def set_button_role(button: QPushButton, role: str) -> None:
    button.setProperty("role", role)
    button.style().unpolish(button)
    button.style().polish(button)
    button.update()


def set_widget_state(widget: QWidget, state: str) -> None:
    widget.setProperty("state", state)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def app_icon() -> QIcon:
    icon = QIcon(str(APP_ICON_PATH))
    return icon if not icon.isNull() else standard_icon(QStyle.StandardPixmap.SP_ComputerIcon, 32)


def set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        # The icon still works in-window if Windows refuses the taskbar identity call.
        pass


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


def preferred_terminal_font_families() -> list[str]:
    families = sorted(QFontDatabase.families(), key=str.casefold)
    preferred = ["Cascadia Mono", "Cascadia Code", "Consolas", "JetBrains Mono"]
    preferred_lookup = {family.casefold(): family for family in families}
    ordered = [
        preferred_lookup[candidate.casefold()]
        for candidate in preferred
        if candidate.casefold() in preferred_lookup
    ]
    ordered.extend(family for family in families if family not in ordered)
    return ordered


def short_label(text: str, limit: int = 40) -> str:
    text = text.strip()
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


# Compatibility: older tests and plugin code import these helpers from app.py.
# Keep the names here, but delegate ownership to quick_actions.py.
SEND_MODES = _quick_actions.SEND_MODES
QUICK_COMMAND_CSV_FIELDS = _quick_actions.QUICK_COMMAND_CSV_FIELDS
QUICK_FILE_CSV_FIELDS = _quick_actions.QUICK_FILE_CSV_FIELDS
QuickActionLibrary = _quick_actions.QuickActionLibrary
QuickCommandImportOptions = _quick_actions.QuickCommandImportOptions
QuickCommandImportResult = _quick_actions.QuickCommandImportResult
QuickFileImportOptions = _quick_actions.QuickFileImportOptions
QuickFileImportResult = _quick_actions.QuickFileImportResult
quick_group_name = _quick_actions.quick_group_name
quick_command_csv_row = _quick_actions.quick_command_csv_row
quick_command_from_csv_row = _quick_actions.quick_command_from_csv_row
quick_file_display_text = _quick_actions.quick_file_display_text
quick_file_csv_row = _quick_actions.quick_file_csv_row
quick_file_from_csv_row = _quick_actions.quick_file_from_csv_row
quick_command_duplicate_key = _quick_actions.quick_command_duplicate_key
quick_file_duplicate_key = _quick_actions.quick_file_duplicate_key
clone_quick_command = _quick_actions.clone_quick_command
clone_quick_file = _quick_actions.clone_quick_file
merge_quick_commands = _quick_actions.merge_quick_commands
merge_quick_files = _quick_actions.merge_quick_files


class ConnectionStatusLabel(QLabel):
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class ConnectionSettingsDialog(QDialog):
    def __init__(
        self,
        profile: SerialProfile,
        ports: list[dict[str, str]],
        parent=None,
        *,
        ports_supplier: Callable[[], list[dict[str, str]]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Serial Settings")
        self.setMinimumWidth(420)
        self._ports_supplier = ports_supplier
        self._port_signature: tuple[tuple[str, str], ...] | None = None

        self.port_combo = ChevronComboBox(self)
        self.port_combo.setEditable(True)
        self._set_ports(ports, preferred_port=profile.port)

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

        self.port_refresh_timer = QTimer(self)
        self.port_refresh_timer.setInterval(1000)
        self.port_refresh_timer.timeout.connect(self.refresh_ports)
        if self._ports_supplier is not None:
            self.port_refresh_timer.start()
        self.finished.connect(lambda *_: self.port_refresh_timer.stop())

    def _port_label(self, port: dict[str, str]) -> str:
        device = str(port.get("device", "")).strip()
        description = str(port.get("description", "")).strip() or device
        return f"{device} - {description}" if description and description != device else device

    def _ports_signature_for(self, ports: list[dict[str, str]]) -> tuple[tuple[str, str], ...]:
        return tuple(
            (
                str(port.get("device", "")).strip(),
                str(port.get("description", "")).strip(),
            )
            for port in ports
        )

    def _current_port_text(self) -> str:
        return self.port_combo.currentText().split(" - ", 1)[0].strip()

    def _set_ports(self, ports: list[dict[str, str]], *, preferred_port: str = "") -> bool:
        signature = self._ports_signature_for(ports)
        if signature == self._port_signature and not preferred_port:
            return False
        self._port_signature = signature
        selected_port = preferred_port or self._current_port_text()
        popup_was_open = self.port_combo.view().isVisible()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for port in ports:
            device = str(port.get("device", "")).strip()
            if device:
                self.port_combo.addItem(self._port_label(port), device)
        if selected_port:
            index = self.port_combo.findData(selected_port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
            else:
                self.port_combo.setEditText(selected_port)
        self.port_combo.blockSignals(False)
        if popup_was_open and self.isVisible():
            QTimer.singleShot(0, self.port_combo.showPopup)
        return True

    def refresh_ports(self) -> bool:
        if self._ports_supplier is None:
            return False
        try:
            ports = self._ports_supplier()
        except Exception:
            return False
        return self._set_ports(ports)

    def profile(self) -> SerialProfile:
        port_value = self.port_combo.currentData()
        port = self._current_port_text() or str(port_value or "").strip()
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


class TerminalFontSettingsDialog(QDialog):
    def __init__(self, family: str, point_size: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Terminal Font Settings")
        self.setMinimumWidth(460)

        self.family_combo = ChevronComboBox(self)
        self.family_combo.setEditable(True)
        self.family_combo.addItem("System default monospace", "")
        for font_family in preferred_terminal_font_families():
            self.family_combo.addItem(font_family, font_family)
        if family:
            index = self.family_combo.findData(family)
            if index >= 0:
                self.family_combo.setCurrentIndex(index)
            else:
                self.family_combo.setEditText(family)

        self.size_input = QSpinBox(self)
        self.size_input.setRange(TERMINAL_FONT_MIN, TERMINAL_FONT_MAX)
        self.size_input.setValue(max(TERMINAL_FONT_MIN, min(point_size, TERMINAL_FONT_MAX)))
        self.size_input.setSuffix(" pt")

        reset = QPushButton("Use Default", self)
        set_button_icon(reset, QStyle.StandardPixmap.SP_BrowserReload)
        reset.clicked.connect(self.reset_defaults)

        self.preview = QTextEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(92)
        self.preview.setPlainText("SYS Connected\nTX> *IDN?\nComPort Zone,Terminal,0.0.2")

        self.family_combo.currentTextChanged.connect(self.update_preview)
        self.size_input.valueChanged.connect(self.update_preview)

        form = QFormLayout()
        form.addRow("Family", self.family_combo)
        form.addRow("Size", self.size_input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(reset)
        layout.addWidget(self.preview)
        layout.addWidget(buttons)
        self.update_preview()

    def reset_defaults(self) -> None:
        self.family_combo.setCurrentIndex(0)
        self.size_input.setValue(10)

    def selected_family(self) -> str:
        data = self.family_combo.currentData()
        if data is not None:
            return str(data)
        return self.family_combo.currentText().strip()

    def selected_size(self) -> int:
        return int(self.size_input.value())

    def update_preview(self) -> None:
        self.preview.setFont(pick_mono_font(self.selected_size(), self.selected_family()))


class QuickCommandDialog(QDialog):
    def __init__(self, command: QuickCommand | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quick Command")
        self.setMinimumWidth(420)
        command = command or QuickCommand()

        self.label_input = QLineEdit(command.label, self)
        self.command_input = QLineEdit(command.command, self)
        self.description_input = QTextEdit(command.description, self)
        self.description_input.setPlaceholderText("Optional note shown when hovering this quick command")
        self.description_input.setFixedHeight(76)
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
        form.addRow("Description", self.description_input)
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
            description=self.description_input.toPlainText().strip(),
            send_mode=self.mode_combo.currentText(),
            group=self.group_input.text().strip() or "General",
            line_ending_override=str(self.line_ending_combo.currentData() or ""),
            created_at=self._original.created_at or now,
            updated_at=now,
        )


class QuickFileDialog(QDialog):
    def __init__(self, quick_file: QuickFile | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quick File")
        self.setMinimumWidth(520)
        self._original = quick_file or QuickFile()

        self.label_input = QLineEdit(self._original.label, self)
        self.label_input.setPlaceholderText("Optional display name")
        self.path_input = QLineEdit(self._original.path, self)
        self.path_input.setPlaceholderText("Path to command file")
        browse = QPushButton("Browse", self)
        set_button_icon(browse, QStyle.StandardPixmap.SP_DialogOpenButton)
        browse.clicked.connect(self.browse_file)

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(6)
        path_row.addWidget(self.path_input, 1)
        path_row.addWidget(browse)

        form = QFormLayout()
        form.addRow("Label", self.label_input)
        form.addRow("File", path_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def browse_file(self) -> None:
        start_dir = self.path_input.text().strip() or str(Path.cwd())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Command File",
            start_dir,
            "Text Files (*.txt *.cmd *.scr);;All Files (*)",
        )
        if path:
            self.path_input.setText(path)

    def quick_file(self) -> QuickFile:
        now = utc_now_iso()
        path = self.path_input.text().strip()
        return QuickFile(
            id=self._original.id,
            label=self.label_input.text().strip() or Path(path).name,
            path=path,
            created_at=self._original.created_at or now,
            updated_at=now,
        )


class QuickCommandImportDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        message: str,
        default_replace: bool,
        default_skip_duplicates: bool,
        append_label: str = "Append imported commands",
        replace_label: str = "Replace current quick commands",
        duplicate_checkbox_text: str = "Skip duplicate commands",
        duplicate_hint_text: str = (
            "Duplicate detection ignores descriptions so imported notes can change without creating extra copies."
        ),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(430)

        intro = QLabel(message, self)
        intro.setWordWrap(True)

        self.behavior_combo = ChevronComboBox(self)
        self.behavior_combo.addItem(append_label, False)
        self.behavior_combo.addItem(replace_label, True)
        self.behavior_combo.setCurrentIndex(1 if default_replace else 0)

        self.skip_duplicates = QCheckBox(duplicate_checkbox_text, self)
        self.skip_duplicates.setToolTip(
            "Duplicates use group, title, command text, and send mode. Descriptions are ignored."
        )
        self.skip_duplicates.setChecked(default_skip_duplicates)

        duplicate_hint = QLabel(duplicate_hint_text, self)
        duplicate_hint.setWordWrap(True)
        duplicate_hint.setObjectName("dialogHint")

        form = QFormLayout()
        form.addRow("Behavior", self.behavior_combo)
        form.addRow("", self.skip_duplicates)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(duplicate_hint)
        layout.addWidget(buttons)

    def options(self) -> QuickCommandImportOptions:
        return QuickCommandImportOptions(
            replace_existing=bool(self.behavior_combo.currentData()),
            skip_duplicates=self.skip_duplicates.isChecked(),
        )


class AppSettingsTransferDialog(QDialog):
    def __init__(self, mode: str = "choose", parent=None) -> None:
        super().__init__(parent)
        self.mode = mode if mode in {"choose", "import", "export"} else "choose"
        self.selected_action = ""
        titles = {
            "choose": "App Settings Import / Export",
            "import": "Import App Settings",
            "export": "Export App Settings",
        }
        self.setWindowTitle(titles[self.mode])
        self.setMinimumWidth(520)

        heading = QLabel(titles[self.mode], self)
        heading.setObjectName("dialogTitle")

        intro_text = {
            "choose": "Choose whether to import or export app-level preferences.",
            "import": "Import app-level preferences from a JSON file.",
            "export": "Export app-level preferences to a JSON file.",
        }[self.mode]
        intro = QLabel(intro_text, self)
        intro.setWordWrap(True)

        explanation = QLabel(APP_SETTINGS_EXPLANATION, self)
        explanation.setObjectName("dialogHint")
        explanation.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        if self.mode in {"choose", "import"}:
            import_button = buttons.addButton(
                "Import App Settings...",
                QDialogButtonBox.ButtonRole.ActionRole,
            )
            import_button.clicked.connect(lambda: self._accept_action("import"))
        if self.mode in {"choose", "export"}:
            export_button = buttons.addButton(
                "Export App Settings...",
                QDialogButtonBox.ButtonRole.ActionRole,
            )
            export_button.clicked.connect(lambda: self._accept_action("export"))
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(intro)
        layout.addWidget(explanation)
        layout.addWidget(buttons)

    def _accept_action(self, action: str) -> None:
        self.selected_action = action
        self.accept()


class CommandPaletteDialog(QDialog):
    def __init__(self, host: "MainWindow") -> None:
        super().__init__(host)
        self.host = host
        self.entries = host.command_palette_entries()
        self.filtered_entries: list[CommandPaletteEntry] = []
        self._executed = False
        self.setObjectName("commandPalette")
        self.setWindowTitle("Command Palette")
        self.setMinimumSize(560, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("commandPaletteSearch")
        self.search_input.setPlaceholderText("Type a command, action, or tab name")
        self.search_input.textChanged.connect(self.refresh_results)
        self.search_input.returnPressed.connect(self.execute_current)
        self.search_input.installEventFilter(self)

        self.result_list = QListWidget(self)
        self.result_list.setObjectName("commandPaletteList")
        self.result_list.itemActivated.connect(lambda _: self.execute_current())
        self.result_list.itemDoubleClicked.connect(lambda _: self.execute_current())

        hint = QLabel("Enter runs the selected command. Esc closes the palette.", self)
        hint.setObjectName("commandPaletteHint")

        layout.addWidget(self.search_input)
        layout.addWidget(self.result_list, 1)
        layout.addWidget(hint)
        self.refresh_results()
        QTimer.singleShot(0, self.search_input.setFocus)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.search_input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Down:
                self.move_selection(1)
                return True
            if event.key() == Qt.Key.Key_Up:
                self.move_selection(-1)
                return True
        return super().eventFilter(watched, event)

    def refresh_results(self) -> None:
        terms = [term for term in self.search_input.text().casefold().split() if term]
        self.filtered_entries = [
            entry
            for entry in self.entries
            if all(term in entry.searchable_text() for term in terms)
        ]
        self.result_list.clear()
        for index, entry in enumerate(self.filtered_entries):
            text = entry.title if not entry.subtitle else f"{entry.title}\n{entry.subtitle}"
            item = QListWidgetItem(text)
            if entry.icon is not None:
                item.setIcon(standard_icon(entry.icon))
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(entry.subtitle)
            item.setSizeHint(QSize(0, 48 if entry.subtitle else 34))
            self.result_list.addItem(item)
        if self.result_list.count() > 0:
            self.result_list.setCurrentRow(0)

    def move_selection(self, direction: int) -> None:
        count = self.result_list.count()
        if count == 0:
            return
        row = self.result_list.currentRow()
        if row < 0:
            row = 0
        self.result_list.setCurrentRow(max(0, min(count - 1, row + direction)))

    def execute_current(self) -> None:
        if self._executed:
            return
        if not self.filtered_entries:
            return
        item = self.result_list.currentItem() or self.result_list.item(0)
        if item is None:
            return
        index = int(item.data(Qt.ItemDataRole.UserRole))
        entry = self.filtered_entries[index]
        self._executed = True
        self.accept()
        QTimer.singleShot(0, entry.callback)


class BatchParameterPromptBridge(QObject):
    prompt_requested = Signal(object)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.parent_widget = parent
        self.prompt_requested.connect(self._handle_prompt)

    def prompt(self, name: str, line_number: int, line_text: str) -> str | None:
        request = {
            "name": name,
            "line_number": line_number,
            "line_text": line_text,
            "event": Event(),
            "accepted": False,
            "value": None,
        }
        self.prompt_requested.emit(request)
        request["event"].wait()
        if not request["accepted"]:
            return None
        return str(request["value"])

    def _handle_prompt(self, request: dict[str, object]) -> None:
        event = request["event"]
        try:
            name = str(request["name"])
            line_number = int(request["line_number"])
            line_text = str(request["line_text"])
            prompt = f"Line {line_number}:\n{line_text}\n\nEnter value for {name}:"
            while True:
                value, accepted = QInputDialog.getText(
                    self.parent_widget,
                    "Command File Parameter",
                    prompt,
                )
                if not accepted:
                    request["accepted"] = False
                    return
                if not value.strip():
                    QMessageBox.warning(
                        self.parent_widget,
                        "Command File Parameter",
                        f"Value for {name} cannot be empty.",
                    )
                    continue
                request["value"] = value
                request["accepted"] = True
                return
        finally:
            event.set()


class TerminalSessionWidget(QWidget):
    def __init__(self, host: "MainWindow", session_id: int, state: TerminalSessionState) -> None:
        super().__init__(host)
        self.host = host
        self.session_id = session_id
        self.title = state.title or f"Terminal {session_id}"
        self.title_is_custom = state.title_is_custom or (
            bool(self.title)
            and not self.title.startswith("Terminal")
            and self.title != "No port"
        )
        self.profile = clone_profile(state.serial) if state.serial is not None else host.default_serial_profile()
        self.parameter_prompt_bridge = BatchParameterPromptBridge(self)
        self.controller = TerminalSessionController(
            self.profile,
            history_commands=host.history_catalog.all_commands(),
            parameter_prompt=self.parameter_prompt_bridge.prompt,
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
        self.apply_drawer_state(host.settings.drawer_collapsed, host.settings.drawer_width)
        self._update_connection_ui(False)

        self.event_timer = QTimer(self)
        self.event_timer.timeout.connect(self._drain_events)
        self.event_timer.start(50)

    @property
    def tab_title(self) -> str:
        if self.title_is_custom:
            return self.title
        if self.profile.port:
            return self.profile.port
        return "No port"

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
        return TerminalSessionState(
            title=self.title,
            title_is_custom=self.title_is_custom,
            transport_kind="serial",
            transport_profile=self.profile.to_dict(),
            serial=clone_profile(self.profile),
            connected_on_launch=self._connected or self.serial_client.is_connected,
            terminal_text=self.terminal.toPlainText(),
            command_draft=self.command_input.text(),
            send_mode=self.mode_combo.currentText(),
        )

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
        self.terminal.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.terminal.customContextMenuRequested.connect(self.show_terminal_context_menu)
        self.terminal_view = TerminalView(self.terminal, self.search_count)

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
        self.command_input = HistoryLineEdit(self.command_bar)
        self.command_input.setPlaceholderText("Send command")
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
        command_layout.addWidget(self.rx_display_combo)
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
        if self.drawer_pages.count() == 0:
            return
        index = max(0, min(index, self.drawer_pages.count() - 1))
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

    def _receive_display_mode_changed(self) -> None:
        mode = self.rx_display_combo.currentData()
        if mode:
            self.host.set_receive_display_mode(str(mode))

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
        self._ports = self.list_ports_snapshot()
        self.host.set_status(f"{len(self._ports)} serial port(s) detected.")
        self._update_connection_ui(self.serial_client.is_connected, update_footer=False)

    def list_ports_snapshot(self) -> list[dict[str, str]]:
        self._ports = self.transport.list_ports()
        self._update_connection_ui(self.serial_client.is_connected, update_footer=False)
        return self._ports

    def open_connection_settings(self, *, connect_after_accept: bool = True) -> bool:
        dialog = ConnectionSettingsDialog(
            self.profile,
            self.list_ports_snapshot(),
            self,
            ports_supplier=self.list_ports_snapshot,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        try:
            self.profile = dialog.profile()
        except ValueError as exc:
            QMessageBox.warning(self, "Serial Settings", str(exc))
            return False
        self.controller.profile = self.profile
        self._update_line_ending_label()
        self._update_connection_ui(self.serial_client.is_connected)
        if connect_after_accept and self.profile.port:
            if self.serial_client.is_connected:
                self.serial_client.disconnect()
            self.host.set_status(f"Connecting to {self.profile.port}...")
            self.serial_client.connect(self.profile)
            self._update_connection_ui(self.serial_client.is_connected)
        self.host.save_settings()
        return True

    def toggle_connection(self) -> None:
        self.controller.profile = self.profile
        self.controller.toggle_connection(
            open_connection_settings=self.open_connection_settings,
            set_status=self.host.set_status,
            update_connection_ui=self._update_connection_ui,
            append_status=self._append_status,
            save_settings=self.host.save_settings,
        )

    def send_from_input(self) -> None:
        raw = self.command_input.text()
        try:
            sent = self.controller.send_input(
                raw,
                self.mode_combo.currentText(),
                record_command=self.host.record_command,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Send", str(exc))
            return
        if sent:
            self._clear_command_input_after_send()

    def _send_payload(self, raw: str, mode: str) -> None:
        self.controller.send_payload(raw, mode)

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

    def run_script_path(self, path: Path) -> None:
        try:
            script_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Run Command File", str(exc))
            return
        self.run_script_text(script_text, source_label=str(path), source_path=path)

    def run_script_text(self, script_text: str, *, source_label: str = "Editor buffer", source_path: Path | None = None) -> None:
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
            return
        if result.empty:
            QMessageBox.information(self, "Run Command File", "Command file is empty.")
            return
        if not result.started:
            return
        self.host.set_status(result.status_text)
        self.host.save_settings()

    def _collect_parameter_values(self, parameter_occurrences) -> tuple[dict[str, str], set[str]] | None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Command File Parameters")
        dialog.setMinimumSize(680, 460)

        intro = QLabel(
            "Review command-file parameters before starting. Fill values now, override defaults, or leave a field empty to ask while running.",
            dialog,
        )
        intro.setWordWrap(True)

        parameter_names: list[str] = []
        defaults: dict[str, str] = {}
        lines_by_parameter: dict[str, list[str]] = {}
        line_details: list[str] = []
        seen_line_details: set[tuple[int, str]] = set()
        for occurrence in parameter_occurrences:
            if occurrence.name not in parameter_names:
                parameter_names.append(occurrence.name)
            if occurrence.default is not None and occurrence.name not in defaults:
                defaults[occurrence.name] = occurrence.default
            line_entry = f"Line {occurrence.line_number}: {occurrence.line_text}"
            lines_by_parameter.setdefault(occurrence.name, [])
            if line_entry not in lines_by_parameter[occurrence.name]:
                lines_by_parameter[occurrence.name].append(line_entry)
            line_key = (occurrence.line_number, occurrence.line_text)
            if line_key not in seen_line_details:
                line_details.append(line_entry)
                seen_line_details.add(line_key)

        field_widget = QWidget(dialog)
        field_layout = QFormLayout(field_widget)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(8)
        inputs: dict[str, QLineEdit] = {}
        for name in parameter_names:
            input_field = QLineEdit(field_widget)
            input_field.setText(defaults.get(name, ""))
            input_field.setPlaceholderText("Ask while running")
            input_field.setClearButtonEnabled(True)
            input_field.setToolTip("\n".join(lines_by_parameter.get(name, [])))
            inputs[name] = input_field
            label = f"{name}"
            if name in defaults:
                label += " (default)"
            field_layout.addRow(label, input_field)

        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(field_widget)

        details = QTextEdit(dialog)
        details.setReadOnly(True)
        details.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        details.setMaximumHeight(120)
        details.setPlainText("\n".join(line_details))

        hint = QLabel(
            "Values are remembered for this run, so the same parameter name is asked only once. Empty default fields will prompt during execution instead of using the deleted default.",
            dialog,
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Start")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout = QVBoxLayout(dialog)
        layout.addWidget(intro)
        layout.addWidget(scroll, 1)
        layout.addWidget(QLabel("Parameterized lines:", dialog))
        layout.addWidget(details)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        values: dict[str, str] = {}
        ignored_defaults: set[str] = set()
        for name, input_field in inputs.items():
            value = input_field.text().strip()
            if value:
                values[name] = value
            else:
                ignored_defaults.add(name)
        return values, ignored_defaults

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
        menu = self.terminal.createStandardContextMenu(position)
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
        menu.exec(self.terminal.mapToGlobal(position))

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
        self._update_completion_model(text)

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
        decision = self.controller.handle_event(event)
        if decision.paused_count is not None:
            self.pause_label.setText(f"Paused ({decision.paused_count})")
            return
        if decision.event_to_render is not None:
            self._render_event(decision.event_to_render)
        if decision.status_message:
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
        if update_footer:
            self.host.set_status(self._status_text)

    def connection_state(self) -> str:
        if self._connected or self.serial_client.is_connected:
            return "connected"
        if self.serial_client.is_reconnecting:
            return "retrying"
        if not self.profile.port:
            return "no-port"
        if self._profile_port_missing():
            return "missing"
        return "closed"

    def connection_state_label(self) -> str:
        return {
            "connected": "Connected",
            "retrying": "Retrying",
            "missing": "Missing",
            "no-port": "No port",
            "closed": "Closed",
        }[self.connection_state()]

    def connection_action_text(self) -> str:
        return {
            "connected": "Disconnect",
            "retrying": "Stop Retry",
            "missing": "Connect",
            "no-port": "Set Port",
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
            return f"{self.profile.port} is not currently detected. Try to connect anyway or open Serial Settings."
        if state == "no-port":
            return "Choose a COM port and connect."
        return f"Connect to {profile_text}."

    def connection_status_text(self) -> str:
        if not self.profile.port:
            return "No port selected"
        framing = f"{self.profile.bytesize}{self.profile.parity}{self.profile.stopbits:g}"
        log_status = "Log on" if self.logger.enabled else "Log off"
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
        if not self.profile.port:
            return "No port"
        return f"{self.profile.port} {self.profile.baudrate} {self.profile.bytesize}{self.profile.parity}{self.profile.stopbits:g}"

    def _profile_port_missing(self) -> bool:
        ports = getattr(self, "_ports", [])
        known_ports = {str(port.get("device", "")) for port in ports}
        return bool(self.profile.port and self.profile.port not in known_ports)

    def _update_line_ending_label(self) -> None:
        self.line_ending_label.setText(self.profile.line_ending)
        self.host.update_connection_status(self)

    def shutdown(self) -> None:
        self.event_timer.stop()
        self.batch_runner.stop(emit_message=False)
        self.serial_client.disconnect()
        self.logger.close()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings_store = SettingsStore(default_config_path())
        self.settings_service = SettingsService(self.settings_store)
        self.settings = self.settings_service.load()
        self.workspace_state_service = WorkspaceStateService()
        self.command_registry = CommandRegistry(self)
        self.quick_actions = self._quick_action_library_from_settings()
        self.history_catalog = HistoryStore(self.settings.command_history)
        self.theme = THEMES.get(self.settings.theme, THEMES["VS Code Dark"])
        self._session_counter = 0
        self._loading = True

        self.setWindowTitle("ComPort Zone")
        self.setWindowIcon(app_icon())
        self.setFont(pick_ui_font())
        self.resize(self.settings.window_width, self.settings.window_height)
        self._build_ui()
        self.tab_workspace = TabWorkspaceController(
            self.tabs,
            terminal_type=TerminalSessionWidget,
            command_file_type=CommandFileEditorDialog,
            add_session=self.add_session,
            confirm_close_command_file_tab=self.confirm_close_command_file_tab,
            save_settings=self.save_settings,
        )
        self._build_menus()
        self.apply_theme(self.theme.name)
        self.restore_sessions()
        self._loading = False
        self.set_status("Ready")

    def _build_ui(self) -> None:
        self.tabs = TerminalTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.newTabRequested.connect(lambda: self.add_session(prompt_settings=True))
        self.tabs.currentChanged.connect(lambda _: self.sync_status_from_current_session())
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.show_tab_context_menu)
        self.setCentralWidget(self.tabs)

        self.footer = QLabel("Ready", self)
        self.footer.setObjectName("footer")
        self.connection_status_label = ConnectionStatusLabel("No port selected", self)
        self.connection_status_label.setObjectName("connectionStatus")
        self.connection_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.connection_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connection_status_label.doubleClicked.connect(self.open_current_connection_settings)
        self.connection_action_button = QPushButton("Set Port", self)
        self.connection_action_button.setObjectName("statusActionButton")
        self.connection_action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connection_action_button.clicked.connect(self.connection_status_action_clicked)
        self.version_label = QLabel(f"ComPort Zone v{__version__}", self)
        self.version_label.setObjectName("versionInfo")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.statusBar().addWidget(self.footer, 1)
        self.statusBar().addPermanentWidget(self.connection_status_label)
        self.statusBar().addPermanentWidget(self.connection_action_button)
        self.statusBar().addPermanentWidget(self.version_label)

    def _build_menus(self) -> None:
        self.file_menu = file_menu = self.menuBar().addMenu("File")
        self._add_registered_menu_section(file_menu, "file")

        self.edit_menu = edit_menu = self.menuBar().addMenu("Edit")
        self._add_registered_menu_section(edit_menu, "edit")

        self.view_menu = view_menu = self.menuBar().addMenu("View")
        view_actions = self._add_registered_menu_section(view_menu, "view")
        self.timestamps_action = view_actions["view.show_timestamps"]
        self.timestamps_action.setChecked(self.settings.timestamps_enabled)
        self.wrap_action = view_actions["view.line_wrap"]
        self.wrap_action.setChecked(self.settings.line_wrap_enabled)
        view_menu.addSeparator()
        self.theme_menu = theme_menu = view_menu.addMenu("Theme")
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

        self.session_menu = session_menu = self.menuBar().addMenu("Session")
        self._add_registered_menu_section(session_menu, "session")

        self.serial_menu = serial_menu = self.menuBar().addMenu("Serial")
        self._add_registered_menu_section(serial_menu, "serial")

        self.tools_menu = tools_menu = self.menuBar().addMenu("Tools")
        self._add_registered_action(tools_menu, "tools.command_palette")
        tools_menu.addSeparator()

        self.command_files_menu = command_files_menu = tools_menu.addMenu("Command Files")
        command_files_menu.setIcon(standard_icon(QStyle.StandardPixmap.SP_MediaPlay))
        self._add_registered_action(command_files_menu, "command_file.new")
        self._add_registered_action(command_files_menu, "command_file.open_editor")
        self.run_editor_menu = command_files_menu.addMenu("Run in Terminal")
        self.run_editor_menu.setIcon(standard_icon(QStyle.StandardPixmap.SP_ArrowForward))
        self.run_editor_menu.aboutToShow.connect(lambda menu=self.run_editor_menu: self.populate_run_editor_menu(menu))
        command_files_menu.addSeparator()
        self._add_registered_action(command_files_menu, "command_file.run")
        self._add_registered_action(command_files_menu, "command_file.stop")

        self.quick_commands_menu = quick_commands_menu = tools_menu.addMenu("Quick Commands")
        quick_commands_menu.setIcon(standard_icon(QStyle.StandardPixmap.SP_CommandLink))
        self._add_registered_menu_section(quick_commands_menu, "quick_commands")

        self.quick_files_menu = quick_files_menu = tools_menu.addMenu("Quick Files")
        quick_files_menu.setIcon(standard_icon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self._add_registered_menu_section(quick_files_menu, "quick_files")

        self.help_menu = help_menu = self.menuBar().addMenu("Help")
        self._add_registered_menu_section(help_menu, "help")

    def _add_registered_menu_section(self, menu, menu_key: str) -> dict[str, QAction]:
        actions: dict[str, QAction] = {}
        for command_id in self.command_registry.menu_items(menu_key):
            if command_id is None:
                menu.addSeparator()
                continue
            actions[command_id] = self._add_registered_action(menu, command_id)
        return actions

    def _add_registered_action(self, menu, command_id: str) -> QAction:
        spec = self.command_registry.spec(command_id)
        return self._add_action(
            menu,
            spec.menu_label(),
            spec.shortcut,
            spec.callback(self),
            checkable=spec.checkable,
            icon=spec.icon,
        )

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

    def _add_context_command_action(
        self,
        menu: QMenu,
        command_id: str,
        callback=None,
        *,
        text: str | None = None,
        enabled: bool = True,
    ) -> QAction:
        spec = self.command_registry.spec(command_id)
        return self._add_context_action(
            menu,
            text or spec.menu_label(),
            callback or spec.callback(self),
            icon=spec.icon,
            enabled=enabled,
        )

    def _quick_action_library_from_settings(self) -> QuickActionLibrary:
        return QuickActionLibrary(
            quick_commands=self.settings.quick_commands,
            quick_files=self.settings.quick_files,
            command_sort_mode=self.settings.quick_command_sort_mode,
            command_hidden_groups=self.settings.quick_command_hidden_groups,
            file_sort_mode=self.settings.quick_file_sort_mode,
        )

    def _sync_quick_actions_to_settings(self) -> None:
        self.settings.quick_commands = list(self.quick_actions.quick_commands)
        self.settings.quick_files = list(self.quick_actions.quick_files)
        self.settings.quick_command_sort_mode = self.quick_actions.command_sort_mode
        self.settings.quick_command_hidden_groups = list(self.quick_actions.command_hidden_groups)
        self.settings.quick_file_sort_mode = self.quick_actions.file_sort_mode

    def _refresh_quick_actions_from_settings(self) -> None:
        self.quick_actions = self._quick_action_library_from_settings()

    def show_command_palette(self) -> None:
        CommandPaletteDialog(self).exec()

    def command_editor_sources(self) -> CommandEditorSources:
        self._refresh_quick_actions_from_settings()
        return CommandEditorSources(
            history_commands=self.history_catalog.all_commands(),
            quick_commands=list(self.quick_actions.quick_commands),
            quick_command_hidden_groups=list(self.quick_actions.command_hidden_groups),
        )

    def quick_commands_snapshot(self) -> list[QuickCommand]:
        self._refresh_quick_actions_from_settings()
        return list(self.quick_actions.quick_commands)

    def visible_quick_commands_snapshot(self) -> list[QuickCommand]:
        self._refresh_quick_actions_from_settings()
        return self.quick_actions.visible_commands()

    def quick_files_snapshot(self) -> list[QuickFile]:
        self._refresh_quick_actions_from_settings()
        return list(self.quick_actions.quick_files)

    def visible_quick_files_snapshot(self) -> list[QuickFile]:
        self._refresh_quick_actions_from_settings()
        return self.quick_actions.visible_files()

    def quick_command_hidden_groups_snapshot(self) -> list[str]:
        self._refresh_quick_actions_from_settings()
        return list(self.quick_actions.command_hidden_groups)

    def quick_command_sort_mode_snapshot(self) -> str:
        self._refresh_quick_actions_from_settings()
        return self.quick_actions.command_sort_mode

    def quick_file_sort_mode_snapshot(self) -> str:
        self._refresh_quick_actions_from_settings()
        return self.quick_actions.file_sort_mode

    def editor_font(self) -> QFont:
        return pick_mono_font(
            max(TERMINAL_FONT_MIN, min(self.settings.terminal_font_size, TERMINAL_FONT_MAX)),
            self.settings.terminal_font_family,
        )

    def new_command_file_editor(self) -> None:
        self.add_command_file_tab()

    def open_command_file_editor(self, path: Path | str | None = None) -> None:
        if path is None:
            start_dir = self.settings.last_script_path or str(Path.cwd())
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Open Command File Editor",
                start_dir,
                "Text Files (*.txt *.cmd *.scr);;All Files (*)",
            )
            if not selected:
                return
            path = Path(selected)
        elif isinstance(path, str):
            path = Path(path)
        self.add_command_file_tab(path=path)

    def add_command_file_tab(self, path: Path | None = None, state: CommandFileTabState | None = None) -> CommandFileEditorDialog:
        editor = CommandFileEditorDialog(
            sources=self.command_editor_sources(),
            path=path,
            run_callback=None,
            font_change_callback=self.change_font_size,
            quick_files_supplier=self.quick_files_snapshot,
            quick_action_callbacks=CommandEditorQuickActionCallbacks(
                quick_commands_supplier=self.quick_commands_snapshot,
                visible_quick_commands_supplier=self.visible_quick_commands_snapshot,
                quick_command_groups_supplier=self.quick_command_group_names,
                quick_command_hidden_groups_supplier=self.quick_command_hidden_groups_snapshot,
                quick_command_sort_mode_supplier=self.quick_command_sort_mode_snapshot,
                set_quick_command_sort_mode=self.set_quick_command_sort_mode,
                set_quick_command_group_visible=self.set_quick_command_group_visible,
                show_all_quick_command_groups=self.show_all_quick_command_groups,
                hide_all_quick_command_groups=self.hide_all_quick_command_groups,
                add_quick_command=self.add_quick_command,
                edit_quick_command=self.edit_quick_command,
                delete_quick_command=self.delete_quick_command,
                move_quick_command=self.move_quick_command,
                reorder_quick_commands=lambda command_ids, selected_id="": self.reorder_quick_commands(
                    command_ids,
                    selected_id=selected_id,
                ),
                import_quick_commands_csv=self.import_quick_commands_csv,
                export_quick_commands_csv=self.export_quick_commands_csv,
                quick_files_supplier=self.quick_files_snapshot,
                visible_quick_files_supplier=self.visible_quick_files_snapshot,
                quick_file_sort_mode_supplier=self.quick_file_sort_mode_snapshot,
                set_quick_file_sort_mode=self.set_quick_file_sort_mode,
                add_quick_file=self.add_quick_file,
                edit_quick_file=self.edit_quick_file,
                delete_quick_file=self.delete_quick_file,
                move_quick_file=self.move_quick_file,
                reorder_quick_files=lambda quick_file_ids, selected_id="", force_custom=False: self.reorder_quick_files(
                    quick_file_ids,
                    selected_id=selected_id,
                    force_custom=force_custom,
                ),
                import_quick_files_csv=self.import_quick_files_csv,
                export_quick_files_csv=self.export_quick_files_csv,
            ),
            run_target_service=CommandRunTargetService(
                targets_supplier=self.command_file_run_targets,
                run_callback=self.run_command_file_request_in_terminal_by_id,
            ),
            embedded=True,
            show_run_button=False,
            show_workspace_side_panel=True,
            parent=self.tabs,
        )
        editor.apply_editor_font(self.editor_font())
        if state is not None:
            if state.text or state.dirty or not state.path:
                editor.restore_text(state.text, dirty=state.dirty)
            if state.path:
                editor.path = Path(state.path)
                editor.update_window_state()
                editor.update_validation_status()
        editor.stateChanged.connect(self.update_tab_titles)
        editor.stateChanged.connect(self.sync_status_from_current_session)
        index = self.tabs.addTab(
            editor,
            standard_icon(QStyle.StandardPixmap.SP_FileIcon),
            editor.tab_title(),
        )
        self.tab_workspace.attach_tab_close_button(index, editor)
        self.tabs.setCurrentIndex(index)
        self.update_tab_titles()
        self.refresh_command_file_targets()
        self.save_settings()
        return editor

    def run_command_editor_buffer(self, text: str, path: Path | None) -> None:
        session = self.current_session()
        if not session:
            self.set_status("No active session to run command file.")
            return
        label = str(path) if path is not None else "editor buffer"
        session.run_script_text(text, source_label=label, source_path=path)

    def connected_terminal_sessions(self) -> list[TerminalSessionWidget]:
        return [
            session
            for session in self.iter_sessions()
            if session.serial_client.is_connected
        ]

    def command_file_run_targets(self) -> list[CommandRunTarget]:
        return [
            CommandRunTarget(session.session_id, session.connection_status_text())
            for session in self.connected_terminal_sessions()
        ]

    def session_by_id(self, session_id: int) -> TerminalSessionWidget | None:
        return next((session for session in self.iter_sessions() if session.session_id == session_id), None)

    def run_command_file_request_in_terminal_by_id(self, request: CommandRunRequest, session_id: int) -> bool:
        session = self.session_by_id(session_id)
        if not session:
            self.set_status("Selected terminal is no longer available.")
            return False
        if not session.serial_client.is_connected:
            self.set_status(f"{session.tab_title} is not connected.")
            return False
        session.run_script_text(request.text, source_label=request.source_label, source_path=request.path)
        self.set_status(f"Running {request.display_name} in {session.tab_title}.")
        return True

    def run_editor_in_terminal_by_id(self, editor: CommandFileEditorDialog, session_id: int) -> None:
        session = self.session_by_id(session_id)
        if not session:
            self.set_status("Selected terminal is no longer available.")
            return
        self.run_editor_in_terminal(editor, session)

    def refresh_command_file_targets(self) -> None:
        for editor in self.iter_command_file_editors():
            editor.refresh_run_targets()

    def populate_run_editor_menu(self, menu: QMenu, editor: CommandFileEditorDialog | None = None) -> None:
        menu.clear()
        editor = editor or self.current_command_file_editor()
        if editor is None:
            action = menu.addAction("Open a command-file tab first")
            action.setEnabled(False)
            return
        if editor.validation_errors():
            action = menu.addAction("Fix syntax errors before running")
            action.setEnabled(False)
            return
        sessions = self.connected_terminal_sessions()
        if not sessions:
            action = menu.addAction("No connected terminals")
            action.setEnabled(False)
            return
        for session in sessions:
            label = session.connection_status_text()
            action = QAction(label, self)
            action.setIcon(standard_icon(QStyle.StandardPixmap.SP_ComputerIcon, 16, self.theme.rx))
            action.triggered.connect(lambda _checked=False, target=session, source=editor: self.run_editor_in_terminal(source, target))
            menu.addAction(action)

    def run_editor_in_terminal(self, editor: CommandFileEditorDialog, session: TerminalSessionWidget) -> None:
        if self.tabs.indexOf(editor) < 0 or self.tabs.indexOf(session) < 0:
            self.set_status("Command-file tab or terminal tab is no longer available.")
            return
        if not session.serial_client.is_connected:
            self.set_status(f"{session.tab_title} is not connected.")
            return
        if editor.validation_errors():
            editor.update_validation_status()
            self.set_status("Fix command-file syntax errors before running.")
            return
        label = str(editor.path) if editor.path else editor.display_name()
        session.run_script_text(editor.text(), source_label=label, source_path=editor.path)
        self.set_status(f"Running {editor.display_name()} in {session.tab_title}.")

    def show_find_in_current_tab(self) -> None:
        editor = self.current_command_file_editor()
        if editor:
            editor.show_find_bar()
            return
        session = self.current_session()
        if session:
            session.show_search()
            return
        self.set_status("No active tab to search.")

    def show_replace_in_current_tab(self) -> None:
        editor = self.current_command_file_editor()
        if editor:
            editor.show_replace_bar()
            return
        self.set_status("Replace is available in command-file editor tabs.")

    def command_palette_entries(self) -> list[CommandPaletteEntry]:
        entries = self.command_registry.palette_entries()
        for index in range(self.tabs.count()):
            session = self.session_at(index)
            editor = self.command_file_editor_at(index)
            title = session.tab_title if session else editor.tab_title() if editor else self.tabs.tabText(index)
            port = session.profile.port if session and session.profile.port else "No port"
            subtitle = session.connection_status_text() if session else editor.status_summary() if editor else port
            icon = QStyle.StandardPixmap.SP_ComputerIcon if session else QStyle.StandardPixmap.SP_FileIcon
            keywords = (
                f"switch tab terminal session {index + 1} {title} {port} {session.title}"
                if session
                else f"switch tab command file editor script {index + 1} {title}"
            )
            entries.append(
                CommandPaletteEntry(
                    title=f"Switch to Tab {index + 1}: {title}",
                    subtitle=subtitle,
                    callback=lambda tab_index=index: self.tabs.setCurrentIndex(tab_index),
                    icon=icon,
                    keywords=keywords,
                )
            )
        return entries

    def show_tab_context_menu(self, position) -> None:
        tab_bar = self.tabs.tabBar()
        index = tab_bar.tabAt(position)
        menu = self.build_tab_context_menu(index)
        menu.exec(tab_bar.mapToGlobal(position))

    def build_tab_context_menu(self, index: int) -> QMenu:
        menu = QMenu(self)
        if index < 0:
            self._add_context_command_action(menu, "file.new_tab")
            self._add_context_command_action(menu, "command_file.new")
            return menu

        session = self.session_at(index)
        editor = self.command_file_editor_at(index)
        if editor:
            menu.setTitle(editor.tab_title())
            self._add_context_command_action(menu, "command_file.new")
            self._add_context_action(
                menu,
                "Save",
                editor.save,
                icon=QStyle.StandardPixmap.SP_DialogSaveButton,
                enabled=editor.is_dirty() or editor.path is None,
            )
            self._add_context_action(
                menu,
                "Save As",
                editor.save_as,
                icon=QStyle.StandardPixmap.SP_DialogSaveButton,
            )
            run_menu = menu.addMenu("Run in Terminal")
            run_menu.setIcon(standard_icon(QStyle.StandardPixmap.SP_ArrowForward))
            run_menu.aboutToShow.connect(lambda menu=run_menu, source=editor: self.populate_run_editor_menu(menu, source))
            if editor.path:
                self._add_context_action(
                    menu,
                    "Show in Explorer",
                    lambda source=editor: self.show_path_in_explorer(source.path),
                    icon=QStyle.StandardPixmap.SP_DirOpenIcon,
                )
            menu.addSeparator()
            self._add_context_command_action(
                menu,
                "file.close_tab",
                lambda tab_index=index: self.close_session(tab_index),
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

        is_connected = bool(session and session.serial_client.is_connected)
        is_reconnecting = bool(session and session.serial_client.is_reconnecting)
        menu.setTitle(session.tab_title if session else self.tabs.tabText(index))
        self._add_context_command_action(menu, "file.new_tab")
        self._add_context_command_action(
            menu,
            "file.duplicate_tab",
            lambda tab_index=index: self.duplicate_session(tab_index),
        )
        self._add_context_command_action(
            menu,
            "session.rename_tab",
            lambda tab_index=index: self.rename_session(tab_index),
        )
        menu.addSeparator()
        self._add_context_command_action(
            menu,
            "serial.settings",
            lambda tab_index=index: self.open_session_settings(tab_index),
            enabled=session is not None,
        )
        self._add_context_action(
            menu,
            "Disconnect" if is_connected else "Stop Retry" if is_reconnecting else "Connect",
            lambda tab_index=index: self.toggle_session_connection(tab_index),
            icon=QStyle.StandardPixmap.SP_ComputerIcon,
            enabled=session is not None,
        )
        self._add_context_command_action(
            menu,
            "edit.find",
            lambda tab_index=index: self.show_session_search(tab_index),
            text="Search",
            enabled=session is not None,
        )
        self._add_context_command_action(
            menu,
            "edit.clear_terminal",
            lambda tab_index=index: self.clear_session_terminal(tab_index),
            enabled=session is not None,
        )
        menu.addSeparator()
        self._add_context_command_action(
            menu,
            "file.close_tab",
            lambda tab_index=index: self.close_session(tab_index),
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

    def restore_sessions(self, *, prompt_first_settings: bool = True) -> None:
        self.workspace_state_service.restore_from_settings(
            self.settings,
            self,
            prompt_first_settings=prompt_first_settings,
        )

    def add_session(self, state: TerminalSessionState | None = None, *, prompt_settings: bool = True) -> None:
        self._session_counter += 1
        state = state or TerminalSessionState(title=f"Terminal {self._session_counter}")
        session = TerminalSessionWidget(self, self._session_counter, state)
        index = self.tabs.addTab(
            session,
            standard_icon(QStyle.StandardPixmap.SP_ComputerIcon),
            session.tab_title,
        )
        self.tab_workspace.attach_tab_close_button(index, session)
        self.tabs.setCurrentIndex(index)
        self.update_tab_titles()
        if prompt_settings:
            self.prompt_session_settings(session)
        if state.connected_on_launch and session.profile.port:
            QTimer.singleShot(0, lambda target=session: self.restore_session_connection(target))

    def restore_session_connection(self, session: TerminalSessionWidget) -> None:
        if self.tabs.indexOf(session) < 0 or session.serial_client.is_connected:
            return
        self.set_status(f"Connecting to {session.profile.port}...")
        session.serial_client.connect(session.profile)
        session._update_connection_ui(session.serial_client.is_connected)

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
        self.tab_workspace.duplicate_current_session()

    def duplicate_session(self, index: int) -> None:
        self.tab_workspace.duplicate_session(index)

    def close_current_session(self) -> None:
        self.tab_workspace.close_current_session()

    def close_session(self, index: int) -> bool:
        return self.tab_workspace.close_session(index)

    def confirm_close_command_file_tab(self, editor: CommandFileEditorDialog) -> bool:
        if not editor.is_dirty():
            return True
        message = QMessageBox(self)
        message.setWindowTitle("Close Command File")
        message.setText(f"Save changes to {editor.display_name()} before closing?")
        message.setIcon(QMessageBox.Icon.Warning)
        save_button = message.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard_button = message.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = message.addButton(QMessageBox.StandardButton.Cancel)
        message.setDefaultButton(save_button)
        message.exec()
        clicked = message.clickedButton()
        if clicked is save_button:
            return editor.save()
        if clicked is discard_button:
            editor._dirty = False
            editor.update_window_state()
            return True
        return clicked is not cancel_button and False

    def close_other_sessions(self, index: int) -> None:
        self.tab_workspace.close_other_sessions(index)

    def close_sessions_to_right(self, index: int) -> None:
        self.tab_workspace.close_sessions_to_right(index)

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
            session.title_is_custom = True
            self.update_tab_titles()
            self.save_settings()

    def current_session(self) -> TerminalSessionWidget | None:
        return cast(TerminalSessionWidget | None, self.tab_workspace.current_session())

    def current_command_file_editor(self) -> CommandFileEditorDialog | None:
        return cast(CommandFileEditorDialog | None, self.tab_workspace.current_command_file_editor())

    def session_at(self, index: int) -> TerminalSessionWidget | None:
        return cast(TerminalSessionWidget | None, self.tab_workspace.session_at(index))

    def command_file_editor_at(self, index: int) -> CommandFileEditorDialog | None:
        return cast(CommandFileEditorDialog | None, self.tab_workspace.command_file_editor_at(index))

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
        return cast(list[TerminalSessionWidget], self.tab_workspace.iter_sessions())

    def iter_command_file_editors(self) -> list[CommandFileEditorDialog]:
        return cast(list[CommandFileEditorDialog], self.tab_workspace.iter_command_file_editors())

    def workspace_tab_count(self) -> int:
        return self.tab_workspace.workspace_tab_count()

    def with_session(self, callback) -> None:
        session = self.current_session()
        if session:
            callback(session)

    def update_tab_titles(self) -> None:
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, TerminalSessionWidget):
                self.tabs.setTabText(index, widget.tab_title)
                state = widget.connection_state()
                color = self.connection_state_color(state)
                icon = QStyle.StandardPixmap.SP_BrowserReload if state == "retrying" else QStyle.StandardPixmap.SP_ComputerIcon
                self.tabs.setTabIcon(index, standard_icon(icon, 18, color))
                self.tabs.setTabToolTip(index, widget.connection_status_text())
                self.tabs.tabBar().setTabTextColor(index, QColor(color))
            elif isinstance(widget, CommandFileEditorDialog):
                color = self.theme.status if widget.is_dirty() else self.theme.text
                if widget.validation_errors():
                    color = self.theme.error
                self.tabs.setTabText(index, widget.tab_title())
                self.tabs.setTabIcon(index, standard_icon(QStyle.StandardPixmap.SP_FileIcon, 18, color))
                self.tabs.setTabToolTip(index, widget.status_summary())
                self.tabs.tabBar().setTabTextColor(index, QColor(color))

    def sync_status_from_current_session(self) -> None:
        session = self.current_session()
        if session:
            self.update_connection_status(session)
            return
        editor = self.current_command_file_editor()
        if editor:
            self.connection_status_label.setText(editor.status_summary())
            self.connection_status_label.setToolTip("Command-file editor tab")
            set_widget_state(self.connection_status_label, "no-port")
            self.connection_action_button.setEnabled(False)
            self.connection_action_button.setText("Terminal only")
            set_button_icon(self.connection_action_button, QStyle.StandardPixmap.SP_FileIcon, 15)
            set_button_role(self.connection_action_button, "no-port")
            self.set_status(editor.status_summary())
            return
        self.connection_status_label.setText("No tab")
        self.connection_action_button.setEnabled(False)

    def connection_state_color(self, state: str) -> str:
        if state == "connected":
            return self.theme.rx
        if state == "retrying":
            return self.theme.status
        if state == "missing":
            return self.theme.error
        if state == "no-port":
            return self.theme.muted
        return self.theme.text

    def connection_status_action_clicked(self) -> None:
        session = self.current_session()
        if session:
            session.toggle_connection()

    def open_current_connection_settings(self) -> None:
        session = self.current_session()
        if session:
            session.open_connection_settings(connect_after_accept=True)

    def update_connection_status(self, session: TerminalSessionWidget | None = None) -> None:
        self.refresh_command_file_targets()
        session = session or self.current_session()
        if not session:
            self.connection_status_label.setText("No session")
            self.connection_action_button.setEnabled(False)
            return
        state = session.connection_state()
        self.connection_status_label.setText(session.connection_status_text())
        self.connection_status_label.setToolTip(
            f"{session.connection_tooltip()}\nDouble-click to open Serial Settings."
        )
        set_widget_state(self.connection_status_label, state)
        self.connection_action_button.setEnabled(True)
        self.connection_action_button.setText(session.connection_action_text())
        self.connection_action_button.setToolTip(session.connection_tooltip())
        action_icon = QStyle.StandardPixmap.SP_MediaStop if state == "retrying" else QStyle.StandardPixmap.SP_ComputerIcon
        if state == "no-port":
            action_icon = QStyle.StandardPixmap.SP_FileDialogDetailedView
        if state == "connected":
            action_icon = QStyle.StandardPixmap.SP_DialogCloseButton
        set_button_icon(self.connection_action_button, action_icon, 15)
        set_button_role(self.connection_action_button, state)

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
        self.apply_terminal_font_settings()
        self.save_settings()

    def show_terminal_font_settings(self) -> None:
        dialog = TerminalFontSettingsDialog(
            self.settings.terminal_font_family,
            self.settings.terminal_font_size,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.settings.terminal_font_family = dialog.selected_family()
        self.settings.terminal_font_size = dialog.selected_size()
        self.apply_terminal_font_settings()
        self.save_settings()

    def apply_terminal_font_settings(self) -> None:
        for session in self.iter_sessions():
            session.apply_settings()
        for editor in self.iter_command_file_editors():
            editor.apply_editor_font(self.editor_font())

    def toggle_timestamps(self) -> None:
        self.settings.timestamps_enabled = self.timestamps_action.isChecked()
        self.save_settings()

    def toggle_line_wrap(self) -> None:
        self.settings.line_wrap_enabled = self.wrap_action.isChecked()
        for session in self.iter_sessions():
            session.apply_settings()
        self.save_settings()

    def set_receive_display_mode(self, mode: str) -> None:
        if mode not in RECEIVE_DISPLAY_MODES:
            mode = "Text"
        if self.settings.receive_display_mode == mode:
            return
        self.settings.receive_display_mode = mode
        for session in self.iter_sessions():
            session.apply_settings()
        self.save_settings()

    def default_serial_profile(self) -> SerialProfile:
        return clone_profile(self.settings.serial)

    def apply_settings_to_ui(self) -> None:
        self.apply_theme(self.settings.theme, save=False)
        if hasattr(self, "timestamps_action"):
            self.timestamps_action.setChecked(self.settings.timestamps_enabled)
        if hasattr(self, "wrap_action"):
            self.wrap_action.setChecked(self.settings.line_wrap_enabled)
        for session in self.iter_sessions():
            session.controller.replace_history(self.history_catalog.all_commands())
            session.history_store = session.controller.history_store
            session.apply_settings()
            session.apply_drawer_state(
                self.settings.drawer_collapsed,
                self.settings.drawer_width,
            )
            session.refresh_quick_commands()
            session.refresh_quick_files()
        for editor in self.iter_command_file_editors():
            editor.apply_editor_font(self.editor_font())
        self.update_tab_titles()
        self.sync_status_from_current_session()

    def quick_command_by_id(self, command_id: str) -> QuickCommand | None:
        self._refresh_quick_actions_from_settings()
        return self.quick_actions.command_by_id(command_id)

    def quick_file_by_id(self, quick_file_id: str) -> QuickFile | None:
        self._refresh_quick_actions_from_settings()
        return self.quick_actions.file_by_id(quick_file_id)

    def quick_command_group_names(self) -> list[str]:
        self._refresh_quick_actions_from_settings()
        return self.quick_actions.command_group_names()

    def set_quick_command_sort_mode(self, mode: str) -> None:
        self._refresh_quick_actions_from_settings()
        if mode not in QUICK_COMMAND_SORT_MODES:
            mode = "Custom"
        if self.quick_actions.command_sort_mode == mode:
            return
        self.quick_actions.set_command_sort_mode(mode)
        self._sync_quick_actions_to_settings()
        self.refresh_quick_commands_everywhere()
        self.save_settings()

    def set_quick_file_sort_mode(self, mode: str) -> None:
        self._refresh_quick_actions_from_settings()
        if mode not in QUICK_FILE_SORT_MODES:
            mode = "Custom"
        if self.quick_actions.file_sort_mode == mode:
            return
        self.quick_actions.set_file_sort_mode(mode)
        self._sync_quick_actions_to_settings()
        self.refresh_quick_files_everywhere()
        self.save_settings()

    def set_quick_command_group_visible(self, group: str, visible: bool) -> None:
        self._refresh_quick_actions_from_settings()
        group = quick_group_name(group)
        before = [item.casefold() for item in self.quick_actions.command_hidden_groups]
        self.quick_actions.set_command_group_visible(group, visible)
        after = [item.casefold() for item in self.quick_actions.command_hidden_groups]
        if before == after:
            return
        self._sync_quick_actions_to_settings()
        self.refresh_quick_commands_everywhere()
        self.save_settings()

    def show_all_quick_command_groups(self) -> None:
        self._refresh_quick_actions_from_settings()
        if not self.quick_actions.command_hidden_groups:
            return
        self.quick_actions.command_hidden_groups = []
        self._sync_quick_actions_to_settings()
        self.refresh_quick_commands_everywhere()
        self.save_settings()

    def hide_all_quick_command_groups(self) -> None:
        self._refresh_quick_actions_from_settings()
        groups = self.quick_command_group_names()
        if [group.casefold() for group in groups] == [
            group.casefold() for group in self.quick_actions.command_hidden_groups
        ]:
            return
        self.quick_actions.command_hidden_groups = groups
        self._sync_quick_actions_to_settings()
        self.refresh_quick_commands_everywhere()
        self.save_settings()

    def add_quick_command(self, command: QuickCommand | None = None) -> None:
        self._refresh_quick_actions_from_settings()
        if command is None or isinstance(command, bool):
            dialog = QuickCommandDialog(parent=self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            command = dialog.quick_command()
        if not command.command:
            return
        self.quick_actions.quick_commands.append(command)
        self._sync_quick_actions_to_settings()
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
        for index, existing in enumerate(self.quick_actions.quick_commands):
            if existing.id == updated.id:
                self.quick_actions.quick_commands[index] = updated
                break
        self._sync_quick_actions_to_settings()
        self.refresh_quick_commands_everywhere()
        self.save_settings()

    def duplicate_quick_command(self, command_id: str) -> None:
        command = self.quick_command_by_id(command_id)
        if not command:
            return
        now = utc_now_iso()
        duplicate = QuickCommand(
            label=f"{command.display_label()} Copy",
            command=command.command,
            description=command.description,
            send_mode=command.send_mode,
            group=command.group,
            line_ending_override=command.line_ending_override,
            created_at=now,
            updated_at=now,
        )
        source_index = next(
            (index for index, existing in enumerate(self.quick_actions.quick_commands) if existing.id == command_id),
            len(self.quick_actions.quick_commands) - 1,
        )
        self.quick_actions.quick_commands.insert(source_index + 1, duplicate)
        self._sync_quick_actions_to_settings()
        self.refresh_quick_commands_everywhere(duplicate.id)
        self.save_settings()

    def delete_quick_command(self, command_id: str) -> None:
        self._refresh_quick_actions_from_settings()
        if not command_id:
            return
        self.quick_actions.quick_commands = [
            command
            for command in self.quick_actions.quick_commands
            if command.id != command_id
        ]
        self._sync_quick_actions_to_settings()
        self.refresh_quick_commands_everywhere()
        self.save_settings()

    def copy_quick_command_text(self, command_id: str) -> None:
        command = self.quick_command_by_id(command_id)
        if not command:
            return
        QApplication.clipboard().setText(command.command)
        self.set_status(f"Copied quick command: {short_label(command.display_label(), 32)}")

    def add_quick_file(self, quick_file: QuickFile | None = None) -> None:
        self._refresh_quick_actions_from_settings()
        if quick_file is None or isinstance(quick_file, bool):
            dialog = QuickFileDialog(parent=self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            quick_file = dialog.quick_file()
        if not quick_file.path:
            return
        self.quick_actions.quick_files.append(quick_file)
        self._sync_quick_actions_to_settings()
        self.refresh_quick_files_everywhere(quick_file.id)
        self.save_settings()

    def edit_quick_file(self, quick_file_id: str) -> None:
        quick_file = self.quick_file_by_id(quick_file_id)
        if not quick_file:
            return
        dialog = QuickFileDialog(quick_file, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.quick_file()
        if not updated.path:
            return
        for index, existing in enumerate(self.quick_actions.quick_files):
            if existing.id == updated.id:
                self.quick_actions.quick_files[index] = updated
                break
        self._sync_quick_actions_to_settings()
        self.refresh_quick_files_everywhere(updated.id)
        self.save_settings()

    def delete_quick_file(self, quick_file_id: str) -> None:
        self._refresh_quick_actions_from_settings()
        if not quick_file_id:
            return
        self.quick_actions.quick_files = [
            quick_file
            for quick_file in self.quick_actions.quick_files
            if quick_file.id != quick_file_id
        ]
        self._sync_quick_actions_to_settings()
        self.refresh_quick_files_everywhere()
        self.save_settings()

    def show_quick_file_in_explorer(self, quick_file_id: str) -> None:
        quick_file = self.quick_file_by_id(quick_file_id)
        if not quick_file:
            return
        path = Path(quick_file.path)
        self.show_path_in_explorer(path)

    def show_path_in_explorer(self, path: Path | None) -> None:
        if path is None:
            return
        if not path.exists():
            QMessageBox.warning(self, "Quick File", f"File not found:\n{path}")
            return
        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
        except OSError as exc:
            QMessageBox.warning(self, "Quick File", str(exc))

    def open_quick_file_editor(self, quick_file_id: str) -> None:
        quick_file = self.quick_file_by_id(quick_file_id)
        if not quick_file:
            return
        self.open_command_file_editor(Path(quick_file.path))

    def edit_selected_quick_file_content(self) -> None:
        session = self.current_session()
        if not session:
            return
        self.open_quick_file_editor(session.selected_quick_file_id())

    def import_quick_commands_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Quick Commands",
            str(Path.cwd()),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        dialog = QuickCommandImportDialog(
            title="Import Quick Commands",
            message="Choose whether this CSV adds to your current quick commands or replaces them.",
            default_replace=False,
            default_skip_duplicates=True,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            result = self.import_quick_commands_from_csv(Path(path), options=dialog.options())
        except (OSError, csv.Error, ValueError) as exc:
            QMessageBox.warning(self, "Import Quick Commands", str(exc))
            return
        self.set_status(
            f"Imported {result.imported_count} quick command(s){result.status_suffix()}."
        )

    def export_quick_commands_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Quick Commands",
            str(Path.cwd() / "comport-zone-quick-commands.csv"),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        try:
            exported_count = self.export_quick_commands_to_csv(Path(path))
        except (OSError, csv.Error) as exc:
            QMessageBox.warning(self, "Export Quick Commands", str(exc))
            return
        self.set_status(f"Exported {exported_count} quick command(s).")

    def import_quick_files_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Quick Files",
            str(Path.cwd()),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        dialog = QuickCommandImportDialog(
            title="Import Quick Files",
            message="Choose whether this CSV adds to your current quick files or replaces them.",
            default_replace=False,
            default_skip_duplicates=True,
            append_label="Append imported files",
            replace_label="Replace current quick files",
            duplicate_checkbox_text="Skip duplicate file paths",
            duplicate_hint_text="Duplicate detection uses the saved file path, ignoring label changes.",
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        import_options = dialog.options()
        try:
            result = self.import_quick_files_from_csv(
                Path(path),
                options=QuickFileImportOptions(
                    replace_existing=import_options.replace_existing,
                    skip_duplicates=import_options.skip_duplicates,
                ),
            )
        except (OSError, csv.Error, ValueError) as exc:
            QMessageBox.warning(self, "Import Quick Files", str(exc))
            return
        self.set_status(
            f"Imported {result.imported_count} quick file(s){result.status_suffix()}."
        )

    def export_quick_files_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Quick Files",
            str(Path.cwd() / "comport-zone-quick-files.csv"),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        try:
            exported_count = self.export_quick_files_to_csv(Path(path))
        except (OSError, csv.Error) as exc:
            QMessageBox.warning(self, "Export Quick Files", str(exc))
            return
        self.set_status(f"Exported {exported_count} quick file(s).")

    def import_quick_commands_from_csv(
        self,
        path: Path,
        *,
        options: QuickCommandImportOptions | None = None,
    ) -> QuickCommandImportResult:
        self._refresh_quick_actions_from_settings()
        result = self.quick_actions.import_commands_from_csv(path, options=options)
        self._sync_quick_actions_to_settings()
        selected_id = self.quick_actions.quick_commands[-1].id if self.quick_actions.quick_commands else ""
        self.refresh_quick_commands_everywhere(selected_id)
        self.save_settings()
        return result

    def export_quick_commands_to_csv(self, path: Path) -> int:
        self._refresh_quick_actions_from_settings()
        return self.quick_actions.export_commands_to_csv(path)

    def import_quick_files_from_csv(
        self,
        path: Path,
        *,
        options: QuickFileImportOptions | None = None,
    ) -> QuickFileImportResult:
        self._refresh_quick_actions_from_settings()
        result = self.quick_actions.import_files_from_csv(path, options=options)
        self._sync_quick_actions_to_settings()
        selected_id = self.quick_actions.quick_files[-1].id if self.quick_actions.quick_files else ""
        self.refresh_quick_files_everywhere(selected_id)
        self.save_settings()
        return result

    def export_quick_files_to_csv(self, path: Path) -> int:
        self._refresh_quick_actions_from_settings()
        return self.quick_actions.export_files_to_csv(path)

    def move_quick_command(self, command_id: str, direction: int) -> None:
        self._refresh_quick_actions_from_settings()
        commands = self.quick_actions.quick_commands
        index = next((i for i, command in enumerate(commands) if command.id == command_id), -1)
        target = index + direction
        if index < 0 or target < 0 or target >= len(commands):
            return
        commands[index], commands[target] = commands[target], commands[index]
        self._sync_quick_actions_to_settings()
        self.refresh_quick_commands_everywhere(command_id)
        self.save_settings()

    def move_quick_file(self, quick_file_id: str, direction: int) -> None:
        self._refresh_quick_actions_from_settings()
        quick_files = self.quick_actions.quick_files
        index = next((i for i, quick_file in enumerate(quick_files) if quick_file.id == quick_file_id), -1)
        target = index + direction
        if index < 0 or target < 0 or target >= len(quick_files):
            return
        quick_files[index], quick_files[target] = quick_files[target], quick_files[index]
        self._sync_quick_actions_to_settings()
        self.refresh_quick_files_everywhere(quick_file_id)
        self.save_settings()

    def reorder_quick_commands(self, command_ids: list[str], *, selected_id: str = "") -> None:
        self._refresh_quick_actions_from_settings()
        if not self.quick_actions.reorder_commands(command_ids):
            return
        self._sync_quick_actions_to_settings()
        self.refresh_quick_commands_everywhere(selected_id)
        self.save_settings()

    def reorder_quick_files(
        self,
        quick_file_ids: list[str],
        *,
        selected_id: str = "",
        force_custom: bool = False,
    ) -> None:
        self._refresh_quick_actions_from_settings()
        if not self.quick_actions.reorder_files(quick_file_ids, force_custom=force_custom):
            return
        self._sync_quick_actions_to_settings()
        self.refresh_quick_files_everywhere(selected_id)
        self.save_settings()

    def refresh_quick_commands_everywhere(self, selected_id: str | None = None) -> None:
        for session in self.iter_sessions():
            session.refresh_quick_commands(selected_id)
        for editor in self.iter_command_file_editors():
            editor.sources = self.command_editor_sources()
            editor.highlighter.sources = editor.sources
            editor._refresh_completion_model()
            editor.highlighter.rehighlight()
            editor.update_validation_status()
            editor.refresh_workspace_side_panel()

    def refresh_quick_files_everywhere(self, selected_id: str | None = None) -> None:
        for session in self.iter_sessions():
            session.refresh_quick_files(selected_id)
        for editor in self.iter_command_file_editors():
            editor.refresh_workspace_side_panel()

    def record_command(self, command: str) -> None:
        self.history_catalog.add(command)
        for session in self.iter_sessions():
            session.history_store.add(command)
            session._update_completion_model()
        self.save_settings()

    def remove_command_from_history(self, command: str) -> bool:
        removed = self.history_catalog.remove(command)
        for session in self.iter_sessions():
            session.history_store.remove(command)
            session._update_completion_model()
        if removed:
            self.save_settings()
        return removed

    def _confirm_bulk_delete(self, title: str, message: str, *, confirm: bool = True) -> bool:
        if not confirm:
            return True
        return (
            QMessageBox.question(
                self,
                title,
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Yes
        )

    def clear_command_history(self, *, confirm: bool = True) -> bool:
        count = len(self.history_catalog.all_commands())
        if count == 0:
            self.set_status("Command history is already empty.")
            return False
        if not self._confirm_bulk_delete(
            "Clear Command History",
            f"Delete all {count} command history entr{'y' if count == 1 else 'ies'}?\n\n"
            "Quick Commands are not affected.",
            confirm=confirm,
        ):
            return False
        self.history_catalog.clear()
        for session in self.iter_sessions():
            session.history_store.clear()
            session._update_completion_model()
        self.save_settings()
        self.set_status(f"Cleared {count} command history entr{'y' if count == 1 else 'ies'}.")
        return True

    def delete_all_quick_commands(self, *, confirm: bool = True) -> bool:
        self._refresh_quick_actions_from_settings()
        count = len(self.quick_actions.quick_commands)
        if count == 0:
            self.set_status("No quick commands to delete.")
            return False
        if not self._confirm_bulk_delete(
            "Delete All Quick Commands",
            f"Delete all {count} quick command{'s' if count != 1 else ''}?\n\n"
            "Command history is not affected.",
            confirm=confirm,
        ):
            return False
        self.quick_actions.quick_commands = []
        self.quick_actions.command_hidden_groups = []
        self._sync_quick_actions_to_settings()
        self.refresh_quick_commands_everywhere()
        self.save_settings()
        self.set_status(f"Deleted {count} quick command{'s' if count != 1 else ''}.")
        return True

    def delete_all_quick_files(self, *, confirm: bool = True) -> bool:
        self._refresh_quick_actions_from_settings()
        count = len(self.quick_actions.quick_files)
        if count == 0:
            self.set_status("No quick files to delete.")
            return False
        if not self._confirm_bulk_delete(
            "Delete All Quick Files",
            f"Delete all {count} saved quick file{'s' if count != 1 else ''}?",
            confirm=confirm,
        ):
            return False
        self.quick_actions.quick_files = []
        self._sync_quick_actions_to_settings()
        self.refresh_quick_files_everywhere()
        self.save_settings()
        self.set_status(f"Deleted {count} quick file{'s' if count != 1 else ''}.")
        return True

    def show_app_settings_transfer_dialog(self) -> None:
        dialog = AppSettingsTransferDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.selected_action == "import":
            self.import_settings(show_explanation=False)
        elif dialog.selected_action == "export":
            self.export_settings(show_explanation=False)

    def confirm_app_settings_transfer(self, mode: str) -> bool:
        dialog = AppSettingsTransferDialog(mode=mode, parent=self)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _show_busy_message(self, title: str, message: str) -> QProgressDialog:
        self.set_status(message)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        dialog = QProgressDialog(message, "", 0, 0, self)
        dialog.setWindowTitle(title)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setCancelButton(None)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        dialog.show()
        QApplication.processEvents()
        return dialog

    def _hide_busy_message(self, dialog: QProgressDialog | None) -> None:
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()
        QApplication.restoreOverrideCursor()
        QApplication.processEvents()

    def import_settings(self, *, show_explanation: bool = True) -> None:
        if show_explanation and not self.confirm_app_settings_transfer("import"):
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import App Settings",
            str(Path.cwd()),
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        busy = self._show_busy_message("Import App Settings", "Importing app settings...")
        try:
            imported_settings = self.load_settings_from_json(Path(path))
            self.apply_imported_settings(imported_settings)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._hide_busy_message(busy)
            QMessageBox.warning(self, "Import App Settings", str(exc))
            return
        saved = self.settings_service.save(self.settings)
        self._hide_busy_message(busy)
        if not saved:
            self.set_status("Could not save imported app settings to disk.")
            QMessageBox.warning(
                self,
                "Import App Settings",
                "Imported settings were applied, but could not be saved to disk.",
            )
            return
        self.set_status(f"Imported app settings from {path}.")

    def export_settings(self, *, show_explanation: bool = True) -> None:
        if show_explanation and not self.confirm_app_settings_transfer("export"):
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export App Settings",
            str(Path.cwd() / "comport-zone-app-settings.json"),
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        busy = self._show_busy_message("Export App Settings", "Exporting app settings...")
        try:
            self.save_settings()
            self.export_settings_to_json(Path(path))
        except OSError as exc:
            self._hide_busy_message(busy)
            QMessageBox.warning(self, "Export App Settings", str(exc))
            return
        self._hide_busy_message(busy)
        self.set_status(f"Exported app settings to {path}")

    def load_settings_from_json(self, path: Path) -> AppSettings:
        return self.settings_service.load_from_json(path)

    def export_settings_to_json(self, path: Path) -> None:
        self.settings_service.export_to_json(self.settings, path)

    def apply_imported_settings(
        self,
        settings: AppSettings,
    ) -> None:
        self._refresh_quick_actions_from_settings()
        self._sync_quick_actions_to_settings()
        settings = self.settings_service.preserve_quick_actions(settings, self.settings)
        for index in range(self.tabs.count() - 1, -1, -1):
            session = self.session_at(index)
            if session:
                session.shutdown()
            widget = self.tabs.widget(index)
            self.tabs.removeTab(index)
            if widget:
                widget.deleteLater()
        previous_loading = self._loading
        self._loading = True
        self.settings = settings
        self.quick_actions = self._quick_action_library_from_settings()
        self.history_catalog = HistoryStore(self.settings.command_history)
        self.theme = THEMES.get(self.settings.theme, THEMES["VS Code Dark"])
        self.resize(self.settings.window_width, self.settings.window_height)
        self.restore_sessions(prompt_first_settings=False)
        self._loading = previous_loading
        self.apply_settings_to_ui()

    def show_about(self) -> None:
        QMessageBox.information(
            self,
            "About ComPort Zone",
            f"ComPort Zone\nVersion {__version__}\n\nCOM-port terminal for Windows device workflows.",
        )

    def apply_theme(self, name: str, *, save: bool = True) -> None:
        self.theme = THEMES.get(name, THEMES["VS Code Dark"])
        self.settings.theme = self.theme.name
        self.setStyleSheet(self._stylesheet(self.theme))
        for theme_name, action in getattr(self, "theme_actions", {}).items():
            action.setChecked(theme_name == self.theme.name)
        self.update_tab_titles()
        self.sync_status_from_current_session()
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
            padding: 8px 8px 8px 16px;
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
        QToolButton#tabCloseButton {{
            background: transparent;
            color: {theme.muted};
            border: 1px solid transparent;
            border-radius: 7px;
            padding: 0;
            margin-right: 2px;
        }}
        QToolButton#tabCloseButton:hover {{
            background: {theme.surface};
            border-color: {theme.border};
        }}
        QToolButton#tabCloseButton:pressed {{
            background: {theme.accent_soft};
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
        QFrame#editorSidePanel {{
            background: {theme.window_alt};
            border-right: 1px solid {theme.border};
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
        QLabel#drawerHelpText {{
            color: {theme.muted};
            line-height: 1.3;
            padding: 2px 3px 6px 3px;
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
        QLabel#connectionStatus {{
            background: {theme.chip};
            color: {theme.text};
            border: 1px solid {theme.border};
            border-radius: 7px;
            padding: 3px 9px;
        }}
        QLabel#connectionStatus[state="connected"] {{
            color: {theme.rx};
            border-color: {theme.rx};
        }}
        QLabel#connectionStatus[state="retrying"] {{
            color: {theme.status};
            border-color: {theme.status};
        }}
        QLabel#connectionStatus[state="missing"] {{
            color: {theme.error};
            border-color: {theme.error};
        }}
        QLabel#connectionStatus[state="no-port"] {{
            color: {theme.muted};
            border-color: {theme.border};
        }}
        QLineEdit, QComboBox, QListWidget {{
            background: {theme.field};
            color: {theme.text};
            border: 1px solid {theme.border};
            border-radius: 8px;
            padding: 7px 9px;
            selection-background-color: {theme.search_highlight};
        }}
        QPlainTextEdit#commandFileEditor {{
            background: {terminal_background};
            color: {theme.text};
            border: 1px solid {theme.border};
            border-radius: 0px;
            selection-background-color: {theme.search_highlight};
        }}
        QLabel#editorPathLabel, QLabel#editorStatusLabel {{
            color: {theme.muted};
            padding: 4px 2px;
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
        QListWidget#quickCommandList,
        QListWidget#quickFileList {{
            padding: 4px;
        }}
        QListWidget#quickCommandList::item,
        QListWidget#quickFileList::item {{
            border-radius: 5px;
            padding: 3px 6px;
            margin: 1px 0;
        }}
        QDialog {{
            background: {theme.window};
            color: {theme.text};
        }}
        QLabel#dialogTitle {{
            font-size: 13pt;
            font-weight: 700;
            color: {theme.text};
        }}
        QLabel#dialogHint {{
            background: {theme.surface_alt};
            color: {theme.muted};
            border: 1px solid {theme.border};
            border-radius: 10px;
            padding: 10px;
        }}
        QDialog#commandPalette {{
            background: {theme.window};
            color: {theme.text};
        }}
        QLineEdit#commandPaletteSearch {{
            font-size: 11pt;
            padding: 10px 12px;
            border-radius: 10px;
        }}
        QListWidget#commandPaletteList {{
            padding: 6px;
            border-radius: 10px;
        }}
        QListWidget#commandPaletteList::item {{
            border-radius: 8px;
            padding: 7px 10px;
            margin: 2px;
        }}
        QLabel#commandPaletteHint {{
            color: {theme.muted};
            padding: 0 4px;
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
        QToolButton#drawerMenuButton {{
            background: {theme.field};
            color: {theme.text};
            border: 1px solid {theme.border};
            border-radius: 8px;
            padding: 7px 9px;
        }}
        QToolButton#drawerMenuButton:hover {{
            background: {theme.surface};
            border-color: {theme.accent};
        }}
        QToolButton#drawerMenuButton::menu-indicator {{
            image: none;
            width: 0px;
        }}
        QSplitter::handle {{
            background: {theme.border};
        }}
        QSplitter::handle:hover {{
            background: {theme.accent};
        }}
        QSplashScreen {{
            color: {theme.text};
        }}
        QStatusBar {{
            background: {theme.window_alt};
            color: {theme.text};
            border-top: 1px solid {theme.border};
        }}
        QLabel#footer {{
            color: {theme.muted};
            padding-left: 4px;
        }}
        QPushButton#statusActionButton {{
            min-width: 92px;
            padding: 3px 10px;
            border-radius: 7px;
            background: {theme.surface_alt};
        }}
        QPushButton#statusActionButton[role="connected"] {{
            color: {theme.rx};
            border-color: {theme.rx};
        }}
        QPushButton#statusActionButton[role="retrying"] {{
            color: {theme.error};
            border-color: {theme.error};
        }}
        QPushButton#statusActionButton[role="missing"] {{
            color: {theme.error};
            border-color: {theme.error};
        }}
        QPushButton#statusActionButton[role="no-port"] {{
            color: {theme.muted};
        }}
        QPushButton#statusActionButton:hover {{
            border-color: {theme.accent};
        }}
        QLabel#versionInfo {{
            color: {theme.muted};
            padding: 0 8px;
        }}
        """

    def save_settings(self) -> None:
        if self._loading:
            return
        self._refresh_quick_actions_from_settings()
        self._sync_quick_actions_to_settings()
        self.workspace_state_service.capture_into_settings(
            self.settings,
            active_session=self.current_session(),
            terminal_sessions=self.iter_sessions(),
            command_file_editors=self.iter_command_file_editors(),
            command_history=self.history_catalog.all_commands(),
            window_width=self.width(),
            window_height=self.height(),
        )
        if not self.settings_service.save(self.settings):
            self.set_status("Could not save settings to disk.")

    def closeEvent(self, event) -> None:
        for editor in self.iter_command_file_editors():
            if not self.confirm_close_command_file_tab(editor):
                event.ignore()
                return
        self.save_settings()
        for session in self.iter_sessions():
            session.shutdown()
        super().closeEvent(event)


def update_boot_splash(message: str):
    try:
        import pyi_splash  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        pyi_splash.update_text(message)
    except Exception:
        return None
    return pyi_splash


def close_boot_splash(boot_splash) -> None:
    if boot_splash is None:
        return
    try:
        boot_splash.close()
    except Exception:
        pass


def create_startup_splash(message: str) -> QSplashScreen:
    width = 520
    height = 320
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor("#111820"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#151c24"))
    painter.drawRoundedRect(18, 18, width - 36, height - 36, 28, 28)
    painter.setBrush(QColor("#1f2933"))
    painter.drawRoundedRect(32, 32, width - 64, height - 64, 22, 22)

    logo = QPixmap(str(APP_ICON_PATH))
    if not logo.isNull():
        logo = logo.scaled(
            QSize(118, 118),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(int((width - logo.width()) / 2), 58, logo)

    title_font = QFont(pick_ui_font())
    title_font.setPointSize(22)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.setPen(QColor("#f4f7fb"))
    painter.drawText(0, 190, width, 36, Qt.AlignmentFlag.AlignCenter, "ComPort Zone")

    body_font = QFont(pick_ui_font())
    body_font.setPointSize(10)
    painter.setFont(body_font)
    painter.setPen(QColor("#9fb0c2"))
    painter.drawText(0, 232, width, 26, Qt.AlignmentFlag.AlignCenter, message)
    painter.setPen(QColor("#4fd1c5"))
    painter.drawLine(210, 274, 310, 274)
    painter.end()

    splash = QSplashScreen(pixmap)
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    QApplication.processEvents()
    return splash


def run() -> int:
    set_windows_app_user_model_id()
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("ComPort Zone")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    app.setFont(pick_ui_font())
    boot_splash = update_boot_splash("Loading ComPort Zone...")
    splash = create_startup_splash("Loading serial workspace...")
    close_boot_splash(boot_splash)
    splash.showMessage(
        "Restoring sessions and settings...",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#9fb0c2"),
    )
    app.processEvents()
    window = MainWindow()
    splash.showMessage(
        "Opening terminal...",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#9fb0c2"),
    )
    window.show()
    splash.finish(window)
    return app.exec()
