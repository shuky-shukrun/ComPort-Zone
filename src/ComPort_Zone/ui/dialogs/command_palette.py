from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ...command_registry import CommandPaletteEntry
from ...icons import standard_icon


class CommandPaletteHost(Protocol):
    def command_palette_entries(self) -> list[CommandPaletteEntry]:
        ...


class CommandPaletteDialog(QDialog):
    def __init__(self, host: CommandPaletteHost, parent: QWidget | None = None) -> None:
        parent_widget = parent if parent is not None else host if isinstance(host, QWidget) else None
        super().__init__(parent_widget)
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
