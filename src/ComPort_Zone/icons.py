from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QPolygonF
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

# Icon set transcribed from the design handoff (``project/icons.jsx``) plus a few
# extra glyphs drawn in the same thin-line house style for actions the mockup did
# not enumerate. Each entry is ``(viewbox, stroke_width, body, filled)``; ``filled``
# glyphs paint with ``fill`` and no stroke (e.g. the play triangle).
MOCKUP_ICONS = {
    # --- exact from the handoff ---
    "x":           (12, 1.3, '<path d="M3 3l6 6M9 3l-6 6" />', False),
    "chevron-down": (12, 1.3, '<path d="M3 4.5L6 7.5 9 4.5" />', False),
    "chevron-up":  (12, 1.3, '<path d="M3 7.5L6 4.5 9 7.5" />', False),
    "plug":        (16, 1.3, '<path d="M5 2v3M11 2v3M3.5 5h9v3a4.5 4.5 0 0 1 -9 0V5zM8 12.5V15" />', False),
    "send":        (16, 1.4, '<path d="M2.5 8h9M8 4l4 4-4 4" />', False),
    "arrow-right": (16, 1.4, '<path d="M2.5 8h9M8 4l4 4-4 4" />', False),
    "arrow-left":  (16, 1.4, '<path d="M13.5 8h-9M8 4l-4 4 4 4" />', False),
    "bolt":        (16, 1.2, '<path d="M8.5 1.5L3 9h4l-1 5.5L12 7H7.5l1-5.5z" />', False),
    "file":        (16, 1.2, '<path d="M4 1.5h5l3 3V14a.5 .5 0 0 1 -.5 .5h-7A.5 .5 0 0 1 4 14V1.5z" /><path d="M9 1.5V4.5h3" />', False),
    "term":        (16, 1.2, '<rect x="1.5" y="2.5" width="13" height="11" rx="1.5" /><path d="M4 6l2 2-2 2M8 10.5h4" />', False),
    "cog":         (24, 1.8, '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" /><circle cx="12" cy="12" r="3" />', False),
    "search":      (16, 1.3, '<circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5l3 3" />', False),
    "trash":       (16, 1.2, '<path d="M2.5 4h11M6 4V2.5h4V4M4 4l.6 9.5h6.8L12 4" />', False),
    "save":        (16, 1.2, '<path d="M2.5 2.5h9l2 2v9h-11v-11z" /><path d="M5 2.5v3h5v-3M5 13v-4h6v4" />', False),
    "play":        (16, 0.0, '<path d="M4 3l9 5-9 5V3z" />', True),
    "clock":       (16, 1.2, '<circle cx="8" cy="8" r="6" /><path d="M8 5v3.2L10 10" />', False),
    "arrows":      (16, 1.2, '<path d="M4 6l2-2 2 2M6 4v6M12 10l-2 2-2-2M10 12V6" />', False),
    "hex":         (16, 1.2, '<path d="M8 1.5l5.5 3.2v6.6L8 14.5 2.5 11.3V4.7L8 1.5z" />', False),
    "pin":         (16, 1.2, '<path d="M6 1.5h4l-.5 4 2 2-1 1H5.5l-1-1 2-2L6 1.5zM8 9.5V14.5" />', False),
    # --- house-style extras (not enumerated in the mockup) ---
    "plus":        (16, 1.5, '<path d="M8 3.5v9M3.5 8h9" />', False),
    "pause":       (16, 0.0, '<path d="M4.5 3h2.5v10H4.5zM9 3h2.5v10H9z" />', True),
    "stop":        (16, 0.0, '<rect x="4" y="4" width="8" height="8" rx="1.2" />', True),
    "list":        (16, 1.3, '<path d="M5.5 4h8M5.5 8h8M5.5 12h8M2.8 4h.01M2.8 8h.01M2.8 12h.01" />', False),
    "folder":      (16, 1.3, '<path d="M2 4.5a1 1 0 0 1 1 -1h3l1.5 1.5h5a1 1 0 0 1 1 1V12a1 1 0 0 1 -1 1H3a1 1 0 0 1 -1 -1V4.5z" />', False),
    "copy":        (16, 1.3, '<rect x="5" y="5" width="8" height="8" rx="1.2" /><path d="M3 9.5V4a1 1 0 0 1 1 -1h5" />', False),
    "edit":        (16, 1.3, '<path d="M3 13l1-3 7-7 2 2-7 7-3 1z" /><path d="M9.5 4.5l2 2" />', False),
    "check":       (16, 1.5, '<path d="M3.5 8.5l3 3 6-7" />', False),
    "info":        (16, 1.3, '<circle cx="8" cy="8" r="6.2" /><path d="M8 7.3v3.7M8 5.2h.01" />', False),
    "import":      (16, 1.3, '<path d="M8 2v7M5 6.5l3 3 3-3" /><path d="M3 11.5v1a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-1" />', False),
    "database":    (16, 1.2, '<path d="M2.5 4c0-1 2.5-1.8 5.5-1.8S13.5 3 13.5 4 11 5.8 8 5.8 2.5 5 2.5 4z" /><path d="M2.5 4v8c0 1 2.5 1.8 5.5 1.8s5.5-.8 5.5-1.8V4" />', False),
    "refresh":     (16, 1.3, '<path d="M13 5.5A5.5 5.5 0 0 0 3 6.5M3 3v3.5h3.5" /><path d="M3 10.5A5.5 5.5 0 0 0 13 9.5M13 13v-3.5h-3.5" />', False),
    "sort":        (16, 1.3, '<path d="M3 4.5h10M3 8h6.5M3 11.5h3.5" />', False),
    "star":        (16, 1.3, '<path d="M8 2l1.7 3.9 4.3.4-3.2 2.8 1 4.2L8 11.1 4.2 13.3l1-4.2L2 6.3l4.3-.4z" />', False),
    "star-fill":   (16, 1.0, '<path d="M8 2l1.7 3.9 4.3.4-3.2 2.8 1 4.2L8 11.1 4.2 13.3l1-4.2L2 6.3l4.3-.4z" />', True),
    "wrap":        (24, 1.8, '<path d="M3 6h18M3 12h15a3 3 0 1 1 0 6h-4M16 16l-2 2 2 2M3 18h7" />', False),
}

STYLE_ICON_MAP = {
    QStyle.StandardPixmap.SP_ArrowBack: "arrow-left",
    QStyle.StandardPixmap.SP_ArrowDown: "chevron-down",
    QStyle.StandardPixmap.SP_ArrowForward: "send",
    QStyle.StandardPixmap.SP_ArrowLeft: "arrow-left",
    QStyle.StandardPixmap.SP_ArrowRight: "arrow-right",
    QStyle.StandardPixmap.SP_ArrowUp: "chevron-up",
    QStyle.StandardPixmap.SP_BrowserReload: "refresh",
    QStyle.StandardPixmap.SP_CommandLink: "bolt",
    QStyle.StandardPixmap.SP_ComputerIcon: "term",
    QStyle.StandardPixmap.SP_DialogApplyButton: "check",
    QStyle.StandardPixmap.SP_DialogCloseButton: "x",
    QStyle.StandardPixmap.SP_DialogOpenButton: "import",
    QStyle.StandardPixmap.SP_DialogSaveButton: "save",
    QStyle.StandardPixmap.SP_DirOpenIcon: "file",
    QStyle.StandardPixmap.SP_DriveHDIcon: "database",
    QStyle.StandardPixmap.SP_FileDialogContentsView: "search",
    QStyle.StandardPixmap.SP_FileDialogDetailedView: "edit",
    QStyle.StandardPixmap.SP_FileDialogInfoView: "clock",
    QStyle.StandardPixmap.SP_FileDialogListView: "list",
    QStyle.StandardPixmap.SP_FileDialogNewFolder: "plus",
    QStyle.StandardPixmap.SP_FileIcon: "file",
    QStyle.StandardPixmap.SP_MediaPause: "pause",
    QStyle.StandardPixmap.SP_MediaPlay: "play",
    QStyle.StandardPixmap.SP_MediaStop: "stop",
    QStyle.StandardPixmap.SP_MessageBoxInformation: "info",
    QStyle.StandardPixmap.SP_TitleBarCloseButton: "x",
    QStyle.StandardPixmap.SP_TrashIcon: "trash",
}

# Connection-action button state -> themed icon name. Shared by the terminal command
# bar and the window status-bar action button so the two stay identical:
# Connect/Disconnect read as a power plug, Stop-Retry as a stop square, a vanished
# port as a reconnect arrow, and "no endpoint yet" as the settings cog.
CONNECTION_STATE_ICONS = {
    "connected": "plug",     # Disconnect
    "retrying": "stop",      # Stop Retry
    "missing": "refresh",    # Reconnect (port dropped out)
    "no-port": "cog",        # Set Port / Set Endpoint
    "closed": "plug",        # Connect
}


def connection_state_icon(state: str) -> str:
    """Themed icon name for a connection-action button in ``state``."""
    return CONNECTION_STATE_ICONS.get(state, "plug")


def _icon_svg(name: str, size: int, stroke: str) -> str:
    viewbox, stroke_width, body, filled = MOCKUP_ICONS.get(name, MOCKUP_ICONS["info"])
    if filled:
        paint = f'fill="{stroke}" stroke="none"'
    else:
        paint = (
            f'fill="none" stroke="{stroke}" stroke-width="{stroke_width}" '
            'stroke-linecap="round" stroke-linejoin="round"'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {viewbox} {viewbox}" {paint}>{body}</svg>'
    )


def themed_icon(name: str, size: int = 16, color: str | None = None) -> QIcon:
    """Build a themed mockup icon by name (e.g. ``"bolt"``, ``"play"``)."""
    stroke = color if color is not None else _ICON_COLOR
    return _render_svg_icon(_icon_svg(name, size, stroke), size)


def standard_icon(
    pixmap: QStyle.StandardPixmap,
    size: int = 18,
    color: str | None = None,
) -> QIcon:
    icon_name = STYLE_ICON_MAP.get(pixmap, "info")
    stroke = color if color is not None else _ICON_COLOR
    svg = _icon_svg(icon_name, size, stroke)
    return _render_svg_icon(svg, size)


def _render_svg_icon(svg: str, size: int) -> QIcon:
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


def build_icon(source, size: int = 18, color: str | None = None) -> QIcon:
    """Build a themed icon from a mockup icon name (str) or a ``QStyle`` pixmap enum."""
    if isinstance(source, str):
        return themed_icon(source, size, color)
    return standard_icon(source, size, color)


_CHECKBOX_CACHE: dict[tuple, str] = {}


def checked_checkbox_image_path(
    accent: str, check_color: str = "#ffffff", size: int = 16, radius: int = 4
) -> str:
    """Render a checked checkbox indicator (accent rounded square + tick) to a cached
    PNG and return a forward-slashed path for QSS ``image: url(...)``.

    QSS-styled ``QCheckBox::indicator`` rules drop the native tick, so the checked
    state needs an explicit image — a flat tick reads far better than a bare square.
    """
    key = (accent, check_color, size, radius)
    cached = _CHECKBOX_CACHE.get(key)
    if cached and os.path.exists(cached):
        return cached
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(accent))
    painter.drawRoundedRect(0, 0, size, size, radius, radius)
    inset = round(size * 0.16)
    QSvgRenderer(QByteArray(_icon_svg("check", size, check_color).encode("utf-8"))).render(
        painter, QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    )
    painter.end()
    cache_dir = Path(tempfile.gettempdir()) / "comport-zone-ui"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"checkbox-{accent.lstrip('#')}-{check_color.lstrip('#')}-{size}.png"
    pixmap.save(str(path), "PNG")
    result = str(path).replace("\\", "/")
    _CHECKBOX_CACHE[key] = result
    return result


_ARROW_CACHE: dict[tuple, str] = {}


def scrollbar_arrow_image_path(direction: str, color: str, size: int = 9) -> str:
    """Render a small filled scrollbar arrow (up/down/left/right) to a cached PNG
    and return a forward-slashed path for QSS ``image: url(...)``.

    QSS-styled ``QScrollBar`` sub-controls drop the native arrows, so the two
    arrow buttons need explicit images to show their glyphs."""
    key = (direction, color, size)
    cached = _ARROW_CACHE.get(key)
    if cached and os.path.exists(cached):
        return cached
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    m = size * 0.26  # inset from the edges so the triangle isn't clipped
    far = size - m
    mid = size / 2
    if direction == "up":
        points = [(mid, m), (far, far), (m, far)]
    elif direction == "down":
        points = [(m, m), (far, m), (mid, far)]
    elif direction == "left":
        points = [(m, mid), (far, m), (far, far)]
    else:  # right
        points = [(m, m), (far, mid), (m, far)]
    painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    painter.end()
    cache_dir = Path(tempfile.gettempdir()) / "comport-zone-ui"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"scroll-{direction}-{color.lstrip('#')}-{size}.png"
    pixmap.save(str(path), "PNG")
    result = str(path).replace("\\", "/")
    _ARROW_CACHE[key] = result
    return result


class _IconSpec:
    """Remembers how an icon was built so it can be re-tinted on theme change."""

    __slots__ = ("source", "size", "color")

    def __init__(self, source, size: int, color: str | None) -> None:
        self.source = source
        self.size = size
        self.color = color


# Qt dynamic-property key under which the build spec is stashed on each widget/action.
_ICON_SPEC_PROP = "_comportIconSpec"


def set_button_icon(
    button,
    source,
    size: int = 16,
    color: str | None = None,
) -> None:
    button.setIcon(build_icon(source, size, color))
    button.setIconSize(QSize(size, size))
    button.setProperty(_ICON_SPEC_PROP, _IconSpec(source, size, color))


def set_action_icon(
    action,
    source,
    size: int = 18,
    color: str | None = None,
) -> None:
    """Set a themed icon on a QAction or submenu QMenu and remember it for re-tint."""
    action.setIcon(build_icon(source, size, color))
    action.setProperty(_ICON_SPEC_PROP, _IconSpec(source, size, color))


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
        obj.setIcon(build_icon(spec.source, spec.size, None))
        if isinstance(obj, QAbstractButton):
            obj.setIconSize(QSize(spec.size, spec.size))
