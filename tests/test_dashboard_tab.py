"""Tests for the dashboard tab widget (tick loop, binding, pause reasons)
and the entry editor dialog."""

from __future__ import annotations

import threading
import time
import unittest
from collections.abc import Callable

from PySide6.QtWidgets import QApplication

from ComPort_Zone.dashboard_engine import DISPATCHER_THREAD_NAME
from ComPort_Zone.dashboard_models import (
    ColorRule,
    DashboardConfig,
    DashboardEntry,
    DashboardTabState,
    ParseRule,
    TilePlacement,
)
from ComPort_Zone.themes import THEMES
from ComPort_Zone.ui.dashboard_tab import DashboardTabWidget
from ComPort_Zone.ui.dashboard_targets import DashboardRunCoordinator
from ComPort_Zone.ui.dialogs.dashboard_entry import DashboardEntryDialog

from tests.fakes.fake_terminal_session import FakeTerminalSession


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance_ms(self, milliseconds: float) -> None:
        self.now += milliseconds / 1000


class FakeHost:
    def __init__(self) -> None:
        self.theme = THEMES["ComPort Zone Dark"]
        self.save_count = 0

    def save_settings(self) -> None:
        self.save_count += 1


def wait_for(condition: Callable[[], bool], timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def volt_entry() -> DashboardEntry:
    return DashboardEntry(
        id="volts",
        label="Volts",
        unit="V",
        command="MEAS:VOLT?",
        interval_ms=1000,
        timeout_ms=500,
        parse=ParseRule(kind="line", value_type="number"),
        rules=[ColorRule(op="gt", operand="13.0", state="warn")],
        tile=TilePlacement(col=0, row=0, kind="value"),
    )


def trip_entry() -> DashboardEntry:
    return DashboardEntry(
        id="trip",
        label="Trip",
        command="TRIP?",
        interval_ms=1000,
        timeout_ms=500,
        parse=ParseRule(kind="line", value_type="number"),
        rules=[ColorRule(op="eq_num", operand="1", state="fail", label="TRIPPED")],
        tile=TilePlacement(col=1, row=0, kind="led"),
    )


class DashboardTabTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.host = FakeHost()
        self.clock = FakeClock()
        self.session = FakeTerminalSession(1, endpoint="COM7")
        self.sessions = [self.session]
        self.open_widgets: set[object] | None = None
        self.tabs: list[DashboardTabWidget] = []
        self.coordinator = DashboardRunCoordinator(
            sessions_supplier=lambda: self.sessions,
            dashboards_supplier=lambda: self.tabs,
            is_widget_open=self._is_open,
            set_status=lambda _text: None,
            target_icon_color=lambda: "#abcdef"[:0] or "white",
        )

    def tearDown(self) -> None:
        for tab in self.tabs:
            tab.shutdown()
            tab.deleteLater()
        self.coordinator.shutdown()
        names = [thread.name for thread in threading.enumerate()]
        self.assertNotIn(DISPATCHER_THREAD_NAME, names)

    def _is_open(self, widget: object) -> bool:
        if self.open_widgets is None:
            return True
        return widget in self.open_widgets

    def make_tab(
        self,
        *entries: DashboardEntry,
        tab_state: DashboardTabState | None = None,
    ) -> DashboardTabWidget:
        config = DashboardConfig(name="Bench", entries=list(entries))
        tab = DashboardTabWidget(
            self.host,
            config,
            tab_state,
            coordinator=self.coordinator,
            clock=self.clock,
            start_timer=False,
        )
        self.tabs.append(tab)
        return tab

    def run_poll_round(self, tab: DashboardTabWidget, *responses: bytes) -> None:
        """Queue device responses, tick to submit, wait for results, tick to
        drain them into tiles."""
        expected = len(responses)
        before = len(self.session.transport.sent_text) + len(self.session.transport.sent_bytes)
        for response in responses:
            self.session.transport.queue_response(response)
        tab._tick()
        self.assertTrue(
            wait_for(lambda: tab.result_queue.qsize() >= expected),
            msg="poll results did not arrive",
        )
        tab._tick()
        del before


class DashboardTabPollingTests(DashboardTabTestBase):
    def test_full_poll_round_updates_tiles(self) -> None:
        tab = self.make_tab(volt_entry(), trip_entry())
        self.assertTrue(tab.bind_to_session(1))
        self.clock.advance_ms(50)  # past the 25 ms submit stagger
        self.run_poll_round(tab, b"13.2\r\n", b"1\r\n")

        value_tile = tab.grid.tile("volts")
        led_tile = tab.grid.tile("trip")
        assert value_tile is not None and led_tile is not None
        self.assertEqual(value_tile.value_label.text(), "13.2 V")
        self.assertEqual(value_tile.property("tileState"), "warn")
        self.assertEqual(led_tile.caption_label.text(), "TRIPPED")
        self.assertEqual(led_tile.property("tileState"), "fail")
        self.assertEqual(
            self.session.transport.sent_text,
            [("MEAS:VOLT?", None), ("TRIP?", None)],
        )

    def test_chip_shows_polling_state(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.assertEqual(tab.bind_chip.text(), "Polling COM7")
        self.assertEqual(tab.bind_chip.property("state"), "polling")

    def test_disconnect_pauses_and_blocks_sends(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"12.0\r\n")
        sends_before = len(self.session.transport.sent_text)

        self.session.transport.disconnect()
        tab._tick()
        self.assertEqual(tab.scheduler.paused_reasons, frozenset({"connection"}))
        self.assertEqual(tab.bind_chip.text(), "Paused — disconnected")
        self.assertEqual(tab.bind_chip.property("state"), "paused")

        self.clock.advance_ms(10_000)
        tab._tick()
        tab._tick()
        self.assertEqual(len(self.session.transport.sent_text), sends_before)

    def test_reconnect_resumes_polling(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.session.transport.disconnect()
        tab._tick()
        self.assertIn("connection", tab.scheduler.paused_reasons)

        self.session.transport.connect(object())
        self.clock.advance_ms(5000)
        self.run_poll_round(tab, b"12.5\r\n")
        self.assertEqual(tab.scheduler.paused_reasons, frozenset())
        value_tile = tab.grid.tile("volts")
        assert value_tile is not None
        self.assertEqual(value_tile.value_label.text(), "12.5 V")

    def test_batch_run_suspends_polling(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.session.batch_running = True
        tab._tick()
        self.assertIn("batch", tab.scheduler.paused_reasons)
        self.assertEqual(tab.bind_chip.text(), "Paused — command file running")
        self.session.batch_running = False
        tab._tick()
        self.assertEqual(tab.scheduler.paused_reasons, frozenset())

    def test_user_pause_persists_into_tab_state(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        tab.set_polling_enabled(False)
        self.assertIn("user", tab.scheduler.paused_reasons)
        self.assertFalse(tab.to_tab_state().polling_enabled)
        self.assertGreater(self.host.save_count, 0)
        tab.set_polling_enabled(True)
        self.assertTrue(tab.to_tab_state().polling_enabled)

    def test_restored_user_pause_applies_on_construction(self) -> None:
        state = DashboardTabState(dashboard_id="ignored", polling_enabled=False)
        tab = self.make_tab(volt_entry(), tab_state=state)
        self.assertIn("user", tab.scheduler.paused_reasons)
        self.assertTrue(tab.pause_button.isChecked())
        self.assertEqual(tab.pause_button.toolTip(), "Resume polling")

    def test_pause_button_reflects_state(self) -> None:
        tab = self.make_tab(volt_entry())
        self.assertEqual(tab.pause_button.toolTip(), "Pause polling")
        tab.pause_button.setChecked(True)  # user clicks pause
        self.assertEqual(tab.pause_button.toolTip(), "Resume polling")
        self.assertIn("user", tab.scheduler.paused_reasons)
        tab.pause_button.setChecked(False)  # user clicks play
        self.assertEqual(tab.pause_button.toolTip(), "Pause polling")
        self.assertNotIn("user", tab.scheduler.paused_reasons)

    def test_saved_indicator_updates_on_persisted_changes(self) -> None:
        tab = self.make_tab(volt_entry())
        self.assertEqual(tab.save_state_label.text(), "")
        tab.rename("Rack 9")
        self.assertTrue(tab.save_state_label.text().startswith("Saved "))
        tab.save_state_label.setText("")
        tab.add_entry(trip_entry())
        self.assertTrue(tab.save_state_label.text().startswith("Saved "))

    def test_timeout_marks_tile_stale_keeps_last_value(self) -> None:
        entry = volt_entry()
        entry.timeout_ms = 60
        tab = self.make_tab(entry)
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"12.0\r\n")
        value_tile = tab.grid.tile("volts")
        assert value_tile is not None
        self.assertEqual(value_tile.value_label.text(), "12 V")

        # Next poll gets no response -> timeout -> stale marker, value kept.
        self.clock.advance_ms(entry.interval_ms + 100)
        tab._tick()
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty(), timeout=1.0))
        tab._tick()
        self.assertEqual(value_tile.property("tileState"), "stale")
        self.assertEqual(value_tile.value_label.text(), "12 V")
        self.assertIn("No response", value_tile.toolTip())

    def test_staleness_sweep_degrades_quiet_tiles(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"12.0\r\n")
        value_tile = tab.grid.tile("volts")
        assert value_tile is not None
        self.assertEqual(value_tile.property("tileState"), "neutral")

        tab.set_polling_enabled(False)  # stop new polls; data now just ages
        self.clock.advance_ms(volt_entry().effective_stale_after_ms() + 1000)
        for _ in range(10):
            tab._tick()
        self.assertEqual(value_tile.property("tileState"), "stale")

    def test_send_error_marks_error_state(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)

        def explode(text: str, line_ending_override=None, *, source: str = "") -> None:
            raise RuntimeError("port vanished")

        self.session.transport.send_text = explode  # type: ignore[method-assign]
        self.clock.advance_ms(50)
        tab._tick()
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty()))
        tab._tick()
        value_tile = tab.grid.tile("volts")
        assert value_tile is not None
        self.assertEqual(value_tile.property("tileState"), "error")
        self.assertIn("port vanished", value_tile.toolTip())


class DashboardTabBindingTests(DashboardTabTestBase):
    def test_unbound_by_default(self) -> None:
        tab = self.make_tab(volt_entry())
        self.assertIn("unbound", tab.scheduler.paused_reasons)
        self.assertEqual(tab.bind_chip.text(), "Unbound")
        self.assertEqual(tab.bind_chip.property("state"), "unbound")

    def test_closing_target_unbinds_and_releases(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.assertEqual(self.coordinator.dispatcher_count(), 1)
        self.open_widgets = set()  # the terminal tab is gone
        tab._tick()
        self.assertIsNone(tab.bound_session_id)
        self.assertIn("unbound", tab.scheduler.paused_reasons)
        self.assertEqual(self.coordinator.dispatcher_count(), 0)
        self.assertEqual(tab.bind_chip.text(), "Unbound")

    def test_transport_swap_rebinds(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        old_transport = self.session.transport
        from tests.fakes.fake_serial_transport import FakeSerialTransport

        self.session.transport = FakeSerialTransport()
        self.session.transport.connect(object())
        self.session.serial_client = self.session.transport
        tab._tick()
        self.assertEqual(tab.bound_session_id, 1)
        self.assertEqual(old_transport._subscribers, [])
        self.assertEqual(len(self.session.transport._subscribers), 1)

    def test_resolve_persisted_binding_unique_endpoint(self) -> None:
        state = DashboardTabState(dashboard_id="x", target_endpoint="COM7")
        tab = self.make_tab(volt_entry(), tab_state=state)
        tab.resolve_persisted_binding()
        self.assertEqual(tab.bound_session_id, 1)

    def test_resolve_persisted_binding_ambiguous_stays_unbound(self) -> None:
        self.sessions.append(FakeTerminalSession(2, endpoint="COM7"))
        state = DashboardTabState(dashboard_id="x", target_endpoint="COM7")
        tab = self.make_tab(volt_entry(), tab_state=state)
        tab.resolve_persisted_binding()
        self.assertIsNone(tab.bound_session_id)

    def test_two_tabs_share_one_dispatcher(self) -> None:
        first = self.make_tab(volt_entry())
        second = self.make_tab(trip_entry())
        first.bind_to_session(1)
        second.bind_to_session(1)
        self.assertEqual(self.coordinator.dispatcher_count(), 1)
        first.shutdown()
        self.assertEqual(self.coordinator.dispatcher_count(), 1)
        second.shutdown()
        self.assertEqual(self.coordinator.dispatcher_count(), 0)


class DashboardTabConfigTests(DashboardTabTestBase):
    def test_add_entry_places_below_and_saves(self) -> None:
        tab = self.make_tab(volt_entry())
        saves = self.host.save_count
        new_entry = trip_entry()
        tab.add_entry(new_entry)
        self.assertEqual((new_entry.tile.col, new_entry.tile.row), (0, 1))
        self.assertIsNotNone(tab.grid.tile("trip"))
        self.assertGreater(self.host.save_count, saves)

    def test_apply_entry_edit_replaces(self) -> None:
        tab = self.make_tab(volt_entry())
        edited = volt_entry()
        edited.label = "Rail A"
        edited.interval_ms = 250
        tab.apply_entry_edit(edited)
        entry = tab.config.entry_by_id("volts")
        assert entry is not None
        self.assertEqual(entry.label, "Rail A")
        tile = tab.grid.tile("volts")
        assert tile is not None
        self.assertEqual(tile.title_label.text(), "Rail A")

    def test_remove_entry_drops_tile_and_runtime(self) -> None:
        tab = self.make_tab(volt_entry(), trip_entry())
        tab.remove_entry("trip")
        self.assertIsNone(tab.grid.tile("trip"))
        self.assertIsNone(tab.config.entry_by_id("trip"))

    def test_disable_entry_skips_polling(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        tab.set_entry_enabled("volts", False)
        self.clock.advance_ms(10_000)
        tab._tick()
        self.assertEqual(self.session.transport.sent_text, [])

    def test_invalid_parse_rule_renders_error_not_scheduled(self) -> None:
        bad = volt_entry()
        bad.parse = ParseRule(kind="regex", pattern="(unclosed")
        tab = self.make_tab(bad)
        tab.bind_to_session(1)
        self.clock.advance_ms(10_000)
        tab._tick()
        self.assertEqual(self.session.transport.sent_text, [])
        tile = tab.grid.tile("volts")
        assert tile is not None
        self.assertEqual(tile.property("tileState"), "error")
        self.assertIn("Invalid parse rule", tile.toolTip())

    def test_empty_state_page_switches(self) -> None:
        tab = self.make_tab()
        self.assertEqual(tab.stack.currentIndex(), 0)
        tab.add_entry(volt_entry())
        self.assertEqual(tab.stack.currentIndex(), 1)

    def test_rename_updates_title_and_summary(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.rename("Rack 3")
        self.assertEqual(tab.tab_title(), "Rack 3")
        self.assertIn("Rack 3", tab.status_summary())

    def test_status_summary_counts_alerts(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"14.0\r\n")  # > 13 -> warn
        self.assertIn("1 alert(s)", tab.status_summary())


class DashboardEntryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_values_round_trip(self) -> None:
        entry = volt_entry()
        dialog = DashboardEntryDialog(entry)
        result = dialog.values()
        self.assertEqual(result.id, entry.id)
        self.assertEqual(result.command, "MEAS:VOLT?")
        self.assertEqual(result.unit, "V")
        self.assertEqual(result.interval_ms, 1000)
        self.assertEqual(result.parse.kind, "line")
        self.assertEqual(result.parse.value_type, "number")
        self.assertEqual(len(result.rules), 1)
        self.assertEqual(result.rules[0].op, "gt")
        dialog.deleteLater()

    def test_ok_gated_on_validation(self) -> None:
        dialog = DashboardEntryDialog()
        dialog.command_input.setText("")
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 0)
        self.assertTrue(dialog.error_label.isVisible() or dialog.error_label.text())
        self.assertIn("Command must not be empty", dialog.error_label.text())
        dialog.deleteLater()

    def test_bad_regex_blocks_accept(self) -> None:
        dialog = DashboardEntryDialog()
        dialog.command_input.setText("X?")
        index = dialog.parse_kind_combo.findData("regex")
        dialog.parse_kind_combo.setCurrentIndex(index)
        dialog.pattern_input.setText("(unclosed")
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 0)
        self.assertIn("Invalid regex", dialog.error_label.text())
        dialog.deleteLater()

    def test_live_tester_shows_value_and_state(self) -> None:
        entry = volt_entry()
        dialog = DashboardEntryDialog(entry)
        dialog.sample_input.setPlainText("13.5\r\n")
        self.assertIn("13.5 V", dialog.tester_result.text())
        self.assertIn("WARN", dialog.tester_result.text())
        dialog.deleteLater()

    def test_live_tester_reports_waiting(self) -> None:
        dialog = DashboardEntryDialog(volt_entry())
        dialog.sample_input.setPlainText("13.5")  # no line terminator
        self.assertIn("keep waiting", dialog.tester_result.text())
        dialog.deleteLater()

    def test_live_tester_reports_rule_error(self) -> None:
        dialog = DashboardEntryDialog()
        index = dialog.parse_kind_combo.findData("regex")
        dialog.parse_kind_combo.setCurrentIndex(index)
        dialog.pattern_input.setText("(bad")
        dialog.sample_input.setPlainText("anything")
        self.assertIn("Rule error", dialog.tester_result.text())
        dialog.deleteLater()

    def test_hex_mode_validation(self) -> None:
        dialog = DashboardEntryDialog()
        dialog.command_input.setText("ABC")
        dialog.mode_combo.setCurrentText("Hex Bytes")
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 0)
        self.assertIn("even", dialog.error_label.text())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
