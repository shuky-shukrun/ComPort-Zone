"""ControlPanel library manager: open, rename, duplicate, delete, transfer.

Operates on the live :class:`ControlPanelCatalog` and persists every change
immediately through the injected ``save_settings`` callback (FR-1..FR-4).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...control_panel_catalog import (
    ControlPanelCatalog,
    merge_imported,
    read_control_panels_json,
    write_control_panels_json,
)
from ...control_panel_models import ControlPanelConfig

ROLE_CONTROL_PANEL_ID = Qt.ItemDataRole.UserRole


class ControlPanelManagerDialog(QDialog):
    def __init__(
        self,
        *,
        catalog: ControlPanelCatalog,
        open_control_panel: Callable[[str], None],
        close_control_panel_tab: Callable[[str], None],
        save_settings: Callable[[], None],
        set_status: Callable[[str], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Control Panels")
        self.setMinimumSize(460, 360)
        self._catalog = catalog
        self._open_control_panel = open_control_panel
        self._close_control_panel_tab = close_control_panel_tab
        self._save_settings = save_settings
        self._set_status = set_status

        self.list_widget = QListWidget(self)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._open_selected())

        self.open_button = QPushButton("Open", self)
        self.open_button.clicked.connect(self._open_selected)
        self.new_button = QPushButton("New", self)
        self.new_button.clicked.connect(self._create_new)
        self.rename_button = QPushButton("Rename", self)
        self.rename_button.clicked.connect(self._rename_selected)
        self.duplicate_button = QPushButton("Duplicate", self)
        self.duplicate_button.clicked.connect(self._duplicate_selected)
        self.delete_button = QPushButton("Delete", self)
        self.delete_button.clicked.connect(self._delete_selected)
        self.import_button = QPushButton("Import...", self)
        self.import_button.clicked.connect(self._import_json)
        self.export_button = QPushButton("Export...", self)
        self.export_button.clicked.connect(self._export_json)

        buttons_column = QVBoxLayout()
        for button in (
            self.open_button,
            self.new_button,
            self.rename_button,
            self.duplicate_button,
            self.delete_button,
        ):
            buttons_column.addWidget(button)
        buttons_column.addStretch(1)
        buttons_column.addWidget(self.import_button)
        buttons_column.addWidget(self.export_button)

        body = QHBoxLayout()
        body.addWidget(self.list_widget, 1)
        body.addLayout(buttons_column)

        self.hint_label = QLabel(
            "Control Panels poll commands in the background and drive controls "
            "over a bound terminal tab.",
            self,
        )
        self.hint_label.setObjectName("dialogHint")
        self.hint_label.setWordWrap(True)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(self.hint_label)
        layout.addWidget(close_box)

        self.refresh()

    # -------------------------------------------------------------- helpers

    def refresh(self) -> None:
        selected = self.selected_control_panel_id()
        self.list_widget.clear()
        for config in self._catalog.all():
            count = len(config.entries)
            item = QListWidgetItem(f"{config.name}  ·  {count} entr{'y' if count == 1 else 'ies'}")
            item.setData(ROLE_CONTROL_PANEL_ID, config.id)
            item.setToolTip(config.description or config.name)
            self.list_widget.addItem(item)
            if config.id == selected:
                self.list_widget.setCurrentItem(item)
        if self.list_widget.currentRow() < 0 and self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        has_items = self.list_widget.count() > 0
        for button in (
            self.open_button,
            self.rename_button,
            self.duplicate_button,
            self.delete_button,
            self.export_button,
        ):
            button.setEnabled(has_items)

    def selected_control_panel_id(self) -> str:
        item = self.list_widget.currentItem()
        return str(item.data(ROLE_CONTROL_PANEL_ID)) if item else ""

    def _changed(self) -> None:
        self._save_settings()
        self.refresh()

    # -------------------------------------------------------------- actions

    def _open_selected(self) -> None:
        control_panel_id = self.selected_control_panel_id()
        if control_panel_id:
            self._open_control_panel(control_panel_id)
            self.accept()

    def _create_new(self) -> None:
        name, accepted = QInputDialog.getText(
            self,
            "New Control Panel",
            "Control Panel name",
            text="Control Panel",
        )
        if not accepted or not name.strip():
            return
        config = self._catalog.add(ControlPanelConfig(name=name.strip()))
        self._changed()
        self._open_control_panel(config.id)
        self.accept()

    def _rename_selected(self) -> None:
        control_panel_id = self.selected_control_panel_id()
        config = self._catalog.by_id(control_panel_id)
        if config is None:
            return
        name, accepted = QInputDialog.getText(
            self,
            "Rename Control Panel",
            "Control Panel name",
            text=config.name,
        )
        if accepted and name.strip() and self._catalog.rename(control_panel_id, name):
            self._changed()

    def _duplicate_selected(self) -> None:
        clone = self._catalog.duplicate(self.selected_control_panel_id())
        if clone is not None:
            self._set_status(f"Duplicated control panel as {clone.name}.")
            self._changed()

    def _delete_selected(self) -> None:
        control_panel_id = self.selected_control_panel_id()
        config = self._catalog.by_id(control_panel_id)
        if config is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete Control Panel",
            f"Delete control panel '{config.name}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        # An open tab for this control panel is closed too (FR-4).
        self._close_control_panel_tab(control_panel_id)
        if self._catalog.remove(control_panel_id):
            self._set_status(f"Deleted control panel {config.name}.")
            self._changed()

    def _import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Control Panels",
            str(Path.home()),
            "Control Panel Files (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            configs = read_control_panels_json(Path(path))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Import Control Panels", str(exc))
            return
        result = merge_imported(self._catalog, configs)
        self._set_status(result.summary())
        self._changed()

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Control Panels",
            str(Path.home() / "control-panels.json"),
            "Control Panel Files (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            count = write_control_panels_json(Path(path), self._catalog.all())
        except OSError as exc:
            QMessageBox.warning(self, "Export Control Panels", str(exc))
            return
        self._set_status(f"Exported {count} control panel(s) to {path}.")
