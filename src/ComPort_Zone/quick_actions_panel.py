from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Property, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .models import QuickCommand, QuickFile
from .icons import build_icon, set_button_icon, standard_icon, themed_icon
from .quick_actions import quick_file_display_text, quick_group_name
from .themes import COMPORT_DARK, VS_CODE_DARK, ThemePalette

# Per-row data roles consumed by QuickRowDelegate (primary text stays in DisplayRole).
ROLE_ID = Qt.ItemDataRole.UserRole
ROLE_BADGE = Qt.ItemDataRole.UserRole + 1
ROLE_SECONDARY = Qt.ItemDataRole.UserRole + 2
ROLE_KIND = Qt.ItemDataRole.UserRole + 3  # "command" | "file" | "history"
ROLE_FAVORITE = Qt.ItemDataRole.UserRole + 4  # bool: command row is favourited (star fill)

# Each row carries one or more right-aligned inline action glyphs, hit-tested by
# QuickActionList and emitted via actionTriggered(item, key).
ACTION_W = 24
ACTION_ICON = 14


def row_action_keys(kind: str, favorite: bool = False) -> list[str]:
    """Inline action keys for a row, ordered left-to-right (send stays rightmost).

    * saved / favourite command -> star (favourite toggle) + send
    * quick file                -> play
    * history                   -> remove · favourite · save · send
    """
    if kind == "file":
        return ["play"]
    if kind == "history":
        return ["remove", "favorite", "save", "send"]
    return ["star", "send"]


def action_zones(rect: QRect, count: int) -> list[QRect]:
    """Right-aligned hit/paint zones for ``count`` inline actions in ``rect``."""
    cluster_left = rect.right() - count * ACTION_W
    return [
        QRect(cluster_left + i * ACTION_W, rect.top(), ACTION_W, rect.height())
        for i in range(count)
    ]

QUICK_ACTION_ITEM_HEIGHT = 32
FAVORITES_EMPTY_HINT = "No favorites yet — click the star icon next to saved commands or history items to add them."
QUICK_FILE_EMPTY_HINT = "No quick files yet — click “Add File” to add one."


def short_list_label(text: str, limit: int | None = None) -> str:
    text = text.strip()
    if limit is None or len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


class EmptyHintListWidget(QListWidget):
    """A ``QListWidget`` that paints a centered, muted hint while it has no rows.

    The hint is drawn straight onto the viewport rather than inserted as a
    sentinel item, so row-reading helpers such as :func:`item_ids_in_order`
    keep returning only genuine entries when the list is empty.
    """

    def __init__(
        self,
        *,
        placeholder_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._placeholder_text = placeholder_text
        self._placeholder_color = QColor(VS_CODE_DARK.muted)

    def placeholderText(self) -> str:
        return self._placeholder_text

    def _placeholder_color_value(self) -> QColor:
        return QColor(self._placeholder_color)

    def _set_placeholder_color(self, color: QColor) -> None:
        self._placeholder_color = QColor(color)
        if self.count() == 0:
            self.viewport().update()

    # Exposed to QSS as ``qproperty-placeholderColor`` so the hint tracks the
    # active theme's muted color whenever the stylesheet is reapplied.
    placeholderColor = Property(QColor, _placeholder_color_value, _set_placeholder_color)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self.count() != 0 or not self._placeholder_text:
            return
        painter = QPainter(self.viewport())
        painter.setPen(self._placeholder_color)
        flags = int(Qt.AlignmentFlag.AlignCenter.value | Qt.TextFlag.TextWordWrap.value)
        painter.drawText(
            self.viewport().rect().adjusted(16, 0, -16, 0),
            flags,
            self._placeholder_text,
        )
        painter.end()


def _hover_bg(palette: ThemePalette) -> str:
    return getattr(palette, "hover", "") or palette.surface_alt


def _faint(palette: ThemePalette) -> str:
    return palette.text_faint or palette.muted


class QuickRowDelegate(QStyledItemDelegate):
    """Paints quick-action rows: ``[badge|icon] primary · secondary    ⟶/▶``.

    The right-aligned glyph (send arrow for commands/history, play triangle for
    files) is a live affordance — :class:`QuickActionList` hit-tests it and emits
    ``actionTriggered`` without disturbing selection or drag-reorder.
    """

    def __init__(self, palette: ThemePalette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.palette = palette
        self.hover_row = -1
        self.hover_action = -1  # index into the row's action list, -1 = none

    def set_palette(self, palette: ThemePalette) -> None:
        self.palette = palette

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, QUICK_ACTION_ITEM_HEIGHT)

    def _font(self, delta: float = 0.0, *, bold: bool = False) -> QFont:
        font = QFont("Cascadia Mono")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSizeF(9.5 + delta)
        font.setBold(bold)
        return font

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = self.palette
        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = index.row() == self.hover_row

        body = rect.adjusted(2, 1, -2, -1)
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal.search_highlight if selected else _hover_bg(pal)))
            painter.drawRoundedRect(body, 5, 5)

        kind = index.data(ROLE_KIND) or "command"
        badge = index.data(ROLE_BADGE) or ""
        primary = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        secondary = str(index.data(ROLE_SECONDARY) or "")
        cy = rect.center().y()
        x = rect.left() + 11

        if kind == "file":
            painter.drawPixmap(x, cy - 7, standard_icon(QStyle.StandardPixmap.SP_FileIcon, 14, pal.rx).pixmap(14, 14))
            x += 23
        elif kind == "history":
            painter.drawPixmap(x, cy - 7, standard_icon(QStyle.StandardPixmap.SP_FileDialogInfoView, 13, pal.muted).pixmap(13, 13))
            x += 22
        elif badge:
            bfont = self._font(-1.5, bold=True)
            painter.setFont(bfont)
            badge_w = QFontMetrics(bfont).horizontalAdvance(badge) + 12
            badge_rect = QRect(x, cy - 8, badge_w, 16)
            painter.setPen(QColor(pal.border))
            painter.setBrush(QColor(pal.field))
            painter.drawRoundedRect(badge_rect, 3, 3)
            painter.setPen(QColor(pal.muted))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge)
            x += badge_w + 9

        # One or more right-aligned inline affordances (always visible, muted; the
        # one under the cursor lights up). Star toggles favourite, send/play act.
        favorite = bool(index.data(ROLE_FAVORITE))
        actions = row_action_keys(kind, favorite)
        zones = action_zones(rect, len(actions))
        for action_index, (key, zone) in enumerate(zip(actions, zones)):
            self._paint_action(painter, zone, key, favorite, hovered and action_index == self.hover_action, pal)

        text_left = x
        text_right = (zones[0].left() if zones else rect.right()) - 4
        avail = max(10, text_right - text_left)
        pfont = self._font()
        painter.setFont(pfont)
        pfm = QFontMetrics(pfont)
        shown = pfm.elidedText(primary, Qt.TextElideMode.ElideRight, avail)
        painter.setPen(QColor(pal.text))
        painter.drawText(
            QRect(text_left, rect.top(), avail, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            shown,
        )
        if secondary:
            sx = text_left + pfm.horizontalAdvance(shown) + 9
            if sx < text_right - 24:
                sfont = self._font(-1.0)
                painter.setFont(sfont)
                sfm = QFontMetrics(sfont)
                sec = sfm.elidedText("· " + secondary, Qt.TextElideMode.ElideRight, text_right - sx)
                painter.setPen(QColor(pal.muted))
                painter.drawText(
                    QRect(sx, rect.top(), text_right - sx, rect.height()),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    sec,
                )
        painter.restore()

    def _paint_action(self, painter, zone: QRect, key: str, favorite: bool, on: bool, pal: ThemePalette) -> None:
        if key == "send":
            name, color = "send", (pal.accent if on else pal.muted)
        elif key == "play":
            name, color = "play", (pal.tx if on else pal.muted)
        elif key == "star":
            name = "star-fill" if favorite else "star"
            color = (pal.accent if on else pal.status) if favorite else (pal.status if on else pal.muted)
        elif key == "favorite":
            name, color = "star", (pal.status if on else pal.muted)
        elif key == "save":
            name, color = "plus", (pal.accent if on else pal.muted)
        elif key == "remove":
            name, color = "x", (pal.error if on else pal.muted)
        else:
            return
        pix = themed_icon(name, ACTION_ICON, color).pixmap(ACTION_ICON, ACTION_ICON)
        painter.drawPixmap(zone.center().x() - ACTION_ICON // 2, zone.center().y() - ACTION_ICON // 2, pix)


class QuickActionList(EmptyHintListWidget):
    """Quick-action list whose rows expose inline action affordances."""

    # Emitted with the row item and the action key ("send"/"star"/"play"/
    # "favorite"/"save"/"remove") of the clicked inline glyph.
    actionTriggered = Signal(QListWidgetItem, str)

    def __init__(
        self,
        *,
        placeholder_text: str = "",
        palette: ThemePalette | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(placeholder_text=placeholder_text, parent=parent)
        self.row_delegate = QuickRowDelegate(palette or COMPORT_DARK, self)
        self.setItemDelegate(self.row_delegate)
        self.setMouseTracking(True)

    def apply_theme_palette(self, palette: ThemePalette) -> None:
        self.row_delegate.set_palette(palette)
        self.viewport().update()

    def _row_action_keys(self, index) -> list[str]:
        return row_action_keys(str(index.data(ROLE_KIND) or "command"), bool(index.data(ROLE_FAVORITE)))

    def _hit_test(self, pos) -> tuple[int, int]:
        """Return (row, action_index); action_index is -1 when not over a glyph."""
        index = self.indexAt(pos)
        if not index.isValid():
            return -1, -1
        zones = action_zones(self.visualRect(index), len(self._row_action_keys(index)))
        for action_index, zone in enumerate(zones):
            if zone.contains(pos):
                return index.row(), action_index
        return index.row(), -1

    def mouseMoveEvent(self, event) -> None:
        row, action = self._hit_test(event.position().toPoint())
        delegate = self.row_delegate
        if row != delegate.hover_row or action != delegate.hover_action:
            delegate.hover_row = row
            delegate.hover_action = action
            self.viewport().update()
        self.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if action >= 0 else Qt.CursorShape.ArrowCursor
        )
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self.row_delegate.hover_row = -1
        self.row_delegate.hover_action = -1
        self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            row, action = self._hit_test(event.position().toPoint())
            if action >= 0 and row >= 0:
                item = self.item(row)
                if item is not None:
                    keys = row_action_keys(
                        str(item.data(ROLE_KIND) or "command"), bool(item.data(ROLE_FAVORITE))
                    )
                    if 0 <= action < len(keys):
                        self.actionTriggered.emit(item, keys[action])
                event.accept()
                return
        super().mousePressEvent(event)


def create_quick_command_list(
    parent: QWidget,
    *,
    tooltip: str,
    double_clicked: Callable[[], None] | None = None,
    context_menu_requested: Callable | None = None,
    drag_drop: bool = False,
) -> QListWidget:
    quick_list = QuickActionList(placeholder_text=FAVORITES_EMPTY_HINT, parent=parent)
    quick_list.setObjectName("quickCommandList")
    configure_quick_list(
        quick_list,
        tooltip=tooltip,
        double_clicked=double_clicked,
        context_menu_requested=context_menu_requested,
        drag_drop=drag_drop,
    )
    return quick_list


def create_quick_file_list(
    parent: QWidget,
    *,
    tooltip: str,
    double_clicked: Callable[[], None] | None = None,
    context_menu_requested: Callable | None = None,
    drag_drop: bool = False,
) -> QListWidget:
    quick_list = QuickActionList(placeholder_text=QUICK_FILE_EMPTY_HINT, parent=parent)
    quick_list.setObjectName("quickFileList")
    configure_quick_list(
        quick_list,
        tooltip=tooltip,
        double_clicked=double_clicked,
        context_menu_requested=context_menu_requested,
        drag_drop=drag_drop,
    )
    return quick_list


def create_quick_history_list(
    parent: QWidget,
    *,
    tooltip: str,
    double_clicked: Callable[[], None] | None = None,
    context_menu_requested: Callable | None = None,
) -> QuickActionList:
    quick_list = QuickActionList(placeholder_text="No commands sent yet.", parent=parent)
    quick_list.setObjectName("quickHistoryList")
    configure_quick_list(
        quick_list,
        tooltip=tooltip,
        double_clicked=double_clicked,
        context_menu_requested=context_menu_requested,
        drag_drop=False,
    )
    return quick_list


def configure_quick_list(
    quick_list: QListWidget,
    *,
    tooltip: str,
    double_clicked: Callable[[], None] | None = None,
    context_menu_requested: Callable | None = None,
    drag_drop: bool = False,
) -> None:
    # The list's own background is transparent, but its scroll viewport otherwise
    # falls back to the base colour; name it so the side panel tone shows through.
    quick_list.viewport().setObjectName("drawerListViewport")
    quick_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    quick_list.setDragEnabled(drag_drop)
    quick_list.setAcceptDrops(drag_drop)
    quick_list.setDropIndicatorShown(drag_drop)
    quick_list.setDragDropOverwriteMode(False)
    quick_list.setSpacing(1)
    quick_list.setUniformItemSizes(True)
    quick_list.setToolTip(tooltip)
    if drag_drop:
        quick_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        quick_list.setDefaultDropAction(Qt.DropAction.MoveAction)
    else:
        quick_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
    if double_clicked:
        quick_list.itemDoubleClicked.connect(lambda _: double_clicked())
    if context_menu_requested:
        quick_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        quick_list.customContextMenuRequested.connect(context_menu_requested)


def selected_item_id(quick_list: QListWidget) -> str:
    item = quick_list.currentItem()
    return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""


def row_for_item_id(quick_list: QListWidget, item_id: str) -> int:
    for row in range(quick_list.count()):
        item = quick_list.item(row)
        if str(item.data(Qt.ItemDataRole.UserRole)) == item_id:
            return row
    return -1


def item_ids_in_order(quick_list: QListWidget) -> list[str]:
    return [
        str(quick_list.item(row).data(Qt.ItemDataRole.UserRole))
        for row in range(quick_list.count())
    ]


def populate_quick_command_list(
    quick_list: QListWidget,
    commands: Iterable[QuickCommand],
    *,
    selected_id: str = "",
    label_limit: int | None = None,
    group_limit: int | None = None,
    item_height: int | None = QUICK_ACTION_ITEM_HEIGHT,
    draggable: bool = False,
) -> int:
    quick_list.clear()
    selected_row = -1
    for command in commands:
        if not command.command:
            continue
        label = short_list_label(command.display_label(), label_limit)
        group = quick_group_name(command.group)
        item = QListWidgetItem(label)
        item.setData(ROLE_ID, command.id)
        item.setData(ROLE_KIND, "command")
        item.setData(
            ROLE_BADGE,
            "" if group.casefold() == "general" else short_list_label(group, group_limit),
        )
        item.setData(ROLE_SECONDARY, command.description.strip())
        item.setData(ROLE_FAVORITE, bool(command.favorite))
        item.setToolTip(command.description.strip() or f"{group} | {command.command}")
        if item_height is not None:
            item.setSizeHint(QSize(0, item_height))
        if draggable:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
        quick_list.addItem(item)
        if command.id == selected_id:
            selected_row = quick_list.count() - 1
    if selected_row >= 0:
        quick_list.setCurrentRow(selected_row)
    return selected_row


def populate_quick_file_list(
    quick_list: QListWidget,
    quick_files: Iterable[QuickFile],
    *,
    selected_id: str = "",
    label_limit: int | None = None,
    item_height: int | None = QUICK_ACTION_ITEM_HEIGHT,
    draggable: bool = False,
) -> int:
    quick_list.clear()
    selected_row = -1
    for quick_file in quick_files:
        if not quick_file.path:
            continue
        label = short_list_label(quick_file_display_text(quick_file), label_limit)
        item = QListWidgetItem(label or Path(quick_file.path).name or quick_file.path)
        item.setData(ROLE_ID, quick_file.id)
        item.setData(ROLE_KIND, "file")
        item.setData(ROLE_SECONDARY, Path(quick_file.path).parent.name)
        item.setToolTip(quick_file.path)
        if item_height is not None:
            item.setSizeHint(QSize(0, item_height))
        if draggable:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
        quick_list.addItem(item)
        if quick_file.id == selected_id:
            selected_row = quick_list.count() - 1
    if selected_row >= 0:
        quick_list.setCurrentRow(selected_row)
    return selected_row


def populate_quick_history_list(
    quick_list: QListWidget,
    commands: Iterable[str],
    *,
    item_height: int | None = QUICK_ACTION_ITEM_HEIGHT,
) -> None:
    quick_list.clear()
    for index, command in enumerate(commands):
        text = command.strip()
        if not text:
            continue
        item = QListWidgetItem(text)
        item.setData(ROLE_ID, str(index))
        item.setData(ROLE_KIND, "history")
        item.setToolTip(text)
        if item_height is not None:
            item.setSizeHint(QSize(0, item_height))
        quick_list.addItem(item)


class _ElidedLabel(QLabel):
    """A label that elides to its current width and never demands its full text
    width — so it yields space to the header's controls and shows ``…`` instead of
    a hard clip when the dock is narrow."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._apply_elision()

    def setText(self, text: str) -> None:  # type: ignore[override]
        self._full_text = text
        self._apply_elision()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        metrics = QFontMetrics(self.font())
        QLabel.setText(self, metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(0, self.width())))


class QuickActionsPanel(QFrame):
    def __init__(
        self,
        *,
        title: str,
        quick_list: QListWidget,
        header_icon: QStyle.StandardPixmap | str | None = None,
        header_buttons: tuple[QWidget, ...] = (),
        collapsible_buttons: tuple[QWidget, ...] = (),
        controls: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("quickActionPage")
        # Low floor so the dock can be narrow (the row send/play glyph and the
        # header +/⋯ stay visible; the title elides). Fills the dock width.
        self.setMinimumWidth(132)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.quick_list = quick_list
        # Buttons that fold into the ⋯ overflow when the header runs out of room.
        self._collapsible_buttons = tuple(collapsible_buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QFrame(self)
        header.setObjectName("quickPanelHeader")
        self._header = header
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 0, 5, 0)
        header_layout.setSpacing(4)
        self._header_pinned: list[QWidget] = []
        if header_icon is not None:
            icon_label = QLabel(header)
            icon_label.setObjectName("quickPanelIcon")
            icon_label.setPixmap(build_icon(header_icon, 13).pixmap(13, 13))
            header_layout.addWidget(icon_label)
            self._header_pinned.append(icon_label)
        # The title elides and yields width so the header's controls stay on one row.
        title_label = _ElidedLabel(title.upper(), header)
        title_label.setObjectName("quickPanelTitle")
        header_layout.addWidget(title_label, 1)
        self.count_label = QLabel("0", header)
        self.count_label.setObjectName("quickPanelCount")
        header_layout.addWidget(self.count_label)
        self._header_pinned.append(self.count_label)
        for button in self._collapsible_buttons:
            header_layout.addWidget(button)
        for button in header_buttons:
            header_layout.addWidget(button)
            self._header_pinned.append(button)
        layout.addWidget(header)

        if controls is not None:
            controls_holder = QWidget(self)
            controls_holder.setObjectName("drawerContent")
            controls_layout = QVBoxLayout(controls_holder)
            controls_layout.setContentsMargins(8, 0, 8, 0)
            controls_layout.setSpacing(6)
            controls_layout.addWidget(controls)
            layout.addWidget(controls_holder)

        list_holder = QWidget(self)
        list_holder.setObjectName("drawerContent")
        list_layout = QVBoxLayout(list_holder)
        list_layout.setContentsMargins(4, 0, 4, 6)
        list_layout.setSpacing(0)
        list_layout.addWidget(self.quick_list)
        layout.addWidget(list_holder, 1)

        model = quick_list.model()
        model.rowsInserted.connect(self._update_count)
        model.rowsRemoved.connect(self._update_count)
        model.modelReset.connect(self._update_count)
        self._update_count()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout_header()

    def _relayout_header(self) -> None:
        """Fold the collapsible header buttons away when the row is too narrow."""
        if not self._collapsible_buttons:
            return
        header_layout = self._header.layout()
        margins = header_layout.contentsMargins()
        spacing = header_layout.spacing()
        # Collapse only when even an elided title can't keep the buttons on one row:
        # room for the pinned bits + the collapsible icons + a sliver of title.
        needed = margins.left() + margins.right() + 10
        for widget in (*self._header_pinned, *self._collapsible_buttons):
            needed += widget.sizeHint().width() + spacing
        collapse = self._header.width() < needed
        for widget in self._collapsible_buttons:
            widget.setVisible(not collapse)

    def _update_count(self, *args) -> None:
        self.count_label.setText(str(self.quick_list.count()))


def _section_label(text: str, parent: QWidget) -> QLabel:
    section = QLabel(text.upper(), parent)
    section.setObjectName("drawerSection")
    return section


def add_action_rows(
    layout: QVBoxLayout,
    rows: tuple[tuple[QPushButton, ...], ...],
) -> None:
    for row in rows:
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        for button in row:
            line.addWidget(button)
        layout.addLayout(line)


@dataclass(frozen=True, slots=True)
class QuickActionsDrawerPage:
    icon: QStyle.StandardPixmap
    tooltip: str
    widget: QWidget


@dataclass(frozen=True, slots=True)
class QuickActionsRailMode:
    """A rail button mapped to the set of panel sections it reveals."""

    key: str
    icon: QStyle.StandardPixmap
    tooltip: str
    sections: tuple[str, ...]


class _RailPages:
    """``QStackedWidget``-like facade over rail modes + section visibility.

    The drawer moved from one stacked page per rail button to a single scrollable
    panel whose sections are shown/hidden per mode (so the "All" mode can show
    Quick Send + Command Files together). This shim keeps existing callers — and
    the test suite — using ``drawer.pages`` unchanged.
    """

    def __init__(self, drawer: "QuickActionsDrawer") -> None:
        self._drawer = drawer

    def count(self) -> int:
        return len(self._drawer.rail_modes)

    def currentIndex(self) -> int:
        return self._drawer.current_mode_index

    def setCurrentIndex(self, index: int) -> None:
        self._drawer.select_page(index)

    def widget(self, index: int) -> QWidget:
        return self._drawer.content


class QuickActionsDrawer(QFrame):
    def __init__(
        self,
        *,
        sections: dict[str, QWidget],
        rail_modes: Iterable[QuickActionsRailMode],
        on_page_requested: Callable[[int], None] | None = None,
        settings_callback: Callable[[], None] | None = None,
        rail_width: int = 48,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("drawer")
        self.on_page_requested = on_page_requested
        self.rail_buttons: list[QToolButton] = []
        self.sections = dict(sections)
        self.rail_modes = list(rail_modes)
        self.current_mode_index = 0

        drawer_layout = QHBoxLayout(self)
        drawer_layout.setContentsMargins(0, 0, 0, 0)
        drawer_layout.setSpacing(0)

        self.rail = QFrame(self)
        self.rail.setObjectName("drawerRail")
        self.rail.setFixedWidth(rail_width)
        rail_layout = QVBoxLayout(self.rail)
        rail_layout.setContentsMargins(6, 6, 6, 6)
        rail_layout.setSpacing(8)

        for index, mode in enumerate(self.rail_modes):
            button = QToolButton(self.rail)
            button.setObjectName("railButton")
            button.setFixedSize(36, 36)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            set_button_icon(button, mode.icon, 18)
            button.setToolTip(mode.tooltip)
            button.clicked.connect(lambda _checked=False, page_index=index: self._request_page(page_index))
            rail_layout.addWidget(button)
            self.rail_buttons.append(button)
        rail_layout.addStretch(1)

        self.settings_button: QToolButton | None = None
        if settings_callback is not None:
            cog = QToolButton(self.rail)
            cog.setObjectName("railButton")
            cog.setFixedSize(36, 36)
            cog.setToolTip("Settings & commands")
            cog.setCursor(Qt.CursorShape.PointingHandCursor)
            set_button_icon(cog, "cog", 18)
            cog.clicked.connect(lambda _checked=False: settings_callback())
            rail_layout.addWidget(cog)
            self.settings_button = cog

        self.panel = QFrame(self)
        self.panel.setObjectName("drawerPanel")
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(8)

        self.content = QWidget(self.panel)
        self.content.setObjectName("drawerContent")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        for section in self.sections.values():
            content_layout.addWidget(section)
        content_layout.addStretch(0)

        scroll = QScrollArea(self.panel)
        scroll.setObjectName("drawerScroll")
        # Name the internal viewport so the panel colour shows through it (a bare
        # ``QScrollArea > QWidget`` selector does not reliably reach the viewport).
        scroll.viewport().setObjectName("drawerViewport")
        scroll.setWidget(self.content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        panel_layout.addWidget(scroll, 1)
        drawer_layout.addWidget(self.rail)
        drawer_layout.addWidget(self.panel, 1)

        self.pages = _RailPages(self)
        self.select_page(0)

    def _request_page(self, index: int) -> None:
        self._set_active_rail_button(index)
        if self.on_page_requested is not None:
            self.on_page_requested(index)
            return
        self.select_page(index)

    def select_page(self, index: int) -> None:
        if not self.rail_modes:
            return
        clamped = max(0, min(index, len(self.rail_modes) - 1))
        self.current_mode_index = clamped
        visible = set(self.rail_modes[clamped].sections)
        for key, section in self.sections.items():
            section.setVisible(key in visible)
        self._set_active_rail_button(clamped)

    def _set_active_rail_button(self, index: int) -> None:
        if not self.rail_buttons:
            return
        clamped = max(0, min(index, len(self.rail_buttons) - 1))
        for button_index, button in enumerate(self.rail_buttons):
            button.setChecked(button_index == clamped)
