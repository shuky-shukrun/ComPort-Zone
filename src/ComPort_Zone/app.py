from __future__ import annotations

import sys

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from . import __version__
from . import quick_actions as _quick_actions
from .models import LanProfile, SerialProfile
from .serial_core import SerialEvent
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


def run(initial_file: str | None = None) -> int:
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
    window.run_startup_actions()
    if initial_file:
        window.open_command_file_editor(initial_file)
    return app.exec()
