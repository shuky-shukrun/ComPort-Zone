"""Frameless window chrome: a custom title bar + native edge-resize grips.

The design replaces the native OS title bar with a single VS Code-style row that
carries the app logo, the application menu bar (File/Edit/…), a centred command
palette box, and the Minimize/Maximize/Close buttons. The separate menu row is gone.

Window *management* is delegated to the OS through Qt 6's
``QWindow.startSystemMove`` / ``startSystemResize`` so native Aero-snap, maximize
animations and multi-monitor DPI keep working — we only draw the chrome. Eight thin
grip widgets sit on the window edges/corners because child widgets (the terminal,
panels) would otherwise swallow edge mouse events.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenuBar, QToolButton, QWidget

from ..icons import set_button_icon
from .tokens import APP_ICON, TITLE_BAR_H, WINDOW_BTN_W

# Segoe Fluent Icons (Windows 11) window-control glyphs, with a Windows-10 fallback.
_GLYPH_MIN = ""
_GLYPH_MAX = ""
_GLYPH_RESTORE = ""
_GLYPH_CLOSE = ""
_ICON_FAMILY = "Segoe Fluent Icons"
QFont.insertSubstitution(_ICON_FAMILY, "Segoe MDL2 Assets")

# DWM (Win11) window-attribute + corner-preference constants (dwmapi.h).
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2       # standard app-window radius (~8px)
_DWMWCP_ROUNDSMALL = 3  # tighter radius (~4px), used by menus/tooltips


def apply_rounded_corners(widget: QWidget, *, small: bool = True) -> None:
    """Ask Windows 11's DWM to round a frameless window's outer corners.

    Our chrome is custom (``FramelessWindowHint``), so the OS won't round the
    shell on its own. Setting ``DWMWA_WINDOW_CORNER_PREFERENCE`` to ``ROUND``
    gives the subtle, compositor-anti-aliased Windows 11 radius — minimal and
    elegant — and DWM keeps a maximized window square automatically.

    No-op off win32, on pre-Win11, or if the call is otherwise unavailable. Safe
    to call repeatedly (e.g. on every show); the attribute is idempotent.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        pref = ctypes.c_int(_DWMWCP_ROUNDSMALL if small else _DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(int(widget.winId())),
            ctypes.c_uint(_DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(pref),
            ctypes.sizeof(pref),
        )
    except Exception:
        # Older Windows without the attribute, or a sandbox without dwmapi —
        # square corners are a fine fallback, never worth raising for.
        pass


class TitleBar(QWidget):
    """The single VS Code-style window chrome row."""

    commandPaletteRequested = Signal()

    def __init__(self, window: QWidget, icon_path: Path) -> None:
        super().__init__(window)
        self._window = window
        self._press_pos = None
        self._live = False
        self._menu_bar: QMenuBar | None = None
        self.setObjectName("titleBar")
        self.setFixedHeight(TITLE_BAR_H)

        layout = QHBoxLayout(self)
        self._layout = layout
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(6)

        self.icon_label = QLabel(self)
        pixmap = QPixmap(str(icon_path))
        if not pixmap.isNull():
            self.icon_label.setPixmap(
                pixmap.scaled(
                    APP_ICON,
                    APP_ICON,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        layout.addWidget(self.icon_label)
        # The application menu bar is inserted at index 1 by attach_menu_bar().

        layout.addStretch(1)

        # Centred command palette box (VS Code's "command center"). Clicking it opens
        # the command palette; it hides on a narrow window (see _relayout_chrome).
        self.command_center = QToolButton(self)
        self.command_center.setObjectName("commandCenter")
        self.command_center.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        set_button_icon(self.command_center, "search", 13)
        self.command_center.setText("Search commands…")
        self.command_center.setToolTip("Open the command palette")
        self.command_center.setCursor(Qt.CursorShape.PointingHandCursor)
        self.command_center.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.command_center.clicked.connect(self.commandPaletteRequested)
        layout.addWidget(self.command_center)

        layout.addStretch(1)

        icon_font = QFont(_ICON_FAMILY)
        icon_font.setPointSizeF(9.0)
        self.btn_min = self._window_button(_GLYPH_MIN, icon_font, "windowButton")
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_max = self._window_button(_GLYPH_MAX, icon_font, "windowButton")
        self.btn_max.clicked.connect(self.toggle_maximized)
        self.btn_close = self._window_button(_GLYPH_CLOSE, icon_font, "windowButtonClose")
        self.btn_close.clicked.connect(window.close)
        for button in (self.btn_min, self.btn_max, self.btn_close):
            layout.addWidget(button)

    def _window_button(self, glyph: str, font: QFont, name: str) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName(name)
        button.setText(glyph)
        button.setFont(font)
        button.setFixedSize(WINDOW_BTN_W, TITLE_BAR_H)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.ArrowCursor)
        return button

    def attach_menu_bar(self, menu_bar: QMenuBar) -> None:
        """Place the application menu bar just right of the logo, in this single row."""
        self._menu_bar = menu_bar
        menu_bar.setParent(self)
        self._layout.insertWidget(1, menu_bar)
        self._relayout_chrome()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout_chrome()

    def _relayout_chrome(self) -> None:
        """Hide the command box when the bar can't fit it beside the full menu bar;
        the menus then have room (and overflow into their own dots when narrower)."""
        if self._menu_bar is None:
            return
        margins = self._layout.contentsMargins()
        fixed = margins.left() + margins.right() + self.icon_label.sizeHint().width()
        fixed += sum(button.width() for button in (self.btn_min, self.btn_max, self.btn_close))
        fixed += self._menu_bar.sizeHint().width()
        fixed += self._layout.spacing() * 6
        self.command_center.setVisible(self.width() >= fixed + self.command_center.sizeHint().width())

    # ---- live state -----------------------------------------------------
    def set_subtitle(self, text: str) -> None:
        # The connection context now lives in the status bar / command bar; mirror it
        # into the window title so the taskbar and screen readers still see it.
        self._window.setWindowTitle(f"ComPort Zone - {text}" if text else "ComPort Zone")

    def set_live(self, live: bool) -> None:
        self._live = bool(live)

    def refresh_maximize_glyph(self) -> None:
        self.btn_max.setText(_GLYPH_RESTORE if self._window.isMaximized() else _GLYPH_MAX)

    def toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.refresh_maximize_glyph()

    # ---- drag to move (delegated to the OS) -----------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self._press_pos = None
            handle = self._window.windowHandle()
            if handle is not None and not self._window.isMaximized():
                handle.startSystemMove()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
        super().mouseDoubleClickEvent(event)


_GRIP = 5
_CORNER = 12


class _ResizeGrip(QWidget):
    def __init__(self, window: QWidget, edges: Qt.Edge, cursor: Qt.CursorShape) -> None:
        super().__init__(window)
        self._window = window
        self._edges = edges
        self.setCursor(cursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._window.isMaximized():
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemResize(self._edges)


class WindowResizeGrips(QObject):
    """Eight grips around a frameless window that trigger native edge/corner resize."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        edge = Qt.Edge
        self._specs = [
            (edge.TopEdge, Qt.CursorShape.SizeVerCursor),
            (edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
            (edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
            (edge.RightEdge, Qt.CursorShape.SizeHorCursor),
            (edge.TopEdge | edge.LeftEdge, Qt.CursorShape.SizeFDiagCursor),
            (edge.BottomEdge | edge.RightEdge, Qt.CursorShape.SizeFDiagCursor),
            (edge.TopEdge | edge.RightEdge, Qt.CursorShape.SizeBDiagCursor),
            (edge.BottomEdge | edge.LeftEdge, Qt.CursorShape.SizeBDiagCursor),
        ]
        self._grips = [_ResizeGrip(window, edges, cursor) for edges, cursor in self._specs]
        window.installEventFilter(self)
        self.reposition()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._window and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.WindowStateChange,
        ):
            self.reposition()
        return False

    def reposition(self) -> None:
        width = self._window.width()
        height = self._window.height()
        maximized = self._window.isMaximized() or self._window.isFullScreen()
        grip, corner = _GRIP, _CORNER
        geometries = [
            (corner, 0, width - 2 * corner, grip),               # top
            (corner, height - grip, width - 2 * corner, grip),   # bottom
            (0, corner, grip, height - 2 * corner),              # left
            (width - grip, corner, grip, height - 2 * corner),   # right
            (0, 0, corner, corner),                              # top-left
            (width - corner, height - corner, corner, corner),   # bottom-right
            (width - corner, 0, corner, corner),                 # top-right
            (0, height - corner, corner, corner),                # bottom-left
        ]
        for grip_widget, (x, y, grip_w, grip_h) in zip(self._grips, geometries):
            grip_widget.setGeometry(x, y, max(0, grip_w), max(0, grip_h))
            grip_widget.setVisible(not maximized)
            if not maximized:
                grip_widget.raise_()
