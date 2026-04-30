from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from threading import Event

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...batch import BatchParameterOccurrence


@dataclass(frozen=True, slots=True)
class CommandFileParameterSummary:
    names: tuple[str, ...]
    defaults: dict[str, str]
    lines_by_parameter: dict[str, tuple[str, ...]]
    line_details: tuple[str, ...]


def summarize_parameter_occurrences(
    parameter_occurrences: Sequence[BatchParameterOccurrence],
) -> CommandFileParameterSummary:
    parameter_names: list[str] = []
    defaults: dict[str, str] = {}
    lines_by_parameter: dict[str, list[str]] = {}
    line_details: list[str] = []
    seen_line_details: set[tuple[int, str]] = set()
    for occurrence in parameter_occurrences:
        if occurrence.name not in parameter_names:
            parameter_names.append(occurrence.name)
        if occurrence.default is not None and occurrence.name not in defaults:
            defaults[occurrence.name] = occurrence.default
        line_entry = f"Line {occurrence.line_number}: {occurrence.line_text}"
        lines_by_parameter.setdefault(occurrence.name, [])
        if line_entry not in lines_by_parameter[occurrence.name]:
            lines_by_parameter[occurrence.name].append(line_entry)
        line_key = (occurrence.line_number, occurrence.line_text)
        if line_key not in seen_line_details:
            line_details.append(line_entry)
            seen_line_details.add(line_key)
    return CommandFileParameterSummary(
        names=tuple(parameter_names),
        defaults=defaults,
        lines_by_parameter={
            name: tuple(lines)
            for name, lines in lines_by_parameter.items()
        },
        line_details=tuple(line_details),
    )


class CommandFileParametersDialog(QDialog):
    def __init__(
        self,
        parameter_occurrences: Sequence[BatchParameterOccurrence],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Command File Parameters")
        self.setMinimumSize(680, 460)
        self.summary = summarize_parameter_occurrences(parameter_occurrences)
        self.inputs: dict[str, QLineEdit] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        intro = QLabel(
            "Review command-file parameters before starting. Fill values now, override defaults, or leave a field empty to ask while running.",
            self,
        )
        intro.setWordWrap(True)

        field_widget = QWidget(self)
        field_layout = QFormLayout(field_widget)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(8)
        for name in self.summary.names:
            input_field = QLineEdit(field_widget)
            input_field.setText(self.summary.defaults.get(name, ""))
            input_field.setPlaceholderText("Ask while running")
            input_field.setClearButtonEnabled(True)
            input_field.setToolTip("\n".join(self.summary.lines_by_parameter.get(name, ())))
            self.inputs[name] = input_field
            label = f"{name}"
            if name in self.summary.defaults:
                label += " (default)"
            field_layout.addRow(label, input_field)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(field_widget)

        details = QTextEdit(self)
        details.setReadOnly(True)
        details.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        details.setMaximumHeight(120)
        details.setPlainText("\n".join(self.summary.line_details))

        hint = QLabel(
            "Values are remembered for this run, so the same parameter name is asked only once. Empty default fields will prompt during execution instead of using the deleted default.",
            self,
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Start")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(scroll, 1)
        layout.addWidget(QLabel("Parameterized lines:", self))
        layout.addWidget(details)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def values(self) -> tuple[dict[str, str], set[str]]:
        values: dict[str, str] = {}
        ignored_defaults: set[str] = set()
        for name, input_field in self.inputs.items():
            value = input_field.text().strip()
            if value:
                values[name] = value
            else:
                ignored_defaults.add(name)
        return values, ignored_defaults


class BatchParameterPromptBridge(QObject):
    prompt_requested = Signal(object)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.parent_widget = parent
        self.prompt_requested.connect(self._handle_prompt)

    def prompt(self, name: str, line_number: int, line_text: str) -> str | None:
        request = {
            "name": name,
            "line_number": line_number,
            "line_text": line_text,
            "event": Event(),
            "accepted": False,
            "value": None,
        }
        self.prompt_requested.emit(request)
        request["event"].wait()
        if not request["accepted"]:
            return None
        return str(request["value"])

    def _handle_prompt(self, request: dict[str, object]) -> None:
        event = request["event"]
        try:
            name = str(request["name"])
            line_number = int(request["line_number"])
            line_text = str(request["line_text"])
            prompt = f"Line {line_number}:\n{line_text}\n\nEnter value for {name}:"
            while True:
                value, accepted = QInputDialog.getText(
                    self.parent_widget,
                    "Command File Parameter",
                    prompt,
                )
                if not accepted:
                    request["accepted"] = False
                    return
                if not value.strip():
                    QMessageBox.warning(
                        self.parent_widget,
                        "Command File Parameter",
                        f"Value for {name} cannot be empty.",
                    )
                    continue
                request["value"] = value
                request["accepted"] = True
                return
        finally:
            event.set()
