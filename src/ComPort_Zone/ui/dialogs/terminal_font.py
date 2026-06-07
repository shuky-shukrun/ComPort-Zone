from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QPushButton,
    QSpinBox,
    QStyle,
    QTextEdit,
    QVBoxLayout,
)

from ...icons import set_button_icon
from ...widgets import ChevronComboBox, apply_line_spacing
from ..fonts import (
    TERMINAL_FONT_MAX,
    TERMINAL_FONT_MIN,
    TERMINAL_LINE_SPACING_DEFAULT,
    TERMINAL_LINE_SPACING_MAX,
    TERMINAL_LINE_SPACING_MIN,
    pick_mono_font,
    preferred_terminal_font_families,
)


class TerminalFontSettingsDialog(QDialog):
    def __init__(
        self,
        family: str,
        point_size: int,
        line_spacing: int = TERMINAL_LINE_SPACING_DEFAULT,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Terminal Font Settings")
        self.setMinimumWidth(460)

        self.family_combo = ChevronComboBox(self)
        self.family_combo.setEditable(True)
        self.family_combo.addItem("System default monospace", "")
        for font_family in preferred_terminal_font_families():
            self.family_combo.addItem(font_family, font_family)
        if family:
            index = self.family_combo.findData(family)
            if index >= 0:
                self.family_combo.setCurrentIndex(index)
            else:
                self.family_combo.setEditText(family)

        self.size_input = QSpinBox(self)
        self.size_input.setRange(TERMINAL_FONT_MIN, TERMINAL_FONT_MAX)
        self.size_input.setValue(max(TERMINAL_FONT_MIN, min(point_size, TERMINAL_FONT_MAX)))
        self.size_input.setSuffix(" pt")

        self.line_spacing_input = QSpinBox(self)
        self.line_spacing_input.setRange(TERMINAL_LINE_SPACING_MIN, TERMINAL_LINE_SPACING_MAX)
        self.line_spacing_input.setSingleStep(5)
        self.line_spacing_input.setValue(
            max(TERMINAL_LINE_SPACING_MIN, min(line_spacing, TERMINAL_LINE_SPACING_MAX))
        )
        self.line_spacing_input.setSuffix(" %")
        self.line_spacing_input.setToolTip("Space between lines, as a percentage of the font height")

        reset = QPushButton("Use Default", self)
        set_button_icon(reset, QStyle.StandardPixmap.SP_BrowserReload)
        reset.clicked.connect(self.reset_defaults)

        self.preview = QTextEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(92)
        self.preview.setPlainText("SYS Connected\nTX> *IDN?\nComPort Zone,Terminal,0.0.2")

        self.family_combo.currentTextChanged.connect(self.update_preview)
        self.size_input.valueChanged.connect(self.update_preview)
        self.line_spacing_input.valueChanged.connect(self.update_preview)

        form = QFormLayout()
        form.addRow("Family", self.family_combo)
        form.addRow("Size", self.size_input)
        form.addRow("Line spacing", self.line_spacing_input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(reset)
        layout.addWidget(self.preview)
        layout.addWidget(buttons)
        self.update_preview()

    def reset_defaults(self) -> None:
        self.family_combo.setCurrentIndex(0)
        self.size_input.setValue(10)
        self.line_spacing_input.setValue(TERMINAL_LINE_SPACING_DEFAULT)

    def selected_family(self) -> str:
        data = self.family_combo.currentData()
        text = self.family_combo.currentText().strip()
        if data is not None:
            current_index = self.family_combo.currentIndex()
            item_text = self.family_combo.itemText(current_index) if current_index >= 0 else ""
            if data == "" and text and text != item_text:
                return text
            return str(data)
        return text

    def selected_size(self) -> int:
        return int(self.size_input.value())

    def selected_line_spacing(self) -> int:
        return int(self.line_spacing_input.value())

    def update_preview(self) -> None:
        self.preview.setFont(pick_mono_font(self.selected_size(), self.selected_family()))
        apply_line_spacing(self.preview, self.selected_line_spacing())
