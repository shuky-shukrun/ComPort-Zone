from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

APP_SETTINGS_EXPLANATION = (
    "App Settings JSON includes connection defaults (serial, TCP, and UDP), restored "
    "tabs, theme, terminal font, "
    "terminal display preferences, drawer and window state, command history, and last "
    "log/script paths.\n\n"
    "Quick Commands and Quick Files are not included here. Manage them with their own "
    "CSV import/export actions from the Quick Send and Quick Files drawer pages."
)


class AppSettingsTransferDialog(QDialog):
    def __init__(self, mode: str = "choose", parent=None) -> None:
        super().__init__(parent)
        self.mode = mode if mode in {"choose", "import", "export"} else "choose"
        self.selected_action = ""
        titles = {
            "choose": "App Settings Import / Export",
            "import": "Import App Settings",
            "export": "Export App Settings",
        }
        self.setWindowTitle(titles[self.mode])
        self.setMinimumWidth(520)

        heading = QLabel(titles[self.mode], self)
        heading.setObjectName("dialogTitle")

        intro_text = {
            "choose": "Choose whether to import or export app-level preferences.",
            "import": "Import app-level preferences from a JSON file.",
            "export": "Export app-level preferences to a JSON file.",
        }[self.mode]
        intro = QLabel(intro_text, self)
        intro.setWordWrap(True)

        explanation = QLabel(APP_SETTINGS_EXPLANATION, self)
        explanation.setObjectName("dialogHint")
        explanation.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        if self.mode in {"choose", "import"}:
            import_button = buttons.addButton(
                "Import App Settings...",
                QDialogButtonBox.ButtonRole.ActionRole,
            )
            import_button.clicked.connect(lambda: self._accept_action("import"))
        if self.mode in {"choose", "export"}:
            export_button = buttons.addButton(
                "Export App Settings...",
                QDialogButtonBox.ButtonRole.ActionRole,
            )
            export_button.clicked.connect(lambda: self._accept_action("export"))
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(intro)
        layout.addWidget(explanation)
        layout.addWidget(buttons)

    def _accept_action(self, action: str) -> None:
        self.selected_action = action
        self.accept()
