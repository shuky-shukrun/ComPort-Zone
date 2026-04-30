from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QProgressDialog, QWidget

from .models import AppSettings
from .settings_service import SettingsService
from .ui.dialogs import AppSettingsTransferDialog


class AppSettingsController:
    def __init__(
        self,
        *,
        parent: QWidget,
        settings_service: SettingsService,
        settings_supplier: Callable[[], AppSettings],
        save_runtime_settings: Callable[[], None],
        apply_imported_settings: Callable[[AppSettings], None],
        set_status: Callable[[str], None],
    ) -> None:
        self.parent = parent
        self.settings_service = settings_service
        self._settings_supplier = settings_supplier
        self._save_runtime_settings = save_runtime_settings
        self._apply_imported_settings = apply_imported_settings
        self._set_status = set_status

    def show_transfer_dialog(self) -> None:
        dialog = AppSettingsTransferDialog(parent=self.parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.selected_action == "import":
            self.import_settings(show_explanation=False)
        elif dialog.selected_action == "export":
            self.export_settings(show_explanation=False)

    def confirm_transfer(self, mode: str) -> bool:
        dialog = AppSettingsTransferDialog(mode=mode, parent=self.parent)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def import_settings(self, *, show_explanation: bool = True) -> None:
        if show_explanation and not self.confirm_transfer("import"):
            return
        path, _ = QFileDialog.getOpenFileName(
            self.parent,
            "Import App Settings",
            str(Path.cwd()),
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            self.import_settings_from_json(Path(path))

    def export_settings(self, *, show_explanation: bool = True) -> None:
        if show_explanation and not self.confirm_transfer("export"):
            return
        path, _ = QFileDialog.getSaveFileName(
            self.parent,
            "Export App Settings",
            str(Path.cwd() / "comport-zone-app-settings.json"),
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            self.export_settings_to_path(Path(path))

    def import_settings_from_json(self, path: Path) -> bool:
        busy = self._show_busy_message("Import App Settings", "Importing app settings...")
        try:
            imported_settings = self.load_settings_from_json(path)
            self._apply_imported_settings(imported_settings)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._hide_busy_message(busy)
            QMessageBox.warning(self.parent, "Import App Settings", str(exc))
            return False
        saved = self.settings_service.save(self._settings_supplier())
        self._hide_busy_message(busy)
        if not saved:
            self._set_status("Could not save imported app settings to disk.")
            QMessageBox.warning(
                self.parent,
                "Import App Settings",
                "Imported settings were applied, but could not be saved to disk.",
            )
            return False
        self._set_status(f"Imported app settings from {path}.")
        return True

    def export_settings_to_path(self, path: Path) -> bool:
        busy = self._show_busy_message("Export App Settings", "Exporting app settings...")
        try:
            self._save_runtime_settings()
            self.export_settings_to_json(path)
        except OSError as exc:
            self._hide_busy_message(busy)
            QMessageBox.warning(self.parent, "Export App Settings", str(exc))
            return False
        self._hide_busy_message(busy)
        self._set_status(f"Exported app settings to {path}")
        return True

    def load_settings_from_json(self, path: Path) -> AppSettings:
        return self.settings_service.load_from_json(path)

    def export_settings_to_json(self, path: Path) -> None:
        self.settings_service.export_to_json(self._settings_supplier(), path)

    def _show_busy_message(self, title: str, message: str) -> QProgressDialog:
        self._set_status(message)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        dialog = QProgressDialog(message, "", 0, 0, self.parent)
        dialog.setWindowTitle(title)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setCancelButton(None)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        dialog.show()
        QApplication.processEvents()
        return dialog

    def _hide_busy_message(self, dialog: QProgressDialog | None) -> None:
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()
        QApplication.restoreOverrideCursor()
        QApplication.processEvents()
