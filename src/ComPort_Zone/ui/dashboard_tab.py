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
    DashboardPollScheduler,
    PollRequest,
    PollResult,
    SessionPollDispatcher,
)
from ..dashboard_models import (
    DashboardConfig,
    DashboardEntry,
    DashboardTabState,
    grid_row_count,
    normalize_layout,
)
from ..dashboard_parse import CompiledParseRule, evaluate_rules, format_tile_value
from ..icons import set_button_icon
from ..themes import ThemePalette
from .dashboard_grid import DashboardGridWidget
from .dashboard_tiles import TILE_STATE_CAPTIONS, TileRuntime
from .dialogs.dashboard_entry import DashboardEntryDialog
from .tokens import CONTROL_H_SM, SPACE_LG, SPACE_MD, SPACE_XL


class DashboardHostLike(Protocol):
    """What the tab needs from MainWindow (kept tiny for tests)."""

    theme: ThemePalette

    def save_settings(self) -> None:
        ...


class DashboardCoordinatorLike(Protocol):
    def session_by_id(self, session_id: int): ...
    def resolve_endpoint(self, endpoint: str): ...
    def session_health(self, session_id: int): ...
    def acquire_dispatcher(self, session) -> SessionPollDispatcher: ...
    def release_dispatcher(self, session_id: int) -> None: ...
    def populate_bind_menu(self, menu: QMenu, on_bind: Callable[[int], None]) -> None: ...


STALENESS_SWEEP_EVERY_TICKS = 10


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
        self._dispatcher: SessionPollDispatcher | None = None
        self._bound_session_id: int | None = None
        self._compiled: dict[str, CompiledParseRule] = {}
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

        self.stack = QStackedWidget(self)
        self.stack.addWidget(empty_page)
        self.stack.addWidget(self.scroll_area)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(header)
        root.addWidget(self.stack, 1)
        self._refresh_empty_state()

    def _refresh_empty_state(self) -> None:
        self.stack.setCurrentIndex(1 if self.config.entries else 0)

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
        return f"{self.config.name} · {entries_text} · {self._binding_text()}{alert_text}"

    def to_tab_state(self) -> DashboardTabState:
        return DashboardTabState(
            dashboard_id=self.config.id,
            target_endpoint=self._tab_state.target_endpoint,
            target_title=self._tab_state.target_title,
            polling_enabled="user" not in self.scheduler.paused_reasons,
        )

    def shutdown(self) -> None:
        """Stop the tick and release the dispatcher (tab close, app close,
        settings re-apply). Safe to call twice (NFR-4)."""
        self.tick_timer.stop()
        if self._dispatcher is not None:
            self._dispatcher.cancel_dashboard(self.config.id)
        if self._bound_session_id is not None:
            self.coordinator.release_dispatcher(self._bound_session_id)
        self._dispatcher = None
        self._bound_session_id = None

    def apply_theme_palette(self, theme: ThemePalette) -> None:
        self.grid.apply_theme_palette(theme)

    # ------------------------------------------------------------- binding

    @property
    def bound_session_id(self) -> int | None:
        return self._bound_session_id

    def bind_to_session(self, session_id: int) -> bool:
        session = self.coordinator.session_by_id(session_id)
        if session is None:
            return False
        if self._bound_session_id is not None:
            old_dispatcher = self._dispatcher
            if old_dispatcher is not None:
                old_dispatcher.cancel_dashboard(self.config.id)
            self.coordinator.release_dispatcher(self._bound_session_id)
        self._dispatcher = self.coordinator.acquire_dispatcher(session)
        self._bound_session_id = session_id
        self.scheduler.release_all_in_flight()
        self.scheduler.set_paused("unbound", False)
        self._tab_state.target_endpoint = session.connection_endpoint()
        self._tab_state.target_title = session.tab_title
        self.refresh_binding_state()
        self.stateChanged.emit()
        self.host.save_settings()
        self._note_saved()
        return True

    def unbind(self, notice: str = "") -> None:
        if self._bound_session_id is not None:
            if self._dispatcher is not None:
                self._dispatcher.cancel_dashboard(self.config.id)
            self.coordinator.release_dispatcher(self._bound_session_id)
        self._dispatcher = None
        self._bound_session_id = None
        self.scheduler.set_paused("unbound", True)
        self.scheduler.release_all_in_flight()
        if notice:
            self.bind_chip.setToolTip(notice)
        self.refresh_binding_state()
        self.stateChanged.emit()

    def resolve_persisted_binding(self) -> None:
        """Rebind after restore using the endpoint hint — only on a unique
        match (FR-38); otherwise stay unbound with the bind menu ready."""
        endpoint = self._tab_state.target_endpoint
        if not endpoint or self._bound_session_id is not None:
            return
        session = self.coordinator.resolve_endpoint(endpoint)
        if session is not None:
            self.bind_to_session(session.session_id)

    def _populate_bind_menu(self) -> None:
        self.coordinator.populate_bind_menu(self._bind_menu, self.bind_to_session)

    def _binding_text(self) -> str:
        if self._bound_session_id is None:
            return "unbound"
        reasons = self.scheduler.paused_reasons
        if "user" in reasons:
            return "paused"
        if "connection" in reasons:
            return "paused — disconnected"
        if "batch" in reasons:
            return "paused — command file running"
        return f"polling {self._tab_state.target_endpoint or self._tab_state.target_title}"

    def refresh_binding_state(self) -> None:
        """Re-render the binding chip (cheap; called on connection events
        and from the tick when pause reasons change)."""
        if self._bound_session_id is None:
            state, text = "unbound", "Unbound"
            tooltip = "Bind this dashboard to a terminal tab to start polling."
        else:
            reasons = self.scheduler.paused_reasons
            target = self._tab_state.target_endpoint or self._tab_state.target_title
            if not reasons:
                state, text = "polling", f"Polling {target}"
                tooltip = f"Bound to {self._tab_state.target_title} ({target})"
            else:
                state = "paused"
                if "user" in reasons:
                    text, tooltip = "Paused", "Polling paused by you."
                elif "connection" in reasons:
                    text = "Paused — disconnected"
                    tooltip = f"{target} is disconnected; polling resumes on reconnect."
                elif "batch" in reasons:
                    text = "Paused — command file running"
                    tooltip = "A command file is running on the bound terminal."
                else:
                    text, tooltip = "Paused", ""
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
        if self._bound_session_id is None:
            return
        health = self.coordinator.session_health(self._bound_session_id)
        if not health.open:
            self.unbind(notice="The bound terminal tab was closed.")
            return
        if health.transport_changed:
            # Session swapped transports (connection-settings change):
            # re-acquire so the dispatcher subscribes to the live one.
            self.bind_to_session(self._bound_session_id)
            return
        reasons = self.scheduler.paused_reasons
        connection_paused = "connection" in reasons
        if health.connected == connection_paused:
            self.scheduler.set_paused("connection", not health.connected)
            self.refresh_binding_state()
            self.stateChanged.emit()
        batch_paused = "batch" in reasons
        if health.batch_running != batch_paused:
            self.scheduler.set_paused("batch", health.batch_running)
            self.refresh_binding_state()

    def _submit_due(self) -> None:
        dispatcher = self._dispatcher
        if dispatcher is None:
            return
        for entry in self.scheduler.collect_due():
            compiled = self._compiled.get(entry.id)
            if compiled is None:
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

    def _handle_result(self, result: PollResult) -> None:
        if result.status == POLL_CANCELLED:
            self.scheduler.skip(result.entry_id)
            return
        self.scheduler.complete(result.entry_id)
        entry = self.config.entry_by_id(result.entry_id)
        if entry is None:
            return
        runtime = self._runtimes.setdefault(result.entry_id, TileRuntime(entry_id=result.entry_id))
        runtime.last_result_at = self._clock()
        runtime.timestamp_text = datetime.now().strftime("%H:%M:%S")
        if result.status == POLL_OK and result.outcome is not None:
            outcome = result.outcome
            runtime.last_success_at = self._clock()
            runtime.consecutive_timeouts = 0
            runtime.value_text = format_tile_value(outcome, entry.unit)
            verdict = evaluate_rules(entry.rules, outcome)
            runtime.state = verdict.state
            runtime.state_caption = verdict.label or TILE_STATE_CAPTIONS.get(verdict.state, "")
            if outcome.error:
                runtime.tooltip = f"{outcome.error}\nRX window: {result.raw_window[-500:]}"
            else:
                runtime.tooltip = f"RX window: {result.raw_window[-500:]}"
        elif result.status == POLL_TIMEOUT:
            runtime.consecutive_timeouts += 1
            runtime.state = "stale"
            runtime.state_caption = TILE_STATE_CAPTIONS["stale"]
            runtime.tooltip = (
                f"No response within {entry.timeout_ms} ms "
                f"({runtime.consecutive_timeouts} timeout(s) in a row).\n"
                f"RX window: {result.raw_window[-500:]}"
            )
        elif result.status == POLL_SEND_ERROR:
            runtime.state = "error"
            runtime.state_caption = TILE_STATE_CAPTIONS["error"]
            runtime.tooltip = f"Send failed: {result.error}"
        self._update_tile(result.entry_id)

    def _sweep_staleness(self) -> None:
        now = self._clock()
        for entry in self.config.entries:
            runtime = self._runtimes.get(entry.id)
            if runtime is None or not entry.enabled:
                continue
            if runtime.state in ("stale", "error") or not runtime.last_success_at:
                continue
            if (now - runtime.last_success_at) * 1000 > entry.effective_stale_after_ms():
                runtime.state = "stale"
                runtime.state_caption = TILE_STATE_CAPTIONS["stale"]
                self._update_tile(entry.id)

    def _update_tile(self, entry_id: str) -> None:
        runtime = self._runtimes.get(entry_id)
        tile = self.grid.tile(entry_id)
        if runtime is not None and tile is not None:
            tile.update_runtime(runtime)

    # -------------------------------------------------------- config edits

    def _configure_entries(self, *, save: bool = True) -> None:
        """Recompile parse rules, hand the entry list to the scheduler, and
        refresh the grid; called after every config mutation."""
        self._compiled = {}
        schedulable: list[DashboardEntry] = []
        for entry in self.config.entries:
            try:
                self._compiled[entry.id] = CompiledParseRule.compile(entry.parse)
                schedulable.append(entry)
            except ValueError as exc:
                runtime = self._runtimes.setdefault(entry.id, TileRuntime(entry_id=entry.id))
                runtime.state = "error"
                runtime.state_caption = TILE_STATE_CAPTIONS["error"]
                runtime.tooltip = f"Invalid parse rule: {exc}"
        for entry_id in list(self._runtimes):
            if self.config.entry_by_id(entry_id) is None:
                del self._runtimes[entry_id]
        self.scheduler.configure(schedulable)
        self.grid.set_config(self.config)
        for entry_id in self._runtimes:
            self._update_tile(entry_id)
        self._refresh_empty_state()
        if save:
            self.config.touch()
            self.host.save_settings()
            self._note_saved()
        self.stateChanged.emit()

    def add_entry(self, entry: DashboardEntry) -> None:
        entry.tile.col = 0
        entry.tile.row = grid_row_count(self.config.entries)
        self.config.entries.append(entry)
        normalize_layout(self.config.entries, self.config.columns)
        self._configure_entries()

    def apply_entry_edit(self, entry: DashboardEntry) -> None:
        for index, existing in enumerate(self.config.entries):
            if existing.id == entry.id:
                self.config.entries[index] = entry
                break
        else:
            self.config.entries.append(entry)
        normalize_layout(self.config.entries, self.config.columns)
        self._runtimes.pop(entry.id, None)
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

    def add_entry_via_dialog(self) -> None:
        dialog = DashboardEntryDialog(parent=self)
        if dialog.exec():
            self.add_entry(dialog.values())
        dialog.deleteLater()

    def edit_entry_via_dialog(self, entry_id: str) -> None:
        entry = self.config.entry_by_id(entry_id)
        if entry is None:
            return
        dialog = DashboardEntryDialog(entry, parent=self)
        if dialog.exec():
            self.apply_entry_edit(dialog.values())
        dialog.deleteLater()
