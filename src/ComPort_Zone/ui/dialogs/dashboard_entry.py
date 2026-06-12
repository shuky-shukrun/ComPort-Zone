"""Dashboard entry editor dialog: command, schedule, parse rule, color rules.

Laid out as a live tile preview above three tabbed pages (General /
Polling / Response & Rules) so the dialog stays short enough that OK is
always on screen. The preview renders the entry through the real tile
widgets, fed by the same parse/evaluate pipeline as the tester (FR-28):
paste sample RX and both the tester line and the preview tile show what
the dashboard would display. OK is gated on
``DashboardEntry.validation_errors()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...dashboard_expr import ExpressionError, compile_expression
from ...dashboard_models import (
    COLOR_RULE_OPS,
    DASHBOARD_SEND_MODES,
    MAX_POLL_INTERVAL_MS,
    MAX_POLL_TIMEOUT_MS,
    MIN_POLL_INTERVAL_MS,
    MIN_POLL_TIMEOUT_MS,
    RULE_STATES,
    ColorRule,
    ControlSpec,
    DashboardEntry,
    ParseRule,
)
from ...dashboard_parse import CompiledParseRule, evaluate_rules, format_tile_value, parse_response
from ...models import LINE_ENDINGS, utc_now_iso
from ...widgets import ChevronComboBox
from ..dashboard_tiles import (
    SPAN_CHOICES,
    TILE_STATE_CAPTIONS,
    TileFrame,
    TileRuntime,
    create_tile,
    tile_class_for,
)
from ..tokens import SPACE_LG, SPACE_MD

PARSE_KIND_LABELS = (("line", "First complete line"), ("regex", "Regular expression"))
VALUE_TYPE_LABELS = (("text", "Text"), ("number", "Number"))
TILE_KIND_LABELS = (
    ("value", "Value tile"),
    ("led", "LED indicator"),
    ("control", "Control button"),
)
POLL_MODE_LABELS = (("interval", "Every interval"), ("on_connect", "Once on connect"))
SOURCE_LABELS = (("poll", "Polled command"), ("derived", "Computed from other tiles"))
CONTROL_MODE_LABELS = (
    ("button", "Button — send one command"),
    ("toggle", "Toggle — alternate ON/OFF"),
)

_RULE_COLUMNS = ("Operator", "Value", "Value 2", "State", "Color", "Label")

DASHBOARD_DEFAULT_TARGET = ""  # combo data for "use the dashboard binding"

# Preview tile footprint: one grid cell at typical dashboard proportions.
PREVIEW_CELL_W = 190
PREVIEW_CELL_H = 96


@dataclass(slots=True)
class EntryDialogContext:
    """Sibling/session context the dialog needs for v2 fields.

    ``bind_targets`` are (endpoint, label, connected) triples of the open
    terminal tabs (for the per-entry Target combo, FR-54).
    ``expression_resolver``/``expression_sources`` validate derived
    expressions against sibling entries exactly like the dashboard tab
    does at configure time (FR-61); ``reference_labels`` are the
    display-form labels offered in the expression hint.
    ``watch_candidates`` are (entry id, label) pairs a control toggle can
    follow (FR-59).
    """

    bind_targets: list[tuple[str, str, bool]] = field(default_factory=list)
    expression_resolver: dict[str, list[str]] = field(default_factory=dict)
    expression_sources: dict[str, str] = field(default_factory=dict)
    reference_labels: list[str] = field(default_factory=list)
    watch_candidates: list[tuple[str, str]] = field(default_factory=list)


class DashboardEntryDialog(QDialog):
    """Create or edit one dashboard entry."""

    def __init__(
        self,
        entry: DashboardEntry | None = None,
        parent=None,
        *,
        context: EntryDialogContext | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dashboard Entry")
        self.setMinimumWidth(620)  # six rule columns fit without a scrollbar
        self._original = entry or DashboardEntry()
        self._context = context or EntryDialogContext()
        # The preview reads every field via values(); hold it off until the
        # whole dialog exists.
        self._preview_ready = False
        self.preview_tile: TileFrame | None = None
        original = self._original

        # --- identity -------------------------------------------------
        self.label_input = QLineEdit(original.label, self)
        self.label_input.setPlaceholderText("Tile title (defaults to the command)")
        self.unit_input = QLineEdit(original.unit, self)
        self.unit_input.setPlaceholderText("V, °C, rpm…")

        # --- source (v2, FR-61) -------------------------------------------
        self.source_combo = ChevronComboBox(self)
        for source, label in SOURCE_LABELS:
            self.source_combo.addItem(label, source)
        self._select_data(self.source_combo, original.source)
        self.source_combo.currentIndexChanged.connect(self._refresh_shape)

        self.expression_input = QLineEdit(original.expression, self)
        self.expression_input.setPlaceholderText("{Volts} * {Amps}")
        self.expression_input.textChanged.connect(self._refresh_expression_hint)
        self.expression_hint = QLabel("", self)
        self.expression_hint.setObjectName("dialogHint")
        self.expression_hint.setWordWrap(True)
        self.expression_container = QWidget(self)
        expression_layout = QVBoxLayout(self.expression_container)
        expression_layout.setContentsMargins(0, 0, 0, 0)
        expression_layout.setSpacing(SPACE_MD)
        expression_layout.addWidget(self.expression_input)
        expression_layout.addWidget(self.expression_hint)

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

        # --- target session (v2, FR-54) ----------------------------------
        self.target_combo = ChevronComboBox(self)
        self.target_combo.addItem("Dashboard binding (default)", DASHBOARD_DEFAULT_TARGET)
        stored = original.target_endpoint
        stored_listed = False
        for endpoint, label, connected in self._context.bind_targets:
            suffix = "" if connected else " (disconnected)"
            self.target_combo.addItem(f"{label}{suffix}", endpoint)
            if endpoint == stored:
                stored_listed = True
        if stored and not stored_listed:
            # Keep an override to a not-currently-open terminal editable
            # without silently clearing it (FR-54).
            self.target_combo.addItem(f"{stored} (not open)", stored)
        self._select_data(self.target_combo, stored)

        # --- schedule ---------------------------------------------------
        self.poll_mode_combo = ChevronComboBox(self)
        for mode, label in POLL_MODE_LABELS:
            self.poll_mode_combo.addItem(label, mode)
        self._select_data(self.poll_mode_combo, original.poll_mode)
        self.poll_mode_combo.currentIndexChanged.connect(self._refresh_schedule_enablement)

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

        # --- control (v2, FR-59) ------------------------------------------
        self.control_mode_combo = ChevronComboBox(self)
        for mode, label in CONTROL_MODE_LABELS:
            self.control_mode_combo.addItem(label, mode)
        self._select_data(self.control_mode_combo, original.control.mode)
        self.control_mode_combo.currentIndexChanged.connect(self._refresh_control_enablement)
        self.on_command_input = QLineEdit(original.control.on_command, self)
        self.on_command_input.setPlaceholderText("OUTP ON — sent on click")
        self.off_command_input = QLineEdit(original.control.off_command, self)
        self.off_command_input.setPlaceholderText("OUTP OFF — sent when toggling off")
        self.confirm_check = QCheckBox("Ask for confirmation before sending", self)
        self.confirm_check.setChecked(original.control.confirm)
        self.watch_combo = ChevronComboBox(self)
        self.watch_combo.addItem("None — flip optimistically", "")
        stored_watch = original.control.watch_entry_id
        watch_listed = False
        for watch_id, watch_label in self._context.watch_candidates:
            self.watch_combo.addItem(watch_label, watch_id)
            if watch_id == stored_watch:
                watch_listed = True
        if stored_watch and not watch_listed:
            self.watch_combo.addItem(f"{stored_watch} (missing)", stored_watch)
        self._select_data(self.watch_combo, stored_watch)

        self.control_box = QGroupBox("Control", self)
        control_form = QFormLayout(self.control_box)
        control_form.addRow("Mode", self.control_mode_combo)
        control_form.addRow("ON command", self.on_command_input)
        control_form.addRow("OFF command", self.off_command_input)
        control_form.addRow("State follows", self.watch_combo)
        control_form.addRow("", self.confirm_check)
        self._control_form = control_form

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
        self.sample_input.setFixedHeight(48)
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
        self.rules_table.setFixedHeight(104)
        for column, width in ((0, 96), (1, 80), (2, 80), (3, 84), (4, 88)):
            self.rules_table.setColumnWidth(column, width)
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

        # --- preview strip (always visible, above the tabs) ----------------
        self.preview_host = QWidget(self)
        self.preview_host.setObjectName("dashboardPreviewStrip")
        self._preview_layout = QHBoxLayout(self.preview_host)
        self._preview_layout.setContentsMargins(SPACE_LG, SPACE_MD, SPACE_LG, SPACE_MD)
        self._preview_layout.addStretch(1)
        self._preview_layout.addStretch(1)

        # --- tab pages -----------------------------------------------------
        general_form = QFormLayout()
        general_form.addRow("Label", self.label_input)
        general_form.addRow("Unit", self.unit_input)
        general_form.addRow("Source", self.source_combo)
        general_form.addRow("Expression", self.expression_container)
        general_form.addRow("Command", self.command_input)
        general_form.addRow("Tile", self.tile_kind_combo)
        general_form.addRow("Size", self.span_combo)
        general_form.addRow("", self.enabled_check)
        general_page = QWidget(self)
        general_layout = QVBoxLayout(general_page)
        general_layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        general_layout.addLayout(general_form)
        general_layout.addWidget(self.control_box)
        general_layout.addStretch(1)

        polling_form = QFormLayout()
        polling_form.addRow("Send mode", self.mode_combo)
        polling_form.addRow("Line ending", self.line_ending_combo)
        polling_form.addRow("Target", self.target_combo)
        polling_form.addRow("Poll mode", self.poll_mode_combo)
        polling_form.addRow("Poll every", self.interval_spin)
        polling_form.addRow("Timeout", self.timeout_spin)
        polling_form.addRow("Stale after", self.stale_spin)
        polling_page = QWidget(self)
        polling_layout = QVBoxLayout(polling_page)
        polling_layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        polling_layout.addLayout(polling_form)
        polling_layout.addStretch(1)

        response_page = QWidget(self)
        response_layout = QVBoxLayout(response_page)
        response_layout.setContentsMargins(SPACE_MD, SPACE_MD, SPACE_MD, SPACE_MD)
        response_layout.addWidget(parse_box)
        response_layout.addWidget(rules_box)
        response_layout.addStretch(1)

        self.tabs = QTabWidget(self)
        self.GENERAL_TAB = self.tabs.addTab(general_page, "General")
        self.POLLING_TAB = self.tabs.addTab(polling_page, "Polling")
        self.RESPONSE_TAB = self.tabs.addTab(response_page, "Response && Rules")

        self._general_form = general_form
        self._polling_form = polling_form
        self._forms = (general_form, polling_form)
        self._parse_box = parse_box
        self._rules_box = rules_box
        # Row groups per dialog shape (poll / derived / control): sending
        # rows also apply to controls; schedule rows are poll-only.
        self._send_fields: tuple[QWidget, ...] = (
            self.mode_combo,
            self.line_ending_combo,
            self.target_combo,
        )
        self._schedule_fields: tuple[QWidget, ...] = (
            self.command_input,
            self.poll_mode_combo,
            self.interval_spin,
            self.timeout_spin,
            self.stale_spin,
        )

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
        layout.addWidget(self.preview_host)
        layout.addWidget(self.tabs, 1)
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
        self.tile_kind_combo.currentIndexChanged.connect(self._refresh_shape)
        # Everything the preview tile reflects funnels into one refresh.
        for line_edit in (self.label_input, self.unit_input, self.expression_input):
            line_edit.textChanged.connect(self._refresh_preview)
        self.command_input.textChanged.connect(self._refresh_preview)
        self.span_combo.currentIndexChanged.connect(self._refresh_preview)
        self.enabled_check.toggled.connect(self._refresh_preview)
        self.control_mode_combo.currentIndexChanged.connect(self._refresh_preview)
        self.rules_table.cellChanged.connect(lambda *_: self._refresh_preview())
        self._preview_ready = True
        self._refresh_schedule_enablement()
        self._refresh_control_enablement()
        self._refresh_shape()
        self._refresh_tester()

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _select_data(combo: ChevronComboBox, data) -> None:
        # Not findData(): Qt compares wrapped Python objects (the span
        # tuples) by identity, so a runtime-built tuple never matches.
        for index in range(combo.count()):
            if combo.itemData(index) == data:
                combo.setCurrentIndex(index)
                return

    def _refresh_parse_field_enablement(self) -> None:
        is_regex = self.parse_kind_combo.currentData() == "regex"
        self.pattern_input.setEnabled(is_regex)
        self.group_input.setEnabled(is_regex)

    def _refresh_schedule_enablement(self) -> None:
        # on_connect entries have no interval and never age (FR-52).
        is_interval = self.poll_mode_combo.currentData() == "interval"
        self.interval_spin.setEnabled(is_interval)
        self.stale_spin.setEnabled(is_interval)

    def _current_shape(self) -> str:
        """Which of the three entry shapes the dialog is editing: a control
        tile (kind wins), a derived entry, or a polled command."""
        if self.tile_kind_combo.currentData() == "control":
            return "control"
        if self.source_combo.currentData() == "derived":
            return "derived"
        return "poll"

    def _set_row_visible(self, field_widget: QWidget, visible: bool) -> None:
        for form in self._forms:
            if form.indexOf(field_widget) >= 0:
                form.setRowVisible(field_widget, visible)
                return

    def _is_row_visible(self, field_widget: QWidget) -> bool:
        for form in self._forms:
            if form.indexOf(field_widget) >= 0:
                return form.isRowVisible(field_widget)
        return False

    def _refresh_shape(self) -> None:
        shape = self._current_shape()
        is_poll = shape == "poll"
        is_derived = shape == "derived"
        is_control = shape == "control"
        self._set_row_visible(self.source_combo, not is_control)
        self._set_row_visible(self.expression_container, is_derived)
        for field_widget in self._schedule_fields:
            self._set_row_visible(field_widget, is_poll)
        for field_widget in self._send_fields:
            self._set_row_visible(field_widget, not is_derived)
        self._parse_box.setVisible(is_poll)
        self._rules_box.setVisible(not is_control)
        self.control_box.setVisible(is_control)
        # Pages with nothing left to offer disappear entirely.
        self.tabs.setTabVisible(self.POLLING_TAB, not is_derived)
        self.tabs.setTabVisible(self.RESPONSE_TAB, not is_control)
        if not self.tabs.isTabVisible(self.tabs.currentIndex()):
            self.tabs.setCurrentIndex(self.GENERAL_TAB)
        if is_control:
            caption = "Enable this control"
        elif is_derived:
            caption = "Update this tile"
        else:
            caption = "Poll this entry"
        self.enabled_check.setText(caption)
        if is_derived:
            self._refresh_expression_hint()
        self._refresh_preview()

    def _refresh_control_enablement(self) -> None:
        # OFF command and the watch entry only exist for toggles (FR-59).
        is_toggle = self.control_mode_combo.currentData() == "toggle"
        self._control_form.setRowVisible(self.off_command_input, is_toggle)
        self._control_form.setRowVisible(self.watch_combo, is_toggle)

    # ------------------------------------------------------------- preview

    def _refresh_preview(self) -> None:
        """Render the entry-in-progress through the real tile widgets so
        the user sees exactly what the dashboard will add."""
        if not self._preview_ready:
            return
        entry = self.values()
        desired_class = tile_class_for(entry)
        if self.preview_tile is None or type(self.preview_tile) is not desired_class:
            old_tile = self.preview_tile
            tile = create_tile(entry, self.preview_host)
            # Purely illustrative: no context menus, drags, or clicks.
            tile.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._preview_layout.insertWidget(1, tile)
            tile.show()
            if old_tile is not None:
                old_tile.hide()
                old_tile.deleteLater()
            self.preview_tile = tile
        else:
            self.preview_tile.update_entry(entry)
        width = PREVIEW_CELL_W * entry.tile.span_w + SPACE_LG * (entry.tile.span_w - 1)
        height = PREVIEW_CELL_H + (28 if entry.tile.span_h > 1 else 0)
        self.preview_tile.setFixedSize(width, height)
        self.preview_tile.update_runtime(self._preview_runtime(entry))

    def _preview_runtime(self, entry: DashboardEntry) -> TileRuntime:
        """Same pipeline as the tester (FR-28): sample RX -> parse ->
        rules; without a sample the tile previews its neutral shape."""
        runtime = TileRuntime(entry_id=entry.id, timestamp_text="--:--:--")
        if entry.is_control():
            return runtime
        sample = self.sample_input.toPlainText()
        if entry.is_derived() or not sample:
            return runtime
        try:
            compiled = CompiledParseRule.compile(entry.parse)
        except ValueError:
            runtime.state = "error"
            runtime.state_caption = TILE_STATE_CAPTIONS["error"]
            return runtime
        outcome = parse_response(compiled, sample)
        if outcome is None:
            return runtime
        runtime.value_text = format_tile_value(outcome, entry.unit)
        verdict = evaluate_rules(entry.rules, outcome)
        runtime.state = verdict.state
        runtime.state_caption = verdict.label or TILE_STATE_CAPTIONS.get(verdict.state, "")
        runtime.color = verdict.color
        return runtime

    def _refresh_expression_hint(self) -> None:
        if self._current_shape() != "derived":
            return
        text = self.expression_input.text().strip()
        if not text:
            labels = ", ".join(
                "{" + label + "}" for label in self._context.reference_labels[:6]
            )
            hint = "Reference numeric tiles as {Label} — e.g. {Volts} * {Amps}."
            if labels:
                hint += f" Available: {labels}"
            self.expression_hint.setText(hint)
            return
        try:
            compiled = compile_expression(
                text,
                self._context.expression_resolver,
                sources=self._context.expression_sources,
            )
        except ExpressionError as exc:
            self.expression_hint.setText(str(exc))
            return
        count = len(compiled.inputs)
        self.expression_hint.setText(f"✓ Valid — uses {count} input tile(s).")

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
        self.rules_table.setCellWidget(row, 4, self._make_color_button(rule.color))
        self.rules_table.setItem(row, 5, QTableWidgetItem(rule.label))
        op_combo.currentIndexChanged.connect(lambda *_: self._refresh_tester())
        state_combo.currentIndexChanged.connect(lambda *_: self._refresh_tester())

    def _make_color_button(self, color: str) -> QPushButton:
        """Swatch for the rule's custom tile color (FR-62): click to pick,
        right-click to reset to the theme's state color."""
        button = QPushButton(self.rules_table)
        button.setProperty("ruleColor", color)
        button.setToolTip(
            "Custom tile color for this rule — click to choose,\n"
            "right-click to reset to the theme state color."
        )
        button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        button.customContextMenuRequested.connect(
            lambda _pos, b=button: self._set_rule_color(b, "")
        )
        button.clicked.connect(lambda _checked=False, b=button: self._pick_rule_color(b))
        self._style_color_button(button)
        return button

    def _set_rule_color(self, button: QPushButton, color: str) -> None:
        button.setProperty("ruleColor", color)
        self._style_color_button(button)
        self._refresh_preview()

    @staticmethod
    def _style_color_button(button: QPushButton) -> None:
        color = str(button.property("ruleColor") or "")
        if not color:
            button.setText("Auto")
            button.setStyleSheet("")
            return
        parsed = QColor(color)
        luma = 0.299 * parsed.red() + 0.587 * parsed.green() + 0.114 * parsed.blue()
        ink = "#000000" if luma > 140 else "#ffffff"
        button.setText(color)
        button.setStyleSheet(f"background: {color}; color: {ink};")

    def _pick_rule_color(self, button: QPushButton) -> None:
        current = str(button.property("ruleColor") or "")
        initial = QColor(current) if current else QColor(Qt.GlobalColor.white)
        chosen = QColorDialog.getColor(initial, self, "Rule color")
        if chosen.isValid():
            self._set_rule_color(button, chosen.name())

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
            color_button = self.rules_table.cellWidget(row, 4)
            operand_item = self.rules_table.item(row, 1)
            operand2_item = self.rules_table.item(row, 2)
            label_item = self.rules_table.item(row, 5)
            rules.append(
                ColorRule(
                    op=op_combo.currentText() if op_combo else "eq_text",
                    operand=operand_item.text().strip() if operand_item else "",
                    operand2=operand2_item.text().strip() if operand2_item else "",
                    state=state_combo.currentText() if state_combo else "ok",
                    label=label_item.text().strip() if label_item else "",
                    color=str(color_button.property("ruleColor") or "") if color_button else "",
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
        self._refresh_preview()
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
        entry = self.values()
        errors = entry.validation_errors()
        if entry.is_derived() and entry.expression and not errors:
            # Reference resolution needs sibling context the model lacks
            # (unknown/ambiguous labels, derived-of-derived, syntax).
            try:
                compile_expression(
                    entry.expression,
                    self._context.expression_resolver,
                    sources=self._context.expression_sources,
                )
            except ExpressionError as exc:
                errors = [str(exc)]
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
        # A copy, not a mutation: the live preview calls values() on every
        # edit, and Cancel must leave the original placement untouched.
        tile = replace(
            original.tile,
            kind=str(self.tile_kind_combo.currentData() or "value"),
            span_w=int(span_w),
            span_h=int(span_h),
        )
        shape = self._current_shape()
        is_derived = shape == "derived"
        is_control = shape == "control"
        # Fields the current shape does not use are cleared: that keeps
        # the serialized form sparse and display_label() sensible
        # (FR-59/FR-61); a control's commands live in its ControlSpec.
        if is_control:
            control_mode = str(self.control_mode_combo.currentData() or "button")
            is_toggle = control_mode == "toggle"
            control = ControlSpec(
                mode=control_mode,
                on_command=self.on_command_input.text().strip(),
                off_command=self.off_command_input.text().strip() if is_toggle else "",
                confirm=self.confirm_check.isChecked(),
                watch_entry_id=str(self.watch_combo.currentData() or "") if is_toggle else "",
            )
        else:
            control = ControlSpec()
        return DashboardEntry(
            id=original.id,
            label=self.label_input.text().strip(),
            unit=self.unit_input.text().strip(),
            command="" if (is_derived or is_control) else self.command_input.text().strip(),
            send_mode=self.mode_combo.currentText(),
            line_ending_override=str(self.line_ending_combo.currentData() or ""),
            interval_ms=self.interval_spin.value(),
            timeout_ms=self.timeout_spin.value(),
            stale_after_ms=self.stale_spin.value(),
            parse=self._parse_rule_from_fields(),
            tile=tile,
            rules=[] if is_control else self._rules_from_table(),
            enabled=self.enabled_check.isChecked(),
            poll_mode=(
                "interval"
                if is_derived or is_control
                else str(self.poll_mode_combo.currentData() or "interval")
            ),
            target_endpoint="" if is_derived else str(self.target_combo.currentData() or ""),
            source="derived" if is_derived else "poll",
            expression=self.expression_input.text().strip() if is_derived else "",
            show_sparkline=original.show_sparkline,
            alerts_enabled=original.alerts_enabled,
            control=control,
            created_at=original.created_at or utc_now_iso(),
            updated_at=utc_now_iso(),
        )
