"""ControlPanel binding coordinator: terminal-session targets + dispatchers.

Sibling of :class:`~ComPort_Zone.ui.command_file_targets.CommandFileRunCoordinator`,
with two deltas: bind targets include *disconnected* sessions (a control_panel
binds to a session and gates polling on its connection state, FR-10), and
the coordinator owns the per-session :class:`SessionPollDispatcher`
lifecycle with reference counting so every control_panel bound to one session
shares one dispatcher (FR-17, NFR-4).

Requirements: docs/control_panel-view-requirements.md (FR-10..FR-17).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QStyle

from ..control_panel_engine import SessionPollDispatcher
from ..icons import standard_icon


class SerialClientLike(Protocol):
    is_connected: bool


class BatchSnapshotLike(Protocol):
    is_running: bool


class TerminalSessionLike(Protocol):
    session_id: int
    tab_title: str
    transport: object
    serial_client: SerialClientLike

    def connection_endpoint(self) -> str:
        ...

    def run_target_label(self) -> str:
        ...

    def script_snapshot(self) -> BatchSnapshotLike:
        ...


class ControlPanelTabLike(Protocol):
    def refresh_binding_state(self) -> None:
        ...


@dataclass(frozen=True, slots=True)
class ControlPanelBindTarget:
    session_id: int
    label: str
    endpoint: str
    connected: bool


@dataclass(frozen=True, slots=True)
class SessionHealth:
    """Per-tick view of a bound session, driving the pause reasons.

    ``transport_changed`` flags that the session swapped its transport
    object (e.g. serial -> LAN settings change) while a dispatcher still
    subscribes to the old one; the bound control_panel must rebind.
    """

    open: bool = False
    connected: bool = False
    batch_running: bool = False
    transport_changed: bool = False


@dataclass(slots=True)
class _DispatcherSlot:
    dispatcher: SessionPollDispatcher
    transport: object
    refcount: int


class ControlPanelRunCoordinator:
    """MainWindow-level service shared by all control_panel tabs."""

    def __init__(
        self,
        *,
        sessions_supplier: Callable[[], Iterable[TerminalSessionLike]],
        control_panels_supplier: Callable[[], Iterable[ControlPanelTabLike]],
        is_widget_open: Callable[[object], bool],
        set_status: Callable[[str], None],
        target_icon_color: Callable[[], str],
    ) -> None:
        self._sessions_supplier = sessions_supplier
        self._control_panels_supplier = control_panels_supplier
        self._is_widget_open = is_widget_open
        self._set_status = set_status
        self._target_icon_color = target_icon_color
        self._slots: dict[int, _DispatcherSlot] = {}

    def notify(self, text: str) -> None:
        """Surface a one-line message in the workspace status bar."""
        self._set_status(text)

    # ------------------------------------------------------------- targets

    def bind_targets(self) -> list[ControlPanelBindTarget]:
        """All open terminal sessions — disconnected ones included, since
        binding survives disconnects (FR-10)."""
        return [
            ControlPanelBindTarget(
                session_id=session.session_id,
                label=session.run_target_label(),
                endpoint=session.connection_endpoint(),
                connected=session.serial_client.is_connected,
            )
            for session in self._sessions_supplier()
        ]

    def session_by_id(self, session_id: int) -> TerminalSessionLike | None:
        return next(
            (
                session
                for session in self._sessions_supplier()
                if session.session_id == session_id
            ),
            None,
        )

    def resolve_endpoint(self, endpoint: str) -> TerminalSessionLike | None:
        """The open session whose endpoint matches — only when the match
        is unique (FR-38); ambiguous or missing endpoints return None."""
        cleaned = endpoint.strip()
        if not cleaned:
            return None
        matches = [
            session
            for session in self._sessions_supplier()
            if session.connection_endpoint() == cleaned
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def session_health(self, session_id: int) -> SessionHealth:
        session = self.session_by_id(session_id)
        if session is None or not self._is_widget_open(session):
            return SessionHealth(open=False)
        slot = self._slots.get(session_id)
        return SessionHealth(
            open=True,
            connected=session.serial_client.is_connected,
            batch_running=session.script_snapshot().is_running,
            transport_changed=slot is not None and slot.transport is not session.transport,
        )

    # --------------------------------------------------------- dispatchers

    def acquire_dispatcher(self, session: TerminalSessionLike) -> SessionPollDispatcher:
        """Shared, refcounted dispatcher for a session; created and started
        on first acquire. A stale dispatcher (session swapped transports)
        is replaced transparently, keeping the refcount."""
        slot = self._slots.get(session.session_id)
        if slot is not None and slot.transport is not session.transport:
            slot.dispatcher.stop()
            slot = None
            self._slots.pop(session.session_id, None)
        if slot is None:
            dispatcher = SessionPollDispatcher(transport=session.transport)
            dispatcher.start()
            self._slots[session.session_id] = _DispatcherSlot(
                dispatcher=dispatcher, transport=session.transport, refcount=1
            )
        else:
            slot.refcount += 1
            dispatcher = slot.dispatcher
        # Hand the terminal the poll-traffic journal so it can keep
        # background-poll TX/RX out of its transcript.
        self._set_session_journal(session, dispatcher.traffic_journal)
        return dispatcher

    def release_dispatcher(self, session_id: int) -> None:
        """Drop one reference; the last release stops the worker thread
        and unsubscribes its event queue (NFR-4)."""
        slot = self._slots.get(session_id)
        if slot is None:
            return
        slot.refcount -= 1
        if slot.refcount > 0:
            return
        self._slots.pop(session_id, None)
        slot.dispatcher.stop()
        session = self.session_by_id(session_id)
        if session is not None:
            self._set_session_journal(session, None)

    @staticmethod
    def _set_session_journal(session: TerminalSessionLike, journal) -> None:
        attach = getattr(session, "attach_control_panel_traffic_journal", None)
        if callable(attach):
            attach(journal)

    def dispatcher_count(self) -> int:
        return len(self._slots)

    def shutdown(self) -> None:
        """Stop every dispatcher regardless of refcounts (app close)."""
        slots = list(self._slots.values())
        self._slots.clear()
        for slot in slots:
            slot.dispatcher.stop()

    # ------------------------------------------------------------------ UI

    def refresh_control_panels(self) -> None:
        """Ask every open control_panel tab to re-render its binding chip
        (called from MainWindow.update_connection_status)."""
        for control_panel in self._control_panels_supplier():
            control_panel.refresh_binding_state()

    def populate_bind_menu(self, menu: QMenu, on_bind: Callable[[int], None]) -> None:
        """Fill ``menu`` with one action per open terminal session."""
        menu.clear()
        targets = self.bind_targets()
        if not targets:
            action = menu.addAction("No terminal tabs open")
            action.setEnabled(False)
            return
        for target in targets:
            text = target.label if target.connected else f"{target.label} (disconnected)"
            action = QAction(text, menu)
            action.setIcon(
                standard_icon(
                    QStyle.StandardPixmap.SP_ComputerIcon, 16, self._target_icon_color()
                )
            )
            action.triggered.connect(
                lambda _checked=False, session_id=target.session_id: on_bind(session_id)
            )
            menu.addAction(action)
