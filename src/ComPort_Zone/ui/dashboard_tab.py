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
    QApplication,
    QFileDialog,
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

from ..dashboard_alerts import (
    ALERT_KIND,
    RECOVERY_KIND,
    AlertLog,
    AlertRecord,
    detect_transition,
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
from ..dashboard_value_log import DashboardValueLogger
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
from .alert_sound import AlertSounder, QtAlertSounder
from .dashboard_alert_panel import AlertHistoryPanel
from .dashboard_chart import DEFAULT_SPAN_S, DashboardChartPage
from .dashboard_grid import DashboardGridWidget
from .dashboard_tiles import (
    TILE_STATE_CAPTIONS,
    ControlTileWidget,
    EnumTileWidget,
    SetpointTileWidget,
    TileRuntime,
    ValueTileWidget,
    tile_state_color,
)
from .dialogs.dashboard_entry import DashboardEntryDialog, EntryDialogContext
from .tokens import CONTROL_H_SM, SPACE_LG, SPACE_MD, SPACE_XL


class DashboardHostLike(Protocol):
    """What the tab needs from MainWindow (kept tiny for tests)."""

    theme: ThemePalette
    # Optional alert-related fields. They live on AppSettings; the tab
    # reads them on every potential alert so a Preferences change takes
    # effect without a reload.
    dashboard_alerts_enabled: bool
    dashboard_alert_sound: bool

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
        alert_sounder: AlertSounder | None = None,
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
        # v3 writable tiles (FR-66): watched input id -> dependent
        # writable entry ids (setpoint readback, enum indicator). Built
        # in _configure_entries; consumed in _apply_outcome.
        self._writable_watchers: dict[str, list[str]] = {}
        # v2 sparkline history (FR-46/FR-47): one ring per numeric entry,
        # fed from _apply_outcome — never persisted (NFR-3).
        self._histories: dict[str, EntryHistory] = {}
        self._theme: ThemePalette = host.theme
        # Chart-page id (FR-48): "" while the grid is showing, else the
        # focused entry. The refresh timer fires only while non-empty.
        self._chart_entry_id: str = ""
        # CSV value log (FR-49..FR-51): one logger per tab. Toggle lives
        # on the header; settings persist on DashboardConfig. The logger
        # itself is Qt-free so logic stays tested on plain unittest.
        self.value_logger = DashboardValueLogger()
        # Alert pipeline (FR-57/FR-58): per-tab AlertLog + a debounced
        # sounder. Sounder is injectable so tests stub QtMultimedia out.
        self.alerts = AlertLog()
        self.alert_sounder: AlertSounder = alert_sounder or QtAlertSounder()
        # Per-entry previous state for transition detection.
        self._prev_states: dict[str, str] = {}
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
        # Restore CSV logging from the config (FR-49): if the toggle was
        # on and a path is set, reopen the file silently. A missing dir
        # or unwritable path turns the toggle off + reports — restart
        # never crashes on a vanished USB drive.
        if self.config.csv_log_enabled and self.config.csv_log_path:
            self._resume_csv_logging(self.config.csv_log_path)
        self._refresh_csv_button_state()

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

        self.csv_log_button = QToolButton(header)
        self.csv_log_button.setObjectName("dashboardHeaderButton")
        self.csv_log_button.setCheckable(True)
        self.csv_log_button.setToolTip("Log values to CSV")
        set_button_icon(self.csv_log_button, "save", 15)
        self.csv_log_button.toggled.connect(self._csv_log_toggled)
        self.csv_log_button.setFixedHeight(CONTROL_H_SM)
        self.csv_log_button.setCursor(Qt.CursorShape.PointingHandCursor)

        self.bell_button = QToolButton(header)
        self.bell_button.setObjectName("dashboardHeaderButton")
        set_button_icon(self.bell_button, "bell", 15)
        self.bell_button.setToolTip("Show alerts")
        self.bell_button.setFixedHeight(CONTROL_H_SM)
        # Give the badge room to sit in the corner without overlapping
        # the bell glyph (the icon is centered in this minimum width).
        self.bell_button.setMinimumWidth(34)
        self.bell_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bell_button.clicked.connect(self._toggle_alert_panel)
        self.bell_badge = QLabel("", self.bell_button)
        self.bell_badge.setObjectName("dashboardBellBadge")
        self.bell_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bell_badge.hide()

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
        header_layout.addWidget(self.bell_button)
        header_layout.addWidget(self.pause_button)
        header_layout.addWidget(self.csv_log_button)
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

        # Alert popover (FR-58). Anchored over the stack so it floats
        # above the tile grid / chart and repositions on resize.
        self.alert_panel = AlertHistoryPanel(self.stack, parent=self.stack)
        self.alert_panel.clearRequested.connect(self._clear_alerts)
        self.alert_panel.closeRequested.connect(self._refresh_bell_badge)

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
        # A leading bullet marks unseen alerts so the tab strip itself
        # carries the signal — clicking the bell + reading clears it.
        prefix = "● " if self.alerts.unseen_count else ""
        return f"{prefix}{self.config.name}"

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
        self.value_logger.close()
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

    # --------------------------------------------------------- CSV logging

    def _csv_log_toggled(self, checked: bool) -> None:
        """Header toggle — prompts for a path on first enable, reuses the
        saved path on subsequent toggles. A write/open failure flips the
        toggle back off and reports through the coordinator (FR-50)."""
        if not checked:
            self.value_logger.close()
            self.config.csv_log_enabled = False
            self._refresh_csv_button_state()
            self._save_config()
            return
        path = self.config.csv_log_path
        if not path:
            picked = self._prompt_for_csv_path()
            if not picked:
                # User cancelled — keep the toggle off so state stays
                # consistent with what they see (FR-50).
                self.csv_log_button.blockSignals(True)
                self.csv_log_button.setChecked(False)
                self.csv_log_button.blockSignals(False)
                self._refresh_csv_button_state()
                return
            path = picked
            self.config.csv_log_path = picked
        try:
            self.value_logger.open(path)
        except OSError as exc:
            self._fail_csv_logging(f"Could not open {path}: {exc}")
            return
        self.config.csv_log_enabled = True
        self._refresh_csv_button_state()
        self._save_config()
        self.coordinator.notify(f"Logging dashboard values to {path}.")

    def _prompt_for_csv_path(self) -> str:
        """File picker for the CSV destination. Returns "" on cancel."""
        suggested = (
            self.config.csv_log_path
            or f"{self.config.name.replace(' ', '_') or 'dashboard'}.csv"
        )
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Log dashboard values to CSV",
            suggested,
            "CSV files (*.csv);;All files (*)",
        )
        return path

    def _resume_csv_logging(self, path: str) -> None:
        """Open ``path`` for append at construction; on failure clear the
        config flag so the next save doesn't perpetuate a stale state."""
        try:
            self.value_logger.open(path)
        except OSError as exc:
            self.config.csv_log_enabled = False
            self.coordinator.notify(
                f"Dashboard CSV log paused (could not open {path}): {exc}"
            )

    def _fail_csv_logging(self, message: str) -> None:
        """Disable logging and notify; called on open or write errors."""
        self.value_logger.close()
        self.config.csv_log_enabled = False
        self.csv_log_button.blockSignals(True)
        self.csv_log_button.setChecked(False)
        self.csv_log_button.blockSignals(False)
        self._refresh_csv_button_state()
        self._save_config()
        self.coordinator.notify(message)

    def _refresh_csv_button_state(self) -> None:
        active = self.value_logger.enabled
        if self.csv_log_button.isChecked() != active:
            self.csv_log_button.blockSignals(True)
            self.csv_log_button.setChecked(active)
            self.csv_log_button.blockSignals(False)
        path = self.value_logger.path or self.config.csv_log_path
        if active and path:
            self.csv_log_button.setToolTip(f"Logging values to {path}")
        elif path:
            self.csv_log_button.setToolTip(f"Resume logging to {path}")
        else:
            self.csv_log_button.setToolTip("Log values to CSV")

    def _save_config(self) -> None:
        self.config.touch()
        self.host.save_settings()
        self._note_saved()

    # ---------------------------------------------------------- alerts

    def _check_alert_transition(
        self,
        entry: DashboardEntry,
        prev_state: str,
        new_state: str,
        outcome: ParseOutcome | None,
    ) -> None:
        """Classify the state edge and route the result through the
        alert pipeline (FR-57/FR-58).

        Both alerts AND recoveries land in the bounded history so the
        user can audit what happened; only alerts ring the bell and fire
        attention. Per-entry ``alerts_enabled`` and the master toggle on
        ``AppSettings`` gate every side effect except the history entry
        — silencing should never hide forensics.
        """
        kind = detect_transition(prev_state, new_state)
        if not kind:
            return
        value_text = ""
        if outcome is not None:
            value_text = outcome.value_text or (outcome.error or "")
        record = AlertRecord(
            timestamp=datetime.now().strftime("%H:%M:%S"),
            entry_id=entry.id,
            entry_label=entry.display_label(),
            old_state=prev_state,
            new_state=new_state,
            value_text=value_text,
            kind=kind,
        )
        self.alerts.append(record)
        if kind == ALERT_KIND and self._should_fire_attention(entry):
            self._fire_attention()
        self._refresh_bell_badge()
        if not self.alert_panel.isHidden():
            self.alerts.mark_seen()
            self.alert_panel.set_records(self.alerts.records())
        # The tab title carries the unseen marker; the host swapping the
        # text lives behind stateChanged.
        self.stateChanged.emit()

    def _should_fire_attention(self, entry: DashboardEntry) -> bool:
        if not getattr(self.host, "dashboard_alerts_enabled", True):
            return False
        return entry.alerts_enabled

    def _fire_attention(self) -> None:
        """Side effects of a real alert: taskbar flash + (optional) ding.

        Keep this tiny — every condition is checked at the call site, so
        a stubbed sounder in tests still runs the same code path.
        """
        window = self.window()
        if window is not None:
            app = QApplication.instance()
            if app is not None:
                app.alert(window)
        if getattr(self.host, "dashboard_alert_sound", False):
            self.alert_sounder.play()

    def _refresh_bell_badge(self) -> None:
        count = self.alerts.unseen_count
        if count == 0:
            self.bell_badge.hide()
            self.bell_button.setToolTip("Show alerts")
            return
        self.bell_badge.setText(str(count if count < 100 else "99+"))
        self.bell_badge.adjustSize()
        # Top-right corner of the bell button.
        margin = 2
        bx = self.bell_button.width() - self.bell_badge.width() - margin
        by = margin
        self.bell_badge.move(max(0, bx), by)
        self.bell_badge.raise_()
        self.bell_badge.show()
        plural = "" if count == 1 else "s"
        self.bell_button.setToolTip(f"{count} unseen alert{plural}")

    def _toggle_alert_panel(self) -> None:
        # ``isHidden()`` is the explicit-hide flag (set by hide() / show())
        # — ``isVisible()`` requires the whole ancestor chain to be on
        # screen which isn't true under headless tests.
        if not self.alert_panel.isHidden():
            self.alert_panel.hide()
            self._refresh_bell_badge()
            return
        self.alert_panel.open_with(self.alerts)
        self._refresh_bell_badge()
        self.stateChanged.emit()

    def _clear_alerts(self) -> None:
        self.alerts.clear()
        self.alert_panel.set_records([])
        self._refresh_bell_badge()
        self.stateChanged.emit()

    def _log_outcome(self, entry: DashboardEntry, outcome: ParseOutcome) -> None:
        """Append the outcome to the CSV (FR-49). Only successful parses
        — timeouts never reach this funnel and explicit parse errors are
        skipped here so the log stays a clean record of working polls."""
        if not self.value_logger.enabled:
            return
        if outcome.error or not outcome.matched:
            return
        runtime = self._runtimes.get(entry.id)
        state = runtime.state if runtime is not None else "neutral"
        try:
            self.value_logger.log(
                dashboard=self.config.name,
                entry_id=entry.id,
                label=entry.display_label(),
                value_text=outcome.value_text,
                value_number=outcome.value_number,
                state=state,
            )
        except OSError as exc:
            # Disk pulled, permissions lost — fail loud and turn the
            # toggle off so the user sees what happened (FR-50).
            self._fail_csv_logging(f"CSV log write failed: {exc}")

    # ------------------------------------------------------------- controls

    def _activate_control(self, entry_id: str) -> bool:
        """Click handler for any writing tile (FR-59/60, v3 FR-67):
        gate on session health, optionally confirm, then queue exactly
        one tagged send through the target session's FIFO.

        Routing by tile kind:
        - control button: ``ControlSpec.on_command``
        - control toggle: ``on_command`` or ``off_command`` based on state
        - setpoint: ``SetpointSpec.render_command(tile.value)``
        - enum: ``EnumSpec.options[combo_index].command``  (v3-T4)
        """
        entry = self.config.entry_by_id(entry_id)
        if entry is None or not entry.is_writable() or not entry.enabled:
            return False
        tile = self.grid.tile(entry_id)
        if isinstance(tile, ControlTileWidget) and tile.pending:
            return False
        if isinstance(tile, SetpointTileWidget) and tile.pending:
            return False
        if isinstance(tile, EnumTileWidget) and tile.pending:
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
        intent: bool | None = None
        confirm = False
        if entry.is_control():
            control = entry.control
            turn_on = True
            if control.mode == "toggle":
                turn_on = not self._control_is_on(entry)
            command = control.on_command if turn_on else control.off_command
            confirm = control.confirm
            intent = turn_on
        elif entry.is_setpoint():
            if not isinstance(tile, SetpointTileWidget):
                return False
            command = tile.rendered_command()
            confirm = entry.setpoint.confirm
        elif entry.is_enum():
            if not isinstance(tile, EnumTileWidget):
                return False
            command = tile.selected_command()
            if not command:
                self.coordinator.notify(f"{label}: pick an option first.")
                return False
            confirm = entry.enum_spec.confirm
        else:
            return False
        if confirm and not self._confirm_control(label, command):
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
        if intent is not None:
            self._control_intent[entry_id] = intent
        if isinstance(tile, ControlTileWidget):
            tile.set_pending(True)
        elif isinstance(tile, SetpointTileWidget):
            tile.set_pending(True)
        elif isinstance(tile, EnumTileWidget):
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
        elif isinstance(tile, SetpointTileWidget):
            tile.set_pending(False)
        elif isinstance(tile, EnumTileWidget):
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
        existing_runtime = self._runtimes.get(result.entry_id)
        prev_state = existing_runtime.state if existing_runtime is not None else "neutral"
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
        # Send errors are real alerts (FR-58); timeouts produce "stale"
        # which detect_transition deliberately ignores.
        self._check_alert_transition(entry, prev_state, runtime.state, None)

    def _apply_outcome(self, entry: DashboardEntry, outcome: ParseOutcome, raw_window: str = "") -> None:
        """The shared value sink (poll results AND derived recomputes):
        verdict -> runtime -> tile, then fan out to dependent derived
        entries. History/CSV/alert hooks attach here (v2 funnel)."""
        # Capture prev state BEFORE the runtime is overwritten — alert
        # edge detection needs the transition (FR-57).
        existing_runtime = self._runtimes.get(entry.id)
        prev_state = existing_runtime.state if existing_runtime is not None else "neutral"
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
        # v3: setpoint readback + enum indicator mirror the funneled
        # entry's value into any writing tile that watches it (FR-66/70).
        # Enum indicators match against the raw parsed value (no unit),
        # so the outcome's value_text is what we pass for matching.
        if entry.id in self._writable_watchers:
            self._refresh_writable_readbacks(
                entry.id, runtime, raw_value_text=outcome.value_text
            )
        # CSV logging tails the same funnel so derived rows show up too
        # (FR-49). Errors/timeouts are filtered inside _log_outcome.
        self._log_outcome(entry, outcome)
        # Alert edge detection (FR-57/FR-58). Runs last so the runtime
        # snapshot is current; ``prev_state`` was captured above so the
        # transition reflects this exact result.
        self._check_alert_transition(entry, prev_state, runtime.state, outcome)
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

    def _refresh_writable_readbacks(
        self,
        input_entry_id: str,
        runtime: TileRuntime,
        raw_value_text: str | None = None,
    ) -> None:
        """Push the watched entry's latest verdict into every writing
        tile that watches it: setpoint tiles update their readback line
        (FR-66); enum tiles update their indicated option (FR-70).

        Setpoint readbacks show the formatted ``runtime.value_text``
        (with the polled tile's unit) — that's what ops want to see.
        Enum indicators match against the raw parsed value
        (``raw_value_text``) because option ``match_value`` is the
        wire-level token, not the display label.
        """
        color = runtime.color or tile_state_color(runtime.state, self._theme)
        match_text = raw_value_text if raw_value_text is not None else runtime.value_text
        for watcher_id in self._writable_watchers.get(input_entry_id, ()):
            tile = self.grid.tile(watcher_id)
            if isinstance(tile, SetpointTileWidget):
                tile.set_readback(runtime.value_text, runtime.state, color)
            elif isinstance(tile, EnumTileWidget):
                tile.update_indicator(match_text)

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
        self._writable_watchers = {}
        for entry in self.config.entries:
            if entry.is_control() and entry.control.watch_entry_id:
                self._controls_by_watch.setdefault(
                    entry.control.watch_entry_id, []
                ).append(entry.id)
            # v3 writable tiles can also watch a polled tile (setpoint
            # readback, enum indicator). Collected here so the funnel
            # fan-out is a single dict lookup (FR-66, FR-70).
            if entry.is_setpoint() and entry.setpoint.watch_entry_id:
                self._writable_watchers.setdefault(
                    entry.setpoint.watch_entry_id, []
                ).append(entry.id)
            elif entry.is_enum() and entry.enum_spec.watch_entry_id:
                self._writable_watchers.setdefault(
                    entry.enum_spec.watch_entry_id, []
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
