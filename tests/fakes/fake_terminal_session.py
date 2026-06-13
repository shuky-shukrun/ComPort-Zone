"""Stub terminal session for control_panel coordinator/tab tests.

Implements the ``TerminalSessionLike`` surface that
:class:`ComPort_Zone.ui.control_panel_targets.ControlPanelRunCoordinator` consumes,
backed by a :class:`FakeSerialTransport` so dispatcher I/O is in-memory.
"""

from __future__ import annotations

from ComPort_Zone.batch import BatchRunSnapshot

from .fake_serial_transport import FakeSerialTransport


class FakeTerminalSession:
    def __init__(self, session_id: int, *, connected: bool = True, endpoint: str = "") -> None:
        self.session_id = session_id
        self.tab_title = f"Terminal {session_id}"
        self.transport = FakeSerialTransport()
        if connected:
            self.transport.connect(object())
        self.serial_client = self.transport
        self._endpoint = endpoint or f"COM{session_id}"
        self.batch_running = False
        # Mirrors TerminalSessionWidget's journal hook; records every attach
        # so tests can assert the coordinator wired/cleared it.
        self.control_panel_traffic_journal = None
        self.journal_attachments: list[object] = []

    def connection_endpoint(self) -> str:
        return self._endpoint

    def run_target_label(self) -> str:
        return f"{self.tab_title} · Serial"

    def script_snapshot(self) -> BatchRunSnapshot:
        return BatchRunSnapshot(is_running=self.batch_running)

    def attach_control_panel_traffic_journal(self, journal) -> None:
        self.control_panel_traffic_journal = journal
        self.journal_attachments.append(journal)
