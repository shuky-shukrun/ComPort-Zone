from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout

from ...models import FLOW_CONTROL_OPTIONS, LINE_ENDINGS, SerialProfile
from ...widgets import ChevronComboBox

COMMON_BAUD_RATES = ["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"]


class ConnectionSettingsDialog(QDialog):
    def __init__(
        self,
        profile: SerialProfile,
        ports: list[dict[str, str]],
        parent=None,
        *,
        ports_supplier: Callable[[], list[dict[str, str]]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Serial Settings")
        self.setMinimumWidth(420)
        self._ports_supplier = ports_supplier
        self._port_signature: tuple[tuple[str, str], ...] | None = None

        self.port_combo = ChevronComboBox(self)
        self.port_combo.setEditable(True)
        self._set_ports(ports, preferred_port=profile.port)

        self.baud_combo = ChevronComboBox(self)
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(COMMON_BAUD_RATES)
        self.baud_combo.setCurrentText(str(profile.baudrate))

        self.bytesize_combo = ChevronComboBox(self)
        self.bytesize_combo.addItems(["5", "6", "7", "8"])
        self.bytesize_combo.setCurrentText(str(profile.bytesize))

        self.parity_combo = ChevronComboBox(self)
        self.parity_combo.addItems(["N", "E", "O", "M", "S"])
        self.parity_combo.setCurrentText(profile.parity)

        self.stopbits_combo = ChevronComboBox(self)
        self.stopbits_combo.addItems(["1", "1.5", "2"])
        self.stopbits_combo.setCurrentText(str(profile.stopbits).rstrip("0").rstrip("."))

        self.flow_combo = ChevronComboBox(self)
        self.flow_combo.addItems(FLOW_CONTROL_OPTIONS)
        self.flow_combo.setCurrentText(profile.flow_control)

        self.line_ending_combo = ChevronComboBox(self)
        self.line_ending_combo.addItems(LINE_ENDINGS.keys())
        self.line_ending_combo.setCurrentText(profile.line_ending)

        self.auto_reconnect = QCheckBox("Auto-reconnect", self)
        self.auto_reconnect.setChecked(profile.auto_reconnect)
        self.dtr = QCheckBox("DTR", self)
        self.dtr.setChecked(profile.dtr)
        self.rts = QCheckBox("RTS", self)
        self.rts.setChecked(profile.rts)

        form = QFormLayout()
        form.addRow("Port", self.port_combo)
        form.addRow("Baud rate", self.baud_combo)
        form.addRow("Data bits", self.bytesize_combo)
        form.addRow("Parity", self.parity_combo)
        form.addRow("Stop bits", self.stopbits_combo)
        form.addRow("Flow control", self.flow_combo)
        form.addRow("Line ending", self.line_ending_combo)
        form.addRow("", self.auto_reconnect)
        form.addRow("", self.dtr)
        form.addRow("", self.rts)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.port_refresh_timer = QTimer(self)
        self.port_refresh_timer.setInterval(1000)
        self.port_refresh_timer.timeout.connect(self.refresh_ports)
        if self._ports_supplier is not None:
            self.port_refresh_timer.start()
        self.finished.connect(lambda *_: self.port_refresh_timer.stop())

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
        if self._ports_supplier is None:
            return False
        try:
            ports = self._ports_supplier()
        except Exception:
            return False
        return self._set_ports(ports)

    def profile(self) -> SerialProfile:
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
