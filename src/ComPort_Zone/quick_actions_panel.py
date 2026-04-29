from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .models import QuickCommand, QuickFile
from .quick_actions import quick_file_display_text, quick_group_name


def short_list_label(text: str, limit: int | None = None) -> str:
    text = text.strip()
    if limit is None or len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def create_quick_command_list(
    parent: QWidget,
    *,
    tooltip: str,
    double_clicked: Callable[[], None] | None = None,
    context_menu_requested: Callable | None = None,
    drag_drop: bool = False,
) -> QListWidget:
    quick_list = QListWidget(parent)
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
    quick_list = QListWidget(parent)
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
    item_height: int | None = None,
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
    item_height: int | None = None,
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
        command_action_text: str,
        command_action: Callable[[], None],
        file_action_text: str,
        file_action: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("editorSidePanel")
        self.setMinimumWidth(230)
        self.setMaximumWidth(340)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)

        command_title = QLabel("Quick Commands", self)
        command_title.setObjectName("drawerTitle")
        self.quick_command_list = create_quick_command_list(
            self,
            tooltip="Double-click or press Insert to add a command at the editor cursor.",
            double_clicked=command_action,
        )
        self.command_action_button = QPushButton(command_action_text, self)
        self.command_action_button.clicked.connect(command_action)

        file_title = QLabel("Quick Files", self)
        file_title.setObjectName("drawerTitle")
        self.quick_file_list = create_quick_file_list(
            self,
            tooltip="Double-click or press Open to load the saved file into this editor.",
            double_clicked=file_action,
        )
        self.file_action_button = QPushButton(file_action_text, self)
        self.file_action_button.clicked.connect(file_action)

        layout.addWidget(command_title)
        layout.addWidget(self.quick_command_list, 1)
        layout.addWidget(self.command_action_button)
        layout.addWidget(file_title)
        layout.addWidget(self.quick_file_list, 1)
        layout.addWidget(self.file_action_button)
