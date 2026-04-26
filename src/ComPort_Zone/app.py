from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Empty
from threading import Event

from PySide6.QtCore import QByteArray, QEvent, QObject, QSize, Qt, QStringListModel, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap, QTextCharFormat, QTextCursor, QTextDocument
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
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QStyle,
    QVBoxLayout,
    QWidget,
    QCompleter,
)
from PySide6.QtSvg import QSvgRenderer

from .batch import (
    BatchParseError,
    BatchRunner,
    find_batch_parameters,
    load_batch_file,
    parse_batch_template,
    parse_hex_payload,
    substitute_batch_parameters,
)
from .history import HistoryStore
from . import __version__
from .models import (
    AppSettings,
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
from .serial_core import SerialClient, SerialEvent, decode_serial_bytes, format_hex_bytes
from .session_log import SessionLogger
from .storage import SettingsStore, default_config_path
from .themes import THEMES, ThemePalette
from .widgets import ChevronComboBox, HistoryLineEdit

COMMON_BAUD_RATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]
SEND_MODES = ("Text", "Hex Bytes")
QUICK_COMMAND_CSV_FIELDS = (
    "label",
    "command",
    "description",
    "send_mode",
    "group",
    "line_ending_override",
)
QUICK_FILE_CSV_FIELDS = ("label", "path")
TERMINAL_FONT_MIN = 8
TERMINAL_FONT_MAX = 24
DRAWER_COLLAPSED_WIDTH = 48
APP_USER_MODEL_ID = "ComPortZone.Terminal"
APP_ICON_PATH = Path(__file__).resolve().parent / "assets" / "comport-zone-icon.png"

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


def set_widget_state(widget: QWidget, state: str) -> None:
    widget.setProperty("state", state)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


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


def quick_group_name(group: str) -> str:
    return group.strip() or "General"


def quick_command_csv_row(command: QuickCommand) -> dict[str, str]:
    return {
        "label": command.label,
        "command": command.command,
        "description": command.description,
        "send_mode": command.send_mode,
        "group": quick_group_name(command.group),
        "line_ending_override": command.line_ending_override,
    }


def quick_command_from_csv_row(row: dict[str, str]) -> QuickCommand | None:
    command_text = str(row.get("command") or row.get("text") or "").strip()
    if not command_text:
        return None
    send_mode = str(row.get("send_mode") or row.get("mode") or "Text").strip() or "Text"
    if send_mode not in SEND_MODES:
        send_mode = "Text"
    line_ending = str(row.get("line_ending_override") or row.get("line_ending") or "").strip()
    if line_ending and line_ending not in LINE_ENDINGS:
        line_ending = ""
    return QuickCommand(
        label=str(row.get("label") or row.get("title") or "").strip() or command_text,
        command=command_text,
        description=str(row.get("description") or row.get("notes") or "").strip(),
        send_mode=send_mode,
        group=quick_group_name(str(row.get("group", ""))),
        line_ending_override=line_ending,
    )


def quick_file_display_text(quick_file: QuickFile) -> str:
    label = quick_file.display_label()
    if label:
        return label
    return Path(quick_file.path).name or quick_file.path


def quick_file_csv_row(quick_file: QuickFile) -> dict[str, str]:
    return {
        "label": quick_file.label,
        "path": quick_file.path,
    }


def quick_file_from_csv_row(row: dict[str, str]) -> QuickFile | None:
    path = str(
        row.get("path")
        or row.get("file")
        or row.get("command_file")
        or row.get("script")
        or ""
    ).strip()
    if not path:
        return None
    label = str(row.get("label") or row.get("title") or "").strip()
    return QuickFile(label=label or Path(path).name, path=path)


@dataclass(slots=True)
class QuickCommandImportOptions:
    replace_existing: bool = False
    skip_duplicates: bool = True


@dataclass(slots=True)
class QuickCommandImportResult:
    imported_count: int = 0
    skipped_count: int = 0

    def status_suffix(self) -> str:
        if self.skipped_count:
            return f", skipped {self.skipped_count} duplicate(s)"
        return ""


@dataclass(slots=True)
class QuickFileImportOptions:
    replace_existing: bool = False
    skip_duplicates: bool = True


@dataclass(slots=True)
class QuickFileImportResult:
    imported_count: int = 0
    skipped_count: int = 0

    def status_suffix(self) -> str:
        if self.skipped_count:
            return f", skipped {self.skipped_count} duplicate(s)"
        return ""


def quick_command_duplicate_key(command: QuickCommand) -> tuple[str, str, str, str]:
    return (
        quick_group_name(command.group).casefold(),
        command.display_label().strip().casefold(),
        command.command.strip(),
        command.send_mode.strip().casefold(),
    )


def clone_quick_command(command: QuickCommand, *, preserve_id: bool) -> QuickCommand:
    fields = {
        "label": command.label,
        "command": command.command,
        "description": command.description,
        "send_mode": command.send_mode,
        "group": command.group,
        "line_ending_override": command.line_ending_override,
        "created_at": command.created_at,
        "updated_at": command.updated_at,
    }
    if preserve_id:
        fields["id"] = command.id
    return QuickCommand(**fields)


def quick_file_duplicate_key(quick_file: QuickFile) -> str:
    return quick_file.path.strip().replace("\\", "/").casefold()


def clone_quick_file(quick_file: QuickFile, *, preserve_id: bool) -> QuickFile:
    fields = {
        "label": quick_file.label,
        "path": quick_file.path,
        "created_at": quick_file.created_at,
        "updated_at": quick_file.updated_at,
    }
    if preserve_id:
        fields["id"] = quick_file.id
    return QuickFile(**fields)


def merge_quick_commands(
    existing: list[QuickCommand],
    imported: list[QuickCommand],
    options: QuickCommandImportOptions,
) -> tuple[list[QuickCommand], QuickCommandImportResult]:
    merged = [] if options.replace_existing else [
        clone_quick_command(command, preserve_id=True)
        for command in existing
    ]
    seen = {quick_command_duplicate_key(command) for command in merged}
    result = QuickCommandImportResult()
    for command in imported:
        if not command.command.strip():
            continue
        key = quick_command_duplicate_key(command)
        if options.skip_duplicates and key in seen:
            result.skipped_count += 1
            continue
        merged.append(clone_quick_command(command, preserve_id=options.replace_existing))
        seen.add(key)
        result.imported_count += 1
    return merged, result


def merge_quick_files(
    existing: list[QuickFile],
    imported: list[QuickFile],
    options: QuickFileImportOptions,
) -> tuple[list[QuickFile], QuickFileImportResult]:
    merged = [] if options.replace_existing else [
        clone_quick_file(quick_file, preserve_id=True)
        for quick_file in existing
    ]
    seen = {quick_file_duplicate_key(quick_file) for quick_file in merged}
    result = QuickFileImportResult()
    for quick_file in imported:
        if not quick_file.path.strip():
            continue
        key = quick_file_duplicate_key(quick_file)
        if options.skip_duplicates and key in seen:
            result.skipped_count += 1
            continue
        merged.append(clone_quick_file(quick_file, preserve_id=options.replace_existing))
        seen.add(key)
        result.imported_count += 1
    return merged, result


@dataclass(slots=True)
class CommandPaletteEntry:
    title: str
    subtitle: str
    callback: Callable[[], None]
    icon: QStyle.StandardPixmap | None = None
    keywords: str = ""

    def searchable_text(self) -> str:
        return f"{self.title} {self.subtitle} {self.keywords}".casefold()


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


class ConnectionStatusLabel(QLabel):
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


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
        self.serial_client = SerialClient()
        self.history_store = HistoryStore(host.history_catalog.all_commands())
        self.logger = SessionLogger()
        self.parameter_prompt_bridge = BatchParameterPromptBridge(self)
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
        self._quick_list_refreshing = False

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

    def to_state(self) -> TerminalSessionState:
        return TerminalSessionState(
            title=self.title,
            title_is_custom=self.title_is_custom,
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
            (QStyle.StandardPixmap.SP_DirOpenIcon, "Quick files", lambda: self._select_drawer_page(1)),
            (QStyle.StandardPixmap.SP_MediaPlay, "Scripts and shortcuts", lambda: self._select_drawer_page(2)),
            (QStyle.StandardPixmap.SP_DriveHDIcon, "Settings", lambda: self._select_drawer_page(3)),
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
        self.drawer_pages.addWidget(self._build_quick_files_page())
        self.drawer_pages.addWidget(self._build_scripts_page())
        self.drawer_pages.addWidget(self._build_settings_page())
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
        self.terminal.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.terminal.customContextMenuRequested.connect(self.show_terminal_context_menu)

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
        self.quick_list.setObjectName("quickCommandList")
        self.quick_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.quick_list.setDragEnabled(True)
        self.quick_list.setAcceptDrops(True)
        self.quick_list.setDropIndicatorShown(True)
        self.quick_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.quick_list.setDragDropOverwriteMode(False)
        self.quick_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.quick_list.setSpacing(1)
        self.quick_list.setUniformItemSizes(True)
        self.quick_list.setToolTip("Right-click a saved command for actions. Press and drag to reorder.")
        self.quick_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.quick_list.itemDoubleClicked.connect(lambda _: self.send_selected_quick_command())
        self.quick_list.customContextMenuRequested.connect(self.show_quick_command_context_menu)
        self.quick_list.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self.persist_quick_command_order))
        self.quick_list.model().rowsInserted.connect(lambda *_: QTimer.singleShot(0, self.persist_quick_command_order))
        self.quick_list.model().rowsRemoved.connect(lambda *_: QTimer.singleShot(0, self.persist_quick_command_order))
        self.quick_sort_combo = ChevronComboBox(page)
        self.quick_sort_combo.setObjectName("quickSortCombo")
        for mode in QUICK_COMMAND_SORT_MODES:
            label = "Custom order" if mode == "Custom" else mode
            self.quick_sort_combo.addItem(label, mode)
        self.quick_sort_combo.setToolTip("Sort quick commands")
        self.quick_sort_combo.currentIndexChanged.connect(self._quick_sort_changed)
        self.quick_group_button = QToolButton(page)
        self.quick_group_button.setObjectName("drawerMenuButton")
        self.quick_group_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_group_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.quick_group_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.quick_group_button.setToolTip("Show or hide quick command groups")
        set_button_icon(self.quick_group_button, QStyle.StandardPixmap.SP_FileDialogListView)
        send = self._drawer_action("Send Selected", QStyle.StandardPixmap.SP_ArrowForward, self.send_selected_quick_command, page, role="drawerPrimary")
        add = self._drawer_action("Add", QStyle.StandardPixmap.SP_FileDialogNewFolder, self.host.add_quick_command, page)
        edit = self._drawer_action("Edit", QStyle.StandardPixmap.SP_FileDialogDetailedView, lambda: self.host.edit_quick_command(self.selected_quick_command_id()), page)
        delete = self._drawer_action("Delete", QStyle.StandardPixmap.SP_TrashIcon, lambda: self.host.delete_quick_command(self.selected_quick_command_id()), page, role="drawerDanger")
        self.quick_move_up_button = self._drawer_action("Move Up", QStyle.StandardPixmap.SP_ArrowUp, lambda: self.host.move_quick_command(self.selected_quick_command_id(), -1), page)
        self.quick_move_down_button = self._drawer_action("Move Down", QStyle.StandardPixmap.SP_ArrowDown, lambda: self.host.move_quick_command(self.selected_quick_command_id(), 1), page)
        layout.addWidget(title)
        layout.addWidget(self._drawer_section("Saved Commands", page))
        filter_line = QHBoxLayout()
        filter_line.setContentsMargins(0, 0, 0, 0)
        filter_line.setSpacing(8)
        filter_line.addWidget(self.quick_sort_combo, 1)
        filter_line.addWidget(self.quick_group_button, 1)
        layout.addLayout(filter_line)
        layout.addWidget(self.quick_list, 1)
        for row in ((send, add), (edit, delete), (self.quick_move_up_button, self.quick_move_down_button)):
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            for button in row:
                line.addWidget(button)
            layout.addLayout(line)
        return page

    def _build_quick_files_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        title = self._drawer_title("Quick Files", page)
        self.quick_file_sort_combo = ChevronComboBox(page)
        self.quick_file_sort_combo.setObjectName("quickFileSortCombo")
        for mode in QUICK_FILE_SORT_MODES:
            label = "Custom order" if mode == "Custom" else mode
            self.quick_file_sort_combo.addItem(label, mode)
        self.quick_file_sort_combo.setToolTip("Sort quick files")
        self.quick_file_sort_combo.currentIndexChanged.connect(self._quick_file_sort_changed)
        self.quick_file_list = QListWidget(page)
        self.quick_file_list.setObjectName("quickFileList")
        self.quick_file_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.quick_file_list.setSpacing(1)
        self.quick_file_list.setUniformItemSizes(True)
        self.quick_file_list.setToolTip("Double-click a saved command file to run it.")
        self.quick_file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.quick_file_list.itemDoubleClicked.connect(lambda _: self.run_selected_quick_file())
        self.quick_file_list.customContextMenuRequested.connect(self.show_quick_file_context_menu)
        send_file = self._drawer_action("Send Selected", QStyle.StandardPixmap.SP_ArrowForward, self.run_selected_quick_file, page, role="drawerPrimary")
        add_file = self._drawer_action("Add File", QStyle.StandardPixmap.SP_FileDialogNewFolder, self.host.add_quick_file, page)
        edit_file = self._drawer_action("Edit", QStyle.StandardPixmap.SP_FileDialogDetailedView, lambda: self.host.edit_quick_file(self.selected_quick_file_id()), page)
        delete_file = self._drawer_action("Delete", QStyle.StandardPixmap.SP_TrashIcon, lambda: self.host.delete_quick_file(self.selected_quick_file_id()), page, role="drawerDanger")
        import_files = self._drawer_action("Import CSV", QStyle.StandardPixmap.SP_DialogOpenButton, self.host.import_quick_files_csv, page)
        export_files = self._drawer_action("Export CSV", QStyle.StandardPixmap.SP_DialogSaveButton, self.host.export_quick_files_csv, page)
        run = self._drawer_action("Run Command File...", QStyle.StandardPixmap.SP_MediaPlay, self.run_script, page)
        stop = self._drawer_action("Stop Command File", QStyle.StandardPixmap.SP_MediaStop, self.stop_script, page)

        layout.addWidget(title)
        layout.addWidget(self._drawer_section("Saved Files", page))
        layout.addWidget(self.quick_file_sort_combo)
        layout.addWidget(self.quick_file_list, 1)
        for row in ((send_file, add_file), (edit_file, delete_file), (import_files, export_files), (run, stop)):
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
        run = self._drawer_action("Run Command File...", QStyle.StandardPixmap.SP_MediaPlay, self.run_script, page)
        stop = self._drawer_action("Stop Command File", QStyle.StandardPixmap.SP_MediaStop, self.stop_script, page)
        log = self._drawer_action("Start / Stop Log", QStyle.StandardPixmap.SP_DialogSaveButton, self.toggle_logging, page)
        clear = self._drawer_action("Clear Terminal", QStyle.StandardPixmap.SP_TrashIcon, self.clear_terminal, page, role="drawerDanger")
        pause = self._drawer_action("Pause / Resume Output", QStyle.StandardPixmap.SP_MediaPause, self.toggle_pause, page)
        save = self._drawer_action("Save Input to Quick Send", QStyle.StandardPixmap.SP_DialogSaveButton, self.save_current_input_as_quick_command, page)
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
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = self._drawer_title("Settings", page)
        description = QLabel(
            "Export or import the complete app setup as a JSON file. "
            "This includes serial defaults, quick commands, quick files, theme, terminal preferences, and restored tabs.",
            page,
        )
        description.setObjectName("drawerHelpText")
        description.setWordWrap(True)
        export_settings = self._drawer_action(
            "Export Settings",
            QStyle.StandardPixmap.SP_DialogSaveButton,
            self.host.export_settings,
            page,
            role="drawerPrimary",
        )
        import_settings = self._drawer_action(
            "Import Settings",
            QStyle.StandardPixmap.SP_DialogOpenButton,
            self.host.import_settings,
            page,
        )
        export_quick = self._drawer_action(
            "Export Quick Commands CSV",
            QStyle.StandardPixmap.SP_DialogSaveButton,
            self.host.export_quick_commands_csv,
            page,
        )
        import_quick = self._drawer_action(
            "Import Quick Commands CSV",
            QStyle.StandardPixmap.SP_DialogOpenButton,
            self.host.import_quick_commands_csv,
            page,
        )
        export_files = self._drawer_action(
            "Export Quick Files CSV",
            QStyle.StandardPixmap.SP_DialogSaveButton,
            self.host.export_quick_files_csv,
            page,
        )
        import_files = self._drawer_action(
            "Import Quick Files CSV",
            QStyle.StandardPixmap.SP_DialogOpenButton,
            self.host.import_quick_files_csv,
            page,
        )
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(self._drawer_section("Settings Bundle", page))
        layout.addWidget(export_settings)
        layout.addWidget(import_settings)
        layout.addSpacing(8)
        layout.addWidget(self._drawer_section("Quick Commands", page))
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        line.addWidget(export_quick)
        line.addWidget(import_quick)
        layout.addLayout(line)
        layout.addSpacing(8)
        layout.addWidget(self._drawer_section("Quick Files", page))
        file_line = QHBoxLayout()
        file_line.setContentsMargins(0, 0, 0, 0)
        file_line.setSpacing(8)
        file_line.addWidget(export_files)
        file_line.addWidget(import_files)
        layout.addLayout(file_line)
        layout.addStretch(1)
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
        groups: list[str] = []
        seen: set[str] = set()
        for command in self.host.settings.quick_commands:
            group = quick_group_name(command.group)
            key = group.casefold()
            if key not in seen:
                groups.append(group)
                seen.add(key)
        return sorted(groups, key=str.casefold)

    def visible_quick_commands(self) -> list[QuickCommand]:
        hidden = {group.casefold() for group in self.host.settings.quick_command_hidden_groups}
        commands = [
            command
            for command in self.host.settings.quick_commands
            if quick_group_name(command.group).casefold() not in hidden
        ]
        mode = self.host.settings.quick_command_sort_mode
        if mode == "Title":
            return sorted(
                commands,
                key=lambda command: (
                    command.display_label().casefold(),
                    quick_group_name(command.group).casefold(),
                    command.command.casefold(),
                ),
            )
        if mode == "Group":
            return sorted(
                commands,
                key=lambda command: (
                    quick_group_name(command.group).casefold(),
                    command.display_label().casefold(),
                    command.command.casefold(),
                ),
            )
        return commands

    def can_manually_reorder_quick_commands(self) -> bool:
        groups = {group.casefold() for group in self.quick_command_groups()}
        hidden_active = any(
            group.casefold() in groups
            for group in self.host.settings.quick_command_hidden_groups
        )
        return self.host.settings.quick_command_sort_mode == "Custom" and not hidden_active

    def refresh_quick_command_controls(self) -> None:
        mode = (
            self.host.settings.quick_command_sort_mode
            if self.host.settings.quick_command_sort_mode in QUICK_COMMAND_SORT_MODES
            else "Custom"
        )
        self.quick_sort_combo.blockSignals(True)
        index = self.quick_sort_combo.findData(mode)
        if index >= 0:
            self.quick_sort_combo.setCurrentIndex(index)
        self.quick_sort_combo.blockSignals(False)

        groups = self.quick_command_groups()
        hidden = {group.casefold() for group in self.host.settings.quick_command_hidden_groups}
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
        quick_files = list(self.host.settings.quick_files)
        mode = self.host.settings.quick_file_sort_mode
        if mode == "Title":
            return sorted(
                quick_files,
                key=lambda quick_file: (
                    quick_file_display_text(quick_file).casefold(),
                    quick_file.path.casefold(),
                ),
            )
        if mode == "Path":
            return sorted(
                quick_files,
                key=lambda quick_file: (
                    quick_file.path.casefold(),
                    quick_file_display_text(quick_file).casefold(),
                ),
            )
        return quick_files

    def refresh_quick_file_controls(self) -> None:
        if not hasattr(self, "quick_file_sort_combo"):
            return
        mode = (
            self.host.settings.quick_file_sort_mode
            if self.host.settings.quick_file_sort_mode in QUICK_FILE_SORT_MODES
            else "Custom"
        )
        self.quick_file_sort_combo.blockSignals(True)
        index = self.quick_file_sort_combo.findData(mode)
        if index >= 0:
            self.quick_file_sort_combo.setCurrentIndex(index)
        self.quick_file_sort_combo.blockSignals(False)

    def selected_quick_command_id(self) -> str:
        item = self.quick_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""

    def quick_command_row(self, command_id: str) -> int:
        for row in range(self.quick_list.count()):
            item = self.quick_list.item(row)
            if str(item.data(Qt.ItemDataRole.UserRole)) == command_id:
                return row
        return -1

    def quick_command_ids_in_list_order(self) -> list[str]:
        return [
            str(self.quick_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.quick_list.count())
        ]

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
                enabled=bool(self.host.settings.quick_commands),
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
            enabled=bool(self.host.settings.quick_commands),
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
        self.quick_list.clear()
        self.refresh_quick_command_controls()
        selected_row = -1
        for command in self.visible_quick_commands():
            label = short_label(command.display_label(), 30)
            group = quick_group_name(command.group)
            item_text = label if not group or group.casefold() == "general" else f"{short_label(group, 10)}: {label}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, command.id)
            tooltip = command.description.strip() or f"{group} | {command.command}"
            item.setToolTip(tooltip)
            item.setSizeHint(QSize(0, 24))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            self.quick_list.addItem(item)
            if command.id == selected_id:
                selected_row = self.quick_list.count() - 1
        if selected_row >= 0:
            self.quick_list.setCurrentRow(selected_row)
        self._quick_list_refreshing = False
        self._update_completion_model()

    def selected_quick_file_id(self) -> str:
        item = self.quick_file_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""

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
                enabled=bool(self.host.settings.quick_files),
            )
            return menu

        menu.setTitle(quick_file_display_text(quick_file))
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
            "Import from CSV",
            self.host.import_quick_files_csv,
            icon=QStyle.StandardPixmap.SP_DialogOpenButton,
        )
        self.host._add_context_action(
            menu,
            "Export to CSV",
            self.host.export_quick_files_csv,
            icon=QStyle.StandardPixmap.SP_DialogSaveButton,
            enabled=bool(self.host.settings.quick_files),
        )
        return menu

    def refresh_quick_files(self, selected_id: str | None = None) -> None:
        if not hasattr(self, "quick_file_list"):
            return
        selected_id = selected_id or self.selected_quick_file_id()
        self.quick_file_list.clear()
        self.refresh_quick_file_controls()
        selected_row = -1
        for quick_file in self.visible_quick_files():
            label = short_label(quick_file_display_text(quick_file), 32)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, quick_file.id)
            item.setToolTip(quick_file.path)
            item.setSizeHint(QSize(0, 24))
            self.quick_file_list.addItem(item)
            if quick_file.id == selected_id:
                selected_row = self.quick_file_list.count() - 1
        if selected_row >= 0:
            self.quick_file_list.setCurrentRow(selected_row)

    def run_selected_quick_file(self) -> None:
        quick_file = self.host.quick_file_by_id(self.selected_quick_file_id())
        if not quick_file:
            return
        self.run_script_path(Path(quick_file.path))

    def refresh_ports(self) -> None:
        self._ports = self.serial_client.list_ports()
        self.host.set_status(f"{len(self._ports)} serial port(s) detected.")
        self._update_connection_ui(self.serial_client.is_connected, update_footer=False)

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
            self._update_connection_ui(self.serial_client.is_connected)
        self.host.save_settings()
        return True

    def toggle_connection(self) -> None:
        retrying = self.serial_client.is_reconnecting
        if self.serial_client.is_connected or retrying:
            self.serial_client.disconnect()
            if retrying:
                self._append_status("Auto-reconnect stopped.")
            self._update_connection_ui(False)
            self.host.save_settings()
            return
        if not self.profile.port:
            self.open_connection_settings(connect_after_accept=True)
            return
        self.host.set_status(f"Connecting to {self.profile.port}...")
        self.serial_client.connect(self.profile)
        self._update_connection_ui(self.serial_client.is_connected)
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
        self.run_script_path(Path(path))

    def run_script_path(self, path: Path) -> None:
        try:
            script_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Run Command File", str(exc))
            return

        parameter_occurrences = find_batch_parameters(script_text)
        if parameter_occurrences:
            parameter_sheet = self._collect_parameter_values(parameter_occurrences)
            if parameter_sheet is None:
                return
            parameter_values, ignored_defaults = parameter_sheet
            template_steps = parse_batch_template(script_text)

            def resolve_line(line: str, line_number: int) -> str | None:
                return substitute_batch_parameters(
                    line,
                    parameter_values,
                    self.parameter_prompt_bridge.prompt,
                    line_number,
                    ignored_defaults,
                )

            self.host.settings.last_script_path = str(path.parent)
            self.batch_runner.start_template(template_steps, resolve_line)
            self.host.set_status(f"Running command file: {path}")
            self.host.save_settings()
            return

        try:
            steps = load_batch_file(path)
        except (BatchParseError, OSError) as exc:
            QMessageBox.critical(self, "Run Command File", str(exc))
            return
        self.host.settings.last_script_path = str(path.parent)
        self.batch_runner.start(steps)
        self.host.set_status(f"Running command file: {path}")
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
        self.batch_runner.stop()

    def toggle_logging(self) -> None:
        if self.logger.enabled:
            path = self.logger.path
            self.logger.close()
            self.log_label.setText("Log off")
            self.host.update_connection_status(self)
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
        self.host.update_connection_status(self)
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
        if event.kind in {"status", "error"}:
            self.host.set_status(event.message)
            self._update_connection_ui(self.serial_client.is_connected, update_footer=False)
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
        if event.kind == "rx" and self.host.settings.receive_display_mode == "Text":
            self._render_rx_text_event(event, colors["rx"])
            return
        if event.kind != "rx":
            self._ensure_terminal_line_break()
        message = self.display_message_for_event(event).replace("\r\n", "\n").replace("\r", "\n")
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

    def _render_rx_text_event(self, event: SerialEvent, color: str) -> None:
        message = self.display_message_for_event(event).replace("\r\n", "\n").replace("\r", "\n")
        if not message:
            return
        rendered = self._timestamp_rx_stream(message, event) if self.host.settings.timestamps_enabled else message
        self._insert_terminal_text(rendered, color)

    def _timestamp_rx_stream(self, message: str, event: SerialEvent) -> str:
        stamp = f"[{event.timestamp.astimezone().strftime('%H:%M:%S.%f')[:-3]}] "
        rendered: list[str] = []
        at_line_start = self._terminal_at_line_start()
        for chunk in message.splitlines(keepends=True):
            if at_line_start and chunk != "\n":
                rendered.append(stamp)
            rendered.append(chunk)
            at_line_start = chunk.endswith("\n")
        return "".join(rendered)

    def _insert_terminal_text(self, text: str, color: str) -> None:
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(text, fmt)
        self.terminal.setTextCursor(cursor)
        self.terminal.ensureCursorVisible()
        if self.search_bar.isVisible():
            self._refresh_search_highlights(self.search_input.text())

    def _terminal_at_line_start(self) -> bool:
        text = self.terminal.toPlainText()
        return not text or text.endswith("\n")

    def _ensure_terminal_line_break(self) -> None:
        if not self._terminal_at_line_start():
            self._insert_terminal_text("\n", self.host.theme.text)

    def display_message_for_event(self, event: SerialEvent) -> str:
        if event.kind != "rx" or not event.raw:
            return event.message
        mode = self.host.settings.receive_display_mode
        if mode == "Hex":
            return format_hex_bytes(event.raw)
        if mode == "Text + Hex":
            return f"{decode_serial_bytes(event.raw)}\nHEX {format_hex_bytes(event.raw)}"
        return decode_serial_bytes(event.raw)

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
        self.settings = self.settings_store.load()
        self.history_catalog = HistoryStore(self.settings.command_history)
        self.theme = THEMES.get(self.settings.theme, THEMES["VS Code Dark"])
        self._session_counter = 0
        self._loading = True

        self.setWindowTitle("ComPort Zone")
        self.setWindowIcon(app_icon())
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
        file_menu = self.menuBar().addMenu("File")
        self._add_action(file_menu, "New Tab", "Ctrl+T", lambda: self.add_session(prompt_settings=True), icon=QStyle.StandardPixmap.SP_FileDialogNewFolder)
        self._add_action(file_menu, "Duplicate Tab", "Ctrl+Shift+T", self.duplicate_current_session, icon=QStyle.StandardPixmap.SP_FileIcon)
        self._add_action(file_menu, "Close Tab", "Ctrl+W", self.close_current_session, icon=QStyle.StandardPixmap.SP_DialogCloseButton)
        file_menu.addSeparator()
        self._add_action(file_menu, "Run Command File", "Ctrl+R", lambda: self.with_session(lambda s: s.run_script()), icon=QStyle.StandardPixmap.SP_MediaPlay)
        self._add_action(file_menu, "Start / Stop Log", "Ctrl+L", lambda: self.with_session(lambda s: s.toggle_logging()), icon=QStyle.StandardPixmap.SP_DialogSaveButton)
        file_menu.addSeparator()
        self._add_action(file_menu, "Import Settings", "", self.import_settings, icon=QStyle.StandardPixmap.SP_DialogOpenButton)
        self._add_action(file_menu, "Export Settings", "", self.export_settings, icon=QStyle.StandardPixmap.SP_DialogSaveButton)
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
        self._add_action(view_menu, "Terminal Font Settings", "", self.show_terminal_font_settings, icon=QStyle.StandardPixmap.SP_FileDialogDetailedView)
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

        tools_menu = self.menuBar().addMenu("Tools")
        self._add_action(tools_menu, "Command Palette", "Ctrl+Shift+P", self.show_command_palette, icon=QStyle.StandardPixmap.SP_CommandLink)
        tools_menu.addSeparator()
        self._add_action(tools_menu, "Send Selected Quick Command", "", lambda: self.with_session(lambda s: s.send_selected_quick_command()), icon=QStyle.StandardPixmap.SP_ArrowForward)
        tools_menu.addSeparator()
        self._add_action(tools_menu, "Add Quick Command", "", self.add_quick_command, icon=QStyle.StandardPixmap.SP_FileDialogNewFolder)
        self._add_action(tools_menu, "Edit Selected Quick Command", "", lambda: self.with_session(lambda s: self.edit_quick_command(s.selected_quick_command_id())), icon=QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self._add_action(tools_menu, "Delete Selected Quick Command", "", lambda: self.with_session(lambda s: self.delete_quick_command(s.selected_quick_command_id())), icon=QStyle.StandardPixmap.SP_TrashIcon)
        tools_menu.addSeparator()
        self._add_action(tools_menu, "Send Selected Quick File", "", lambda: self.with_session(lambda s: s.run_selected_quick_file()), icon=QStyle.StandardPixmap.SP_ArrowForward)
        self._add_action(tools_menu, "Add Quick File", "", self.add_quick_file, icon=QStyle.StandardPixmap.SP_FileDialogNewFolder)
        tools_menu.addSeparator()
        self._add_action(tools_menu, "Import Quick Commands from CSV", "", self.import_quick_commands_csv, icon=QStyle.StandardPixmap.SP_DialogOpenButton)
        self._add_action(tools_menu, "Export Quick Commands to CSV", "", self.export_quick_commands_csv, icon=QStyle.StandardPixmap.SP_DialogSaveButton)
        self._add_action(tools_menu, "Import Quick Files from CSV", "", self.import_quick_files_csv, icon=QStyle.StandardPixmap.SP_DialogOpenButton)
        self._add_action(tools_menu, "Export Quick Files to CSV", "", self.export_quick_files_csv, icon=QStyle.StandardPixmap.SP_DialogSaveButton)

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

    def show_command_palette(self) -> None:
        CommandPaletteDialog(self).exec()

    def command_palette_entries(self) -> list[CommandPaletteEntry]:
        entries = [
            CommandPaletteEntry(
                title="Connect / Disconnect",
                subtitle="Connect, disconnect, or stop auto-reconnect for the active tab",
                callback=lambda: self.with_session(lambda session: session.toggle_connection()),
                icon=QStyle.StandardPixmap.SP_ComputerIcon,
                keywords="serial port open close reconnect stop retry",
            ),
            CommandPaletteEntry(
                title="Serial Settings",
                subtitle="Open COM port, baud rate, line ending, DTR, and RTS settings",
                callback=lambda: self.with_session(lambda session: session.open_connection_settings()),
                icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
                keywords="settings port baud parity stop bits flow control",
            ),
            CommandPaletteEntry(
                title="Run Command File",
                subtitle="Run a SEND / WAIT / HEX command script in the active tab",
                callback=lambda: self.with_session(lambda session: session.run_script()),
                icon=QStyle.StandardPixmap.SP_MediaPlay,
                keywords="script batch file",
            ),
            CommandPaletteEntry(
                title="Send Selected Quick File",
                subtitle="Run the saved command file selected in the left drawer",
                callback=lambda: self.with_session(lambda session: session.run_selected_quick_file()),
                icon=QStyle.StandardPixmap.SP_ArrowForward,
                keywords="script batch file saved quick",
            ),
            CommandPaletteEntry(
                title="Add Quick File",
                subtitle="Save a command file path in the left drawer",
                callback=self.add_quick_file,
                icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
                keywords="script batch file save shortcut",
            ),
            CommandPaletteEntry(
                title="Clear Terminal",
                subtitle="Clear output in the active tab",
                callback=lambda: self.with_session(lambda session: session.clear_terminal()),
                icon=QStyle.StandardPixmap.SP_TrashIcon,
                keywords="clean erase output",
            ),
            CommandPaletteEntry(
                title="Search Terminal",
                subtitle="Search output in the active tab",
                callback=lambda: self.with_session(lambda session: session.show_search()),
                icon=QStyle.StandardPixmap.SP_FileDialogContentsView,
                keywords="find current tab",
            ),
            CommandPaletteEntry(
                title="Terminal Font Settings",
                subtitle="Choose terminal font family and size",
                callback=self.show_terminal_font_settings,
                icon=QStyle.StandardPixmap.SP_FileDialogDetailedView,
                keywords="font family size monospace terminal",
            ),
            CommandPaletteEntry(
                title="Save Current Input as Quick Command",
                subtitle="Save the command input from the active tab into Quick Send",
                callback=lambda: self.with_session(lambda session: session.save_current_input_as_quick_command()),
                icon=QStyle.StandardPixmap.SP_DialogSaveButton,
                keywords="snippet quick send shortcut",
            ),
            CommandPaletteEntry(
                title="Import Settings",
                subtitle="Load a complete ComPort Zone settings JSON file",
                callback=self.import_settings,
                icon=QStyle.StandardPixmap.SP_DialogOpenButton,
                keywords="settings json restore preferences",
            ),
            CommandPaletteEntry(
                title="Export Settings",
                subtitle="Save the complete app setup to a JSON file",
                callback=self.export_settings,
                icon=QStyle.StandardPixmap.SP_DialogSaveButton,
                keywords="settings json backup preferences",
            ),
            CommandPaletteEntry(
                title="Import Quick Commands from CSV",
                subtitle="Append quick commands from a CSV file",
                callback=self.import_quick_commands_csv,
                icon=QStyle.StandardPixmap.SP_DialogOpenButton,
                keywords="quick send snippets commands csv import",
            ),
            CommandPaletteEntry(
                title="Export Quick Commands to CSV",
                subtitle="Save all quick commands to a CSV file",
                callback=self.export_quick_commands_csv,
                icon=QStyle.StandardPixmap.SP_DialogSaveButton,
                keywords="quick send snippets commands csv export",
            ),
            CommandPaletteEntry(
                title="Import Quick Files from CSV",
                subtitle="Append saved command-file paths from a CSV file",
                callback=self.import_quick_files_csv,
                icon=QStyle.StandardPixmap.SP_DialogOpenButton,
                keywords="quick files command files scripts csv import",
            ),
            CommandPaletteEntry(
                title="Export Quick Files to CSV",
                subtitle="Save all saved command-file paths to a CSV file",
                callback=self.export_quick_files_csv,
                icon=QStyle.StandardPixmap.SP_DialogSaveButton,
                keywords="quick files command files scripts csv export",
            ),
        ]
        for index in range(self.tabs.count()):
            session = self.session_at(index)
            title = session.tab_title if session else self.tabs.tabText(index)
            port = session.profile.port if session and session.profile.port else "No port"
            subtitle = session.connection_status_text() if session else port
            entries.append(
                CommandPaletteEntry(
                    title=f"Switch to Tab {index + 1}: {title}",
                    subtitle=subtitle,
                    callback=lambda tab_index=index: self.tabs.setCurrentIndex(tab_index),
                    icon=QStyle.StandardPixmap.SP_ComputerIcon,
                    keywords=f"switch tab terminal session {index + 1} {title} {port} {session.title if session else ''}",
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
            self._add_context_action(
                menu,
                "New Tab",
                lambda: self.add_session(prompt_settings=True),
                icon=QStyle.StandardPixmap.SP_FileDialogNewFolder,
            )
            return menu

        session = self.session_at(index)
        is_connected = bool(session and session.serial_client.is_connected)
        is_reconnecting = bool(session and session.serial_client.is_reconnecting)
        menu.setTitle(session.tab_title if session else self.tabs.tabText(index))
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
            "Disconnect" if is_connected else "Stop Retry" if is_reconnecting else "Connect",
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

    def restore_sessions(self, *, prompt_first_settings: bool = True) -> None:
        states = self.settings.restored_tabs
        if not states:
            self.add_session(
                TerminalSessionState(title="Terminal 1"),
                prompt_settings=False,
            )
            if prompt_first_settings:
                self.prompt_current_session_settings()
            return
        for state in states:
            self.add_session(state, prompt_settings=False)
        if self.tabs.count() == 0:
            self.add_session(prompt_settings=False)

    def add_session(self, state: TerminalSessionState | None = None, *, prompt_settings: bool = True) -> None:
        self._session_counter += 1
        state = state or TerminalSessionState(title=f"Terminal {self._session_counter}")
        session = TerminalSessionWidget(self, self._session_counter, state)
        index = self.tabs.addTab(
            session,
            standard_icon(QStyle.StandardPixmap.SP_ComputerIcon),
            session.tab_title,
        )
        self.attach_tab_close_button(index, session)
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

    def attach_tab_close_button(self, index: int, session: TerminalSessionWidget) -> None:
        close_button = QToolButton(self.tabs.tabBar())
        close_button.setObjectName("tabCloseButton")
        close_button.setAutoRaise(True)
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.setFixedSize(22, 22)
        close_button.setToolTip(f"Close {session.tab_title}")
        set_button_icon(close_button, QStyle.StandardPixmap.SP_DialogCloseButton, 13)
        close_button.clicked.connect(
            lambda _checked=False, target=session: self.close_session(self.tabs.indexOf(target))
        )
        self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, close_button)

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
            TerminalSessionState(
                title=f"{session.tab_title} Copy",
                title_is_custom=True,
                serial=clone_profile(session.profile),
                connected_on_launch=False,
                terminal_text=session.terminal.toPlainText(),
                command_draft=session.command_input.text(),
                send_mode=session.mode_combo.currentText(),
            ),
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
            session.title_is_custom = True
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
            state = session.connection_state()
            color = self.connection_state_color(state)
            icon = QStyle.StandardPixmap.SP_BrowserReload if state == "retrying" else QStyle.StandardPixmap.SP_ComputerIcon
            self.tabs.setTabIcon(index, standard_icon(icon, 18, color))
            self.tabs.setTabToolTip(index, session.connection_status_text())
            self.tabs.tabBar().setTabTextColor(index, QColor(color))

    def sync_status_from_current_session(self) -> None:
        session = self.current_session()
        if session:
            self.update_connection_status(session)

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
            session.history_store = HistoryStore(self.history_catalog.all_commands())
            session.apply_settings()
            session.apply_drawer_state(
                self.settings.drawer_collapsed,
                self.settings.drawer_width,
            )
            session.refresh_quick_commands()
            session.refresh_quick_files()
        self.update_tab_titles()
        self.sync_status_from_current_session()

    def quick_command_by_id(self, command_id: str) -> QuickCommand | None:
        return next((command for command in self.settings.quick_commands if command.id == command_id), None)

    def quick_file_by_id(self, quick_file_id: str) -> QuickFile | None:
        return next((quick_file for quick_file in self.settings.quick_files if quick_file.id == quick_file_id), None)

    def quick_command_group_names(self) -> list[str]:
        groups: list[str] = []
        seen: set[str] = set()
        for command in self.settings.quick_commands:
            group = quick_group_name(command.group)
            key = group.casefold()
            if key not in seen:
                groups.append(group)
                seen.add(key)
        return sorted(groups, key=str.casefold)

    def set_quick_command_sort_mode(self, mode: str) -> None:
        if mode not in QUICK_COMMAND_SORT_MODES:
            mode = "Custom"
        if self.settings.quick_command_sort_mode == mode:
            return
        self.settings.quick_command_sort_mode = mode
        self.refresh_quick_commands_everywhere()
        self.save_settings()

    def set_quick_file_sort_mode(self, mode: str) -> None:
        if mode not in QUICK_FILE_SORT_MODES:
            mode = "Custom"
        if self.settings.quick_file_sort_mode == mode:
            return
        self.settings.quick_file_sort_mode = mode
        self.refresh_quick_files_everywhere()
        self.save_settings()

    def set_quick_command_group_visible(self, group: str, visible: bool) -> None:
        group = quick_group_name(group)
        hidden = [
            hidden_group
            for hidden_group in self.settings.quick_command_hidden_groups
            if hidden_group.casefold() != group.casefold()
        ]
        if not visible:
            hidden.append(group)
        if [item.casefold() for item in hidden] == [
            item.casefold() for item in self.settings.quick_command_hidden_groups
        ]:
            return
        self.settings.quick_command_hidden_groups = hidden
        self.refresh_quick_commands_everywhere()
        self.save_settings()

    def show_all_quick_command_groups(self) -> None:
        if not self.settings.quick_command_hidden_groups:
            return
        self.settings.quick_command_hidden_groups = []
        self.refresh_quick_commands_everywhere()
        self.save_settings()

    def hide_all_quick_command_groups(self) -> None:
        groups = self.quick_command_group_names()
        if [group.casefold() for group in groups] == [
            group.casefold() for group in self.settings.quick_command_hidden_groups
        ]:
            return
        self.settings.quick_command_hidden_groups = groups
        self.refresh_quick_commands_everywhere()
        self.save_settings()

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
            (index for index, existing in enumerate(self.settings.quick_commands) if existing.id == command_id),
            len(self.settings.quick_commands) - 1,
        )
        self.settings.quick_commands.insert(source_index + 1, duplicate)
        self.refresh_quick_commands_everywhere(duplicate.id)
        self.save_settings()

    def delete_quick_command(self, command_id: str) -> None:
        if not command_id:
            return
        self.settings.quick_commands = [command for command in self.settings.quick_commands if command.id != command_id]
        self.refresh_quick_commands_everywhere()
        self.save_settings()

    def copy_quick_command_text(self, command_id: str) -> None:
        command = self.quick_command_by_id(command_id)
        if not command:
            return
        QApplication.clipboard().setText(command.command)
        self.set_status(f"Copied quick command: {short_label(command.display_label(), 32)}")

    def add_quick_file(self, quick_file: QuickFile | None = None) -> None:
        if quick_file is None or isinstance(quick_file, bool):
            dialog = QuickFileDialog(parent=self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            quick_file = dialog.quick_file()
        if not quick_file.path:
            return
        self.settings.quick_files.append(quick_file)
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
        for index, existing in enumerate(self.settings.quick_files):
            if existing.id == updated.id:
                self.settings.quick_files[index] = updated
                break
        self.refresh_quick_files_everywhere(updated.id)
        self.save_settings()

    def delete_quick_file(self, quick_file_id: str) -> None:
        if not quick_file_id:
            return
        self.settings.quick_files = [
            quick_file
            for quick_file in self.settings.quick_files
            if quick_file.id != quick_file_id
        ]
        self.refresh_quick_files_everywhere()
        self.save_settings()

    def show_quick_file_in_explorer(self, quick_file_id: str) -> None:
        quick_file = self.quick_file_by_id(quick_file_id)
        if not quick_file:
            return
        path = Path(quick_file.path)
        if not path.exists():
            QMessageBox.warning(self, "Quick File", f"File not found:\n{path}")
            return
        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
        except OSError as exc:
            QMessageBox.warning(self, "Quick File", str(exc))

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
        options = options or QuickCommandImportOptions()
        with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            if reader.fieldnames is None:
                raise ValueError("CSV file is empty.")
            normalized_names = {name.strip().casefold() for name in reader.fieldnames if name}
            if "command" not in normalized_names and "text" not in normalized_names:
                raise ValueError("CSV must include a 'command' column.")
            imported: list[QuickCommand] = []
            for row in reader:
                normalized_row = {
                    str(key).strip().casefold(): str(value or "")
                    for key, value in row.items()
                    if key is not None
                }
                quick_command = quick_command_from_csv_row(normalized_row)
                if quick_command:
                    imported.append(quick_command)
        if not imported:
            return QuickCommandImportResult()
        self.settings.quick_commands, result = merge_quick_commands(
            self.settings.quick_commands,
            imported,
            options,
        )
        selected_id = self.settings.quick_commands[-1].id if self.settings.quick_commands else ""
        self.refresh_quick_commands_everywhere(selected_id)
        self.save_settings()
        return result

    def export_quick_commands_to_csv(self, path: Path) -> int:
        with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=QUICK_COMMAND_CSV_FIELDS)
            writer.writeheader()
            for command in self.settings.quick_commands:
                writer.writerow(quick_command_csv_row(command))
        return len(self.settings.quick_commands)

    def import_quick_files_from_csv(
        self,
        path: Path,
        *,
        options: QuickFileImportOptions | None = None,
    ) -> QuickFileImportResult:
        options = options or QuickFileImportOptions()
        with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            if reader.fieldnames is None:
                raise ValueError("CSV file is empty.")
            normalized_names = {name.strip().casefold() for name in reader.fieldnames if name}
            if not normalized_names.intersection({"path", "file", "command_file", "script"}):
                raise ValueError("CSV must include a 'path' column.")
            imported: list[QuickFile] = []
            for row in reader:
                normalized_row = {
                    str(key).strip().casefold(): str(value or "")
                    for key, value in row.items()
                    if key is not None
                }
                quick_file = quick_file_from_csv_row(normalized_row)
                if quick_file:
                    imported.append(quick_file)
        if not imported:
            return QuickFileImportResult()
        self.settings.quick_files, result = merge_quick_files(
            self.settings.quick_files,
            imported,
            options,
        )
        selected_id = self.settings.quick_files[-1].id if self.settings.quick_files else ""
        self.refresh_quick_files_everywhere(selected_id)
        self.save_settings()
        return result

    def export_quick_files_to_csv(self, path: Path) -> int:
        with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=QUICK_FILE_CSV_FIELDS)
            writer.writeheader()
            for quick_file in self.settings.quick_files:
                writer.writerow(quick_file_csv_row(quick_file))
        return len(self.settings.quick_files)

    def move_quick_command(self, command_id: str, direction: int) -> None:
        commands = self.settings.quick_commands
        index = next((i for i, command in enumerate(commands) if command.id == command_id), -1)
        target = index + direction
        if index < 0 or target < 0 or target >= len(commands):
            return
        commands[index], commands[target] = commands[target], commands[index]
        self.refresh_quick_commands_everywhere(command_id)
        self.save_settings()

    def reorder_quick_commands(self, command_ids: list[str], *, selected_id: str = "") -> None:
        existing_ids = [command.id for command in self.settings.quick_commands]
        if command_ids == existing_ids:
            return
        commands_by_id = {command.id: command for command in self.settings.quick_commands}
        seen: set[str] = set()
        reordered: list[QuickCommand] = []
        for command_id in command_ids:
            command = commands_by_id.get(command_id)
            if command and command_id not in seen:
                reordered.append(command)
                seen.add(command_id)
        reordered.extend(command for command in self.settings.quick_commands if command.id not in seen)
        if [command.id for command in reordered] == existing_ids:
            return
        self.settings.quick_commands = reordered
        self.refresh_quick_commands_everywhere(selected_id)
        self.save_settings()

    def refresh_quick_commands_everywhere(self, selected_id: str | None = None) -> None:
        for session in self.iter_sessions():
            session.refresh_quick_commands(selected_id)

    def refresh_quick_files_everywhere(self, selected_id: str | None = None) -> None:
        for session in self.iter_sessions():
            session.refresh_quick_files(selected_id)

    def record_command(self, command: str) -> None:
        self.history_catalog.add(command)
        for session in self.iter_sessions():
            session.history_store.add(command)
            session._update_completion_model()
        self.save_settings()

    def import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Settings",
            str(Path.cwd()),
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            imported_settings = self.load_settings_from_json(Path(path))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "Import Settings", str(exc))
            return
        dialog = QuickCommandImportDialog(
            title="Import Settings",
            message=(
                "The settings bundle will replace the app setup. Choose how quick commands should be handled."
            ),
            default_replace=True,
            default_skip_duplicates=False,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        result = self.apply_imported_settings(imported_settings, quick_command_options=dialog.options())
        if not self.settings_store.save(self.settings):
            self.set_status("Could not save imported settings to disk.")
            return
        self.set_status(
            f"Imported settings from {path}. Quick commands: {result.imported_count}"
            f"{result.status_suffix()}."
        )

    def export_settings(self) -> None:
        self.save_settings()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Settings",
            str(Path.cwd() / "comport-zone-settings.json"),
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            self.export_settings_to_json(Path(path))
        except OSError as exc:
            QMessageBox.warning(self, "Export Settings", str(exc))
            return
        self.set_status(f"Exported settings to {path}")

    def load_settings_from_json(self, path: Path) -> AppSettings:
        return AppSettings.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def export_settings_to_json(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.settings.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def apply_imported_settings(
        self,
        settings: AppSettings,
        *,
        quick_command_options: QuickCommandImportOptions | None = None,
    ) -> QuickCommandImportResult:
        quick_command_options = quick_command_options or QuickCommandImportOptions(
            replace_existing=True,
            skip_duplicates=False,
        )
        current_quick_commands = list(self.settings.quick_commands)
        settings.quick_commands, result = merge_quick_commands(
            current_quick_commands,
            settings.quick_commands,
            quick_command_options,
        )
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
        self.history_catalog = HistoryStore(self.settings.command_history)
        self.theme = THEMES.get(self.settings.theme, THEMES["VS Code Dark"])
        self.resize(self.settings.window_width, self.settings.window_height)
        self.restore_sessions(prompt_first_settings=False)
        self._loading = previous_loading
        self.apply_settings_to_ui()
        return result

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
        session = self.current_session()
        if session:
            self.settings.serial = clone_profile(session.profile)
        self.settings.command_history = self.history_catalog.all_commands()
        self.settings.window_width = self.width()
        self.settings.window_height = self.height()
        self.settings.restored_tabs = [session.to_state() for session in self.iter_sessions()]
        if not self.settings_store.save(self.settings):
            self.set_status("Could not save settings to disk.")

    def closeEvent(self, event) -> None:
        self.save_settings()
        for session in self.iter_sessions():
            session.shutdown()
        super().closeEvent(event)


def run() -> int:
    set_windows_app_user_model_id()
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("ComPort Zone")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    app.setFont(pick_ui_font())
    window = MainWindow()
    window.show()
    return app.exec()
