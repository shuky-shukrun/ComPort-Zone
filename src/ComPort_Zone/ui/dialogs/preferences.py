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
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...models import LINE_ENDINGS, THEME_OPTIONS
from ...widgets import ChevronComboBox, apply_line_spacing
from ..fonts import (
    TERMINAL_FONT_MAX,
    TERMINAL_FONT_MIN,
    TERMINAL_LINE_SPACING_MAX,
    TERMINAL_LINE_SPACING_MIN,
    pick_mono_font,
    preferred_terminal_font_families,
)

SCROLLBACK_MIN = 100
SCROLLBACK_MAX = 1_000_000
RECONNECT_DELAY_MIN = 100
RECONNECT_DELAY_MAX = 600_000


class PreferencesDialog(QDialog):
    """Consolidated application preferences.

    Surfaces settings that were previously editable only by hand-editing the
    JSON config (scrollback, log folder, line spacing, default line ending,
    reconnect delays), plus a Data & Reset tab for destructive bulk actions.
    Editable fields are written back via :meth:`apply_to` when the dialog is
    accepted; the Data & Reset buttons act immediately through ``host``.
    """

    def __init__(self, settings, parent=None, *, host=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(480)
        self._host = host

        tabs = QTabWidget(self)
        tabs.addTab(self._build_terminal_tab(settings), "Terminal")
        tabs.addTab(self._build_connection_tab(settings), "Connection")
        tabs.addTab(self._build_logging_tab(settings), "Logging")
        tabs.addTab(self._build_control_panels_tab(settings), "Control Panels")
        tabs.addTab(self._build_updates_tab(settings), "Updates")
        tabs.addTab(self._build_data_reset_tab(settings), "Data & Reset")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    # ------------------------------------------------------------- tab builders

    def _build_terminal_tab(self, settings) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        layout.addLayout(form)

        self.theme_combo = ChevronComboBox(widget)
        for theme_name in THEME_OPTIONS:
            self.theme_combo.addItem(theme_name, theme_name)
        self.theme_combo.setCurrentIndex(max(self.theme_combo.findData(settings.theme), 0))
        form.addRow("Theme", self.theme_combo)

        self.family_combo = ChevronComboBox(widget)
        self.family_combo.setEditable(True)
        self.family_combo.addItem("System default monospace", "")
        for font_family in preferred_terminal_font_families():
            self.family_combo.addItem(font_family, font_family)
        if settings.terminal_font_family:
            family_index = self.family_combo.findData(settings.terminal_font_family)
            if family_index >= 0:
                self.family_combo.setCurrentIndex(family_index)
            else:
                self.family_combo.setEditText(settings.terminal_font_family)
        form.addRow("Font family", self.family_combo)

        self.size_input = QSpinBox(widget)
        self.size_input.setRange(TERMINAL_FONT_MIN, TERMINAL_FONT_MAX)
        self.size_input.setSuffix(" pt")
        self.size_input.setValue(
            max(TERMINAL_FONT_MIN, min(settings.terminal_font_size, TERMINAL_FONT_MAX))
        )
        form.addRow("Font size", self.size_input)

        self.line_spacing_input = QSpinBox(widget)
        self.line_spacing_input.setRange(TERMINAL_LINE_SPACING_MIN, TERMINAL_LINE_SPACING_MAX)
        self.line_spacing_input.setSingleStep(5)
        self.line_spacing_input.setSuffix(" %")
        self.line_spacing_input.setValue(
            max(
                TERMINAL_LINE_SPACING_MIN,
                min(settings.terminal_line_spacing, TERMINAL_LINE_SPACING_MAX),
            )
        )
        form.addRow("Line spacing", self.line_spacing_input)

        self.scrollback_input = QSpinBox(widget)
        self.scrollback_input.setRange(SCROLLBACK_MIN, SCROLLBACK_MAX)
        self.scrollback_input.setSingleStep(1000)
        self.scrollback_input.setSuffix(" lines")
        self.scrollback_input.setValue(
            max(SCROLLBACK_MIN, min(settings.scrollback_size, SCROLLBACK_MAX))
        )
        form.addRow("Scrollback", self.scrollback_input)

        # Live font/spacing preview (restored from the old Terminal Font dialog).
        self.font_preview = QTextEdit(widget)
        self.font_preview.setReadOnly(True)
        self.font_preview.setFixedHeight(92)
        self.font_preview.setPlainText("SYS Connected\nTX> *IDN?\nComPort Zone,Terminal,0.0.2")
        layout.addWidget(self.font_preview)

        self.family_combo.currentTextChanged.connect(self._update_font_preview)
        self.size_input.valueChanged.connect(self._update_font_preview)
        self.line_spacing_input.valueChanged.connect(self._update_font_preview)
        self._update_font_preview()

        return widget

    def _update_font_preview(self) -> None:
        self.font_preview.setFont(
            pick_mono_font(int(self.size_input.value()), self.selected_family())
        )
        apply_line_spacing(self.font_preview, int(self.line_spacing_input.value()))

    def _build_connection_tab(self, settings) -> QWidget:
        widget = QWidget(self)
        form = QFormLayout(widget)

        self.line_ending_combo = ChevronComboBox(widget)
        for name in LINE_ENDINGS.keys():
            self.line_ending_combo.addItem(name, name)
        self.line_ending_combo.setCurrentIndex(
            max(self.line_ending_combo.findData(settings.serial.line_ending), 0)
        )
        form.addRow("Default line ending", self.line_ending_combo)

        self.reconnect_interval_input = self._delay_spin(
            settings.serial.reconnect_initial_delay_ms, widget
        )
        self.reconnect_interval_input.setToolTip(
            "Auto-reconnect retries at this fixed interval while disconnected."
        )
        form.addRow("Reconnect interval", self.reconnect_interval_input)

        return widget

    def _delay_spin(self, value: int, parent: QWidget) -> QSpinBox:
        spin = QSpinBox(parent)
        spin.setRange(RECONNECT_DELAY_MIN, RECONNECT_DELAY_MAX)
        spin.setSingleStep(100)
        spin.setSuffix(" ms")
        spin.setValue(max(RECONNECT_DELAY_MIN, min(int(value), RECONNECT_DELAY_MAX)))
        return spin

    def _build_logging_tab(self, settings) -> QWidget:
        widget = QWidget(self)
        form = QFormLayout(widget)

        self.log_path_input = QLineEdit(settings.log_path, widget)
        self.log_path_input.setPlaceholderText("Default: app config folder")
        browse = QPushButton("Browse…", widget)
        browse.clicked.connect(self._browse_log_folder)
        row = QWidget(widget)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.log_path_input)
        row_layout.addWidget(browse)
        form.addRow("Log folder", row)

        return widget

    def _build_control_panels_tab(self, settings) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(
            "Tiles entering FAIL or ERROR notify with a badge, a taskbar flash, "
            "and an optional sound. Recovery is logged silently.",
            widget,
        ))
        layout.itemAt(layout.count() - 1).widget().setWordWrap(True)
        self.control_panel_alerts_checkbox = QCheckBox("Show control panel alerts", widget)
        self.control_panel_alerts_checkbox.setChecked(settings.control_panel_alerts_enabled)
        self.control_panel_alerts_checkbox.setToolTip(
            "Master switch — when off, no badge, taskbar flash, or sound fires."
        )
        layout.addWidget(self.control_panel_alerts_checkbox)
        self.control_panel_alert_sound_checkbox = QCheckBox(
            "Play a sound when a tile alerts", widget
        )
        self.control_panel_alert_sound_checkbox.setChecked(settings.control_panel_alert_sound)
        layout.addWidget(self.control_panel_alert_sound_checkbox)
        self.control_panel_alerts_checkbox.toggled.connect(
            self.control_panel_alert_sound_checkbox.setEnabled
        )
        self.control_panel_alert_sound_checkbox.setEnabled(
            self.control_panel_alerts_checkbox.isChecked()
        )
        layout.addStretch(1)
        return widget

    def _build_updates_tab(self, settings) -> QWidget:
        widget = QWidget(self)
        form = QFormLayout(widget)
        self.check_updates_checkbox = QCheckBox("Check for updates on launch", widget)
        self.check_updates_checkbox.setChecked(settings.check_for_updates_on_launch)
        form.addRow("", self.check_updates_checkbox)
        return widget

    def _build_data_reset_tab(self, settings) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)

        self.clear_history_checkbox = QCheckBox("Clear command history on exit", widget)
        self.clear_history_checkbox.setChecked(settings.clear_history_on_exit)
        layout.addWidget(self.clear_history_checkbox)

        layout.addWidget(QLabel("Bulk actions (apply immediately):", widget))
        for label, slot in (
            ("Clear Command History Now", self._do_clear_history),
            ("Delete All Saved Commands", self._do_delete_commands),
            ("Delete All Saved Files", self._do_delete_files),
            ("Clear All Favorite Commands", self._do_clear_favorite_commands),
            ("Clear All Favorite Files", self._do_clear_favorite_files),
        ):
            button = QPushButton(label, widget)
            button.clicked.connect(slot)
            layout.addWidget(button)

        reset_button = QPushButton("Factory Reset…", widget)
        reset_button.setObjectName("destructiveButton")
        reset_button.clicked.connect(self._do_factory_reset)
        layout.addWidget(reset_button)
        layout.addStretch(1)
        return widget

    # --------------------------------------- Data & Reset immediate actions

    def _do_clear_history(self) -> None:
        if self._host is not None:
            self._host.clear_command_history()

    def _do_delete_commands(self) -> None:
        if self._host is not None:
            self._host.delete_all_quick_commands()

    def _do_delete_files(self) -> None:
        if self._host is not None:
            self._host.delete_all_quick_files()

    def _do_clear_favorite_commands(self) -> None:
        if self._host is not None:
            self._host.clear_all_favorite_commands()

    def _do_clear_favorite_files(self) -> None:
        if self._host is not None:
            self._host.clear_all_favorite_files()

    def _do_factory_reset(self) -> None:
        # Factory reset replaces the whole settings object, so close the dialog
        # afterwards (its controls now reference stale values).
        if self._host is not None and self._host.factory_reset():
            self.reject()

    def _browse_log_folder(self) -> None:
        start = self.log_path_input.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose Log Folder", start)
        if folder:
            self.log_path_input.setText(folder)

    # ------------------------------------------------------------------- apply

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

    def apply_to(self, settings) -> None:
        settings.theme = str(self.theme_combo.currentData() or settings.theme)
        settings.terminal_font_family = self.selected_family()
        settings.terminal_font_size = int(self.size_input.value())
        settings.terminal_line_spacing = int(self.line_spacing_input.value())
        settings.scrollback_size = int(self.scrollback_input.value())

        line_ending = str(self.line_ending_combo.currentData() or settings.serial.line_ending)
        settings.serial.line_ending = line_ending
        settings.lan.line_ending = line_ending

        interval = int(self.reconnect_interval_input.value())
        settings.serial.reconnect_initial_delay_ms = interval
        settings.lan.reconnect_initial_delay_ms = interval

        settings.log_path = self.log_path_input.text().strip()
        settings.check_for_updates_on_launch = self.check_updates_checkbox.isChecked()
        settings.clear_history_on_exit = self.clear_history_checkbox.isChecked()
        settings.control_panel_alerts_enabled = self.control_panel_alerts_checkbox.isChecked()
        settings.control_panel_alert_sound = self.control_panel_alert_sound_checkbox.isChecked()
