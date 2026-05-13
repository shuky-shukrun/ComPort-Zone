from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...models import FLOW_CONTROL_OPTIONS, LINE_ENDINGS, LanProfile, SerialProfile
from ...widgets import ChevronComboBox

COMMON_BAUD_RATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]


class ConnectionSettingsDialog(QDialog):
    def __init__(
        self,
        profile: SerialProfile | LanProfile,
        ports: list[dict[str, str]],
        parent=None,
        *,
        transport_kind: str | None = None,
        serial_profile: SerialProfile | None = None,
        lan_profile: LanProfile | None = None,
        ports_supplier: Callable[[], list[dict[str, str]]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connection Settings")
        self.setMinimumWidth(420)
        self._ports_supplier = ports_supplier
        self._port_signature: tuple[tuple[str, str], ...] | None = None
        self._transport_kind = transport_kind or ("lan" if isinstance(profile, LanProfile) else "serial")
        serial_profile = serial_profile or (profile if isinstance(profile, SerialProfile) else SerialProfile())
        lan_profile = lan_profile or (profile if isinstance(profile, LanProfile) else LanProfile())

        self.connection_type_combo = ChevronComboBox(self)
        self.connection_type_combo.addItem("Serial", "serial")
        self.connection_type_combo.addItem("LAN", "lan")
        selected_type = self.connection_type_combo.findData(self._transport_kind)
        self.connection_type_combo.setCurrentIndex(max(selected_type, 0))
        self.connection_type_combo.currentIndexChanged.connect(self._connection_type_changed)

        self.port_combo = ChevronComboBox(self)
        self.port_combo.setEditable(True)
        self._set_ports(ports, preferred_port=serial_profile.port)

        self.baud_combo = ChevronComboBox(self)
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(COMMON_BAUD_RATES)
        self.baud_combo.setCurrentText(str(serial_profile.baudrate))

        self.bytesize_combo = ChevronComboBox(self)
        self.bytesize_combo.addItems(["5", "6", "7", "8"])
        self.bytesize_combo.setCurrentText(str(serial_profile.bytesize))

        self.parity_combo = ChevronComboBox(self)
        self.parity_combo.addItems(["N", "E", "O", "M", "S"])
        self.parity_combo.setCurrentText(serial_profile.parity)

        self.stopbits_combo = ChevronComboBox(self)
        self.stopbits_combo.addItems(["1", "1.5", "2"])
        self.stopbits_combo.setCurrentText(str(serial_profile.stopbits).rstrip("0").rstrip("."))

        self.flow_combo = ChevronComboBox(self)
        self.flow_combo.addItems(FLOW_CONTROL_OPTIONS)
        self.flow_combo.setCurrentText(serial_profile.flow_control)

        self.line_ending_combo = ChevronComboBox(self)
        self.line_ending_combo.addItems(LINE_ENDINGS.keys())
        self.line_ending_combo.setCurrentText(serial_profile.line_ending)

        self.auto_reconnect = QCheckBox("Auto-reconnect", self)
        self.auto_reconnect.setChecked(serial_profile.auto_reconnect)
        self.dtr = QCheckBox("DTR", self)
        self.dtr.setChecked(serial_profile.dtr)
        self.rts = QCheckBox("RTS", self)
        self.rts.setChecked(serial_profile.rts)

        serial_widget = QWidget(self)
        serial_form = QFormLayout(serial_widget)
        serial_form.addRow("Port", self.port_combo)
        serial_form.addRow("Baud rate", self.baud_combo)
        serial_form.addRow("Data bits", self.bytesize_combo)
        serial_form.addRow("Parity", self.parity_combo)
        serial_form.addRow("Stop bits", self.stopbits_combo)
        serial_form.addRow("Flow control", self.flow_combo)
        serial_form.addRow("Line ending", self.line_ending_combo)
        serial_form.addRow("", self.auto_reconnect)
        serial_form.addRow("", self.dtr)
        serial_form.addRow("", self.rts)

        self.lan_host_input = QLineEdit(lan_profile.host, self)
        self.lan_host_input.setPlaceholderText("192.168.1.50 or device.local")
        self.lan_port_spin = QSpinBox(self)
        self.lan_port_spin.setRange(1, 65535)
        self.lan_port_spin.setValue(max(1, min(int(lan_profile.port), 65535)))
        self.lan_timeout_spin = QSpinBox(self)
        self.lan_timeout_spin.setRange(10, 60000)
        self.lan_timeout_spin.setSuffix(" ms")
        self.lan_timeout_spin.setValue(max(10, min(int(lan_profile.timeout_ms), 60000)))
        self.lan_line_ending_combo = ChevronComboBox(self)
        self.lan_line_ending_combo.addItems(LINE_ENDINGS.keys())
        self.lan_line_ending_combo.setCurrentText(lan_profile.line_ending)
        self.lan_auto_reconnect = QCheckBox("Auto-reconnect", self)
        self.lan_auto_reconnect.setChecked(lan_profile.auto_reconnect)

        lan_widget = QWidget(self)
        lan_form = QFormLayout(lan_widget)
        lan_form.addRow("Host", self.lan_host_input)
        lan_form.addRow("Port", self.lan_port_spin)
        lan_form.addRow("Line ending", self.lan_line_ending_combo)
        lan_form.addRow("Timeout", self.lan_timeout_spin)
        lan_form.addRow("", self.lan_auto_reconnect)

        self.connection_stack = QStackedWidget(self)
        self.connection_stack.addWidget(serial_widget)
        self.connection_stack.addWidget(lan_widget)
        self._connection_type_changed()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        type_form = QFormLayout()
        type_form.addRow("Type", self.connection_type_combo)
        layout.addLayout(type_form)
        layout.addWidget(self.connection_stack)
        layout.addWidget(buttons)

        self.port_refresh_timer = QTimer(self)
        self.port_refresh_timer.setInterval(1000)
        self.port_refresh_timer.timeout.connect(self.refresh_ports)
        if self._ports_supplier is not None:
            self.port_refresh_timer.start()
        self.finished.connect(lambda *_: self.port_refresh_timer.stop())

    def _connection_type_changed(self, *_args) -> None:
        kind = self.transport_kind()
        self.connection_stack.setCurrentIndex(1 if kind == "lan" else 0)

    def _port_label(self, port: dict[str, str]) -> str:
        device = str(port.get("device", "")).strip()
        description = str(port.get("description", "")).strip() or device
        return f"{device} - {description}" if description and description != device else device

    def _ports_signature_for(self, ports: list[dict[str, str]]) -> tuple[tuple[str, str], ...]:
        return tuple(
            (
                str(port.get("device", "")).strip(),
                str(port.get("description", "")).strip(),
            )
            for port in ports
        )

    def _current_port_text(self) -> str:
        return self.port_combo.currentText().split(" - ", 1)[0].strip()

    def _set_ports(self, ports: list[dict[str, str]], *, preferred_port: str = "") -> bool:
        signature = self._ports_signature_for(ports)
        if signature == self._port_signature and not preferred_port:
            return False
        self._port_signature = signature
        selected_port = preferred_port or self._current_port_text()
        popup_was_open = self.port_combo.view().isVisible()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for port in ports:
            device = str(port.get("device", "")).strip()
            if device:
                self.port_combo.addItem(self._port_label(port), device)
        if selected_port:
            index = self.port_combo.findData(selected_port)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
            else:
                self.port_combo.setEditText(selected_port)
        self.port_combo.blockSignals(False)
        if popup_was_open and self.isVisible():
            QTimer.singleShot(0, self.port_combo.showPopup)
        return True

    def refresh_ports(self) -> bool:
        if self.transport_kind() != "serial" or self._ports_supplier is None:
            return False
        try:
            ports = self._ports_supplier()
        except Exception:
            return False
        return self._set_ports(ports)

    def transport_kind(self) -> str:
        return str(self.connection_type_combo.currentData() or "serial")

    def profile(self) -> SerialProfile | LanProfile:
        if self.transport_kind() == "lan":
            return LanProfile(
                host=self.lan_host_input.text().strip(),
                port=int(self.lan_port_spin.value()),
                line_ending=self.lan_line_ending_combo.currentText(),
                timeout_ms=int(self.lan_timeout_spin.value()),
                auto_reconnect=self.lan_auto_reconnect.isChecked(),
            )
        port_value = self.port_combo.currentData()
        port = self._current_port_text() or str(port_value or "").strip()
        return SerialProfile(
            port=port,
            baudrate=int(self.baud_combo.currentText()),
            bytesize=int(self.bytesize_combo.currentText()),
            parity=self.parity_combo.currentText(),
            stopbits=float(self.stopbits_combo.currentText()),
            flow_control=self.flow_combo.currentText(),
            line_ending=self.line_ending_combo.currentText(),
            auto_reconnect=self.auto_reconnect.isChecked(),
            dtr=self.dtr.isChecked(),
            rts=self.rts.isChecked(),
        )
