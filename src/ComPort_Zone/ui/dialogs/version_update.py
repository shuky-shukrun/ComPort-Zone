from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from ...version_check import VersionCheckResult


class VersionUpdateDialog(QDialog):
    def __init__(
        self,
        result: VersionCheckResult,
        check_on_launch: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            "New Version Available"
            if result.update_available
            else "ComPort Zone Is Up to Date"
        )
        self.setMinimumWidth(420)

        title_text = (
            f"ComPort Zone {escape(result.latest_version)} is available"
            if result.update_available
            else "ComPort Zone is up to date"
        )
        title = QLabel(title_text, self)
        title.setObjectName("dialogTitle")
        title.setWordWrap(True)

        body_text = (
            f"You are running version {escape(result.current_version)}. "
            "Download and run the installer, or open the release page below."
            if result.update_available
            else f"You are using the latest version of ComPort Zone ({escape(result.current_version)})."
        )
        body = QLabel(body_text, self)
        body.setWordWrap(True)

        release_url = escape(result.release_url, quote=True)
        link = QLabel(f'<a href="{release_url}">{release_url}</a>', self)
        link.setTextFormat(Qt.TextFormat.RichText)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link.setOpenExternalLinks(True)
        link.setWordWrap(True)

        self.check_on_launch = QCheckBox("Check for updates when ComPort Zone starts", self)
        self.check_on_launch.setChecked(check_on_launch)

        if result.update_available:
            buttons = QDialogButtonBox(self)
            install_button = buttons.addButton(
                "Download and Install", QDialogButtonBox.ButtonRole.AcceptRole
            )
            buttons.addButton("Later", QDialogButtonBox.ButtonRole.RejectRole)
            install_button.setDefault(True)
        else:
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addWidget(link)
        layout.addWidget(self.check_on_launch)
        layout.addWidget(buttons)

    def check_on_launch_enabled(self) -> bool:
        return self.check_on_launch.isChecked()
