from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Property, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .models import QuickCommand, QuickFile
from .icons import set_button_icon
from .quick_actions import quick_file_display_text, quick_group_name
from .themes import VS_CODE_DARK

QUICK_ACTION_ITEM_HEIGHT = 32
QUICK_COMMAND_EMPTY_HINT = "No quick commands yet — click “Add Command” to create one."
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


def create_quick_command_list(
    parent: QWidget,
    *,
    tooltip: str,
    double_clicked: Callable[[], None] | None = None,
    context_menu_requested: Callable | None = None,
    drag_drop: bool = False,
) -> QListWidget:
    quick_list = EmptyHintListWidget(placeholder_text=QUICK_COMMAND_EMPTY_HINT, parent=parent)
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
    quick_list = EmptyHintListWidget(placeholder_text=QUICK_FILE_EMPTY_HINT, parent=parent)
    quick_list.setObjectName("quickFileList")
    configure_quick_list(
        quick_list,
        tooltip=tooltip,
        double_clicked=double_clicked,
        context_menu_requested=context_menu_requested,
        drag_drop=drag_drop,
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
        if group.casefold() == "general":
            item_text = label
        else:
            group_text = short_list_label(group, group_limit)
            item_text = f"{group_text}: {label}"
        item = QListWidgetItem(item_text)
        item.setData(Qt.ItemDataRole.UserRole, command.id)
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
        item.setData(Qt.ItemDataRole.UserRole, quick_file.id)
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


class QuickActionsPanel(QFrame):
    def __init__(
        self,
        *,
        title: str,
        section_title: str,
        quick_list: QListWidget,
        controls: QWidget | None = None,
        action_title: str | None = "Actions",
        action_rows: tuple[tuple[QPushButton, ...], ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("quickActionPage")
        self.setMinimumWidth(230)
        self.setMaximumWidth(340)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.quick_list = quick_list

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title_label = QLabel(title, self)
        title_label.setObjectName("drawerTitle")
        section_label = _section_label(section_title, self)

        layout.addWidget(title_label)
        layout.addWidget(section_label)
        if controls is not None:
            layout.addWidget(controls)
        layout.addWidget(self.quick_list, 1)
        if action_rows:
            if action_title:
                layout.addWidget(_section_label(action_title, self))
            add_action_rows(layout, action_rows)


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


class QuickActionsDrawer(QFrame):
    def __init__(
        self,
        *,
        pages: Iterable[QuickActionsDrawerPage],
        on_page_requested: Callable[[int], None] | None = None,
        rail_width: int = 48,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("drawer")
        self.on_page_requested = on_page_requested
        self.rail_buttons: list[QToolButton] = []

        drawer_layout = QHBoxLayout(self)
        drawer_layout.setContentsMargins(0, 0, 0, 0)
        drawer_layout.setSpacing(0)

        self.rail = QFrame(self)
        self.rail.setObjectName("drawerRail")
        self.rail.setFixedWidth(rail_width)
        rail_layout = QVBoxLayout(self.rail)
        rail_layout.setContentsMargins(6, 6, 6, 6)
        rail_layout.setSpacing(8)

        self.panel = QFrame(self)
        self.panel.setObjectName("drawerPanel")
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(8)

        self.pages = QStackedWidget(self.panel)
        for index, page in enumerate(pages):
            button = QToolButton(self.rail)
            button.setObjectName("railButton")
            button.setFixedSize(36, 36)
            set_button_icon(button, page.icon, 18)
            button.setToolTip(page.tooltip)
            button.clicked.connect(lambda _checked=False, page_index=index: self._request_page(page_index))
            rail_layout.addWidget(button)
            self.rail_buttons.append(button)
            self.pages.addWidget(page.widget)
        rail_layout.addStretch(1)

        panel_layout.addWidget(self.pages, 1)
        drawer_layout.addWidget(self.rail)
        drawer_layout.addWidget(self.panel, 1)

    def _request_page(self, index: int) -> None:
        if self.on_page_requested is not None:
            self.on_page_requested(index)
            return
        self.select_page(index)

    def select_page(self, index: int) -> None:
        if self.pages.count() == 0:
            return
        self.pages.setCurrentIndex(max(0, min(index, self.pages.count() - 1)))
