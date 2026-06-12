"""Dashboard workspace tab: one open dashboard config.

The third tab type beside terminal and command-file tabs. Owns the GUI
side of polling: a 100 ms tick drains poll results into tiles, watches
the bound session's health (pause reasons), sweeps staleness, and submits
due entries to the session's shared dispatcher. All transport I/O stays
on the dispatcher thread (NFR-1); this widget only moves queue items and
updates labels.

Config edits live-save through the host (``host.save_settings()``) —
there is no dirty state (FR-9).

Requirements: docs/dashboard-view-requirements.md (FR-5..FR-17, FR-22,
FR-27, FR-31, FR-32, FR-36).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from queue import Empty, Queue
from typing import Protocol

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..dashboard_engine import (
    POLL_CANCELLED,
    POLL_OK,
    POLL_SEND_ERROR,
    POLL_TIMEOUT,
    ControlRequest,
    ControlResult,
    DashboardPollScheduler,
    PollRequest,
    PollResult,
    SessionPollDispatcher,
)
from ..dashboard_expr import (
    CompiledExpression,
    ExpressionError,
    build_label_resolver,
    compile_expression,
    rewrite_references,
)
from ..dashboard_history import EntryHistory
from ..dashboard_models import (
    DashboardConfig,
    DashboardEntry,
    DashboardTabState,
    grid_row_count,
    normalize_layout,
)
from ..dashboard_parse import (
    CompiledParseRule,
    ParseOutcome,
    evaluate_rules,
    format_tile_value,
)
from ..icons import set_button_icon
from ..themes import ThemePalette
from .dashboard_chart import DEFAULT_SPAN_S, DashboardChartPage
from .dashboard_grid import DashboardGridWidget
from .dashboard_tiles import (
    TILE_STATE_CAPTIONS,
    ControlTileWidget,
    TileRuntime,
    ValueTileWidget,
    tile_state_color,
)
from .dialogs.dashboard_entry import DashboardEntryDialog, EntryDialogContext
from .tokens import CONTROL_H_SM, SPACE_LG, SPACE_MD, SPACE_XL


class DashboardHostLike(Protocol):
    """What the tab needs from MainWindow (kept tiny for tests)."""

    theme: ThemePalette

    def save_settings(self) -> None:
        ...


class SessionHealthLike(Protocol):
    open: bool
    connected: bool
    batch_running: bool
    transport_changed: bool


class DashboardCoordinatorLike(Protocol):
    def session_by_id(self, session_id: int): ...
    def resolve_endpoint(self, endpoint: str): ...
    def session_health(self, session_id: int) -> SessionHealthLike: ...
    def acquire_dispatcher(self, session) -> SessionPollDispatcher: ...
    def release_dispatcher(self, session_id: int) -> None: ...
    def bind_targets(self) -> list: ...
    def populate_bind_menu(self, menu: QMenu, on_bind: Callable[[int], None]) -> None: ...
    def notify(self, text: str) -> None: ...


STALENESS_SWEEP_EVERY_TICKS = 10
# ~10 Hz chart refresh while the chart page is the current view (FR-49);
# nothing fires when the grid is visible.
CHART_REFRESH_INTERVAL_MS = 100


class DashboardTabWidget(QWidget):
    """Renders one dashboard config and drives its polling."""

    TICK_INTERVAL_MS = 100

    stateChanged = Signal()

    def __init__(
        self,
        host: DashboardHostLike,
        config: DashboardConfig,
        tab_state: DashboardTabState | None,
        *,
        coordinator: DashboardCoordinatorLike,
        clock: Callable[[], float] = time.monotonic,
        start_timer: bool = True,
    ) -> None:
        super().__init__()
        self.host = host
        self.config = config
        self.coordinator = coordinator
        self._clock = clock
        self.scheduler = DashboardPollScheduler(clock=clock)
        self.result_queue: Queue[PollResult] = Queue()
        # v2 multi-session topology (FR-54..56): the dashboard's default
        # binding plus per-entry overrides each hold a shared, refcounted
        # dispatcher; health is gated per session at submit time.
        self._bound_session_id: int | None = None
        self._dispatchers: dict[int, SessionPollDispatcher] = {}
        self._gates: dict[int, "SessionHealthLike"] = {}
        self._gate_connected_prev: dict[int, bool] = {}
        self._gate_healthy_prev: dict[int, bool] = {}
        self._entry_session: dict[str, int | None] = {}
        self._has_entry_overrides = False
        self._compiled: dict[str, CompiledParseRule] = {}
        # v2 derived tiles (FR-61): compiled expressions, reverse dependency
        # map (input entry id -> derived entry ids) and the latest numeric
        # value per polled entry feeding them.
        self._compiled_exprs: dict[str, CompiledExpression] = {}
        self._derived_by_input: dict[str, list[str]] = {}
        self._latest_numbers: dict[str, float] = {}
        self._has_derived = False
        # v2 control tiles (FR-59/60): watch entry id -> dependent control
        # ids, and the ON/OFF state each in-flight click aims for.
        self._controls_by_watch: dict[str, list[str]] = {}
        self._control_intent: dict[str, bool] = {}
        # v2 sparkline history (FR-46/FR-47): one ring per numeric entry,
        # fed from _apply_outcome — never persisted (NFR-3).
        self._histories: dict[str, EntryHistory] = {}
        self._theme: ThemePalette = host.theme
        # Chart-page id (FR-48): "" while the grid is showing, else the
        # focused entry. The refresh timer fires only while non-empty.
        self._chart_entry_id: str = ""
        self._runtimes: dict[str, TileRuntime] = {}
        self._tick_count = 0
        self._tab_state = tab_state or DashboardTabState(dashboard_id=config.id)
        self._tab_state.dashboard_id = config.id

        self._build_ui()
        self.scheduler.set_paused("unbound", True)
        if not self._tab_state.polling_enabled:
            self.scheduler.set_paused("user", True)
            self.pause_button.blockSignals(True)
            self.pause_button.setChecked(True)
            self.pause_button.blockSignals(False)
            set_button_icon(self.pause_button, "play", 15)
            self.pause_button.setToolTip("Resume polling")
        self._configure_entries(save=False)
        self.refresh_binding_state()

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self._tick)
        if start_timer:
            self.tick_timer.start(self.TICK_INTERVAL_MS)

        # Chart refresh runs on its own timer so the grid tick stays
        # untouched. Only starts when the chart opens (FR-49 — visible
        # only).
        self.chart_refresh_timer = QTimer(self)
        self.chart_refresh_timer.timeout.connect(self._refresh_chart)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        header = QWidget(self)
        header.setObjectName("dashboardHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(SPACE_XL, SPACE_MD, SPACE_XL, SPACE_MD)
        header_layout.setSpacing(SPACE_LG)

        self.name_label = QLabel(self.config.name, header)
        self.name_label.setObjectName("dialogTitle")

        self.bind_button = QToolButton(header)
        self.bind_button.setObjectName("dashboardHeaderButton")
        self.bind_button.setText("Bind")
        self.bind_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        set_button_icon(self.bind_button, "plug", 15)
        self.bind_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._bind_menu = QMenu(self.bind_button)
        self._bind_menu.aboutToShow.connect(self._populate_bind_menu)
        self.bind_button.setMenu(self._bind_menu)
        self.bind_button.setFixedHeight(CONTROL_H_SM)
        self.bind_button.setCursor(Qt.CursorShape.PointingHandCursor)

        self.bind_chip = QLabel("Unbound", header)
        self.bind_chip.setObjectName("dashboardBindChip")

        self.save_state_label = QLabel("", header)
        self.save_state_label.setObjectName("dashboardSaveState")
        self.save_state_label.setToolTip(
            "Dashboard changes save automatically — this shows the last save time."
        )

        self.pause_button = QToolButton(header)
        self.pause_button.setObjectName("dashboardHeaderButton")
        self.pause_button.setCheckable(True)
        self.pause_button.setToolTip("Pause polling")
        set_button_icon(self.pause_button, "pause", 15)
        self.pause_button.toggled.connect(self._pause_toggled)
        self.pause_button.setFixedHeight(CONTROL_H_SM)
        self.pause_button.setCursor(Qt.CursorShape.PointingHandCursor)

        self.edit_layout_button = QToolButton(header)
        self.edit_layout_button.setObjectName("dashboardHeaderButton")
        self.edit_layout_button.setCheckable(True)
        self.edit_layout_button.setToolTip("Edit layout: drag tiles, resize via right-click")
        set_button_icon(self.edit_layout_button, "arrows", 15)
        self.edit_layout_button.toggled.connect(self._edit_mode_toggled)
        self.edit_layout_button.setFixedHeight(CONTROL_H_SM)
        self.edit_layout_button.setCursor(Qt.CursorShape.PointingHandCursor)

        self.add_entry_button = QToolButton(header)
        self.add_entry_button.setObjectName("dashboardHeaderButton")
        self.add_entry_button.setText("Add Entry")
        self.add_entry_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        set_button_icon(self.add_entry_button, "plus", 15)
        self.add_entry_button.clicked.connect(self.add_entry_via_dialog)
        self.add_entry_button.setFixedHeight(CONTROL_H_SM)
        self.add_entry_button.setCursor(Qt.CursorShape.PointingHandCursor)

        header_layout.addWidget(self.name_label)
        header_layout.addWidget(self.bind_button)
        header_layout.addWidget(self.bind_chip)
        header_layout.addStretch(1)
        header_layout.addWidget(self.save_state_label)
        header_layout.addWidget(self.pause_button)
        header_layout.addWidget(self.edit_layout_button)
        header_layout.addWidget(self.add_entry_button)

        self.grid = DashboardGridWidget()
        self.grid.layoutChanged.connect(self._layout_changed)
        self.grid.tileEditRequested.connect(self.edit_entry_via_dialog)
        self.grid.tileRemoveRequested.connect(self.remove_entry)
        self.grid.tileEnableToggled.connect(self.set_entry_enabled)
        self.grid.tilePollNowRequested.connect(self.poll_now)
        self.grid.tileControlActivated.connect(self._activate_control)
        self.grid.tileChartRequested.connect(self.open_chart)
        self.grid.set_config(self.config)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidget(self.grid)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)

        empty_page = QWidget(self)
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.addStretch(1)
        empty_title = QLabel("No entries yet", empty_page)
        empty_title.setObjectName("dashboardEmptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint = QLabel(
            "Add an entry to poll a command in the background and watch its value here.",
            empty_page,
        )
        empty_hint.setObjectName("dashboardEmptyHint")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint.setWordWrap(True)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_hint)
        empty_layout.addStretch(1)

        self.chart_page = DashboardChartPage(self)
        self.chart_page.backRequested.connect(self.close_chart)

        self.stack = QStackedWidget(self)
        self.EMPTY_PAGE = self.stack.addWidget(empty_page)
        self.GRID_PAGE = self.stack.addWidget(self.scroll_area)
        self.CHART_PAGE = self.stack.addWidget(self.chart_page)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(header)
        root.addWidget(self.stack, 1)
        self._refresh_empty_state()

    def _refresh_empty_state(self) -> None:
        # The chart page is its own mode; only switch between empty + grid
        # so opening the chart doesn't get clobbered by a config edit.
        if self.stack.currentIndex() == self.CHART_PAGE:
            return
        self.stack.setCurrentIndex(self.GRID_PAGE if self.config.entries else self.EMPTY_PAGE)

    def _note_saved(self) -> None:
        """Reflect the auto-save in the header (dashboards have no dirty
        state — every change is persisted the moment it happens)."""
        self.save_state_label.setText(f"Saved {datetime.now():%H:%M:%S}")

    # ------------------------------------------------------- tab protocol

    def tab_title(self) -> str:
        return self.config.name

    def status_summary(self) -> str:
        count = len(self.config.entries)
        entries_text = f"{count} entr{'y' if count == 1 else 'ies'}"
        alerts = sum(
            1 for runtime in self._runtimes.values() if runtime.state in ("warn", "fail", "error")
        )
        alert_text = f" · {alerts} alert(s)" if alerts else ""
        return f"{self.config.name} · {entries_text} · {self._binding_summary_text()}{alert_text}"

    def _binding_summary_text(self) -> str:
        if "user" in self.scheduler.paused_reasons:
            return "paused"
        lines = self._target_status_lines()
        resolvable = [line for line in lines if line[1] != "no matching terminal tab"]
        if not resolvable:
            return "unbound"
        if not self._has_entry_overrides:
            label, status, healthy = lines[0]
            if healthy:
                return f"polling {label}"
            if status == "disconnected":
                return "paused — disconnected"
            return "paused — command file running"
        healthy_lines = [line for line in lines if line[2]]
        if healthy_lines:
            return f"polling {len(healthy_lines)}/{len(lines)} targets"
        return f"paused · {len(lines)} targets"

    def to_tab_state(self) -> DashboardTabState:
        return DashboardTabState(
            dashboard_id=self.config.id,
            target_endpoint=self._tab_state.target_endpoint,
            target_title=self._tab_state.target_title,
            polling_enabled="user" not in self.scheduler.paused_reasons,
        )

    def shutdown(self) -> None:
        """Stop the tick and release every held dispatcher (tab close, app
        close, settings re-apply). Safe to call twice (NFR-4)."""
        self.tick_timer.stop()
        self.chart_refresh_timer.stop()
        for session_id, dispatcher in list(self._dispatchers.items()):
            dispatcher.cancel_dashboard(self.config.id)
            self.coordinator.release_dispatcher(session_id)
        self._dispatchers.clear()
        self._gates.clear()
        self._bound_session_id = None

    def apply_theme_palette(self, theme: ThemePalette) -> None:
        self._theme = theme
        self.grid.apply_theme_palette(theme)
        self.chart_page.apply_theme_palette(theme)
        # Color depends on the active theme, so feed every visible tile.
        for entry in self.config.entries:
            self._refresh_sparkline(entry.id)

    # ------------------------------------------------------------- binding

    @property
    def bound_session_id(self) -> int | None:
        return self._bound_session_id

    def bind_to_session(self, session_id: int) -> bool:
        """Set the dashboard's default binding (override entries keep their
        own targets, FR-54)."""
        session = self.coordinator.session_by_id(session_id)
        if session is None:
            return False
        self._bound_session_id = session_id
        self.scheduler.release_all_in_flight()
        self._tab_state.target_endpoint = session.connection_endpoint()
        self._tab_state.target_title = session.tab_title
        self._refresh_session_topology()
        self.refresh_binding_state()
        self.stateChanged.emit()
        self.host.save_settings()
        self._note_saved()
        return True

    def unbind(self, notice: str = "") -> None:
        self._bound_session_id = None
        self.scheduler.release_all_in_flight()
        self._refresh_session_topology()
        if notice:
            self.bind_chip.setToolTip(notice)
        self.refresh_binding_state()
        self.stateChanged.emit()

    def resolve_persisted_binding(self) -> None:
        """Rebind after restore using the endpoint hint — only on a unique
        match (FR-38); otherwise stay unbound with the bind menu ready.
        Per-entry overrides resolve continuously in the tick."""
        endpoint = self._tab_state.target_endpoint
        if not endpoint or self._bound_session_id is not None:
            return
        session = self.coordinator.resolve_endpoint(endpoint)
        if session is not None:
            self.bind_to_session(session.session_id)

    def _populate_bind_menu(self) -> None:
        self.coordinator.populate_bind_menu(self._bind_menu, self.bind_to_session)

    # ----------------------------------------------- multi-session topology

    def _resolve_entry_sessions(self) -> None:
        """entry_id -> session_id (or None) for every schedulable/control
        entry. Fast path: with no overrides, everything maps to the
        default binding without per-entry work."""
        mapping: dict[str, int | None] = {}
        for entry in self.config.entries:
            if entry.is_derived():
                continue
            if entry.target_endpoint:
                session = self.coordinator.resolve_endpoint(entry.target_endpoint)
                mapping[entry.id] = session.session_id if session is not None else None
            else:
                mapping[entry.id] = self._bound_session_id
        self._entry_session = mapping

    def _required_session_ids(self) -> set[int]:
        return {
            session_id for session_id in self._entry_session.values() if session_id is not None
        }

    def _refresh_session_topology(self) -> None:
        """Resolve entries, acquire dispatchers for newly needed sessions,
        release no-longer-needed ones, and refresh health gates."""
        self._resolve_entry_sessions()
        required = self._required_session_ids()
        for session_id in list(self._dispatchers):
            if session_id not in required:
                self._dispatchers.pop(session_id).cancel_dashboard(self.config.id)
                self.coordinator.release_dispatcher(session_id)
                self._gates.pop(session_id, None)
                self._gate_connected_prev.pop(session_id, None)
                self._gate_healthy_prev.pop(session_id, None)
        for session_id in required:
            if session_id in self._dispatchers:
                continue
            session = self.coordinator.session_by_id(session_id)
            if session is None:
                continue
            self._dispatchers[session_id] = self.coordinator.acquire_dispatcher(session)
        self.scheduler.set_paused("unbound", not self._dispatchers)
        self._refresh_gates()

    def _refresh_gates(self) -> None:
        """Snapshot per-session health; fire connect-edge triggers and
        gate-open restaggers (FR-52/FR-55)."""
        for session_id in list(self._dispatchers):
            health = self.coordinator.session_health(session_id)
            if not health.open:
                # Session's tab closed: drop it; affected entries go stale.
                self._dispatchers.pop(session_id).cancel_dashboard(self.config.id)
                self.coordinator.release_dispatcher(session_id)
                self._gates.pop(session_id, None)
                self._gate_connected_prev.pop(session_id, None)
                self._gate_healthy_prev.pop(session_id, None)
                if session_id == self._bound_session_id:
                    self.unbind(notice="The bound terminal tab was closed.")
                continue
            if health.transport_changed:
                # Session swapped transports (connection-settings change):
                # re-acquire so the dispatcher subscribes to the live one.
                old = self._dispatchers.pop(session_id)
                old.cancel_dashboard(self.config.id)
                self.coordinator.release_dispatcher(session_id)
                session = self.coordinator.session_by_id(session_id)
                if session is not None:
                    self._dispatchers[session_id] = self.coordinator.acquire_dispatcher(session)
                health = self.coordinator.session_health(session_id)
            self._gates[session_id] = health
            connected_prev = self._gate_connected_prev.get(session_id, False)
            if health.connected and not connected_prev:
                self._trigger_on_connect(session_id)
            self._gate_connected_prev[session_id] = health.connected
            healthy = health.connected and not health.batch_running
            if healthy and not self._gate_healthy_prev.get(session_id, False):
                self.scheduler.restagger(self._session_entry_ids(session_id))
            self._gate_healthy_prev[session_id] = healthy

    def _session_entry_ids(self, session_id: int) -> list[str]:
        return [
            entry_id
            for entry_id, mapped in self._entry_session.items()
            if mapped == session_id
        ]

    def _trigger_on_connect(self, session_id: int) -> None:
        """Fire each enabled on_connect entry targeting this session once,
        staggered (FR-52)."""
        index = 0
        for entry in self.config.entries:
            if entry.poll_mode != "on_connect" or not entry.enabled:
                continue
            if self._entry_session.get(entry.id) != session_id:
                continue
            if self.scheduler.trigger_now(entry.id, delay_s=index * 0.025):
                index += 1

    def poll_now(self, entry_id: str) -> bool:
        """Manual one-shot poll for any pollable entry (FR-53)."""
        entry = self.config.entry_by_id(entry_id)
        if entry is None or not entry.is_polled():
            return False
        return self.scheduler.trigger_now(entry_id)

    # ---------------------------------------------------------- chart page

    def open_chart(self, entry_id: str) -> bool:
        """Switch the workspace to the chart view for ``entry_id``.

        Numeric polled or derived entries only; controls/text entries are
        rejected silently. Closing returns to the grid via
        :meth:`close_chart` (or automatically when the entry is removed,
        FR-48)."""
        entry = self.config.entry_by_id(entry_id)
        if entry is None or not entry.is_numeric() or entry.is_control():
            return False
        self._chart_entry_id = entry_id
        self.chart_page.apply_theme_palette(self._theme)
        self.chart_page.set_entry(entry)
        self._refresh_chart()
        self.stack.setCurrentIndex(self.CHART_PAGE)
        if not self.chart_refresh_timer.isActive():
            self.chart_refresh_timer.start(CHART_REFRESH_INTERVAL_MS)
        return True

    def close_chart(self) -> None:
        if self.chart_refresh_timer.isActive():
            self.chart_refresh_timer.stop()
        self._chart_entry_id = ""
        # Switch off CHART_PAGE first, then let the empty/grid logic
        # pick — _refresh_empty_state intentionally guards against
        # config edits clobbering an open chart, so it would no-op here.
        self.stack.setCurrentIndex(self.GRID_PAGE if self.config.entries else self.EMPTY_PAGE)

    @property
    def chart_entry_id(self) -> str:
        return self._chart_entry_id

    def _refresh_chart(self) -> None:
        entry_id = self._chart_entry_id
        if not entry_id:
            return
        entry = self.config.entry_by_id(entry_id)
        if entry is None:
            # The entry was removed (or kind-converted away from numeric)
            # while the chart was open — drop back to the grid.
            self.close_chart()
            return
        history = self._histories.get(entry_id)
        samples = history.samples() if history is not None else []
        runtime = self._runtimes.get(entry_id)
        if runtime is not None and runtime.color:
            color = runtime.color
        elif runtime is not None:
            color = tile_state_color(runtime.state, self._theme)
        else:
            color = tile_state_color("ok", self._theme)
        self.chart_page.set_history(samples, color, now=self._clock())

    # ------------------------------------------------------------- controls

    def _activate_control(self, entry_id: str) -> bool:
        """Click handler for control tiles (FR-59/FR-60): gate, optionally
        confirm, then queue exactly one tagged send through the target
        session's FIFO. Allowed while user-paused — a click is explicit
        intent — but refused while disconnected or batch-running."""
        entry = self.config.entry_by_id(entry_id)
        if entry is None or not entry.is_control() or not entry.enabled:
            return False
        tile = self.grid.tile(entry_id)
        if isinstance(tile, ControlTileWidget) and tile.pending:
            return False
        label = entry.display_label()
        session_id = self._entry_session.get(entry_id)
        gate = self._gates.get(session_id) if session_id is not None else None
        dispatcher = self._dispatchers.get(session_id) if session_id is not None else None
        if gate is None or dispatcher is None:
            self.coordinator.notify(f"{label}: no matching terminal tab to send to.")
            return False
        if not gate.connected:
            self.coordinator.notify(f"{label}: the target terminal is not connected.")
            return False
        if gate.batch_running:
            self.coordinator.notify(
                f"{label}: a command file is running on the target terminal."
            )
            return False
        control = entry.control
        turn_on = True
        if control.mode == "toggle":
            turn_on = not self._control_is_on(entry)
        command = control.on_command if turn_on else control.off_command
        if control.confirm and not self._confirm_control(label, command):
            return False
        request = ControlRequest(
            dashboard_id=self.config.id,
            entry_id=entry_id,
            command=command,
            send_mode=entry.send_mode,
            line_ending_override=entry.line_ending_override,
            result_queue=self.result_queue,
        )
        if not dispatcher.submit_control(request):
            self.coordinator.notify(f"{label}: could not queue the command.")
            return False
        self._control_intent[entry_id] = turn_on
        if isinstance(tile, ControlTileWidget):
            tile.set_pending(True)
        return True

    def _control_is_on(self, entry: DashboardEntry) -> bool:
        """A toggle's current state: the watch entry's verdict when one is
        set ("ok" means ON), else the tile's optimistic state."""
        watch_id = entry.control.watch_entry_id
        if watch_id:
            runtime = self._runtimes.get(watch_id)
            return bool(runtime is not None and runtime.state == "ok")
        tile = self.grid.tile(entry.id)
        return isinstance(tile, ControlTileWidget) and tile.is_on

    def _confirm_control(self, label: str, command: str) -> bool:
        answer = QMessageBox.question(
            self,
            "Confirm control",
            f"Send '{command}' ({label})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _handle_control_result(self, result: ControlResult) -> None:
        entry = self.config.entry_by_id(result.entry_id)
        tile = self.grid.tile(result.entry_id)
        if isinstance(tile, ControlTileWidget):
            tile.set_pending(False)
        intent = self._control_intent.pop(result.entry_id, None)
        if entry is None:
            return
        runtime = self._runtimes.setdefault(
            result.entry_id, TileRuntime(entry_id=result.entry_id)
        )
        runtime.last_result_at = self._clock()
        runtime.timestamp_text = datetime.now().strftime("%H:%M:%S")
        if result.status == POLL_OK:
            runtime.last_success_at = self._clock()
            runtime.state = "neutral"
            runtime.state_caption = ""
            runtime.tooltip = "Command sent."
            if (
                entry.control.mode == "toggle"
                and not entry.control.watch_entry_id
                and intent is not None
                and isinstance(tile, ControlTileWidget)
            ):
                tile.set_on(intent)  # optimistic flip — no watch entry (FR-59)
        elif result.status == POLL_SEND_ERROR:
            runtime.state = "error"
            runtime.state_caption = TILE_STATE_CAPTIONS["error"]
            runtime.tooltip = f"Send failed: {result.error}"
        # Cancelled sends just clear the pending state.
        self._update_tile(result.entry_id)

    # ----------------------------------------------------------- chip text

    def _target_status_lines(self) -> list[tuple[str, str, bool]]:
        """(endpoint label, status text, healthy) per involved target."""
        lines: list[tuple[str, str, bool]] = []
        seen: set[int | None] = set()
        ordered_targets: list[tuple[str, int | None]] = []
        if self._bound_session_id is not None or not self._has_entry_overrides:
            default_label = self._tab_state.target_endpoint or self._tab_state.target_title or "—"
            ordered_targets.append((default_label, self._bound_session_id))
            seen.add(self._bound_session_id)
        for entry in self.config.entries:
            if not entry.target_endpoint:
                continue
            session_id = self._entry_session.get(entry.id)
            if session_id in seen and session_id is not None:
                continue
            seen.add(session_id)
            ordered_targets.append((entry.target_endpoint, session_id))
        for label, session_id in ordered_targets:
            if session_id is None:
                lines.append((label, "no matching terminal tab", False))
                continue
            gate = self._gates.get(session_id)
            if gate is None or not gate.connected:
                lines.append((label, "disconnected", False))
            elif gate.batch_running:
                lines.append((label, "command file running", False))
            else:
                lines.append((label, "polling", True))
        return lines

    def refresh_binding_state(self) -> None:
        """Re-render the binding chip (cheap; called on connection events
        and from the tick when gate states change)."""
        lines = self._target_status_lines()
        user_paused = "user" in self.scheduler.paused_reasons
        healthy_lines = [line for line in lines if line[2]]
        resolvable = [line for line in lines if line[1] != "no matching terminal tab"]
        if user_paused:
            state, text = "paused", "Paused"
            tooltip = "Polling paused by you."
        elif not resolvable:
            state = "unbound"
            if self._has_entry_overrides and lines:
                text = f"Unbound · {len(lines)} target(s)"
            else:
                text = "Unbound"
            tooltip = "Bind this dashboard to a terminal tab to start polling."
        elif not self._has_entry_overrides:
            # Single-target dashboards keep the exact v1 chip language.
            label, status, healthy = lines[0]
            if healthy:
                state, text = "polling", f"Polling {label}"
                tooltip = f"Bound to {self._tab_state.target_title} ({label})"
            else:
                state = "paused"
                if status == "disconnected":
                    text = "Paused — disconnected"
                    tooltip = f"{label} is disconnected; polling resumes on reconnect."
                else:
                    text = "Paused — command file running"
                    tooltip = "A command file is running on the bound terminal."
        else:
            extra = len(lines) - 1
            if healthy_lines:
                state = "polling"
                text = f"Polling {healthy_lines[0][0]} · +{extra} target(s)" if extra else f"Polling {healthy_lines[0][0]}"
            else:
                state, text = "paused", f"Paused · {len(lines)} target(s)"
            tooltip = "\n".join(f"{label} — {status}" for label, status, _healthy in lines)
        if self.bind_chip.text() != text:
            self.bind_chip.setText(text)
        if tooltip:
            self.bind_chip.setToolTip(tooltip)
        if self.bind_chip.property("state") != state:
            self.bind_chip.setProperty("state", state)
            style = self.bind_chip.style()
            style.unpolish(self.bind_chip)
            style.polish(self.bind_chip)
            self.bind_chip.update()

    # ------------------------------------------------------------- polling

    def set_polling_enabled(self, enabled: bool) -> None:
        self.scheduler.set_paused("user", not enabled)
        self._tab_state.polling_enabled = enabled
        if self.pause_button.isChecked() == enabled:
            self.pause_button.blockSignals(True)
            self.pause_button.setChecked(not enabled)
            self.pause_button.blockSignals(False)
        # The button always shows the action a click would take: pause while
        # polling, play while paused.
        set_button_icon(self.pause_button, "pause" if enabled else "play", 15)
        self.pause_button.setToolTip("Pause polling" if enabled else "Resume polling")
        self.refresh_binding_state()
        self.stateChanged.emit()
        self.host.save_settings()
        self._note_saved()

    def _pause_toggled(self, checked: bool) -> None:
        self.set_polling_enabled(not checked)

    def _tick(self) -> None:
        """One scheduler tick — also called directly by tests."""
        self._tick_count += 1
        self._drain_results()
        self._check_session_health()
        if self._tick_count % STALENESS_SWEEP_EVERY_TICKS == 0:
            self._sweep_staleness()
        self._submit_due()

    def _drain_results(self) -> None:
        while True:
            try:
                result = self.result_queue.get_nowait()
            except Empty:
                return
            self._handle_result(result)

    def _check_session_health(self) -> None:
        """Per-tick topology + health refresh.

        Override targets can appear/close at any moment, so dashboards
        with overrides re-resolve every tick (a dict-lookup loop over the
        entries). Without overrides the mapping only changes through
        bind/unbind/config edits — which refresh it themselves — so the
        tick just refreshes gates (the v1 cost profile, NFR-12)."""
        previous = (dict(self._gates), self._bound_session_id, set(self._dispatchers))
        if self._has_entry_overrides:
            self._refresh_session_topology()
        else:
            self._refresh_gates()
        if (dict(self._gates), self._bound_session_id, set(self._dispatchers)) != previous:
            self.refresh_binding_state()
            self.stateChanged.emit()

    def _submit_due(self) -> None:
        if not self._dispatchers:
            return
        for entry in self.scheduler.collect_due():
            session_id = self._entry_session.get(entry.id)
            gate = self._gates.get(session_id) if session_id is not None else None
            # Per-entry gating (FR-55): an unhealthy target's entries are
            # skipped (they stay due and retry next tick) without touching
            # entries on healthy sessions.
            if gate is None or not gate.connected or gate.batch_running:
                self.scheduler.skip(entry.id)
                continue
            dispatcher = self._dispatchers.get(session_id)
            compiled = self._compiled.get(entry.id)
            if dispatcher is None or compiled is None:
                self.scheduler.skip(entry.id)
                continue
            request = PollRequest(
                dashboard_id=self.config.id,
                entry=entry,
                compiled=compiled,
                result_queue=self.result_queue,
            )
            if not dispatcher.submit(request):
                self.scheduler.skip(entry.id)

    def _handle_result(self, result) -> None:
        if isinstance(result, ControlResult):
            self._handle_control_result(result)
            return
        if result.status == POLL_CANCELLED:
            self.scheduler.skip(result.entry_id)
            return
        self.scheduler.complete(result.entry_id)
        entry = self.config.entry_by_id(result.entry_id)
        if entry is None:
            return
        if result.status == POLL_OK and result.outcome is not None:
            self._apply_outcome(entry, result.outcome, result.raw_window)
            return
        runtime = self._runtimes.setdefault(result.entry_id, TileRuntime(entry_id=result.entry_id))
        runtime.last_result_at = self._clock()
        runtime.timestamp_text = datetime.now().strftime("%H:%M:%S")
        if result.status == POLL_TIMEOUT:
            runtime.consecutive_timeouts += 1
            runtime.state = "stale"
            runtime.state_caption = TILE_STATE_CAPTIONS["stale"]
            runtime.color = ""  # the matched rule's color is no longer current
            runtime.tooltip = (
                f"No response within {entry.timeout_ms} ms "
                f"({runtime.consecutive_timeouts} timeout(s) in a row).\n"
                f"RX window: {result.raw_window[-500:]}"
            )
        elif result.status == POLL_SEND_ERROR:
            runtime.state = "error"
            runtime.state_caption = TILE_STATE_CAPTIONS["error"]
            runtime.color = ""
            runtime.tooltip = f"Send failed: {result.error}"
        self._update_tile(result.entry_id)

    def _apply_outcome(self, entry: DashboardEntry, outcome: ParseOutcome, raw_window: str = "") -> None:
        """The shared value sink (poll results AND derived recomputes):
        verdict -> runtime -> tile, then fan out to dependent derived
        entries. History/CSV/alert hooks attach here (v2 funnel)."""
        runtime = self._runtimes.setdefault(entry.id, TileRuntime(entry_id=entry.id))
        runtime.last_result_at = self._clock()
        runtime.timestamp_text = datetime.now().strftime("%H:%M:%S")
        runtime.last_success_at = self._clock()
        runtime.consecutive_timeouts = 0
        runtime.value_text = format_tile_value(outcome, entry.unit)
        verdict = evaluate_rules(entry.rules, outcome)
        runtime.state = verdict.state
        runtime.state_caption = verdict.label or TILE_STATE_CAPTIONS.get(verdict.state, "")
        runtime.color = verdict.color
        if entry.is_derived():
            runtime.tooltip = f"= {entry.expression}"
            if outcome.error:
                runtime.tooltip = f"{outcome.error}\n= {entry.expression}"
        elif outcome.error:
            runtime.tooltip = f"{outcome.error}\nRX window: {raw_window[-500:]}"
        else:
            runtime.tooltip = f"RX window: {raw_window[-500:]}"
        # Numeric outcomes feed the sparkline history (poll + derived,
        # FR-46/FR-47); cleared with the runtime in _configure_entries.
        if entry.is_numeric() and outcome.value_number is not None and not outcome.error:
            history = self._histories.setdefault(entry.id, EntryHistory())
            history.append(self._clock(), float(outcome.value_number))
        self._update_tile(entry.id)
        self._refresh_sparkline(entry.id)
        if self._has_derived and entry.is_polled() and outcome.value_number is not None:
            self._latest_numbers[entry.id] = outcome.value_number
            self._recompute_dependents(entry.id)

    def _recompute_dependents(self, input_entry_id: str) -> None:
        for derived_id in self._derived_by_input.get(input_entry_id, []):
            self._recompute_derived(derived_id)

    def _recompute_derived(self, derived_id: str) -> None:
        entry = self.config.entry_by_id(derived_id)
        compiled = self._compiled_exprs.get(derived_id)
        if entry is None or compiled is None or not entry.enabled:
            return
        missing = [
            input_id for input_id in compiled.inputs if input_id not in self._latest_numbers
        ]
        if missing:
            runtime = self._runtimes.setdefault(derived_id, TileRuntime(entry_id=derived_id))
            waiting = ", ".join(
                (self.config.entry_by_id(input_id).display_label() if self.config.entry_by_id(input_id) else "?")
                for input_id in missing
            )
            runtime.tooltip = f"Waiting for: {waiting}\n= {entry.expression}"
            self._update_tile(derived_id)
            return
        try:
            value = compiled.evaluate(self._latest_numbers)
            outcome = ParseOutcome(matched=True, value_text=f"{value:.6g}", value_number=value)
        except ExpressionError as exc:
            outcome = ParseOutcome(matched=True, value_text="", value_number=None, error=str(exc))
        self._apply_outcome(entry, outcome)

    def _sweep_staleness(self) -> None:
        now = self._clock()
        # 1 Hz window slide so the sparkline "ages out" old samples even
        # while polling is paused (FR-46).
        for entry in self.config.entries:
            if entry.is_numeric() and entry.id in self._histories:
                self._refresh_sparkline(entry.id)
        for entry in self.config.entries:
            runtime = self._runtimes.get(entry.id)
            if runtime is None or not entry.enabled:
                continue
            if runtime.state in ("stale", "error") or not runtime.last_success_at:
                continue
            if entry.is_control():
                continue
            if entry.is_derived():
                # A derived value is as fresh as its inputs (FR-61).
                if self._any_input_stale(entry.id):
                    runtime.state = "stale"
                    runtime.state_caption = TILE_STATE_CAPTIONS["stale"]
                    runtime.color = ""
                    self._update_tile(entry.id)
                continue
            if entry.poll_mode == "on_connect":
                # Event-driven values never age (FR-52).
                continue
            if (now - runtime.last_success_at) * 1000 > entry.effective_stale_after_ms():
                runtime.state = "stale"
                runtime.state_caption = TILE_STATE_CAPTIONS["stale"]
                runtime.color = ""
                self._update_tile(entry.id)

    def _any_input_stale(self, derived_id: str) -> bool:
        compiled = self._compiled_exprs.get(derived_id)
        if compiled is None:
            return False
        for input_id in compiled.inputs:
            input_entry = self.config.entry_by_id(input_id)
            if input_entry is None or not input_entry.enabled:
                # A disabled input never updates again — its dependents
                # must not keep looking fresh.
                return True
            input_runtime = self._runtimes.get(input_id)
            if input_runtime is None or input_runtime.state in ("stale", "error"):
                return True
        return False

    def _update_tile(self, entry_id: str) -> None:
        runtime = self._runtimes.get(entry_id)
        tile = self.grid.tile(entry_id)
        if runtime is not None and tile is not None:
            tile.update_runtime(runtime)
        for control_id in self._controls_by_watch.get(entry_id, ()):
            # Toggle visuals follow their watch entry's verdict (FR-59).
            control_tile = self.grid.tile(control_id)
            if isinstance(control_tile, ControlTileWidget):
                control_tile.set_on(bool(runtime is not None and runtime.state == "ok"))

    def _refresh_sparkline(self, entry_id: str) -> None:
        tile = self.grid.tile(entry_id)
        if not isinstance(tile, ValueTileWidget):
            return
        history = self._histories.get(entry_id)
        if history is None or len(history) < 2:
            tile.set_history([], "", now=self._clock())
            return
        runtime = self._runtimes.get(entry_id)
        if runtime is not None and runtime.color:
            color = runtime.color
        elif runtime is not None and runtime.state in ("stale", "error"):
            color = tile_state_color(runtime.state, self._theme)
        else:
            color = tile_state_color(runtime.state if runtime else "ok", self._theme)
        tile.set_history(history.samples(), color, now=self._clock())

    # -------------------------------------------------------- config edits

    def _configure_entries(self, *, save: bool = True) -> None:
        """Recompile parse rules, hand the entry list to the scheduler, and
        refresh the grid + session topology; called after every config
        mutation."""
        self._compiled = {}
        self._has_entry_overrides = any(
            entry.target_endpoint for entry in self.config.entries if not entry.is_derived()
        )
        schedulable: list[DashboardEntry] = []
        for entry in self.config.entries:
            if entry.is_control() or entry.is_derived():
                # Controls send on click (FR-59); derived entries compute
                # from siblings (FR-61) — neither is ever scheduled.
                continue
            try:
                self._compiled[entry.id] = CompiledParseRule.compile(entry.parse)
                schedulable.append(entry)
            except ValueError as exc:
                runtime = self._runtimes.setdefault(entry.id, TileRuntime(entry_id=entry.id))
                runtime.state = "error"
                runtime.state_caption = TILE_STATE_CAPTIONS["error"]
                runtime.tooltip = f"Invalid parse rule: {exc}"
        self._configure_derived_entries()
        self._controls_by_watch = {}
        for entry in self.config.entries:
            if entry.is_control() and entry.control.watch_entry_id:
                self._controls_by_watch.setdefault(
                    entry.control.watch_entry_id, []
                ).append(entry.id)
        for entry_id in list(self._runtimes):
            if self.config.entry_by_id(entry_id) is None:
                del self._runtimes[entry_id]
        for entry_id in list(self._latest_numbers):
            if self.config.entry_by_id(entry_id) is None:
                del self._latest_numbers[entry_id]
        for entry_id in list(self._control_intent):
            if self.config.entry_by_id(entry_id) is None:
                del self._control_intent[entry_id]
        # History clears when the entry goes away OR when it stops being
        # numeric (e.g. converted to a control tile) — re-enabling later
        # should start fresh rather than replay old samples (FR-46).
        for entry_id in list(self._histories):
            entry = self.config.entry_by_id(entry_id)
            if entry is None or not entry.is_numeric():
                del self._histories[entry_id]
        # If the chart was open on an entry that just went away (removed
        # or kind-converted), bail back to the grid (FR-48).
        if self._chart_entry_id:
            chart_entry = self.config.entry_by_id(self._chart_entry_id)
            if chart_entry is None or not chart_entry.is_numeric() or chart_entry.is_control():
                self.close_chart()
        self.scheduler.configure(schedulable)
        self._refresh_session_topology()
        self.grid.set_config(self.config)
        for entry_id in self._runtimes:
            self._update_tile(entry_id)
        self._refresh_empty_state()
        self.refresh_binding_state()
        if save:
            self.config.touch()
            self.host.save_settings()
            self._note_saved()
        self.stateChanged.emit()

    def _configure_derived_entries(self) -> None:
        """Compile derived expressions against sibling labels and build the
        input -> dependents map (FR-61)."""
        self._compiled_exprs = {}
        self._derived_by_input = {}
        derived_entries = [entry for entry in self.config.entries if entry.is_derived()]
        self._has_derived = bool(derived_entries)
        if not derived_entries:
            return
        siblings = [
            entry
            for entry in self.config.entries
            if entry.is_polled() and entry.is_numeric()
        ]
        resolver = build_label_resolver(siblings)
        sources = {entry.id: entry.source for entry in self.config.entries}
        for entry in derived_entries:
            try:
                compiled = compile_expression(entry.expression, resolver, sources=sources)
            except ExpressionError as exc:
                runtime = self._runtimes.setdefault(entry.id, TileRuntime(entry_id=entry.id))
                runtime.state = "error"
                runtime.state_caption = TILE_STATE_CAPTIONS["error"]
                runtime.tooltip = f"{exc}\n= {entry.expression}"
                continue
            self._compiled_exprs[entry.id] = compiled
            for input_id in compiled.inputs:
                self._derived_by_input.setdefault(input_id, []).append(entry.id)
            # Compute immediately when inputs already have values.
            self._recompute_derived(entry.id)

    def add_entry(self, entry: DashboardEntry) -> None:
        entry.tile.col = 0
        entry.tile.row = grid_row_count(self.config.entries)
        self.config.entries.append(entry)
        normalize_layout(self.config.entries, self.config.columns)
        self._configure_entries()

    def apply_entry_edit(self, entry: DashboardEntry) -> None:
        old_label = ""
        for index, existing in enumerate(self.config.entries):
            if existing.id == entry.id:
                old_label = existing.display_label()
                self.config.entries[index] = entry
                break
        else:
            self.config.entries.append(entry)
        # Renaming a referenced entry rewrites sibling expressions so
        # derived tiles keep working (FR-61).
        new_label = entry.display_label()
        if old_label and old_label != new_label:
            for sibling in self.config.entries:
                if sibling.is_derived() and sibling.id != entry.id:
                    sibling.expression = rewrite_references(
                        sibling.expression, old_label, new_label
                    )
        normalize_layout(self.config.entries, self.config.columns)
        self._runtimes.pop(entry.id, None)
        self._latest_numbers.pop(entry.id, None)
        self._histories.pop(entry.id, None)
        self._configure_entries()

    def remove_entry(self, entry_id: str) -> None:
        self.config.entries = [entry for entry in self.config.entries if entry.id != entry_id]
        self._runtimes.pop(entry_id, None)
        self._configure_entries()

    def set_entry_enabled(self, entry_id: str, enabled: bool) -> None:
        entry = self.config.entry_by_id(entry_id)
        if entry is None or entry.enabled == enabled:
            return
        entry.enabled = enabled
        self._configure_entries()

    def rename(self, name: str) -> None:
        self.config.name = name
        self.name_label.setText(name)
        self.config.touch()
        self.host.save_settings()
        self._note_saved()
        self.stateChanged.emit()

    def _layout_changed(self) -> None:
        self.config.touch()
        self.host.save_settings()
        self._note_saved()

    def _edit_mode_toggled(self, checked: bool) -> None:
        self.grid.set_edit_mode(checked)

    # -------------------------------------------------------------- dialogs

    def _entry_dialog_context(self, exclude_id: str = "") -> EntryDialogContext:
        targets = [
            (target.endpoint, target.label, target.connected)
            for target in self.coordinator.bind_targets()
        ]
        # Referencable siblings for derived expressions: polled numeric
        # entries, never the entry being edited (no self-reference, FR-61).
        siblings = [
            entry
            for entry in self.config.entries
            if entry.is_polled() and entry.is_numeric() and entry.id != exclude_id
        ]
        return EntryDialogContext(
            bind_targets=targets,
            expression_resolver=build_label_resolver(siblings),
            expression_sources={entry.id: entry.source for entry in self.config.entries},
            reference_labels=[entry.display_label() for entry in siblings],
            # Anything with a verdict can drive a toggle visual (FR-59).
            watch_candidates=[
                (entry.id, entry.display_label())
                for entry in self.config.entries
                if not entry.is_control() and entry.id != exclude_id
            ],
        )

    def add_entry_via_dialog(self) -> None:
        dialog = DashboardEntryDialog(parent=self, context=self._entry_dialog_context())
        if dialog.exec():
            self.add_entry(dialog.values())
        dialog.deleteLater()

    def edit_entry_via_dialog(self, entry_id: str) -> None:
        entry = self.config.entry_by_id(entry_id)
        if entry is None:
            return
        dialog = DashboardEntryDialog(
            entry, parent=self, context=self._entry_dialog_context(exclude_id=entry_id)
        )
        if dialog.exec():
            self.apply_entry_edit(dialog.values())
        dialog.deleteLater()
