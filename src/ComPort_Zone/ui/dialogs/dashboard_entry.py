"""Dashboard entry editor dialog: command, schedule, parse rule, color rules.

Includes a live tester (FR-28): paste a sample of the device's RX and the
dialog shows the extracted value and the resulting rule state using the
exact production parse/evaluate pipeline. OK is gated on
``DashboardEntry.validation_errors()``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...dashboard_models import (
    COLOR_RULE_OPS,
    DASHBOARD_SEND_MODES,
    MAX_POLL_INTERVAL_MS,
    MAX_POLL_TIMEOUT_MS,
    MIN_POLL_INTERVAL_MS,
    MIN_POLL_TIMEOUT_MS,
    RULE_STATES,
    ColorRule,
    DashboardEntry,
    ParseRule,
)
from ...dashboard_parse import CompiledParseRule, evaluate_rules, format_tile_value, parse_response
from ...models import LINE_ENDINGS, utc_now_iso
from ...widgets import ChevronComboBox
from ..dashboard_tiles import SPAN_CHOICES
from ..tokens import SPACE_MD

PARSE_KIND_LABELS = (("line", "First complete line"), ("regex", "Regular expression"))
VALUE_TYPE_LABELS = (("text", "Text"), ("number", "Number"))
TILE_KIND_LABELS = (("value", "Value tile"), ("led", "LED indicator"))

_RULE_COLUMNS = ("Operator", "Value", "Value 2", "State", "Label")


class DashboardEntryDialog(QDialog):
    """Create or edit one dashboard entry."""

    def __init__(self, entry: DashboardEntry | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dashboard Entry")
        self.setMinimumWidth(560)
        self._original = entry or DashboardEntry()
        original = self._original

        # --- identity -------------------------------------------------
        self.label_input = QLineEdit(original.label, self)
        self.label_input.setPlaceholderText("Tile title (defaults to the command)")
        self.unit_input = QLineEdit(original.unit, self)
        self.unit_input.setPlaceholderText("V, °C, rpm…")

        # --- command ----------------------------------------------------
        self.command_input = QLineEdit(original.command, self)
        self.command_input.setPlaceholderText("MEAS:VOLT? — sent on every poll")
        self.mode_combo = ChevronComboBox(self)
        self.mode_combo.addItems(DASHBOARD_SEND_MODES)
        if original.send_mode in DASHBOARD_SEND_MODES:
            self.mode_combo.setCurrentText(original.send_mode)
        self.line_ending_combo = ChevronComboBox(self)
        self.line_ending_combo.addItem("Use session setting", "")
        for name in LINE_ENDINGS:
            self.line_ending_combo.addItem(name, name)
        if original.line_ending_override:
            self.line_ending_combo.setCurrentText(original.line_ending_override)

        # --- schedule ---------------------------------------------------
        self.interval_spin = QSpinBox(self)
        self.interval_spin.setRange(MIN_POLL_INTERVAL_MS, MAX_POLL_INTERVAL_MS)
        self.interval_spin.setValue(original.interval_ms)
        self.interval_spin.setSuffix(" ms")
        self.timeout_spin = QSpinBox(self)
        self.timeout_spin.setRange(MIN_POLL_TIMEOUT_MS, MAX_POLL_TIMEOUT_MS)
        self.timeout_spin.setValue(original.timeout_ms)
        self.timeout_spin.setSuffix(" ms")
        self.stale_spin = QSpinBox(self)
        self.stale_spin.setRange(0, MAX_POLL_INTERVAL_MS * 4)
        self.stale_spin.setValue(original.stale_after_ms)
        self.stale_spin.setSuffix(" ms")
        self.stale_spin.setSpecialValueText("Auto")

        # --- tile -------------------------------------------------------
        self.tile_kind_combo = ChevronComboBox(self)
        for kind, label in TILE_KIND_LABELS:
            self.tile_kind_combo.addItem(label, kind)
        self._select_data(self.tile_kind_combo, original.tile.kind)
        self.span_combo = ChevronComboBox(self)
        for span_w, span_h in SPAN_CHOICES:
            self.span_combo.addItem(f"{span_w}×{span_h}", (span_w, span_h))
        self._select_data(self.span_combo, (original.tile.span_w, original.tile.span_h))
        self.enabled_check = QCheckBox("Poll this entry", self)
        self.enabled_check.setChecked(original.enabled)

        # --- parse rule ---------------------------------------------------
        self.parse_kind_combo = ChevronComboBox(self)
        for kind, label in PARSE_KIND_LABELS:
            self.parse_kind_combo.addItem(label, kind)
        self._select_data(self.parse_kind_combo, original.parse.kind)
        self.pattern_input = QLineEdit(original.parse.pattern, self)
        self.pattern_input.setPlaceholderText(r"e.g. ^V=([\d.]+)")
        self.group_input = QLineEdit(str(original.parse.group), self)
        self.group_input.setPlaceholderText("Capture group index or name (0 = whole match)")
        self.value_type_combo = ChevronComboBox(self)
        for value_type, label in VALUE_TYPE_LABELS:
            self.value_type_combo.addItem(label, value_type)
        self._select_data(self.value_type_combo, original.parse.value_type)

        parse_form = QFormLayout()
        parse_form.addRow("Parse", self.parse_kind_combo)
        parse_form.addRow("Pattern", self.pattern_input)
        parse_form.addRow("Group", self.group_input)
        parse_form.addRow("Value type", self.value_type_combo)

        # --- live tester ---------------------------------------------------
        self.sample_input = QPlainTextEdit(self)
        self.sample_input.setPlaceholderText("Paste sample device output here to test the rule…")
        self.sample_input.setFixedHeight(64)
        self.tester_result = QLabel("—", self)
        self.tester_result.setObjectName("dialogHint")
        self.tester_result.setWordWrap(True)

        tester_box = QGroupBox("Test against sample RX", self)
        tester_layout = QVBoxLayout(tester_box)
        tester_layout.setSpacing(SPACE_MD)
        tester_layout.addWidget(self.sample_input)
        tester_layout.addWidget(self.tester_result)

        parse_box = QGroupBox("Response parsing", self)
        parse_box_layout = QVBoxLayout(parse_box)
        parse_box_layout.addLayout(parse_form)
        parse_box_layout.addWidget(tester_box)

        # --- color rules ---------------------------------------------------
        self.rules_table = QTableWidget(0, len(_RULE_COLUMNS), self)
        self.rules_table.setHorizontalHeaderLabels(_RULE_COLUMNS)
        self.rules_table.horizontalHeader().setStretchLastSection(True)
        self.rules_table.verticalHeader().setVisible(False)
        self.rules_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.rules_table.setFixedHeight(140)
        for rule in original.rules:
            self._append_rule_row(rule)

        add_rule = QPushButton("Add", self)
        add_rule.clicked.connect(lambda: self._append_rule_row(ColorRule()))
        remove_rule = QPushButton("Remove", self)
        remove_rule.clicked.connect(self._remove_selected_rule)
        rule_up = QPushButton("Up", self)
        rule_up.clicked.connect(lambda: self._move_selected_rule(-1))
        rule_down = QPushButton("Down", self)
        rule_down.clicked.connect(lambda: self._move_selected_rule(1))
        rule_buttons = QHBoxLayout()
        rule_buttons.addWidget(add_rule)
        rule_buttons.addWidget(remove_rule)
        rule_buttons.addStretch(1)
        rule_buttons.addWidget(rule_up)
        rule_buttons.addWidget(rule_down)

        rules_box = QGroupBox("Color rules (first match wins)", self)
        rules_layout = QVBoxLayout(rules_box)
        rules_layout.addWidget(self.rules_table)
        rules_layout.addLayout(rule_buttons)

        # --- assembly ---------------------------------------------------
        form = QFormLayout()
        form.addRow("Label", self.label_input)
        form.addRow("Unit", self.unit_input)
        form.addRow("Command", self.command_input)
        form.addRow("Send mode", self.mode_combo)
        form.addRow("Line ending", self.line_ending_combo)
        form.addRow("Poll every", self.interval_spin)
        form.addRow("Timeout", self.timeout_spin)
        form.addRow("Stale after", self.stale_spin)
        form.addRow("Tile", self.tile_kind_combo)
        form.addRow("Size", self.span_combo)
        form.addRow("", self.enabled_check)

        self.error_label = QLabel("", self)
        self.error_label.setObjectName("dashboardEntryErrors")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(parse_box)
        layout.addWidget(rules_box)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)

        for signal in (
            self.parse_kind_combo.currentIndexChanged,
            self.value_type_combo.currentIndexChanged,
        ):
            signal.connect(self._refresh_tester)
        self.pattern_input.textChanged.connect(self._refresh_tester)
        self.group_input.textChanged.connect(self._refresh_tester)
        self.sample_input.textChanged.connect(self._refresh_tester)
        self._refresh_parse_field_enablement()
        self.parse_kind_combo.currentIndexChanged.connect(self._refresh_parse_field_enablement)
        self._refresh_tester()

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _select_data(combo: ChevronComboBox, data) -> None:
        index = combo.findData(data)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _refresh_parse_field_enablement(self) -> None:
        is_regex = self.parse_kind_combo.currentData() == "regex"
        self.pattern_input.setEnabled(is_regex)
        self.group_input.setEnabled(is_regex)

    # --------------------------------------------------------- rules table

    def _append_rule_row(self, rule: ColorRule) -> None:
        row = self.rules_table.rowCount()
        self.rules_table.insertRow(row)
        op_combo = ChevronComboBox(self.rules_table)
        op_combo.addItems(COLOR_RULE_OPS)
        if rule.op in COLOR_RULE_OPS:
            op_combo.setCurrentText(rule.op)
        self.rules_table.setCellWidget(row, 0, op_combo)
        self.rules_table.setItem(row, 1, QTableWidgetItem(rule.operand))
        self.rules_table.setItem(row, 2, QTableWidgetItem(rule.operand2))
        state_combo = ChevronComboBox(self.rules_table)
        state_combo.addItems(RULE_STATES)
        if rule.state in RULE_STATES:
            state_combo.setCurrentText(rule.state)
        self.rules_table.setCellWidget(row, 3, state_combo)
        self.rules_table.setItem(row, 4, QTableWidgetItem(rule.label))

    def _remove_selected_rule(self) -> None:
        row = self.rules_table.currentRow()
        if row >= 0:
            self.rules_table.removeRow(row)

    def _move_selected_rule(self, delta: int) -> None:
        row = self.rules_table.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.rules_table.rowCount():
            return
        rules = self._rules_from_table()
        rules[row], rules[target] = rules[target], rules[row]
        self.rules_table.setRowCount(0)
        for rule in rules:
            self._append_rule_row(rule)
        self.rules_table.selectRow(target)

    def _rules_from_table(self) -> list[ColorRule]:
        rules: list[ColorRule] = []
        for row in range(self.rules_table.rowCount()):
            op_combo = self.rules_table.cellWidget(row, 0)
            state_combo = self.rules_table.cellWidget(row, 3)
            operand_item = self.rules_table.item(row, 1)
            operand2_item = self.rules_table.item(row, 2)
            label_item = self.rules_table.item(row, 4)
            rules.append(
                ColorRule(
                    op=op_combo.currentText() if op_combo else "eq_text",
                    operand=operand_item.text().strip() if operand_item else "",
                    operand2=operand2_item.text().strip() if operand2_item else "",
                    state=state_combo.currentText() if state_combo else "ok",
                    label=label_item.text().strip() if label_item else "",
                )
            )
        return rules

    # -------------------------------------------------------------- tester

    def _parse_rule_from_fields(self) -> ParseRule:
        group_text = self.group_input.text().strip() or "1"
        group: int | str
        if group_text.lstrip("-").isdigit():
            group = int(group_text)
        else:
            group = group_text
        return ParseRule(
            kind=str(self.parse_kind_combo.currentData() or "line"),
            pattern=self.pattern_input.text(),
            group=group,
            value_type=str(self.value_type_combo.currentData() or "text"),
        )

    def _refresh_tester(self) -> None:
        sample = self.sample_input.toPlainText()
        if not sample:
            self.tester_result.setText("Paste sample output above to preview the parsed value.")
            return
        rule = self._parse_rule_from_fields()
        try:
            compiled = CompiledParseRule.compile(rule)
        except ValueError as exc:
            self.tester_result.setText(f"Rule error: {exc}")
            return
        outcome = parse_response(compiled, sample)
        if outcome is None:
            self.tester_result.setText(
                "No match yet — the poll would keep waiting until its timeout."
            )
            return
        verdict = evaluate_rules(self._rules_from_table(), outcome)
        value = format_tile_value(outcome, self.unit_input.text().strip())
        if outcome.error:
            self.tester_result.setText(f"Parse error: {outcome.error} → state ERROR")
            return
        caption = f" ({verdict.label})" if verdict.label else ""
        self.tester_result.setText(f"Value: {value} → state {verdict.state.upper()}{caption}")

    # -------------------------------------------------------------- result

    def _accept_if_valid(self) -> None:
        errors = self.values().validation_errors()
        if errors:
            self.error_label.setText("\n".join(f"• {error}" for error in errors))
            self.error_label.setVisible(True)
            return
        self.accept()

    def values(self) -> DashboardEntry:
        """The edited entry. Grid position is preserved from the original;
        span/kind come from the dialog (layout normalization happens in the
        host when the entry is applied)."""
        original = self._original
        span_w, span_h = self.span_combo.currentData() or (1, 1)
        tile = original.tile
        tile.kind = str(self.tile_kind_combo.currentData() or "value")
        tile.span_w = int(span_w)
        tile.span_h = int(span_h)
        return DashboardEntry(
            id=original.id,
            label=self.label_input.text().strip(),
            unit=self.unit_input.text().strip(),
            command=self.command_input.text().strip(),
            send_mode=self.mode_combo.currentText(),
            line_ending_override=str(self.line_ending_combo.currentData() or ""),
            interval_ms=self.interval_spin.value(),
            timeout_ms=self.timeout_spin.value(),
            stale_after_ms=self.stale_spin.value(),
            parse=self._parse_rule_from_fields(),
            tile=tile,
            rules=self._rules_from_table(),
            enabled=self.enabled_check.isChecked(),
            created_at=original.created_at or utc_now_iso(),
            updated_at=utc_now_iso(),
        )
