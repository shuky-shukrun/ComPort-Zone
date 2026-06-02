from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QApplication, QMenu, QStyle

# Module-level icon tint. Icons are monochrome Tabler glyphs whose stroke color
# must follow the active theme — otherwise the default light gray is invisible on
# the light theme. ``MainWindow.apply_theme`` calls ``set_icon_color(theme.text)``
# and re-tints the persistent buttons; menu/action icons rebuild on open.
_ICON_COLOR = "#d4d4d4"


def set_icon_color(color: str) -> None:
    """Set the default stroke color for newly built icons (call on theme change)."""
    global _ICON_COLOR
    _ICON_COLOR = color


def current_icon_color() -> str:
    return _ICON_COLOR


def _device_pixel_ratio() -> float:
    """Render scale for the primary screen, or 1.0 before a QApplication exists."""
    app = QApplication.instance()
    if app is not None:
        screen = app.primaryScreen()
        if screen is not None:
            return float(screen.devicePixelRatio())
    return 1.0

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


def standard_icon(
    pixmap: QStyle.StandardPixmap,
    size: int = 18,
    color: str | None = None,
) -> QIcon:
    icon_name = STYLE_ICON_MAP.get(pixmap, "info-circle")
    stroke = color if color is not None else _ICON_COLOR
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{stroke}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
        <path stroke="none" d="M0 0h24v24H0z" fill="none" />
        {TABLER_ICON_PATHS[icon_name]}
    </svg>
    """
    # Render at device-pixel resolution so glyphs stay crisp at 125%/150% scaling,
    # then tag the logical size so layout still treats the icon as ``size`` px.
    dpr = _device_pixel_ratio()
    pixels = max(1, round(size * dpr))
    pixmap_icon = QPixmap(pixels, pixels)
    pixmap_icon.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    painter = QPainter(pixmap_icon)
    renderer.render(painter)
    painter.end()
    pixmap_icon.setDevicePixelRatio(dpr)
    return QIcon(pixmap_icon)


class _IconSpec:
    """Remembers how an icon was built so it can be re-tinted on theme change."""

    __slots__ = ("pixmap", "size", "color")

    def __init__(self, pixmap: QStyle.StandardPixmap, size: int, color: str | None) -> None:
        self.pixmap = pixmap
        self.size = size
        self.color = color


# Qt dynamic-property key under which the build spec is stashed on each widget/action.
_ICON_SPEC_PROP = "_comportIconSpec"


def set_button_icon(
    button,
    pixmap: QStyle.StandardPixmap,
    size: int = 16,
    color: str | None = None,
) -> None:
    button.setIcon(standard_icon(pixmap, size, color))
    button.setIconSize(QSize(size, size))
    button.setProperty(_ICON_SPEC_PROP, _IconSpec(pixmap, size, color))


def set_action_icon(
    action,
    pixmap: QStyle.StandardPixmap,
    size: int = 18,
    color: str | None = None,
) -> None:
    """Set a themed icon on a QAction or submenu QMenu and remember it for re-tint."""
    action.setIcon(standard_icon(pixmap, size, color))
    action.setProperty(_ICON_SPEC_PROP, _IconSpec(pixmap, size, color))


def retint_icons(root) -> None:
    """Rebuild every theme-colored icon under ``root`` with the current icon color.

    Qt caches QIcon pixmaps, so persistent buttons, menu-bar actions, and submenu
    icons do not recolor by themselves when the theme changes. We walk the object
    tree and re-issue any icon that was built with the default tint (``color is
    None``); state-colored icons (tab connection glyphs, run targets) keep their
    explicit color and are refreshed by their own state logic.
    """
    children = (
        *root.findChildren(QAbstractButton),
        *root.findChildren(QAction),
        *root.findChildren(QMenu),
    )
    for obj in children:
        spec = obj.property(_ICON_SPEC_PROP)
        if not isinstance(spec, _IconSpec) or spec.color is not None:
            continue
        obj.setIcon(standard_icon(spec.pixmap, spec.size, None))
        if isinstance(obj, QAbstractButton):
            obj.setIconSize(QSize(spec.size, spec.size))
