from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QTextEdit,
    QVBoxLayout,
)

from ...icons import set_button_icon
from ...models import LINE_ENDINGS, QuickCommand, QuickFile, utc_now_iso
from ...quick_actions import SEND_MODES, QuickCommandImportOptions
from ...widgets import ChevronComboBox


class QuickCommandDialog(QDialog):
    def __init__(self, command: QuickCommand | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quick Command")
        self.setMinimumWidth(420)
        command = command or QuickCommand()

        self.label_input = QLineEdit(command.label, self)
        self.command_input = QLineEdit(command.command, self)
        self.description_input = QTextEdit(command.description, self)
        self.description_input.setPlaceholderText("Optional note shown when hovering this quick command")
        self.description_input.setFixedHeight(76)
        self.group_input = QLineEdit(command.group, self)
        self.mode_combo = ChevronComboBox(self)
        self.mode_combo.addItems(SEND_MODES)
        self.mode_combo.setCurrentText(command.send_mode if command.send_mode in SEND_MODES else "Text")
        self.line_ending_combo = ChevronComboBox(self)
        self.line_ending_combo.addItem("Use session setting", "")
        for name in LINE_ENDINGS:
            self.line_ending_combo.addItem(name, name)
        if command.line_ending_override:
            self.line_ending_combo.setCurrentText(command.line_ending_override)
        self._original = command

        form = QFormLayout()
        form.addRow("Label", self.label_input)
        form.addRow("Command", self.command_input)
        form.addRow("Description", self.description_input)
        form.addRow("Group", self.group_input)
        form.addRow("Send mode", self.mode_combo)
        form.addRow("Line ending", self.line_ending_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def quick_command(self) -> QuickCommand:
        now = utc_now_iso()
        return QuickCommand(
            id=self._original.id,
            label=self.label_input.text().strip() or self.command_input.text().strip(),
            command=self.command_input.text().strip(),
            description=self.description_input.toPlainText().strip(),
            send_mode=self.mode_combo.currentText(),
            group=self.group_input.text().strip() or "General",
            line_ending_override=str(self.line_ending_combo.currentData() or ""),
            created_at=self._original.created_at or now,
            updated_at=now,
        )


class QuickFileDialog(QDialog):
    def __init__(self, quick_file: QuickFile | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quick File")
        self.setMinimumWidth(520)
        self._original = quick_file or QuickFile()

        self.label_input = QLineEdit(self._original.label, self)
        self.label_input.setPlaceholderText("Optional display name")
        self.path_input = QLineEdit(self._original.path, self)
        self.path_input.setPlaceholderText("Path to command file")
        browse = QPushButton("Browse", self)
        set_button_icon(browse, QStyle.StandardPixmap.SP_DialogOpenButton)
        browse.clicked.connect(self.browse_file)

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(6)
        path_row.addWidget(self.path_input, 1)
        path_row.addWidget(browse)

        form = QFormLayout()
        form.addRow("Label", self.label_input)
        form.addRow("File", path_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def browse_file(self) -> None:
        start_dir = self.path_input.text().strip() or str(Path.cwd())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Command File",
            start_dir,
            "Command Files (*.cpz *.txt *.cmd *.scr);;ComPort Zone Files (*.cpz);;All Files (*)",
        )
        if path:
            self.path_input.setText(path)

    def quick_file(self) -> QuickFile:
        now = utc_now_iso()
        path = self.path_input.text().strip()
        return QuickFile(
            id=self._original.id,
            label=self.label_input.text().strip() or Path(path).name,
            path=path,
            created_at=self._original.created_at or now,
            updated_at=now,
        )


class QuickCommandImportDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        message: str,
        default_replace: bool,
        default_skip_duplicates: bool,
        append_label: str = "Append imported commands",
        replace_label: str = "Replace current quick commands",
        duplicate_checkbox_text: str = "Skip duplicate commands",
        duplicate_hint_text: str = (
            "Duplicate detection ignores descriptions so imported notes can change without creating extra copies."
        ),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(430)

        intro = QLabel(message, self)
        intro.setWordWrap(True)

        self.behavior_combo = ChevronComboBox(self)
        self.behavior_combo.addItem(append_label, False)
        self.behavior_combo.addItem(replace_label, True)
        self.behavior_combo.setCurrentIndex(1 if default_replace else 0)

        self.skip_duplicates = QCheckBox(duplicate_checkbox_text, self)
        self.skip_duplicates.setToolTip(
            "Duplicates use group, title, command text, and send mode. Descriptions are ignored."
        )
        self.skip_duplicates.setChecked(default_skip_duplicates)

        duplicate_hint = QLabel(duplicate_hint_text, self)
        duplicate_hint.setWordWrap(True)
        duplicate_hint.setObjectName("dialogHint")

        form = QFormLayout()
        form.addRow("Behavior", self.behavior_combo)
        form.addRow("", self.skip_duplicates)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(duplicate_hint)
        layout.addWidget(buttons)

    def options(self) -> QuickCommandImportOptions:
        return QuickCommandImportOptions(
            replace_existing=bool(self.behavior_combo.currentData()),
            skip_duplicates=self.skip_duplicates.isChecked(),
        )
