"""MainWindow-level integration tests for the Dashboard View feature.

Covers the end-to-end loops the unit suites cannot: opening/restoring
dashboard tabs inside the real workspace, binding to live terminal tabs
(with their transport replaced by FakeSerialTransport), polling through
the shared dispatcher, persistence round-trips, and resource lifecycle.
"""

from __future__ import annotations

import json
import threading
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from PySide6.QtWidgets import QApplication

from ComPort_Zone import app as app_module
from ComPort_Zone.batch import BatchRunSnapshot
from ComPort_Zone.dashboard_engine import DISPATCHER_THREAD_NAME
from ComPort_Zone.dashboard_models import (
    ColorRule,
    DashboardConfig,
    DashboardEntry,
    DashboardTabState,
    ParseRule,
    TilePlacement,
)
from ComPort_Zone.models import (
    AppSettings,
    SerialProfile,
    TerminalSessionState,
    WorkspaceLayoutState,
    WorkspacePaneState,
    WorkspaceTabState,
)
from ComPort_Zone.settings_service import SettingsService
from ComPort_Zone.storage import SettingsStore
from ComPort_Zone.ui.dashboard_tab import DashboardTabWidget

from tests.fakes.fake_serial_transport import FakeSerialTransport


def cleanup_tmp_settings_artifacts() -> None:
    tests_dir = Path(__file__).parent
    for pattern in (
        "_tmp_settings_dash*.json",
        "_tmp_settings_dash*.json.bak",
        "._tmp_settings_dash*.json.*.tmp",
    ):
        for path in tests_dir.glob(pattern):
            path.unlink(missing_ok=True)


def wait_for(condition: Callable[[], bool], timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def volt_entry(entry_id: str = "volts", command: str = "MEAS:VOLT?") -> DashboardEntry:
    return DashboardEntry(
        id=entry_id,
        label="Volts",
        unit="V",
        command=command,
        interval_ms=1000,
        timeout_ms=500,
        parse=ParseRule(kind="line", value_type="number"),
        rules=[ColorRule(op="gt", operand="13.0", state="warn")],
        tile=TilePlacement(col=0, row=0, kind="value"),
    )


def make_dashboard(name: str = "PSU Bench", entry_id: str = "volts", command: str = "MEAS:VOLT?") -> DashboardConfig:
    return DashboardConfig(name=name, entries=[volt_entry(entry_id, command)])


class DashboardAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        cleanup_tmp_settings_artifacts()
        self.addCleanup(cleanup_tmp_settings_artifacts)
        self.addCleanup(self._assert_no_dispatcher_threads)

    def _assert_no_dispatcher_threads(self) -> None:
        self.qt.processEvents()
        names = [thread.name for thread in threading.enumerate()]
        self.assertNotIn(DISPATCHER_THREAD_NAME, names)

    def launch_window(self, settings: AppSettings, tag: str):
        settings_path = Path(__file__).with_name(f"_tmp_settings_dash_{tag}.json")
        settings_path.unlink(missing_ok=True)
        settings.check_for_updates_on_launch = False
        self.assertTrue(SettingsService(SettingsStore(settings_path)).save(settings))

        old_config_path = app_module.default_config_path
        old_prompt_current = app_module.MainWindow.prompt_current_session_settings
        old_prompt_session = app_module.MainWindow.prompt_session_settings
        old_restore_connection = app_module.MainWindow.restore_session_connection
        app_module.default_config_path = lambda: settings_path
        app_module.MainWindow.prompt_current_session_settings = lambda self: None
        app_module.MainWindow.prompt_session_settings = lambda self, session: None
        app_module.MainWindow.restore_session_connection = lambda self, session: None

        def restore_patches() -> None:
            app_module.default_config_path = old_config_path
            app_module.MainWindow.prompt_current_session_settings = old_prompt_current
            app_module.MainWindow.prompt_session_settings = old_prompt_session
            app_module.MainWindow.restore_session_connection = old_restore_connection

        self.addCleanup(restore_patches)

        window = app_module.MainWindow()
        self.qt.processEvents()

        def teardown_window() -> None:
            for dashboard in window.iter_dashboards():
                dashboard.shutdown()
            window.dashboard_runs.shutdown()
            for session in window.iter_sessions():
                session.shutdown()
            window.deleteLater()
            self.qt.processEvents()

        self.addCleanup(teardown_window)
        return window, settings_path

    @staticmethod
    def fake_out_session(session) -> FakeSerialTransport:
        """Swap a live terminal session's transport for the in-memory fake."""
        fake = FakeSerialTransport()
        fake.connect(object())
        session.transport = fake
        session.serial_client = fake
        return fake

    @staticmethod
    def stop_tick_timer(dashboard: DashboardTabWidget) -> None:
        dashboard.tick_timer.stop()

    # ------------------------------------------------------------- opening

    def test_open_dashboard_tab_creates_then_focuses(self) -> None:
        config = make_dashboard()
        window, _path = self.launch_window(AppSettings(dashboards=[config]), "open")
        dashboard = window.open_dashboard_tab(config.id)
        self.assertIsNotNone(dashboard)
        self.stop_tick_timer(dashboard)
        self.assertEqual(len(window.iter_dashboards()), 1)
        self.assertEqual(window.tabs.tabText(window.tabs.indexOf(dashboard)), "PSU Bench")

        window.tabs.setCurrentIndex(0)
        again = window.open_dashboard_tab(config.id)
        self.assertIs(again, dashboard)
        self.assertEqual(len(window.iter_dashboards()), 1)
        self.assertIs(window.tabs.currentWidget(), dashboard)

    def test_new_dashboard_tab_dedupes_names(self) -> None:
        window, _path = self.launch_window(AppSettings(dashboards=[]), "new")
        window.new_dashboard_tab()
        window.new_dashboard_tab()
        for dashboard in window.iter_dashboards():
            self.stop_tick_timer(dashboard)
        names = sorted(config.name for config in window.settings.dashboards)
        self.assertEqual(names, ["Dashboard", "Dashboard (2)"])
        self.assertEqual(len(window.iter_dashboards()), 2)

    def test_open_unknown_dashboard_reports_status(self) -> None:
        window, _path = self.launch_window(AppSettings(), "unknown")
        self.assertIsNone(window.open_dashboard_tab("ghost"))
        self.assertIn("no longer exists", window.footer.text())

    # ------------------------------------------------------------- polling

    def test_full_poll_loop_updates_tile_and_terminal_traffic(self) -> None:
        config = make_dashboard()
        window, _path = self.launch_window(AppSettings(dashboards=[config]), "poll")
        session = window.iter_sessions()[0]
        fake = self.fake_out_session(session)
        dashboard = window.open_dashboard_tab(config.id)
        self.stop_tick_timer(dashboard)

        self.assertTrue(dashboard.bind_to_session(session.session_id))
        fake.queue_response(b"13.2\r\n")
        dashboard._tick()
        self.assertTrue(wait_for(lambda: not dashboard.result_queue.empty()))
        dashboard._tick()

        tile = dashboard.grid.tile("volts")
        assert tile is not None
        self.assertEqual(tile.value_label.text(), "13.2 V")
        self.assertEqual(tile.property("tileState"), "warn")
        # The poll went through the session's transport — the bound terminal
        # sees the same TX/RX stream (FR-15).
        self.assertEqual(fake.sent_text, [("MEAS:VOLT?", None)])
        self.assertIn("1 alert(s)", dashboard.status_summary())

    def test_disconnect_pauses_and_terminal_close_unbinds(self) -> None:
        config = make_dashboard()
        window, _path = self.launch_window(AppSettings(dashboards=[config]), "pauses")
        session = window.iter_sessions()[0]
        fake = self.fake_out_session(session)
        dashboard = window.open_dashboard_tab(config.id)
        self.stop_tick_timer(dashboard)
        dashboard.bind_to_session(session.session_id)

        fake.disconnect()
        dashboard._tick()
        self.assertEqual(dashboard.bind_chip.text(), "Paused — disconnected")
        self.assertEqual(dashboard.bind_chip.property("state"), "paused")

        index = window.tabs.indexOf(session)
        self.assertTrue(window.close_session(index))
        dashboard._tick()
        self.assertIsNone(dashboard.bound_session_id)
        self.assertIn("unbound", dashboard.scheduler.paused_reasons)
        self.assertEqual(window.dashboard_runs.dispatcher_count(), 0)

    def test_batch_run_suspends_polling(self) -> None:
        config = make_dashboard()
        window, _path = self.launch_window(AppSettings(dashboards=[config]), "batch")
        session = window.iter_sessions()[0]
        fake = self.fake_out_session(session)
        dashboard = window.open_dashboard_tab(config.id)
        self.stop_tick_timer(dashboard)
        dashboard.bind_to_session(session.session_id)

        session.script_snapshot = lambda: BatchRunSnapshot(is_running=True)
        dashboard._tick()
        self.assertEqual(dashboard.bind_chip.text(), "Paused — command file running")
        dashboard._tick()
        self.assertEqual(fake.sent_text, [])  # gated: nothing reaches the wire
        session.script_snapshot = lambda: BatchRunSnapshot(is_running=False)
        dashboard._tick()
        self.assertEqual(dashboard.bind_chip.property("state"), "polling")

    def test_two_dashboards_share_one_dispatcher_with_strict_ordering(self) -> None:
        first_config = make_dashboard("First", "v1", "CMD1")
        second_config = make_dashboard("Second", "v2", "CMD2")
        window, _path = self.launch_window(
            AppSettings(dashboards=[first_config, second_config]), "shared"
        )
        session = window.iter_sessions()[0]
        fake = self.fake_out_session(session)
        first = window.open_dashboard_tab(first_config.id)
        second = window.open_dashboard_tab(second_config.id)
        self.stop_tick_timer(first)
        self.stop_tick_timer(second)
        first.bind_to_session(session.session_id)
        second.bind_to_session(session.session_id)
        self.assertEqual(window.dashboard_runs.dispatcher_count(), 1)

        fake.queue_response(b"1\r\n")
        fake.queue_response(b"2\r\n")
        first._tick()
        second._tick()
        self.assertTrue(wait_for(lambda: not first.result_queue.empty()))
        self.assertTrue(wait_for(lambda: not second.result_queue.empty()))
        self.assertEqual(fake.sent_text, [("CMD1", None), ("CMD2", None)])

        # Closing one dashboard keeps the shared dispatcher alive (FR-17).
        self.assertTrue(window.close_session(window.tabs.indexOf(first)))
        self.assertEqual(window.dashboard_runs.dispatcher_count(), 1)
        self.assertTrue(window.close_session(window.tabs.indexOf(second)))
        self.assertEqual(window.dashboard_runs.dispatcher_count(), 0)

    def test_dashboard_traffic_hidden_from_bound_terminal(self) -> None:
        from ComPort_Zone.serial_core import SerialEvent

        config = make_dashboard()
        window, _path = self.launch_window(AppSettings(dashboards=[config]), "muted")
        session = window.iter_sessions()[0]
        fake = self.fake_out_session(session)
        dashboard = window.open_dashboard_tab(config.id)
        self.stop_tick_timer(dashboard)
        dashboard.bind_to_session(session.session_id)
        journal = session._dashboard_traffic_journal
        self.assertIsNotNone(journal)

        # A dashboard poll TX and its in-window RX never reach the transcript.
        journal.open_window()
        session._handle_event(SerialEvent(kind="tx", message="MEAS:VOLT?", source="dashboard"))
        session._handle_event(SerialEvent(kind="rx", message="13.2\r\n"))
        journal.close_window()
        transcript = session.terminal.toPlainText()
        self.assertNotIn("MEAS:VOLT?", transcript)
        self.assertNotIn("13.2", transcript)

        # User traffic outside a poll window still renders normally.
        from datetime import datetime, timedelta, timezone

        later = datetime.now(timezone.utc).astimezone() + timedelta(seconds=5)
        session._handle_event(SerialEvent(kind="tx", message="*IDN?"))
        session._handle_event(
            SerialEvent(kind="rx", message="ACME,PSU,1.0\r\n", timestamp=later)
        )
        transcript = session.terminal.toPlainText()
        self.assertIn("*IDN?", transcript)
        self.assertIn("ACME,PSU,1.0", transcript)

        # Closing the dashboard detaches the journal from the terminal.
        self.assertTrue(window.close_session(window.tabs.indexOf(dashboard)))
        self.assertIsNone(session._dashboard_traffic_journal)
        del fake

    def test_send_error_renders_error_tile(self) -> None:
        config = make_dashboard()
        window, _path = self.launch_window(AppSettings(dashboards=[config]), "senderr")
        session = window.iter_sessions()[0]
        fake = self.fake_out_session(session)
        dashboard = window.open_dashboard_tab(config.id)
        self.stop_tick_timer(dashboard)
        dashboard.bind_to_session(session.session_id)

        def explode(text: str, line_ending_override=None, *, source: str = "") -> None:
            raise RuntimeError("port vanished")

        fake.send_text = explode  # type: ignore[method-assign]
        dashboard._tick()
        self.assertTrue(wait_for(lambda: not dashboard.result_queue.empty()))
        dashboard._tick()
        tile = dashboard.grid.tile("volts")
        assert tile is not None
        self.assertEqual(tile.property("tileState"), "error")

    # --------------------------------------------------------- persistence

    def test_save_captures_dashboard_tab_in_layout_and_schema(self) -> None:
        config = make_dashboard()
        window, settings_path = self.launch_window(AppSettings(dashboards=[config]), "capture")
        session = window.iter_sessions()[0]
        self.fake_out_session(session)
        dashboard = window.open_dashboard_tab(config.id)
        self.stop_tick_timer(dashboard)
        dashboard.bind_to_session(session.session_id)
        window.save_settings()

        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        # schema_version always stamps the latest the producing build
        # supports (v3 → 7); the floor is the back-compat predicate.
        self.assertEqual(payload["schema_version"], 7)
        # The test dashboard is v1-shaped, so the library declares the v1
        # dashboard floor, not v2/v3.
        self.assertEqual(payload["minimum_compatible_schema_version"], 5)
        self.assertEqual(len(payload["libraries"]["dashboards"]), 1)
        kinds = [
            tab["kind"]
            for pane in payload["workspace"]["layout"]["panes"]
            for tab in pane["tabs"]
        ]
        self.assertIn("dashboard", kinds)
        dashboard_tabs = payload["workspace"]["dashboard_tabs"]
        self.assertEqual(len(dashboard_tabs), 1)
        self.assertEqual(dashboard_tabs[0]["dashboard_id"], config.id)

    def test_restore_recreates_dashboard_tab_and_rebinds_unique_endpoint(self) -> None:
        config = make_dashboard()
        layout = WorkspaceLayoutState(
            panes=[
                WorkspacePaneState(
                    tabs=[
                        WorkspaceTabState(
                            kind="terminal",
                            terminal=TerminalSessionState(
                                title="DUT", serial=SerialProfile(port="COM77")
                            ),
                        ),
                        WorkspaceTabState(
                            kind="dashboard",
                            dashboard=DashboardTabState(
                                dashboard_id=config.id,
                                target_endpoint="COM77",
                                polling_enabled=False,
                            ),
                        ),
                    ],
                    active_tab=1,
                )
            ]
        )
        settings = AppSettings(dashboards=[config], workspace_layout=layout)
        window, _path = self.launch_window(settings, "restore")

        dashboards = window.iter_dashboards()
        self.assertEqual(len(dashboards), 1)
        dashboard = dashboards[0]
        self.stop_tick_timer(dashboard)
        session = window.iter_sessions()[0]
        self.assertEqual(dashboard.bound_session_id, session.session_id)
        # The user pause survived the restart; the disconnected session adds
        # its own pause reason on the next tick.
        self.assertIn("user", dashboard.scheduler.paused_reasons)
        self.assertFalse(dashboard.to_tab_state().polling_enabled)

    def test_restore_skips_dashboard_with_deleted_config(self) -> None:
        layout = WorkspaceLayoutState(
            panes=[
                WorkspacePaneState(
                    tabs=[
                        WorkspaceTabState(
                            kind="terminal",
                            terminal=TerminalSessionState(title="DUT"),
                        ),
                        WorkspaceTabState(
                            kind="dashboard",
                            dashboard=DashboardTabState(dashboard_id="deleted"),
                        ),
                    ]
                )
            ]
        )
        window, _path = self.launch_window(AppSettings(workspace_layout=layout), "skip")
        self.assertEqual(window.iter_dashboards(), [])
        self.assertEqual(len(window.iter_sessions()), 1)

    def test_restore_with_ambiguous_endpoint_stays_unbound(self) -> None:
        config = make_dashboard()
        layout = WorkspaceLayoutState(
            panes=[
                WorkspacePaneState(
                    tabs=[
                        WorkspaceTabState(
                            kind="terminal",
                            terminal=TerminalSessionState(
                                title="A", serial=SerialProfile(port="COM77")
                            ),
                        ),
                        WorkspaceTabState(
                            kind="terminal",
                            terminal=TerminalSessionState(
                                title="B", serial=SerialProfile(port="COM77")
                            ),
                        ),
                        WorkspaceTabState(
                            kind="dashboard",
                            dashboard=DashboardTabState(
                                dashboard_id=config.id, target_endpoint="COM77"
                            ),
                        ),
                    ]
                )
            ]
        )
        window, _path = self.launch_window(
            AppSettings(dashboards=[config], workspace_layout=layout), "ambiguous"
        )
        dashboard = window.iter_dashboards()[0]
        self.stop_tick_timer(dashboard)
        self.assertIsNone(dashboard.bound_session_id)
        self.assertIn("unbound", dashboard.scheduler.paused_reasons)

    def test_apply_imported_settings_stops_dispatchers(self) -> None:
        config = make_dashboard()
        window, _path = self.launch_window(AppSettings(dashboards=[config]), "import")
        session = window.iter_sessions()[0]
        self.fake_out_session(session)
        dashboard = window.open_dashboard_tab(config.id)
        self.stop_tick_timer(dashboard)
        dashboard.bind_to_session(session.session_id)
        self.assertEqual(window.dashboard_runs.dispatcher_count(), 1)

        window.apply_imported_settings(AppSettings(check_for_updates_on_launch=False))
        self.qt.processEvents()
        self.assertEqual(window.dashboard_runs.dispatcher_count(), 0)
        self.assertEqual(window.iter_dashboards(), [])
        names = [thread.name for thread in threading.enumerate()]
        self.assertNotIn(DISPATCHER_THREAD_NAME, names)

    # ------------------------------------------------------------- sidebar

    def test_sidebar_lists_dashboards_and_favorites(self) -> None:
        starred = make_dashboard("Starred")
        starred.favorite = True
        plain = make_dashboard("Plain", "p1", "P?")
        window, _path = self.launch_window(AppSettings(dashboards=[starred, plain]), "sidebar")
        drawer = window.shared_drawer
        names = [drawer.dashboard_list.item(i).text() for i in range(drawer.dashboard_list.count())]
        self.assertEqual(names, ["Plain", "Starred"])
        favorite_names = [
            drawer.favorite_dashboard_list.item(i).text()
            for i in range(drawer.favorite_dashboard_list.count())
        ]
        self.assertEqual(favorite_names, ["Starred"])

    def test_set_dashboard_favorite_updates_lists_and_persists(self) -> None:
        config = make_dashboard()
        window, _path = self.launch_window(AppSettings(dashboards=[config]), "star")
        drawer = window.shared_drawer
        self.assertEqual(drawer.favorite_dashboard_list.count(), 0)
        window.set_dashboard_favorite(config.id, True)
        self.assertEqual(drawer.favorite_dashboard_list.count(), 1)
        self.assertTrue(window.settings.dashboards[0].favorite)
        window.set_dashboard_favorite(config.id, False)
        self.assertEqual(drawer.favorite_dashboard_list.count(), 0)

    def test_delete_dashboard_by_id_closes_tab_and_removes(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        import ComPort_Zone.ui.main_window as main_window_module

        config = make_dashboard()
        window, _path = self.launch_window(AppSettings(dashboards=[config]), "deletebyid")
        dashboard = window.open_dashboard_tab(config.id)
        self.stop_tick_timer(dashboard)
        original_question = QMessageBox.question
        main_window_module.QMessageBox.question = staticmethod(
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes
        )
        try:
            window.delete_dashboard_by_id(config.id)
        finally:
            main_window_module.QMessageBox.question = original_question
        self.assertEqual(window.settings.dashboards, [])
        self.assertEqual(window.iter_dashboards(), [])
        self.assertEqual(window.shared_drawer.dashboard_list.count(), 0)

    def test_new_dashboard_appears_in_sidebar(self) -> None:
        window, _path = self.launch_window(AppSettings(dashboards=[]), "sidebar_new")
        window.new_dashboard_tab()
        for dashboard in window.iter_dashboards():
            self.stop_tick_timer(dashboard)
        self.assertEqual(window.shared_drawer.dashboard_list.count(), 1)

    def test_fresh_install_shows_example_dashboard_in_sidebar_and_favorites(self) -> None:
        window, _path = self.launch_window(AppSettings(), "seeded")
        drawer = window.shared_drawer
        names = [
            drawer.dashboard_list.item(i).text() for i in range(drawer.dashboard_list.count())
        ]
        self.assertEqual(names, ["Example Dashboard"])
        favorite_names = [
            drawer.favorite_dashboard_list.item(i).text()
            for i in range(drawer.favorite_dashboard_list.count())
        ]
        self.assertEqual(favorite_names, ["Example Dashboard"])
        # And it opens like any saved dashboard.
        example_id = window.settings.dashboards[0].id
        dashboard = window.open_dashboard_tab(example_id)
        self.assertIsNotNone(dashboard)
        self.stop_tick_timer(dashboard)
        self.assertEqual(len(dashboard.config.entries), 3)

    # --------------------------------------------------------- performance

    def test_tick_budget_with_64_entries(self) -> None:
        entries = [volt_entry(f"e{index}", f"READ:{index}?") for index in range(64)]
        for index, entry in enumerate(entries):
            entry.tile = TilePlacement(col=index % 4, row=index // 4)
            entry.interval_ms = 3_600_000  # nothing comes due during the benchmark
        config = DashboardConfig(name="Big", entries=entries)
        window, _path = self.launch_window(AppSettings(dashboards=[config]), "budget")
        session = window.iter_sessions()[0]
        self.fake_out_session(session)
        dashboard = window.open_dashboard_tab(config.id)
        self.stop_tick_timer(dashboard)
        dashboard.bind_to_session(session.session_id)
        dashboard._tick()  # absorb first-tick lazy work

        started = perf_counter()
        rounds = 100
        for _ in range(rounds):
            dashboard._tick()
        average_ms = (perf_counter() - started) * 1000 / rounds
        # NFR-1: steady-state tick stays well inside the GUI budget. The CI
        # bound is loose (5 ms) to absorb shared-runner noise.
        self.assertLess(average_ms, 5.0)

    def test_tick_budget_with_v2_features(self) -> None:
        """NFR-12: tick stays under budget when v2 load is layered on top.

        Mirrors the v1 benchmark with a heavier mix:
        - 60 polled numeric entries (each with rules + a custom color)
        - 4 derived entries that depend on a subset of them
        - 1 second session bound via per-entry overrides
        - full sparkline history rings pre-seeded so paint/dedup cost
          is realistic
        - active AlertLog with prior records
        - CSV logging enabled with rows actively appending
        """
        from ComPort_Zone.dashboard_alerts import ALERT_KIND, AlertRecord
        from ComPort_Zone.dashboard_history import HISTORY_MAX_SAMPLES, EntryHistory

        polled_count = 60
        entries: list[DashboardEntry] = []
        for index in range(polled_count):
            entry = volt_entry(f"e{index}", f"READ:{index}?")
            entry.interval_ms = 3_600_000
            entry.tile = TilePlacement(col=index % 4, row=index // 4)
            entry.rules = [
                ColorRule(op="gt", operand="13.0", state="warn", color="#ff9f43"),
                ColorRule(op="between", operand="11", operand2="13", state="ok"),
            ]
            if index % 2 == 0:
                # Alternate halves target a second terminal session, so
                # _refresh_session_topology has real work each tick.
                entry.target_endpoint = "COM99"
            entries.append(entry)

        # Derived entries reference earlier polled siblings by label.
        derived_specs = [
            ("d0", "{Volts} * 2", 60),
            ("d1", "{Volts} + 3", 61),
            ("d2", "max({Volts}, 5)", 62),
            ("d3", "abs({Volts} - 12)", 63),
        ]
        # Make sure the first entry's label is a known reference target.
        entries[0].label = "Volts"
        for derived_id, expression, row_index in derived_specs:
            derived = DashboardEntry(
                id=derived_id,
                label=derived_id.upper(),
                unit="W",
                source="derived",
                expression=expression,
                tile=TilePlacement(col=row_index % 4, row=row_index // 4 + 1),
            )
            entries.append(derived)

        config = DashboardConfig(name="V2 Big", entries=entries)
        # Persisted layout: two terminals (COM7 + COM99) so override
        # bindings have real targets to resolve.
        layout = WorkspaceLayoutState(
            panes=[
                WorkspacePaneState(
                    tabs=[
                        WorkspaceTabState(
                            kind="terminal",
                            terminal=TerminalSessionState(title="A", serial=SerialProfile(port="COM7")),
                        ),
                        WorkspaceTabState(
                            kind="terminal",
                            terminal=TerminalSessionState(title="B", serial=SerialProfile(port="COM99")),
                        ),
                    ]
                )
            ]
        )
        window, _path = self.launch_window(
            AppSettings(dashboards=[config], workspace_layout=layout), "budget_v2"
        )
        sessions = window.iter_sessions()
        for session in sessions:
            self.fake_out_session(session)
        dashboard = window.open_dashboard_tab(config.id)
        self.stop_tick_timer(dashboard)
        dashboard.bind_to_session(sessions[0].session_id)

        # Pre-seed history (sparkline + chart math runs every sweep) and
        # a populated alert log so unseen_count / panel paths have load.
        now = dashboard._clock()
        for entry in entries:
            if not entry.is_numeric():
                continue
            history = EntryHistory()
            for index in range(HISTORY_MAX_SAMPLES):
                history.append(now - HISTORY_MAX_SAMPLES + index, 12.0 + (index % 5) * 0.3)
            dashboard._histories[entry.id] = history
        for index in range(50):
            dashboard.alerts.append(
                AlertRecord(
                    timestamp="14:00:00",
                    entry_id=f"e{index}",
                    entry_label=f"E{index}",
                    old_state="ok",
                    new_state="fail",
                    value_text="14.0",
                    kind=ALERT_KIND,
                )
            )

        # Enable CSV logging so each successful outcome writes a row.
        log_path = Path(__file__).with_name("_tmp_dash_budget_v2.csv")
        log_path.unlink(missing_ok=True)
        # Close the logger BEFORE unlinking — Windows holds the handle.
        self.addCleanup(log_path.unlink, missing_ok=True)
        self.addCleanup(dashboard.value_logger.close)
        dashboard.config.csv_log_path = str(log_path)
        dashboard.csv_log_button.setChecked(True)

        dashboard._tick()  # absorb first-tick lazy work
        started = perf_counter()
        rounds = 100
        for _ in range(rounds):
            dashboard._tick()
        average_ms = (perf_counter() - started) * 1000 / rounds
        # NFR-12: v2 load stays inside the same GUI budget v1 used (5 ms
        # average per tick, with CI noise headroom).
        self.assertLess(average_ms, 5.0)

    def test_restore_with_per_entry_override_endpoint(self) -> None:
        """Persisted v2 override endpoints resolve at restart (FR-54)."""
        bench = volt_entry()
        bench.id = "bench"
        bench.label = "Bench V"
        chamber = volt_entry()
        chamber.id = "chamber"
        chamber.label = "Chamber V"
        chamber.target_endpoint = "COM99"  # override binding
        config = DashboardConfig(name="Multi-device", entries=[bench, chamber])
        layout = WorkspaceLayoutState(
            panes=[
                WorkspacePaneState(
                    tabs=[
                        WorkspaceTabState(
                            kind="terminal",
                            terminal=TerminalSessionState(
                                title="Bench", serial=SerialProfile(port="COM7")
                            ),
                        ),
                        WorkspaceTabState(
                            kind="terminal",
                            terminal=TerminalSessionState(
                                title="Chamber", serial=SerialProfile(port="COM99")
                            ),
                        ),
                        WorkspaceTabState(
                            kind="dashboard",
                            dashboard=DashboardTabState(
                                dashboard_id=config.id,
                                target_endpoint="COM7",
                            ),
                        ),
                    ],
                    active_tab=2,
                )
            ]
        )
        settings = AppSettings(dashboards=[config], workspace_layout=layout)
        window, _path = self.launch_window(settings, "restore_v2_override")

        dashboards = window.iter_dashboards()
        self.assertEqual(len(dashboards), 1)
        dashboard = dashboards[0]
        self.stop_tick_timer(dashboard)
        sessions = window.iter_sessions()
        bench_session = next(s for s in sessions if s.connection_endpoint() == "COM7")
        chamber_session = next(s for s in sessions if s.connection_endpoint() == "COM99")
        self.assertEqual(dashboard.bound_session_id, bench_session.session_id)
        # Both sessions appear in the entry topology: default + override.
        self.assertEqual(
            sorted(dashboard._entry_session.values()),
            sorted([bench_session.session_id, chamber_session.session_id]),
        )
        # Coordinator now holds two dispatcher refcounts (one per target).
        self.assertEqual(window.dashboard_runs.dispatcher_count(), 2)

    def test_v2_export_round_trips_through_settings(self) -> None:
        """A dashboard with derived + control + custom color survives a
        save/reload via the real SettingsService (FR-43 + v2 fields)."""
        from ComPort_Zone.dashboard_models import ControlSpec

        polled = volt_entry()
        polled.id = "volts"
        polled.label = "Volts"
        polled.rules = [
            ColorRule(op="gt", operand="13.0", state="warn", color="#ff9f43"),
        ]
        derived = DashboardEntry(
            id="power",
            label="Power",
            unit="W",
            source="derived",
            expression="{Volts} * 2",
            tile=TilePlacement(col=1, row=0),
        )
        control = DashboardEntry(
            id="output",
            label="Output",
            tile=TilePlacement(col=2, row=0, kind="control"),
            control=ControlSpec(
                mode="toggle",
                on_command="OUTP ON",
                off_command="OUTP OFF",
                confirm=True,
                watch_entry_id="volts",
            ),
        )
        config = DashboardConfig(name="V2 Bench", entries=[polled, derived, control])
        config.csv_log_enabled = False
        config.csv_log_path = "/tmp/never-written.csv"

        settings_path = Path(__file__).with_name("_tmp_settings_dash_v2_roundtrip.json")
        settings_path.unlink(missing_ok=True)
        self.addCleanup(settings_path.unlink, missing_ok=True)
        service = SettingsService(SettingsStore(settings_path))
        original = AppSettings(dashboards=[config])
        self.assertTrue(service.save(original))
        # Sanity: the test config uses v2 features (derived + custom rule
        # color + control toggle), so the floor pegs to v6 even on a v3
        # build. schema_version stamps the latest the build supports.
        with settings_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload.get("minimum_compatible_schema_version"), 6)
        self.assertEqual(payload["schema_version"], 7)

        restored = service.load()
        # Every v2 field round-trips intact.
        configs = {item.name: item for item in restored.dashboards}
        round_tripped = configs["V2 Bench"]
        entries = {entry.id: entry for entry in round_tripped.entries}
        self.assertEqual(entries["volts"].rules[0].color, "#ff9f43")
        self.assertEqual(entries["power"].source, "derived")
        self.assertEqual(entries["power"].expression, "{Volts} * 2")
        self.assertEqual(entries["output"].tile.kind, "control")
        self.assertEqual(entries["output"].control.mode, "toggle")
        self.assertEqual(entries["output"].control.watch_entry_id, "volts")
        self.assertTrue(entries["output"].control.confirm)
        self.assertEqual(round_tripped.csv_log_path, "/tmp/never-written.csv")


if __name__ == "__main__":
    unittest.main()
