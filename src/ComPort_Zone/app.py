from __future__ import annotations

import faulthandler
import os
import sys

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from . import __version__
from . import quick_actions as _quick_actions
from .models import LanProfile, SerialProfile
from .serial_core import SerialEvent
from .single_instance import SingleInstanceServer, default_instance_key, forward_open_request
from .storage import default_config_path
from .themes import VS_CODE_DARK
from .ui.tokens import RADIUS_LG, SPACE_2XL
from .ui.dialogs import (
    AppSettingsTransferDialog,
    BatchParameterPromptBridge,
    COMMON_BAUD_RATES,
    CommandPaletteDialog,
    ConnectionSettingsDialog,
    QuickCommandDialog,
    QuickCommandImportDialog,
    QuickFileDialog,
    TerminalFontSettingsDialog,
    VersionUpdateDialog,
)
from .ui.fonts import pick_ui_font
from .ui.main_window import APP_ICON_PATH, ConnectionStatusLabel, MainWindow, app_icon, clone_profile
from .ui.terminal_tab import TerminalSessionWidget

APP_USER_MODEL_ID = "ComPortZone.Terminal"

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

# Preserve the historical test/plugin seam where ComPort_Zone.app.default_config_path
# can be monkeypatched before constructing MainWindow.
MainWindow.config_path_supplier = staticmethod(lambda: default_config_path())


# If the GUI thread stalls (a deadlock or a busy-loop), the app would just
# look "stuck" with no clue why. The watchdog below keeps pushing a
# faulthandler "dump after N seconds" deadline forward from the GUI thread;
# while the UI is responsive the dump never fires, but the moment the GUI
# thread stops servicing its timer, the pending dump fires from
# faulthandler's own thread and writes every thread's stack to
# freeze-dump.txt — including the stuck GUI thread — so the hang can be
# diagnosed instead of guessed at.
_FREEZE_WATCHDOG_STALL_S = 10.0
_FREEZE_WATCHDOG_TICK_MS = 2000
_freeze_dump_file = None  # module-level so the handle outlives install_*


def freeze_dump_path():
    return default_config_path().parent / "freeze-dump.txt"


def install_freeze_watchdog(window) -> QTimer | None:
    global _freeze_dump_file
    try:
        path = freeze_dump_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Append so a captured dump survives a relaunch (the user can send
        # the file after force-killing the frozen app).
        _freeze_dump_file = open(path, "a", encoding="utf-8")
        # Point faulthandler at the dump file explicitly. A windowed
        # PyInstaller build has no console, so sys.stderr is None and a
        # bare faulthandler.enable() raises "sys.stderr is None" — which
        # crashed the packaged app on launch. Inside the try so the
        # diagnostic watchdog can never prevent the app from starting.
        faulthandler.enable(file=_freeze_dump_file)
    except Exception:
        return None

    def _heartbeat() -> None:
        faulthandler.cancel_dump_traceback_later()
        faulthandler.dump_traceback_later(
            _FREEZE_WATCHDOG_STALL_S, file=_freeze_dump_file, exit=False
        )

    timer = QTimer(window)
    timer.timeout.connect(_heartbeat)
    timer.start(_FREEZE_WATCHDOG_TICK_MS)
    _heartbeat()
    return timer


def set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        # The icon still works in-window if Windows refuses the taskbar identity call.
        pass


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
    # Settings (and the chosen theme) are not loaded yet, so derive the splash
    # chrome from the default palette and the shared design tokens.
    theme = VS_CODE_DARK
    width = 520
    height = 320
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(theme.window))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    card = SPACE_2XL
    painter.setPen(QPen(QColor(theme.border), 1))
    painter.setBrush(QColor(theme.surface))
    painter.drawRoundedRect(
        card, card, width - 2 * card, height - 2 * card, RADIUS_LG * 2, RADIUS_LG * 2
    )

    logo = QPixmap(str(APP_ICON_PATH))
    if not logo.isNull():
        logo = logo.scaled(
            QSize(96, 96),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(int((width - logo.width()) / 2), 52, logo)

    title_font = QFont(pick_ui_font())
    title_font.setPointSize(22)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.setPen(QColor(theme.text))
    painter.drawText(0, 166, width, 36, Qt.AlignmentFlag.AlignCenter, "ComPort Zone")

    tagline_font = QFont(pick_ui_font())
    tagline_font.setPointSize(10)
    painter.setFont(tagline_font)
    painter.setPen(QColor(theme.muted))
    painter.drawText(
        0, 204, width, 22, Qt.AlignmentFlag.AlignCenter,
        "COM-port terminal for physical devices",
    )
    painter.setPen(QColor(theme.muted))
    painter.drawText(0, 244, width, 22, Qt.AlignmentFlag.AlignCenter, message)

    accent_pen = QPen(QColor(theme.accent), 3)
    accent_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(accent_pen)
    center_x = width // 2
    painter.drawLine(center_x - 60, 280, center_x + 60, 280)
    painter.end()

    splash = QSplashScreen(pixmap)
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    QApplication.processEvents()
    return splash


def run(initial_file: str | None = None, *, initial_files: list[str] | None = None) -> int:
    files = list(initial_files) if initial_files else ([initial_file] if initial_file else [])
    set_windows_app_user_model_id()
    if QApplication.instance() is None:
        # Keep fractional display scales (125%/150%) intact so device-pixel icon
        # rendering stays crisp instead of being rounded to the nearest integer.
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("ComPort Zone")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    app.setFont(pick_ui_font())

    # Single-instance forward: when a file is opened (the .cpz association) while an
    # instance is already running, hand the path(s) to it and exit quietly — no second
    # window, no splash. Done before any UI is built so the forwarded launch is fast.
    instance_key = default_instance_key()
    abs_files = [os.path.abspath(item) for item in files]
    if abs_files and forward_open_request(instance_key, abs_files):
        return 0

    boot_splash = update_boot_splash("Loading ComPort Zone...")
    splash = create_startup_splash("Loading serial workspace...")
    close_boot_splash(boot_splash)
    splash.showMessage(
        "Restoring sessions and settings...",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor(VS_CODE_DARK.muted),
    )
    app.processEvents()
    window = MainWindow(defer_startup_actions=True)
    splash.showMessage(
        "Opening terminal...",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor(VS_CODE_DARK.muted),
    )
    window.show()
    splash.finish(window)
    install_freeze_watchdog(window)
    window.run_startup_actions()

    # Become the primary listener (the first instance — launched however — owns the
    # name). A secondary launch gets False here and just runs as its own window; it
    # won't receive forwards, which is the accepted trade-off of "forward-only".
    instance_server = SingleInstanceServer()
    if instance_server.listen(instance_key):
        instance_server.openRequested.connect(window.handle_forwarded_open)
        window._instance_server = instance_server  # keep a ref for the app's lifetime

    if abs_files:
        window.open_command_files_in_tabs(abs_files)
    result = app.exec()
    # Clean exit: cancel the armed dump so a slow-but-normal shutdown
    # never writes a spurious freeze report.
    faulthandler.cancel_dump_traceback_later()
    return result
