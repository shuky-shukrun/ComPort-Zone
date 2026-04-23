from __future__ import annotations

from datetime import datetime
from pathlib import Path
from queue import Empty
from typing import Iterable

from PySide6.QtCore import Qt, QStringListModel, QTimer
from PySide6.QtGui import QAction, QColor, QFontDatabase, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QCompleter,
)

from .batch import BatchParseError, BatchRunner, load_batch_file
from .history import HistoryStore
from .models import AppSettings, FLOW_CONTROL_OPTIONS, SerialProfile, THEME_OPTIONS
from .serial_core import SerialClient, SerialEvent
from .session_log import SessionLogger
from .storage import SettingsStore, default_config_path
from .themes import THEMES, ThemePalette
from .widgets import HistoryLineEdit

COMMON_BAUD_RATES = [
    "9600",
    "19200",
    "38400",
    "57600",
    "115200",
    "230400",
    "460800",
    "921600",
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings_store = SettingsStore(default_config_path())
        self.settings = self.settings_store.load()
        self.settings.ensure_active_profile()
        self.serial_client = SerialClient()
        self.history_store = HistoryStore(self.settings.command_history)
        self.logger = SessionLogger()
        self.batch_runner = BatchRunner(
            event_queue=self.serial_client.events,
            send_text=self.serial_client.send_text,
            send_bytes=self.serial_client.send_bytes,
            connected_supplier=lambda: self.serial_client.is_connected,
        )
        self._loading_profile = False
        self._loaded_profile_name = self.settings.active_profile
        self._theme = THEMES[self.settings.theme] if self.settings.theme in THEMES else THEMES["Workshop Dark"]

        self.setWindowTitle("Serial Terminal")
        self.resize(self.settings.window_width, self.settings.window_height)
        self._build_ui()
        self._build_menu()
        self._apply_theme(self._theme)
        self._load_profiles()
        self.refresh_ports()
        self._update_completion_model()
        self._update_connection_state(False)
        if self.settings.log_path:
            self._set_detail(f"Last log path: {self.settings.log_path}")

        self.event_timer = QTimer(self)
        self.event_timer.timeout.connect(self._drain_events)
        self.event_timer.start(50)

    def _build_ui(self) -> None:
        root = QWidget(self)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        form_widget = QWidget(self)
        form_layout = QFormLayout(form_widget)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.setSpacing(8)

        self.profile_combo = QComboBox()
        self.profile_combo.currentTextChanged.connect(self._on_profile_selected)

        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(COMMON_BAUD_RATES)

        self.bytesize_combo = QComboBox()
        self.bytesize_combo.addItems(["5", "6", "7", "8"])

        self.parity_combo = QComboBox()
        self.parity_combo.addItems(["N", "E", "O", "M", "S"])

        self.stopbits_combo = QComboBox()
        self.stopbits_combo.addItems(["1", "1.5", "2"])

        self.flow_control_combo = QComboBox()
        self.flow_control_combo.addItems(FLOW_CONTROL_OPTIONS)

        self.line_ending_combo = QComboBox()
        self.line_ending_combo.addItems(["None", "CR", "LF", "CRLF"])

        self.auto_reconnect_checkbox = QCheckBox("Auto-reconnect")
        self.timestamps_checkbox = QCheckBox("Show timestamps")
        self.timestamps_checkbox.setChecked(self.settings.timestamps_enabled)
        self.dtr_checkbox = QCheckBox("DTR")
        self.rts_checkbox = QCheckBox("RTS")

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEME_OPTIONS)
        self.theme_combo.setCurrentText(self.settings.theme)
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)

        profile_row = QWidget(self)
        profile_layout = QHBoxLayout(profile_row)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.addWidget(self.profile_combo)
        save_profile_button = QPushButton("Save Profile As")
        save_profile_button.clicked.connect(self._save_profile_as)
        profile_layout.addWidget(save_profile_button)
        delete_profile_button = QPushButton("Delete Profile")
        delete_profile_button.clicked.connect(self._delete_profile)
        profile_layout.addWidget(delete_profile_button)

        port_row = QWidget(self)
        port_layout = QHBoxLayout(port_row)
        port_layout.setContentsMargins(0, 0, 0, 0)
        port_layout.addWidget(self.port_combo, 2)
        refresh_ports_button = QPushButton("Refresh")
        refresh_ports_button.clicked.connect(self.refresh_ports)
        port_layout.addWidget(refresh_ports_button)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._toggle_connection)
        port_layout.addWidget(self.connect_button)

        extra_row = QWidget(self)
        extra_layout = QHBoxLayout(extra_row)
        extra_layout.setContentsMargins(0, 0, 0, 0)
        extra_layout.addWidget(self.auto_reconnect_checkbox)
        extra_layout.addWidget(self.timestamps_checkbox)
        extra_layout.addWidget(self.dtr_checkbox)
        extra_layout.addWidget(self.rts_checkbox)
        extra_layout.addStretch(1)
        extra_layout.addWidget(QLabel("Theme"))
        extra_layout.addWidget(self.theme_combo)

        form_layout.addRow("Profile", profile_row)
        form_layout.addRow("Port", port_row)
        form_layout.addRow("Baud Rate", self.baud_combo)
        form_layout.addRow("Data Bits", self.bytesize_combo)
        form_layout.addRow("Parity", self.parity_combo)
        form_layout.addRow("Stop Bits", self.stopbits_combo)
        form_layout.addRow("Flow Control", self.flow_control_combo)
        form_layout.addRow("Line Ending", self.line_ending_combo)
        form_layout.addRow("Options", extra_row)

        self.terminal = QTextEdit(self)
        self.terminal.setReadOnly(True)
        self.terminal.setAcceptRichText(False)
        self.terminal.document().setMaximumBlockCount(5000)
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fixed_font.setPointSize(10)
        self.terminal.setFont(fixed_font)

        command_row = QWidget(self)
        command_layout = QHBoxLayout(command_row)
        command_layout.setContentsMargins(0, 0, 0, 0)
        command_layout.setSpacing(8)

        self.command_input = HistoryLineEdit(self)
        self.command_input.setPlaceholderText("Type a command and press Enter")
        self.command_input.returnPressed.connect(self._send_command)
        self.command_input.historyRequested.connect(self._navigate_history)
        self.command_input.textEdited.connect(self._update_completion_model)

        self.completion_model = QStringListModel(self)
        completer = QCompleter(self.completion_model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.command_input.setCompleter(completer)

        send_button = QPushButton("Send")
        send_button.clicked.connect(self._send_command)
        run_script_button = QPushButton("Run Script")
        run_script_button.clicked.connect(self._run_script)
        stop_script_button = QPushButton("Stop Script")
        stop_script_button.clicked.connect(self._stop_script)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.terminal.clear)
        self.log_button = QPushButton("Start Log")
        self.log_button.clicked.connect(self._toggle_logging)

        command_layout.addWidget(self.command_input, 1)
        command_layout.addWidget(send_button)
        command_layout.addWidget(run_script_button)
        command_layout.addWidget(stop_script_button)
        command_layout.addWidget(clear_button)
        command_layout.addWidget(self.log_button)

        root_layout.addWidget(form_widget)
        root_layout.addWidget(self.terminal, 1)
        root_layout.addWidget(command_row)

        self.status_label = QLabel("Disconnected")
        self.detail_label = QLabel("")
        self.statusBar().addPermanentWidget(self.status_label)
        self.statusBar().addPermanentWidget(self.detail_label, 1)

        self.setCentralWidget(root)
        self.addToolBar(self._build_toolbar())

    def _build_toolbar(self) -> QToolBar:
        toolbar = QToolBar("Session", self)
        toolbar.setMovable(False)
        refresh_action = QAction("Refresh Ports", self)
        refresh_action.triggered.connect(self.refresh_ports)
        toolbar.addAction(refresh_action)
        run_action = QAction("Run Script", self)
        run_action.triggered.connect(self._run_script)
        toolbar.addAction(run_action)
        log_action = QAction("Start or Stop Log", self)
        log_action.triggered.connect(self._toggle_logging)
        toolbar.addAction(log_action)
        clear_action = QAction("Clear Output", self)
        clear_action.triggered.connect(self.terminal.clear)
        toolbar.addAction(clear_action)
        return toolbar

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        run_action = QAction("Run Script...", self)
        run_action.triggered.connect(self._run_script)
        file_menu.addAction(run_action)
        log_action = QAction("Toggle Log", self)
        log_action.triggered.connect(self._toggle_logging)
        file_menu.addAction(log_action)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        session_menu = self.menuBar().addMenu("Session")
        connect_action = QAction("Connect / Disconnect", self)
        connect_action.triggered.connect(self._toggle_connection)
        session_menu.addAction(connect_action)
        save_profile_action = QAction("Save Profile As", self)
        save_profile_action.triggered.connect(self._save_profile_as)
        session_menu.addAction(save_profile_action)

    def _load_profiles(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for name in self.settings.profiles:
            self.profile_combo.addItem(name)
        self.profile_combo.setCurrentText(self.settings.active_profile)
        self.profile_combo.blockSignals(False)
        self._loaded_profile_name = self.settings.active_profile
        self._apply_profile_to_form(self.settings.profiles[self.settings.active_profile])

    def refresh_ports(self) -> None:
        current_port = self.port_combo.currentText().strip()
        ports = self.serial_client.list_ports()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for port in ports:
            label = f"{port['device']} - {port['description']}"
            self.port_combo.addItem(label, port["device"])
        if current_port:
            index = self.port_combo.findData(current_port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
            else:
                self.port_combo.setEditText(current_port)
        self.port_combo.blockSignals(False)
        self._set_detail(f"{len(ports)} serial port(s) detected.")

    def _apply_profile_to_form(self, profile: SerialProfile) -> None:
        self._loading_profile = True
        try:
            port_index = self.port_combo.findData(profile.port)
            if port_index >= 0:
                self.port_combo.setCurrentIndex(port_index)
            else:
                self.port_combo.setEditText(profile.port)
            self.baud_combo.setCurrentText(str(profile.baudrate))
            self.bytesize_combo.setCurrentText(str(profile.bytesize))
            self.parity_combo.setCurrentText(profile.parity)
            self.stopbits_combo.setCurrentText(str(profile.stopbits).rstrip("0").rstrip("."))
            self.flow_control_combo.setCurrentText(profile.flow_control)
            self.line_ending_combo.setCurrentText(profile.line_ending)
            self.auto_reconnect_checkbox.setChecked(profile.auto_reconnect)
            self.dtr_checkbox.setChecked(profile.dtr)
            self.rts_checkbox.setChecked(profile.rts)
            self.timestamps_checkbox.setChecked(self.settings.timestamps_enabled)
            self.theme_combo.setCurrentText(self.settings.theme)
        finally:
            self._loading_profile = False

    def _collect_profile_from_form(self) -> SerialProfile:
        port_value = self.port_combo.currentData()
        port = str(port_value or self.port_combo.currentText()).split(" - ", 1)[0].strip()
        return SerialProfile(
            port=port,
            baudrate=int(self.baud_combo.currentText()),
            bytesize=int(self.bytesize_combo.currentText()),
            parity=self.parity_combo.currentText(),
            stopbits=float(self.stopbits_combo.currentText()),
            flow_control=self.flow_control_combo.currentText(),
            line_ending=self.line_ending_combo.currentText(),
            auto_reconnect=self.auto_reconnect_checkbox.isChecked(),
            dtr=self.dtr_checkbox.isChecked(),
            rts=self.rts_checkbox.isChecked(),
        )

    def _persist_current_profile(self) -> None:
        if self._loading_profile:
            return
        name = self._loaded_profile_name or self.profile_combo.currentText().strip() or "Default"
        self.settings.profiles[name] = self._collect_profile_from_form()
        self.settings.active_profile = self.profile_combo.currentText().strip() or name
        self.settings.timestamps_enabled = self.timestamps_checkbox.isChecked()
        self.settings.theme = self.theme_combo.currentText()

    def _on_profile_selected(self, name: str) -> None:
        self._persist_current_profile()
        self.settings.ensure_active_profile()
        if name in self.settings.profiles:
            self.settings.active_profile = name
            self._loaded_profile_name = name
            self._apply_profile_to_form(self.settings.profiles[name])

    def _save_profile_as(self) -> None:
        self._persist_current_profile()
        name, accepted = QInputDialog.getText(self, "Save Profile", "Profile name")
        if not accepted or not name.strip():
            return
        trimmed = name.strip()
        self.settings.profiles[trimmed] = self._collect_profile_from_form()
        if self.profile_combo.findText(trimmed) < 0:
            self.profile_combo.addItem(trimmed)
        self.profile_combo.setCurrentText(trimmed)
        self._save_settings()

    def _delete_profile(self) -> None:
        name = self.profile_combo.currentText().strip()
        if len(self.settings.profiles) <= 1:
            QMessageBox.information(self, "Profiles", "At least one profile must remain.")
            return
        if not name:
            return
        self.settings.profiles.pop(name, None)
        self.settings.active_profile = next(iter(self.settings.profiles))
        self._load_profiles()
        self._save_settings()

    def _toggle_connection(self) -> None:
        if self.serial_client.is_connected:
            self.serial_client.disconnect()
            return
        self._persist_current_profile()
        profile = self._collect_profile_from_form()
        if not profile.port:
            QMessageBox.warning(self, "Connect", "Choose a COM port before connecting.")
            return
        self.serial_client.connect(profile)
        self._save_settings()

    def _send_command(self) -> None:
        command = self.command_input.text().strip()
        if not command:
            return
        try:
            self.serial_client.send_text(command)
        except Exception as exc:
            QMessageBox.warning(self, "Send Command", str(exc))
            return
        self.history_store.add(command)
        self._update_completion_model()
        self.command_input.clear()

    def _navigate_history(self, direction: int) -> None:
        next_text = self.history_store.navigate(direction, self.command_input.text())
        self.command_input.setText(next_text)
        self.command_input.setCursorPosition(len(next_text))

    def _update_completion_model(self, prefix: str | None = None) -> None:
        current_prefix = prefix if prefix is not None else self.command_input.text()
        self.completion_model.setStringList(self.history_store.suggestions(current_prefix))

    def _run_script(self) -> None:
        start_dir = self.settings.last_script_path or str(Path.cwd())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Run Command Script",
            start_dir,
            "Text Files (*.txt *.cmd *.scr);;All Files (*)",
        )
        if not path:
            return
        try:
            steps = load_batch_file(path)
        except (BatchParseError, OSError) as exc:
            QMessageBox.critical(self, "Run Script", str(exc))
            return
        self.settings.last_script_path = str(Path(path).parent)
        self.batch_runner.start(steps)

    def _stop_script(self) -> None:
        self.batch_runner.stop()

    def _toggle_logging(self) -> None:
        if self.logger.enabled:
            path = self.logger.path
            self.logger.close()
            self.log_button.setText("Start Log")
            self._append_local_status(f"Logging stopped: {path}" if path else "Logging stopped.")
            return
        default_dir = Path(self.settings.log_path).parent if self.settings.log_path else Path.cwd()
        default_name = f"serial-session-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Choose Log File",
            str(default_dir / default_name),
            "Log Files (*.log *.txt);;All Files (*)",
        )
        if not path:
            return
        self.logger.open(path)
        self.settings.log_path = path
        self.log_button.setText("Stop Log")
        self._append_local_status(f"Logging to {path}")
        self._save_settings()

    def _append_local_status(self, message: str) -> None:
        event = SerialEvent(kind="status", message=message)
        self._render_event(event)
        if self.logger.enabled:
            self.logger.log_event(event)
        self._set_detail(message)

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.serial_client.events.get_nowait()
            except Empty:
                break
            self._handle_event(event)

    def _handle_event(self, event: SerialEvent) -> None:
        if event.kind == "connection":
            self._update_connection_state(event.message == "connected")
            self.batch_runner.notify_connection_state(event.message == "connected")
            self._set_detail("Connected." if event.message == "connected" else "Disconnected.")
            return
        self._render_event(event)
        if self.logger.enabled:
            self.logger.log_event(event)
        self._set_detail(event.message.replace("\n", " ")[:180])

    def _render_event(self, event: SerialEvent) -> None:
        color_map = {
            "tx": self._theme.tx,
            "rx": self._theme.rx,
            "error": self._theme.error,
            "status": self._theme.status,
        }
        prefix_map = {
            "tx": "TX>",
            "rx": "RX<",
            "error": "ERR",
            "status": "SYS",
        }
        text = self._format_terminal_text(event, prefix_map.get(event.kind, "LOG"))
        cursor = self.terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        char_format = QTextCharFormat()
        char_format.setForeground(QColor(color_map.get(event.kind, self._theme.text)))
        cursor.insertText(text, char_format)
        if not text.endswith("\n"):
            cursor.insertText("\n", char_format)
        self.terminal.setTextCursor(cursor)
        self.terminal.ensureCursorVisible()

    def _format_terminal_text(self, event: SerialEvent, prefix: str) -> str:
        normalized = event.message.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1] or [""]
        if self.timestamps_checkbox.isChecked():
            stamp = event.timestamp.astimezone().strftime("%H:%M:%S.%f")[:-3]
            return "".join(f"[{stamp}] {prefix} {line}\n" for line in lines)
        return "".join(f"{prefix} {line}\n" for line in lines)

    def _update_connection_state(self, connected: bool) -> None:
        self.connect_button.setText("Disconnect" if connected else "Connect")
        self.status_label.setText("Connected" if connected else "Disconnected")
        for widget in (
            self.profile_combo,
            self.port_combo,
            self.baud_combo,
            self.bytesize_combo,
            self.parity_combo,
            self.stopbits_combo,
            self.flow_control_combo,
            self.line_ending_combo,
            self.auto_reconnect_checkbox,
            self.dtr_checkbox,
            self.rts_checkbox,
        ):
            widget.setEnabled(not connected)

    def _set_detail(self, text: str) -> None:
        self.detail_label.setText(text)

    def _on_theme_changed(self, name: str) -> None:
        if name not in THEMES:
            return
        self._theme = THEMES[name]
        self._apply_theme(self._theme)
        self.settings.theme = name

    def _apply_theme(self, theme: ThemePalette) -> None:
        self.setStyleSheet(
            f"""
            QMainWindow {{
                background: {theme.window};
                color: {theme.text};
            }}
            QWidget {{
                background: {theme.window};
                color: {theme.text};
            }}
            QMenuBar, QMenu, QToolBar {{
                background: {theme.panel};
                color: {theme.text};
                border: 1px solid {theme.border};
            }}
            QLineEdit, QComboBox, QTextEdit {{
                background: {theme.field};
                color: {theme.text};
                border: 1px solid {theme.border};
                padding: 4px;
            }}
            QPushButton {{
                background: {theme.panel};
                color: {theme.text};
                border: 1px solid {theme.border};
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                border-color: {theme.accent};
            }}
            QLabel {{
                color: {theme.text};
            }}
            QStatusBar {{
                background: {theme.panel};
                color: {theme.muted};
            }}
            """
        )
        self.terminal.setStyleSheet(
            f"background: {theme.field}; color: {theme.text}; border: 1px solid {theme.border};"
        )

    def _save_settings(self) -> None:
        self._persist_current_profile()
        self.settings.command_history = self.history_store.all_commands()
        self.settings.window_width = self.width()
        self.settings.window_height = self.height()
        if not self.settings_store.save(self.settings):
            self._set_detail("Could not save settings to disk.")

    def closeEvent(self, event) -> None:
        self.batch_runner.stop(emit_message=False)
        self.serial_client.disconnect()
        self.logger.close()
        self._save_settings()
        super().closeEvent(event)


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Serial Terminal")
    window = MainWindow()
    window.show()
    return app.exec()
