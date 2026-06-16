"""Tests for the control_panel tab widget (tick loop, binding, pause reasons)
and the entry editor dialog."""

from __future__ import annotations

import threading
import time
import unittest
from collections.abc import Callable
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from ComPort_Zone.control_panel_alerts import ALERT_KIND, RECOVERY_KIND
from ComPort_Zone.control_panel_engine import DISPATCHER_THREAD_NAME
from ComPort_Zone.control_panel_models import (
    ColorRule,
    ControlSpec,
    ControlPanelConfig,
    ControlPanelEntry,
    ControlPanelTabState,
    ParseRule,
    ReadbackSpec,
    TilePlacement,
)
from ComPort_Zone.themes import THEMES
from ComPort_Zone.ui.control_panel_tab import ControlPanelTabWidget
from ComPort_Zone.ui.control_panel_targets import ControlPanelRunCoordinator
from ComPort_Zone.ui.control_panel_tiles import ControlTileWidget, ValueTileWidget
from ComPort_Zone.ui.dialogs.control_panel_entry import ControlPanelEntryDialog

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
        # T13: AppSettings exposes these to the tab via the host Protocol.
        self.control_panel_alerts_enabled = True
        self.control_panel_alert_sound = False

    def save_settings(self) -> None:
        self.save_count += 1


class StubAlertSounder:
    """Test sounder — counts plays so suite never opens QtMultimedia."""

    def __init__(self) -> None:
        self.play_count = 0

    def play(self) -> None:
        self.play_count += 1


def wait_for(condition: Callable[[], bool], timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def volt_entry() -> ControlPanelEntry:
    return ControlPanelEntry(
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


def trip_entry() -> ControlPanelEntry:
    return ControlPanelEntry(
        id="trip",
        label="Trip",
        command="TRIP?",
        interval_ms=1000,
        timeout_ms=500,
        parse=ParseRule(kind="line", value_type="number"),
        rules=[ColorRule(op="eq_num", operand="1", state="fail", label="TRIPPED")],
        tile=TilePlacement(col=1, row=0, kind="led"),
    )


class ControlPanelTabTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.host = FakeHost()
        self.clock = FakeClock()
        self.session = FakeTerminalSession(1, endpoint="COM7")
        self.sessions = [self.session]
        self.open_widgets: set[object] | None = None
        self.tabs: list[ControlPanelTabWidget] = []
        self.coordinator = ControlPanelRunCoordinator(
            sessions_supplier=lambda: self.sessions,
            control_panels_supplier=lambda: self.tabs,
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
        *entries: ControlPanelEntry,
        tab_state: ControlPanelTabState | None = None,
    ) -> ControlPanelTabWidget:
        config = ControlPanelConfig(name="Bench", entries=list(entries))
        tab = ControlPanelTabWidget(
            self.host,
            config,
            tab_state,
            coordinator=self.coordinator,
            clock=self.clock,
            start_timer=False,
            alert_sounder=StubAlertSounder(),
        )
        self.tabs.append(tab)
        return tab

    def run_poll_round(self, tab: ControlPanelTabWidget, *responses: bytes) -> None:
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


class ControlPanelTabPollingTests(ControlPanelTabTestBase):
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
        # v2: disconnect gates the session's entries at submit time
        # (FR-55) — no sends happen, the chip reads paused, the entries
        # simply stay due (no scheduler-level "connection" reason).
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"12.0\r\n")
        sends_before = len(self.session.transport.sent_text)

        self.session.transport.disconnect()
        tab._tick()
        self.assertEqual(tab.bind_chip.text(), "Paused — disconnected")
        self.assertEqual(tab.bind_chip.property("state"), "paused")
        self.assertNotIn("connection", tab.scheduler.paused_reasons)

        self.clock.advance_ms(10_000)
        tab._tick()
        tab._tick()
        self.assertEqual(len(self.session.transport.sent_text), sends_before)

    def test_reconnect_resumes_polling(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.session.transport.disconnect()
        tab._tick()
        self.assertEqual(tab.bind_chip.property("state"), "paused")

        self.session.transport.connect(object())
        self.clock.advance_ms(5000)
        self.run_poll_round(tab, b"12.5\r\n")
        self.assertEqual(tab.bind_chip.property("state"), "polling")
        value_tile = tab.grid.tile("volts")
        assert value_tile is not None
        self.assertEqual(value_tile.value_label.text(), "12.5 V")

    def test_batch_run_suspends_polling(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.session.batch_running = True
        tab._tick()
        self.assertEqual(tab.bind_chip.text(), "Paused — command file running")
        self.clock.advance_ms(10_000)
        tab._tick()
        self.assertEqual(self.session.transport.sent_text, [])

        self.session.batch_running = False
        self.run_poll_round(tab, b"12.0\r\n")
        self.assertEqual(tab.bind_chip.property("state"), "polling")
        self.assertEqual(len(self.session.transport.sent_text), 1)

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
        state = ControlPanelTabState(control_panel_id="ignored", polling_enabled=False)
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

    def test_history_collected_for_numeric_polls(self) -> None:
        # The sparkline pipeline starts at _apply_outcome (FR-46): every
        # successful numeric poll appends a (clock, value) sample.
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.assertNotIn("volts", tab._histories)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"12.0\r\n")
        self.assertEqual(len(tab._histories["volts"]), 1)
        self.clock.advance_ms(1100)
        self.run_poll_round(tab, b"12.5\r\n")
        self.assertEqual(len(tab._histories["volts"]), 2)
        # Tile actually paints something now.
        tile = tab.grid.tile("volts")
        from ComPort_Zone.ui.control_panel_tiles import ValueTileWidget

        assert isinstance(tile, ValueTileWidget)
        self.assertTrue(tile.sparkline.has_data())

    def test_history_ignores_text_and_errors(self) -> None:
        # Text entries and parse errors must not pollute the ring (the
        # sparkline domain is "numeric trend").
        from ComPort_Zone.control_panel_models import ParseRule

        text_entry = volt_entry()
        text_entry.id = "mode"
        text_entry.parse = ParseRule(kind="line", value_type="text")
        bad_entry = volt_entry()
        bad_entry.id = "bad"
        tab = self.make_tab(text_entry, bad_entry)
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        # Text outcome and a non-number "ERR" both reach _apply_outcome
        # but should NOT land in the history rings.
        self.run_poll_round(tab, b"CV\r\n", b"ERR\r\n")
        self.assertNotIn("mode", tab._histories)
        self.assertNotIn("bad", tab._histories)

    def test_history_collected_for_derived_entries(self) -> None:
        # Derived tiles route their computed value through _apply_outcome
        # too, so the sparkline pipeline applies (FR-47).
        tab = self.make_tab(volt_entry(), amps_entry(), power_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(80)
        self.run_poll_round(tab, b"12.0\r\n", b"2.0\r\n")
        self.assertEqual(len(tab._histories["power"]), 1)
        latest = tab._histories["power"].latest()
        assert latest is not None
        self.assertEqual(latest[1], 24.0)

    def test_history_cleared_when_entry_removed(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"12.0\r\n")
        self.assertIn("volts", tab._histories)
        tab.remove_entry("volts")
        self.assertNotIn("volts", tab._histories)

    def test_history_cleared_when_entry_becomes_non_numeric(self) -> None:
        # Editing parse to text drops the ring; the next text poll must
        # not append (was a tempting one-line miss).
        from ComPort_Zone.control_panel_models import ParseRule

        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"12.0\r\n")
        self.assertIn("volts", tab._histories)
        edited = volt_entry()
        edited.parse = ParseRule(kind="line", value_type="text")
        tab.apply_entry_edit(edited)
        self.assertNotIn("volts", tab._histories)

    def test_window_slide_runs_on_staleness_sweep(self) -> None:
        # A long quiet period should still slide the sparkline window so
        # samples eventually age out; this also exercises the sweep path
        # against entries that have histories but no tile-runtime yet.
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"12.0\r\n")
        self.clock.advance_ms(2_000)  # > sweep cadence
        # Trigger the sweep tick (every 10th _tick at 100 ms).
        for _ in range(10):
            tab._tick()
        # The history itself doesn't get pruned — only the visible window
        # slides — but the call path must not raise and the sparkline's
        # paint must still cope.
        self.assertGreaterEqual(len(tab._histories["volts"]), 1)

    def test_open_chart_switches_to_chart_page_and_starts_timer(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.assertEqual(tab.stack.currentIndex(), tab.GRID_PAGE)
        self.assertFalse(tab.chart_refresh_timer.isActive())

        self.assertTrue(tab.open_chart("volts"))
        self.assertEqual(tab.stack.currentIndex(), tab.CHART_PAGE)
        self.assertEqual(tab.chart_entry_id, "volts")
        self.assertTrue(tab.chart_refresh_timer.isActive())

        tab.close_chart()
        self.assertEqual(tab.stack.currentIndex(), tab.GRID_PAGE)
        self.assertEqual(tab.chart_entry_id, "")
        self.assertFalse(tab.chart_refresh_timer.isActive())

    def test_open_chart_refuses_non_numeric_and_control(self) -> None:
        from ComPort_Zone.control_panel_models import ParseRule

        text_entry = volt_entry()
        text_entry.id = "mode"
        text_entry.parse = ParseRule(kind="line", value_type="text")
        tab = self.make_tab(text_entry, control_entry())
        tab.bind_to_session(1)
        self.assertFalse(tab.open_chart("mode"))
        self.assertFalse(tab.open_chart("ctrl"))
        self.assertFalse(tab.open_chart("nope"))
        self.assertEqual(tab.stack.currentIndex(), tab.GRID_PAGE)

    def test_chart_receives_history_on_refresh(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"12.0\r\n")
        self.clock.advance_ms(1100)
        self.run_poll_round(tab, b"12.5\r\n")
        self.assertTrue(tab.open_chart("volts"))
        # Chart view should now hold those two samples.
        visible = tab.chart_page.chart_view.visible_samples()
        self.assertEqual(len(visible), 2)
        self.assertEqual([round(v, 2) for _t, v in visible], [12.0, 12.5])

    def test_chart_closes_when_entry_removed(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        tab.open_chart("volts")
        self.assertEqual(tab.stack.currentIndex(), tab.CHART_PAGE)
        tab.remove_entry("volts")
        self.assertEqual(tab.chart_entry_id, "")
        self.assertNotEqual(tab.stack.currentIndex(), tab.CHART_PAGE)

    def test_chart_uses_runtime_color_when_set(self) -> None:
        entry = volt_entry()
        entry.rules = [
            ColorRule(op="gt", operand="13.0", state="warn", color="#12ab34")
        ]
        tab = self.make_tab(entry)
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"14.0\r\n")
        tab.open_chart("volts")
        # Triggers _refresh_chart on the next timer fire; call it directly.
        tab._refresh_chart()
        self.assertEqual(tab.chart_page.chart_view._color, "#12ab34")

    def test_config_edit_does_not_clobber_chart_page(self) -> None:
        # _refresh_empty_state used to unconditionally pick between empty
        # and grid; that would yank the user off the chart on any edit.
        tab = self.make_tab(volt_entry(), trip_entry())
        tab.bind_to_session(1)
        tab.open_chart("volts")
        tab.set_entry_enabled("trip", False)
        self.assertEqual(tab.stack.currentIndex(), tab.CHART_PAGE)
        self.assertEqual(tab.chart_entry_id, "volts")

    def test_shutdown_stops_chart_timer(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        tab.open_chart("volts")
        self.assertTrue(tab.chart_refresh_timer.isActive())
        tab.shutdown()
        self.assertFalse(tab.chart_refresh_timer.isActive())
        # tearDown will call shutdown again — must stay safe.

    def test_alert_on_fail_transition_fires_sound_and_badge(self) -> None:
        entry = volt_entry()
        entry.rules = [ColorRule(op="gt", operand="13.0", state="fail", label="OVP")]
        self.host.control_panel_alert_sound = True
        tab = self.make_tab(entry)
        tab.bind_to_session(1)
        self.assertEqual(tab.alerts.unseen_count, 0)
        self.assertTrue(tab.bell_badge.isHidden())

        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"14.0\r\n")  # neutral -> fail edge fires.
        self.assertEqual(tab.alerts.unseen_count, 1)
        self.assertFalse(tab.bell_badge.isHidden())
        self.assertEqual(tab.bell_badge.text(), "1")
        self.assertEqual(tab.alert_sounder.play_count, 1)

        # Recovery: fail -> neutral is logged but does NOT bump unseen.
        self.clock.advance_ms(1100)
        self.run_poll_round(tab, b"12.0\r\n")
        records = tab.alerts.records()
        self.assertEqual(records[0].kind, RECOVERY_KIND)
        self.assertEqual(tab.alerts.unseen_count, 1)
        # Recoveries never play the sound.
        self.assertEqual(tab.alert_sounder.play_count, 1)

    def test_alerts_disabled_silences_sound_and_taskbar(self) -> None:
        entry = volt_entry()
        entry.rules = [ColorRule(op="gt", operand="13.0", state="fail")]
        self.host.control_panel_alerts_enabled = False
        self.host.control_panel_alert_sound = True  # but the master is off
        tab = self.make_tab(entry)
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"14.0\r\n")
        # History is still recorded — silencing must not hide forensics.
        self.assertEqual(len(tab.alerts), 1)
        # But sound never fires.
        self.assertEqual(tab.alert_sounder.play_count, 0)

    def test_per_entry_alerts_disabled_silences_just_that_one(self) -> None:
        quiet = volt_entry()
        quiet.rules = [ColorRule(op="gt", operand="13.0", state="fail")]
        quiet.alerts_enabled = False
        tab = self.make_tab(quiet)
        tab.bind_to_session(1)
        self.host.control_panel_alert_sound = True
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"14.0\r\n")
        # Record still lands so the user can audit, but no sound.
        self.assertEqual(len(tab.alerts), 1)
        self.assertEqual(tab.alert_sounder.play_count, 0)

    def test_send_error_alerts_once_timeout_does_not(self) -> None:
        # FR-58: a stuck device should not machine-gun. The first send
        # error alerts; the next poll's timeout produces "stale" which
        # detect_transition deliberately ignores.
        entry = volt_entry()
        entry.timeout_ms = 60
        tab = self.make_tab(entry)
        tab.bind_to_session(1)

        def explode(text: str, line_ending_override=None, *, source: str = "") -> None:
            raise RuntimeError("port vanished")

        self.session.transport.send_text = explode  # type: ignore[method-assign]
        self.clock.advance_ms(50)
        tab._tick()
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty()))
        tab._tick()
        self.assertEqual(tab.alerts.unseen_count, 1)

        # Restore send (so the next poll tries), but stage no response —
        # the entry will time out; that must NOT add a second alert.
        self.session.transport.send_text = (
            lambda text, line_ending_override=None, *, source="": None
        )  # type: ignore[method-assign]
        self.clock.advance_ms(entry.interval_ms + 100)
        tab._tick()
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty()))
        tab._tick()
        self.assertEqual(tab.alerts.unseen_count, 1)

    def test_repeat_fail_does_not_refire(self) -> None:
        entry = volt_entry()
        entry.rules = [ColorRule(op="gt", operand="13.0", state="fail")]
        tab = self.make_tab(entry)
        tab.bind_to_session(1)
        self.host.control_panel_alert_sound = True
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"14.0\r\n")
        self.clock.advance_ms(1100)
        self.run_poll_round(tab, b"15.0\r\n")  # still fail
        self.assertEqual(tab.alerts.unseen_count, 1)
        self.assertEqual(tab.alert_sounder.play_count, 1)

    def test_bell_button_opens_panel_and_marks_seen(self) -> None:
        entry = volt_entry()
        entry.rules = [ColorRule(op="gt", operand="13.0", state="fail")]
        tab = self.make_tab(entry)
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"14.0\r\n")
        self.assertEqual(tab.alerts.unseen_count, 1)
        self.assertEqual(tab.tab_title(), "● Bench")
        tab.bell_button.click()
        self.assertFalse(tab.alert_panel.isHidden())
        self.assertEqual(tab.alerts.unseen_count, 0)
        self.assertEqual(tab.tab_title(), "Bench")
        # Clicking again hides the panel.
        tab.bell_button.click()
        self.assertTrue(tab.alert_panel.isHidden())

    def test_clear_button_drops_history(self) -> None:
        entry = volt_entry()
        entry.rules = [ColorRule(op="gt", operand="13.0", state="fail")]
        tab = self.make_tab(entry)
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"14.0\r\n")
        tab.bell_button.click()
        tab.alert_panel.clear_button.click()
        self.assertEqual(len(tab.alerts), 0)
        self.assertTrue(tab.bell_badge.isHidden())

    def test_csv_log_records_polled_values_only(self) -> None:
        import csv
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="dash-csv-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        log_path = tmp / "values.csv"
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        # Programmatically toggle on with a preset path so the QFileDialog
        # never opens during tests.
        tab.config.csv_log_path = str(log_path)
        tab.csv_log_button.setChecked(True)
        self.assertTrue(tab.value_logger.enabled)

        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"12.0\r\n")

        with log_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry_id"], "volts")
        self.assertEqual(rows[0]["value_number"], "12")
        self.assertEqual(rows[0]["state"], "neutral")
        # v3: poll rows carry kind="poll".
        self.assertEqual(rows[0]["kind"], "poll")

    def test_csv_log_skips_timeouts_and_parse_errors(self) -> None:
        import csv
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="dash-csv-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        log_path = tmp / "values.csv"
        # Tight timeout so we can force a timeout result; the parse rule
        # is numeric so a non-numeric response will produce an error.
        entry = volt_entry()
        entry.timeout_ms = 60
        tab = self.make_tab(entry)
        tab.bind_to_session(1)
        tab.config.csv_log_path = str(log_path)
        tab.csv_log_button.setChecked(True)

        # Timeout: no response staged, advance past the timeout.
        self.clock.advance_ms(50)
        tab._tick()
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty(), timeout=1.0))
        tab._tick()

        # Parse error: numeric expected, text arrives.
        self.clock.advance_ms(entry.interval_ms + 100)
        self.run_poll_round(tab, b"NOPE\r\n")

        with log_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        # Neither the timeout nor the parse error should appear.
        self.assertEqual(rows, [])

    def test_csv_log_records_derived_outcomes(self) -> None:
        import csv
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="dash-csv-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        log_path = tmp / "values.csv"
        tab = self.make_tab(volt_entry(), amps_entry(), power_entry())
        tab.bind_to_session(1)
        tab.config.csv_log_path = str(log_path)
        tab.csv_log_button.setChecked(True)

        self.clock.advance_ms(80)
        self.run_poll_round(tab, b"12.0\r\n", b"2.0\r\n")
        with log_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        ids = [row["entry_id"] for row in rows]
        self.assertEqual(sorted(ids), ["amps", "power", "volts"])
        power_row = next(row for row in rows if row["entry_id"] == "power")
        self.assertEqual(power_row["value_number"], "24")

    def test_csv_log_toggle_persists_in_config(self) -> None:
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="dash-csv-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        log_path = tmp / "values.csv"
        tab = self.make_tab(volt_entry())
        tab.config.csv_log_path = str(log_path)
        tab.csv_log_button.setChecked(True)
        self.assertTrue(tab.config.csv_log_enabled)
        self.assertEqual(tab.config.csv_log_path, str(log_path))
        tab.csv_log_button.setChecked(False)
        self.assertFalse(tab.config.csv_log_enabled)
        # Path stays so re-enabling later picks up where it left off.
        self.assertEqual(tab.config.csv_log_path, str(log_path))

    def test_csv_log_open_failure_clears_toggle(self) -> None:
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="dash-csv-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        # Point the path at a directory; open() will raise OSError when
        # it tries to open the directory for write.
        bad_path = tmp / "dir.csv"
        bad_path.mkdir()
        status: list[str] = []
        self.coordinator._set_status = status.append
        tab = self.make_tab(volt_entry())
        tab.config.csv_log_path = str(bad_path)
        tab.csv_log_button.setChecked(True)
        self.assertFalse(tab.value_logger.enabled)
        self.assertFalse(tab.csv_log_button.isChecked())
        self.assertFalse(tab.config.csv_log_enabled)
        self.assertTrue(any("Could not open" in text for text in status))

    def test_csv_log_resumes_on_construction(self) -> None:
        import csv
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="dash-csv-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        log_path = tmp / "values.csv"
        # Pre-seed a tab so the file has a header + one row.
        first = self.make_tab(volt_entry())
        first.bind_to_session(1)
        first.config.csv_log_path = str(log_path)
        first.csv_log_button.setChecked(True)
        self.clock.advance_ms(50)
        self.run_poll_round(first, b"12.0\r\n")
        first.shutdown()
        # Build a fresh tab whose config already has logging enabled and
        # the path set — construction should reopen, NOT rewrite header.
        from ComPort_Zone.control_panel_models import (
            ControlPanelConfig,
            ControlPanelTabState,
        )
        from ComPort_Zone.ui.control_panel_tab import ControlPanelTabWidget

        config = ControlPanelConfig(
            name="Bench",
            entries=[volt_entry()],
            csv_log_enabled=True,
            csv_log_path=str(log_path),
        )
        second = ControlPanelTabWidget(
            self.host,
            config,
            ControlPanelTabState(control_panel_id=config.id),
            coordinator=self.coordinator,
            clock=self.clock,
            start_timer=False,
        )
        self.tabs.append(second)
        self.assertTrue(second.value_logger.enabled)
        second.bind_to_session(1)
        self.clock.advance_ms(2000)
        self.run_poll_round(second, b"12.5\r\n")
        with log_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        # Both polls landed, header appears only once (DictReader sees 2).
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["value_number"] for row in rows], ["12", "12.5"])

    def test_custom_rule_color_applies_and_clears_on_staleness(self) -> None:
        entry = volt_entry()
        entry.rules = [ColorRule(op="gt", operand="13.0", state="warn", color="#12ab34")]
        tab = self.make_tab(entry)
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"14.0\r\n")  # matches the colored rule
        value_tile = tab.grid.tile("volts")
        assert value_tile is not None
        self.assertIn("#12ab34", value_tile.value_label.styleSheet())

        # Aging to stale drops the custom color with the verdict (FR-62).
        tab.set_polling_enabled(False)
        self.clock.advance_ms(entry.effective_stale_after_ms() + 1000)
        for _ in range(10):
            tab._tick()
        self.assertEqual(value_tile.property("tileState"), "stale")
        self.assertEqual(value_tile.value_label.styleSheet(), "")


class MultiSessionBindingTests(ControlPanelTabTestBase):
    """v2 per-entry session binding (FR-54..FR-56) and poll modes."""

    def add_session(self, session_id: int, endpoint: str) -> FakeTerminalSession:
        session = FakeTerminalSession(session_id, endpoint=endpoint)
        self.sessions.append(session)
        return session

    @staticmethod
    def override_entry(endpoint: str) -> "ControlPanelEntry":
        entry = trip_entry()
        entry.target_endpoint = endpoint
        return entry

    def test_override_entry_polls_its_own_session(self) -> None:
        second = self.add_session(2, "COM9")
        tab = self.make_tab(volt_entry(), self.override_entry("COM9"))
        tab.bind_to_session(1)
        self.assertEqual(self.coordinator.dispatcher_count(), 2)

        self.clock.advance_ms(50)
        self.session.transport.queue_response(b"12.0\r\n")
        second.transport.queue_response(b"0\r\n")
        tab._tick()
        self.assertTrue(wait_for(lambda: tab.result_queue.qsize() >= 2))
        tab._tick()

        self.assertEqual(self.session.transport.sent_text, [("MEAS:VOLT?", None)])
        self.assertEqual(second.transport.sent_text, [("TRIP?", None)])

    def test_one_sessions_disconnect_gates_only_its_entries(self) -> None:
        second = self.add_session(2, "COM9")
        tab = self.make_tab(volt_entry(), self.override_entry("COM9"))
        tab.bind_to_session(1)
        second.transport.disconnect()
        self.clock.advance_ms(50)

        self.session.transport.queue_response(b"12.0\r\n")
        tab._tick()
        self.assertTrue(wait_for(lambda: tab.result_queue.qsize() >= 1))
        tab._tick()

        self.assertEqual(len(self.session.transport.sent_text), 1)
        self.assertEqual(second.transport.sent_text, [])
        self.assertIn("Polling COM7", tab.bind_chip.text())
        self.assertIn("COM9 — disconnected", tab.bind_chip.toolTip())

    def test_batch_on_one_session_gates_only_it(self) -> None:
        second = self.add_session(2, "COM9")
        tab = self.make_tab(volt_entry(), self.override_entry("COM9"))
        tab.bind_to_session(1)
        second.batch_running = True
        self.clock.advance_ms(50)

        self.session.transport.queue_response(b"12.0\r\n")
        tab._tick()
        self.assertTrue(wait_for(lambda: tab.result_queue.qsize() >= 1))
        tab._tick()

        self.assertEqual(len(self.session.transport.sent_text), 1)
        self.assertEqual(second.transport.sent_text, [])
        self.assertIn("COM9 — command file running", tab.bind_chip.toolTip())

    def test_unresolved_override_never_submits(self) -> None:
        tab = self.make_tab(volt_entry(), self.override_entry("COM99"))
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.session.transport.queue_response(b"12.0\r\n")
        tab._tick()
        self.assertTrue(wait_for(lambda: tab.result_queue.qsize() >= 1))
        tab._tick()
        self.assertEqual(len(self.session.transport.sent_text), 1)
        self.assertIn("COM99 — no matching terminal tab", tab.bind_chip.toolTip())
        self.assertEqual(self.coordinator.dispatcher_count(), 1)

    def test_dispatcher_released_when_override_edited_away(self) -> None:
        self.add_session(2, "COM9")
        tab = self.make_tab(volt_entry(), self.override_entry("COM9"))
        tab.bind_to_session(1)
        self.assertEqual(self.coordinator.dispatcher_count(), 2)

        edited = self.override_entry("")
        tab.apply_entry_edit(edited)
        self.assertEqual(self.coordinator.dispatcher_count(), 1)

    def test_shutdown_releases_all_sessions(self) -> None:
        self.add_session(2, "COM9")
        tab = self.make_tab(volt_entry(), self.override_entry("COM9"))
        tab.bind_to_session(1)
        self.assertEqual(self.coordinator.dispatcher_count(), 2)
        tab.shutdown()
        self.assertEqual(self.coordinator.dispatcher_count(), 0)

    def test_on_connect_fires_once_per_connect_edge(self) -> None:
        entry = volt_entry()
        entry.poll_mode = "on_connect"
        tab = self.make_tab(entry)
        self.session.transport.queue_response(b"12.0\r\n")
        tab.bind_to_session(1)  # bind-when-connected counts as an edge
        tab._tick()
        self.assertTrue(wait_for(lambda: tab.result_queue.qsize() >= 1))
        tab._tick()
        self.assertEqual(len(self.session.transport.sent_text), 1)

        # No periodic follow-up, ever.
        self.clock.advance_ms(3_600_000)
        tab._tick()
        tab._tick()
        self.assertEqual(len(self.session.transport.sent_text), 1)

        # Reconnect fires it exactly once more.
        self.session.transport.disconnect()
        tab._tick()
        self.session.transport.connect(object())
        self.session.transport.queue_response(b"12.5\r\n")
        tab._tick()
        self.assertTrue(wait_for(lambda: tab.result_queue.qsize() >= 1))
        tab._tick()
        self.assertEqual(len(self.session.transport.sent_text), 2)

    def test_poll_now_fires_interval_entry_immediately(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"12.0\r\n")
        # Not due again (interval 1000 ms)...
        tab._tick()
        self.assertEqual(len(self.session.transport.sent_text), 1)
        # ...but Poll Now arms an immediate one-shot (FR-53).
        self.assertTrue(tab.poll_now("volts"))
        self.run_poll_round(tab, b"12.1\r\n")
        self.assertEqual(len(self.session.transport.sent_text), 2)

    def test_poll_now_rejects_unknown_and_unpollable(self) -> None:
        tab = self.make_tab(volt_entry())
        tab.bind_to_session(1)
        self.assertFalse(tab.poll_now("ghost"))


def amps_entry(interval_ms: int = 1000) -> ControlPanelEntry:
    return ControlPanelEntry(
        id="amps",
        label="Amps",
        unit="A",
        command="MEAS:CURR?",
        interval_ms=interval_ms,
        timeout_ms=500,
        parse=ParseRule(kind="line", value_type="number"),
        tile=TilePlacement(col=1, row=0, kind="value"),
    )


def power_entry(expression: str = "{Volts} * {Amps}") -> ControlPanelEntry:
    return ControlPanelEntry(
        id="power",
        label="Power",
        unit="W",
        source="derived",
        expression=expression,
        tile=TilePlacement(col=2, row=0, kind="value"),
    )


class DerivedTileTests(ControlPanelTabTestBase):
    """Derived/math tiles computed from sibling poll results (FR-61)."""

    def test_derived_updates_on_either_input(self) -> None:
        tab = self.make_tab(volt_entry(), amps_entry(interval_ms=2000), power_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(80)
        self.run_poll_round(tab, b"12.0\r\n", b"2.0\r\n")
        power_tile = tab.grid.tile("power")
        assert power_tile is not None
        self.assertEqual(power_tile.value_label.text(), "24 W")
        self.assertEqual(power_tile.toolTip(), "= {Volts} * {Amps}")

        # Only Volts is due next round; Power recomputes with the cached
        # Amps value — either input refreshes the derived tile.
        self.clock.advance_ms(1000)
        self.run_poll_round(tab, b"10.0\r\n")
        self.assertEqual(power_tile.value_label.text(), "20 W")

        # The expression itself is never sent to a device.
        self.assertEqual(
            [text for text, _ in self.session.transport.sent_text],
            ["MEAS:VOLT?", "MEAS:CURR?", "MEAS:VOLT?"],
        )

    def test_rules_apply_to_computed_value(self) -> None:
        entry = power_entry()
        entry.rules = [ColorRule(op="gt", operand="21", state="warn", label="HIGH")]
        tab = self.make_tab(volt_entry(), amps_entry(), entry)
        tab.bind_to_session(1)
        self.clock.advance_ms(80)
        self.run_poll_round(tab, b"12.0\r\n", b"2.0\r\n")
        power_tile = tab.grid.tile("power")
        assert power_tile is not None
        self.assertEqual(power_tile.property("tileState"), "warn")

    def test_missing_inputs_render_neutral_waiting(self) -> None:
        tab = self.make_tab(volt_entry(), amps_entry(), power_entry())
        power_tile = tab.grid.tile("power")
        assert power_tile is not None
        self.assertEqual(power_tile.property("tileState"), "neutral")
        self.assertEqual(power_tile.value_label.text(), "—")
        self.assertIn("Waiting for: Volts, Amps", power_tile.toolTip())

    def test_partial_input_keeps_waiting_for_the_rest(self) -> None:
        idle_amps = amps_entry()
        idle_amps.enabled = False  # never polls -> Power keeps waiting
        tab = self.make_tab(volt_entry(), idle_amps, power_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(80)
        self.run_poll_round(tab, b"12.0\r\n")
        power_tile = tab.grid.tile("power")
        assert power_tile is not None
        self.assertEqual(power_tile.property("tileState"), "neutral")
        self.assertIn("Waiting for: Amps", power_tile.toolTip())

    def test_stale_input_makes_derived_stale(self) -> None:
        tab = self.make_tab(volt_entry(), amps_entry(), power_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(80)
        self.run_poll_round(tab, b"12.0\r\n", b"2.0\r\n")
        power_tile = tab.grid.tile("power")
        assert power_tile is not None
        self.assertEqual(power_tile.value_label.text(), "24 W")

        tab.set_polling_enabled(False)  # inputs now silently age
        self.clock.advance_ms(volt_entry().effective_stale_after_ms() + 1000)
        for _ in range(10):
            tab._tick()
        volt_tile = tab.grid.tile("volts")
        assert volt_tile is not None
        self.assertEqual(volt_tile.property("tileState"), "stale")
        self.assertEqual(power_tile.property("tileState"), "stale")
        # The last computed value stays readable while stale (FR-32).
        self.assertEqual(power_tile.value_label.text(), "24 W")

    def test_disabling_an_input_makes_derived_stale(self) -> None:
        tab = self.make_tab(volt_entry(), amps_entry(), power_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(80)
        self.run_poll_round(tab, b"12.0\r\n", b"2.0\r\n")
        power_tile = tab.grid.tile("power")
        assert power_tile is not None

        tab.set_entry_enabled("amps", False)
        for _ in range(10):  # staleness sweeps run every few ticks
            tab._tick()
        self.assertEqual(power_tile.property("tileState"), "stale")

    def test_evaluation_error_renders_error_tile(self) -> None:
        tab = self.make_tab(volt_entry(), amps_entry(), power_entry("{Volts} / {Amps}"))
        tab.bind_to_session(1)
        self.clock.advance_ms(80)
        self.run_poll_round(tab, b"12.0\r\n", b"0\r\n")
        power_tile = tab.grid.tile("power")
        assert power_tile is not None
        self.assertEqual(power_tile.property("tileState"), "error")
        self.assertIn("Division by zero", power_tile.toolTip())

    def test_unknown_reference_renders_error_tile(self) -> None:
        tab = self.make_tab(volt_entry(), power_entry("{Ghost} + 1"))
        power_tile = tab.grid.tile("power")
        assert power_tile is not None
        self.assertEqual(power_tile.property("tileState"), "error")
        self.assertIn("Unknown reference {Ghost}", power_tile.toolTip())

    def test_rename_rewrites_sibling_expressions(self) -> None:
        tab = self.make_tab(volt_entry(), amps_entry(), power_entry())
        tab.bind_to_session(1)
        renamed = volt_entry()
        renamed.label = "Rail A"
        tab.apply_entry_edit(renamed)

        power = tab.config.entry_by_id("power")
        assert power is not None
        self.assertEqual(power.expression, "{Rail A} * {Amps}")

        # The rewritten expression still computes.
        self.clock.advance_ms(80)
        self.run_poll_round(tab, b"12.0\r\n", b"2.0\r\n")
        power_tile = tab.grid.tile("power")
        assert power_tile is not None
        self.assertEqual(power_tile.value_label.text(), "24 W")

    def test_derived_entry_has_no_poll_now(self) -> None:
        tab = self.make_tab(volt_entry(), power_entry())
        tab.bind_to_session(1)
        self.assertFalse(tab.poll_now("power"))


def control_entry(
    mode: str = "button",
    *,
    confirm: bool = False,
    watch_entry_id: str = "",
) -> ControlPanelEntry:
    return ControlPanelEntry(
        id="ctrl",
        label="Output",
        control=ControlSpec(
            mode=mode,
            on_command="OUTP ON",
            off_command="OUTP OFF" if mode == "toggle" else "",
            confirm=confirm,
            watch_entry_id=watch_entry_id,
        ),
        tile=TilePlacement(col=0, row=1, kind="control"),
    )


def outp_state_entry() -> ControlPanelEntry:
    """Polled output state whose verdict is "ok" when the device says 1."""
    return ControlPanelEntry(
        id="outp",
        label="Output state",
        command="OUTP?",
        interval_ms=1000,
        timeout_ms=500,
        parse=ParseRule(kind="line", value_type="number"),
        rules=[ColorRule(op="eq_num", operand="1", state="ok", label="ON")],
        tile=TilePlacement(col=1, row=1, kind="led"),
    )


class ControlTileTests(ControlPanelTabTestBase):
    """Control tiles: gated, optionally confirmed sends (FR-59/FR-60)."""

    def setUp(self) -> None:
        super().setUp()
        self.status_messages: list[str] = []
        # Capture coordinator.notify() output for refusal assertions.
        self.coordinator._set_status = self.status_messages.append

    def make_tab(self, *args, **kwargs):
        # Control-tile tests exercise the send pipeline; the master-arm
        # gate (v3) defaults to disarmed which would block every click.
        # Auto-arm so each test asserts the tile's own behavior. Tests
        # that specifically exercise the disarmed path call
        # set_armed(False) themselves.
        tab = super().make_tab(*args, **kwargs)
        tab.set_armed(True)
        return tab

    def test_click_sends_exactly_one_tagged_command(self) -> None:
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)
        tile = tab.grid.tile("ctrl")
        assert isinstance(tile, ControlTileWidget)

        self.assertTrue(tab._activate_control("ctrl"))
        self.assertTrue(tile.pending)
        self.assertTrue(wait_for(lambda: len(self.session.transport.sent_text) >= 1))
        self.assertEqual(self.session.transport.sent_text, [("OUTP ON", None)])
        self.assertEqual(self.session.transport.sent_sources, ["control_panel"])

        self.assertTrue(wait_for(lambda: not tab.result_queue.empty()))
        tab._tick()
        self.assertFalse(tile.pending)
        self.assertEqual(tile.toolTip(), "Command sent.")

    def test_button_click_routes_through_grid_signal(self) -> None:
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)
        tile = tab.grid.tile("ctrl")
        assert isinstance(tile, ControlTileWidget)
        tile.button.click()
        self.assertTrue(wait_for(lambda: len(self.session.transport.sent_text) >= 1))
        self.assertEqual(self.session.transport.sent_text, [("OUTP ON", None)])

    def test_confirm_default_no_sends_nothing(self) -> None:
        tab = self.make_tab(control_entry(confirm=True))
        tab.bind_to_session(1)
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.No
        ) as question:
            self.assertFalse(tab._activate_control("ctrl"))
        question.assert_called_once()
        # The fourth positional argument is the default button: No (FR-59).
        self.assertEqual(
            question.call_args.args[4], QMessageBox.StandardButton.No
        )
        self.assertEqual(self.session.transport.sent_text, [])

        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            self.assertTrue(tab._activate_control("ctrl"))
        self.assertTrue(wait_for(lambda: len(self.session.transport.sent_text) >= 1))

    def test_toggle_sends_off_when_watch_verdict_ok(self) -> None:
        # Follow-mode toggle: the watched OUTP? poll drives the visual
        # state; clicking the toggle while the device says "on" should
        # send the OFF command and *not* queue a redundant readback
        # (the OUTP? cycle keeps running on its own).
        tab = self.make_tab(outp_state_entry(), control_entry("toggle", watch_entry_id="outp"))
        tab.bind_to_session(1)
        self.clock.advance_ms(80)
        self.run_poll_round(tab, b"1\r\n")  # watch verdict -> ok -> tile ON
        tile = tab.grid.tile("ctrl")
        assert isinstance(tile, ControlTileWidget)
        self.assertTrue(tile.is_on)
        self.assertEqual(tile.button.text(), "ON")

        self.assertTrue(tab._activate_control("ctrl"))
        # We expect exactly: the existing OUTP? polls + one OUTP OFF.
        # Crucially the click must NOT queue another OUTP? right behind
        # the write — follow-mode is pure fan-out so the device only
        # sees the toggle send, plus whatever regular polls already
        # had on the wire.
        self.assertTrue(wait_for(lambda: ("OUTP OFF", None) in self.session.transport.sent_text))
        # Count OUTP? sends issued during the click — should be zero
        # net-new (any future OUTP? comes from the regular poll cycle,
        # not the toggle).
        before = list(self.session.transport.sent_text)
        # Drain any pending result without further ticks.
        tab._drain_results()
        self.assertEqual(self.session.transport.sent_text, before)

    def test_unwatched_toggle_flips_optimistically(self) -> None:
        tab = self.make_tab(control_entry("toggle"))
        tab.bind_to_session(1)
        tile = tab.grid.tile("ctrl")
        assert isinstance(tile, ControlTileWidget)
        self.assertFalse(tile.is_on)

        self.assertTrue(tab._activate_control("ctrl"))
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty()))
        tab._tick()
        self.assertTrue(tile.is_on)
        self.assertEqual(self.session.transport.sent_text, [("OUTP ON", None)])

        self.assertTrue(tab._activate_control("ctrl"))
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty()))
        tab._tick()
        self.assertFalse(tile.is_on)
        self.assertEqual(self.session.transport.sent_text[-1], ("OUTP OFF", None))

    def test_batch_run_blocks_click_with_status(self) -> None:
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)
        self.session.batch_running = True
        tab._tick()  # refresh the gate snapshot
        self.assertFalse(tab._activate_control("ctrl"))
        self.assertEqual(self.session.transport.sent_text, [])
        self.assertTrue(any("command file" in text for text in self.status_messages))

    def test_disconnect_blocks_click_with_status(self) -> None:
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)
        self.session.transport.disconnect()
        tab._tick()
        self.assertFalse(tab._activate_control("ctrl"))
        self.assertEqual(self.session.transport.sent_text, [])
        self.assertTrue(any("not connected" in text for text in self.status_messages))

    def test_user_pause_does_not_block_click(self) -> None:
        # A click is explicit intent — only disconnect/batch gate it.
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)
        tab.set_polling_enabled(False)
        self.assertTrue(tab._activate_control("ctrl"))
        self.assertTrue(wait_for(lambda: len(self.session.transport.sent_text) >= 1))

    def test_disabled_control_refuses_click(self) -> None:
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)
        tab.set_entry_enabled("ctrl", False)
        self.assertFalse(tab._activate_control("ctrl"))
        self.assertEqual(self.session.transport.sent_text, [])

    def test_edit_mode_makes_button_inert_but_draggable(self) -> None:
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)
        tile = tab.grid.tile("ctrl")
        assert isinstance(tile, ControlTileWidget)
        self.assertTrue(tile.button.isEnabled())

        tab.grid.set_edit_mode(True)
        self.assertFalse(tile.button.isEnabled())
        # Press events must pass through to the tile so dragging works.
        self.assertTrue(
            tile.button.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        )
        tab.grid.set_edit_mode(False)
        self.assertTrue(tile.button.isEnabled())
        self.assertFalse(
            tile.button.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        )

    def test_controls_are_never_scheduled(self) -> None:
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(60_000)
        tab._tick()
        tab._tick()
        self.assertEqual(self.session.transport.sent_text, [])
        self.assertFalse(tab.poll_now("ctrl"))

    def test_send_error_marks_error_state(self) -> None:
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)

        def explode(text: str, line_ending_override=None, *, source: str = "") -> None:
            raise RuntimeError("port vanished")

        self.session.transport.send_text = explode  # type: ignore[method-assign]
        self.assertTrue(tab._activate_control("ctrl"))
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty()))
        tab._tick()
        tile = tab.grid.tile("ctrl")
        assert isinstance(tile, ControlTileWidget)
        self.assertFalse(tile.pending)
        self.assertEqual(tile.property("tileState"), "error")
        self.assertIn("port vanished", tile.toolTip())

    def test_kind_change_recreates_tile_class(self) -> None:
        tab = self.make_tab(control_entry())
        self.assertIsInstance(tab.grid.tile("ctrl"), ControlTileWidget)
        edited = control_entry()
        edited.tile.kind = "value"
        edited.command = "OUTP?"  # value tiles need a polled command
        edited.control = ControlSpec()
        tab.apply_entry_edit(edited)
        self.assertIsInstance(tab.grid.tile("ctrl"), ValueTileWidget)

    def test_csv_log_records_control_send(self) -> None:
        import csv
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="dash-ctrl-csv-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        log_path = tmp / "values.csv"
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)
        tab.config.csv_log_path = str(log_path)
        tab.csv_log_button.setChecked(True)
        self.addCleanup(tab.value_logger.close)

        self.assertTrue(tab._activate_control("ctrl"))
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty()))
        tab._tick()

        with log_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "control")
        self.assertEqual(rows[0]["entry_id"], "ctrl")
        self.assertEqual(rows[0]["value_text"], "OUTP ON")
        self.assertEqual(rows[0]["state"], "ok")
        self.assertEqual(rows[0]["value_number"], "")

    def test_csv_log_records_control_send_error(self) -> None:
        import csv
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="dash-ctrl-csv-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        log_path = tmp / "values.csv"
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)
        tab.config.csv_log_path = str(log_path)
        tab.csv_log_button.setChecked(True)
        self.addCleanup(tab.value_logger.close)

        def explode(text, line_ending_override=None, *, source=""):
            raise RuntimeError("port lost")

        self.session.transport.send_text = explode  # type: ignore[method-assign]
        self.assertTrue(tab._activate_control("ctrl"))
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty()))
        tab._tick()

        with log_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "control")
        self.assertEqual(rows[0]["state"], "error")
        # Errors still carry the attempted command for auditability.
        self.assertEqual(rows[0]["value_text"], "OUTP ON")

    def test_confirm_no_does_not_log(self) -> None:
        from unittest.mock import patch
        import csv
        import tempfile
        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox

        tmp = Path(tempfile.mkdtemp(prefix="dash-ctrl-csv-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        log_path = tmp / "values.csv"
        tab = self.make_tab(control_entry(confirm=True))
        tab.bind_to_session(1)
        tab.config.csv_log_path = str(log_path)
        tab.csv_log_button.setChecked(True)
        self.addCleanup(tab.value_logger.close)

        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.No
        ):
            self.assertFalse(tab._activate_control("ctrl"))

        with log_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            rows = list(csv.DictReader(csv_file))
        # Cancellation never logs — only sends that left the queue.
        self.assertEqual(rows, [])


def setpoint_entry(
    *,
    min_value: float = 0.0,
    max_value: float = 30.0,
    step: float = 0.1,
    decimals: int = 2,
    unit: str = "V",
    template: str = "VOLT {value}",
    watch_entry_id: str = "",
    confirm: bool = False,
) -> ControlPanelEntry:
    from ComPort_Zone.control_panel_models import SetpointSpec

    return ControlPanelEntry(
        id="sp",
        label="Voltage",
        tile=TilePlacement(col=0, row=2, kind="setpoint"),
        setpoint=SetpointSpec(
            min_value=min_value,
            max_value=max_value,
            step=step,
            decimals=decimals,
            unit=unit,
            command_template=template,
            watch_entry_id=watch_entry_id,
            confirm=confirm,
        ),
    )


class SetpointTileTests(ControlPanelTabTestBase):
    """Setpoint widget end-to-end (v3, FR-63..FR-67)."""

    def setUp(self) -> None:
        super().setUp()
        self.status_messages: list[str] = []
        self.coordinator._set_status = self.status_messages.append

    def make_tab(self, *args, **kwargs):
        tab = super().make_tab(*args, **kwargs)
        tab.set_armed(True)  # see ControlTileTests.make_tab
        return tab

    def test_setpoint_uses_spinbox_without_slider(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        tab = self.make_tab(setpoint_entry())
        tile = tab.grid.tile("sp")
        assert isinstance(tile, SetpointTileWidget)
        self.assertFalse(hasattr(tile, "slider"))
        self.assertTrue(tile.readback_field.isReadOnly())
        self.assertTrue(tile.readback_field.isHidden())

        tile.set_value(5.0)
        self.assertAlmostEqual(tile.value, 5.0, places=4)
        self.assertAlmostEqual(tile.spin.value(), 5.0, places=4)

        tile.spin.setValue(12.5)
        self.assertAlmostEqual(tile.value, 12.5, places=4)

    def test_spinbox_clamps_out_of_range(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        tab = self.make_tab(setpoint_entry(min_value=0.0, max_value=10.0))
        tile = tab.grid.tile("sp")
        assert isinstance(tile, SetpointTileWidget)
        # QDoubleSpinBox clamps on setValue, so the typed-out-of-range
        # path still lands on the bound.
        tile.spin.setValue(99.0)
        self.assertEqual(tile.value, 10.0)
        tile.spin.setValue(-5.0)
        self.assertEqual(tile.value, 0.0)

    def test_send_submits_one_templated_command(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        tab = self.make_tab(setpoint_entry())
        tab.bind_to_session(1)
        tile = tab.grid.tile("sp")
        assert isinstance(tile, SetpointTileWidget)
        tile.spin.setValue(12.5)
        self.assertTrue(tab._activate_control("sp"))
        self.assertTrue(tile.pending)
        self.assertTrue(wait_for(lambda: len(self.session.transport.sent_text) >= 1))
        self.assertEqual(
            self.session.transport.sent_text,
            [("VOLT 12.50", None)],
        )
        self.assertEqual(self.session.transport.sent_sources, ["control_panel"])
        # Result clears the pending flag.
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty()))
        tab._tick()
        self.assertFalse(tile.pending)

    def test_send_blocked_when_disconnected(self) -> None:
        tab = self.make_tab(setpoint_entry())
        tab.bind_to_session(1)
        self.session.transport.disconnect()
        tab._tick()
        self.assertFalse(tab._activate_control("sp"))
        self.assertEqual(self.session.transport.sent_text, [])
        self.assertTrue(any("not connected" in t for t in self.status_messages))

    def test_send_blocked_during_batch(self) -> None:
        tab = self.make_tab(setpoint_entry())
        tab.bind_to_session(1)
        self.session.batch_running = True
        tab._tick()
        self.assertFalse(tab._activate_control("sp"))
        self.assertEqual(self.session.transport.sent_text, [])
        self.assertTrue(any("command file" in t for t in self.status_messages))

    def test_setpoint_button_click_routes_through_send_button(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        tab = self.make_tab(setpoint_entry())
        tab.bind_to_session(1)
        tile = tab.grid.tile("sp")
        assert isinstance(tile, SetpointTileWidget)
        tile.spin.setValue(3.5)
        tile.send_button.click()
        self.assertTrue(wait_for(lambda: len(self.session.transport.sent_text) >= 1))
        self.assertEqual(self.session.transport.sent_text, [("VOLT 3.50", None)])

    def test_confirm_no_blocks_send(self) -> None:
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        tab = self.make_tab(setpoint_entry(confirm=True))
        tab.bind_to_session(1)
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.No
        ) as question:
            self.assertFalse(tab._activate_control("sp"))
        question.assert_called_once()
        self.assertEqual(self.session.transport.sent_text, [])

    def test_readback_follows_watched_entry(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        # The setpoint watches the polled volt entry's value.
        polled = volt_entry()
        polled.id = "vmeas"
        polled.label = "Measured"
        sp = setpoint_entry(watch_entry_id="vmeas")
        tab = self.make_tab(polled, sp)
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"12.34\r\n")
        tile = tab.grid.tile("sp")
        assert isinstance(tile, SetpointTileWidget)
        self.assertFalse(tile.readback_field.isHidden())
        self.assertTrue(tile.readback_field.isReadOnly())
        self.assertEqual(tile.readback_field.text(), "12.34 V")

    def test_direct_readback_command_runs_after_send(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        sp = setpoint_entry()
        sp.readback = ReadbackSpec(
            source="command",
            command="MEAS:VOLT?",
            delay_ms=0,
            parse=ParseRule(kind="line", value_type="number"),
            rules=[ColorRule(op="gt", operand="12", state="ok", label="READY")],
        )
        tab = self.make_tab(sp)
        tab.bind_to_session(1)
        tile = tab.grid.tile("sp")
        assert isinstance(tile, SetpointTileWidget)
        tile.spin.setValue(12.5)
        # First queued response is stale/echo after the write; the
        # readback transaction drains it before sending its query.
        self.session.transport.queue_response(b"echo\r\n")
        self.session.transport.queue_response(b"12.6\r\n")

        self.assertTrue(tab._activate_control("sp"))
        self.assertTrue(wait_for(lambda: len(self.session.transport.sent_text) >= 2))
        self.assertEqual(
            self.session.transport.sent_text,
            [("VOLT 12.50", None), ("MEAS:VOLT?", None)],
        )
        self.assertTrue(wait_for(lambda: tab.result_queue.qsize() >= 2))
        tab._tick()
        self.assertFalse(tile.pending)
        self.assertEqual(tile.readback_field.text(), "12.6 V")
        self.assertAlmostEqual(tile.spin.value(), 12.5, places=4)
        self.assertEqual(tile.property("tileState"), "ok")

    def test_direct_readback_runs_once_on_connect(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        sp = setpoint_entry()
        sp.readback = ReadbackSpec(
            source="command",
            command="MEAS:VOLT?",
            delay_ms=0,
        )
        tab = self.make_tab(sp)
        tile = tab.grid.tile("sp")
        assert isinstance(tile, SetpointTileWidget)
        self.assertAlmostEqual(tile.spin.value(), 0.0, places=4)
        self.session.transport.queue_response(b"11.1\r\n")
        tab.bind_to_session(1)
        tab._tick()
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty()))
        tab._tick()
        self.assertEqual(self.session.transport.sent_text, [("MEAS:VOLT?", None)])
        self.assertEqual(tile.readback_field.text(), "11.1 V")
        self.assertAlmostEqual(tile.spin.value(), 11.1, places=4)

    def test_followed_readback_on_connect_seeds_setpoint_value(self) -> None:
        # Follow-mode setpoint should adopt the watched tile's first
        # poll result for both the readback box AND the editable
        # command field — without queueing a separate readback
        # transaction (the polled tile is already on the wire).
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        polled = volt_entry()
        polled.id = "vmeas"
        polled.label = "Measured"
        sp = setpoint_entry(watch_entry_id="vmeas")
        tab = self.make_tab(polled, sp)
        tile = tab.grid.tile("sp")
        assert isinstance(tile, SetpointTileWidget)
        self.assertAlmostEqual(tile.spin.value(), 0.0, places=4)

        self.session.transport.queue_response(b"7.25\r\n")
        tab.bind_to_session(1)
        tab._tick()
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty()))
        tab._tick()

        # Exactly ONE MEAS:VOLT? on the wire — the polled tile's regular
        # poll. No redundant readback for the setpoint.
        self.assertEqual(
            self.session.transport.sent_text,
            [("MEAS:VOLT?", None)],
        )
        self.assertEqual(tile.readback_field.text(), "7.25 V")
        self.assertAlmostEqual(tile.spin.value(), 7.25, places=4)

    def test_send_error_marks_tile_error(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        tab = self.make_tab(setpoint_entry())
        tab.bind_to_session(1)

        def explode(text, line_ending_override=None, *, source: str = ""):
            raise RuntimeError("device offline")

        self.session.transport.send_text = explode  # type: ignore[method-assign]
        self.assertTrue(tab._activate_control("sp"))
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty()))
        tab._tick()
        tile = tab.grid.tile("sp")
        assert isinstance(tile, SetpointTileWidget)
        self.assertFalse(tile.pending)
        self.assertEqual(tile.property("tileState"), "error")
        self.assertIn("device offline", tile.toolTip())

    def test_follow_mode_does_not_double_poll(self) -> None:
        """A setpoint following another tile must not queue an extra
        readback transaction — that's pure fan-out, no device traffic.

        The pre-refactor wiring re-polled the watched tile from the
        setpoint, doubling device load AND extending the per-poll
        journal window so manual terminal RX got suppressed. This
        regression test locks down the fan-out-only behaviour.
        """
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        polled = volt_entry()
        polled.id = "vmeas"
        polled.label = "Measured"
        sp = setpoint_entry(watch_entry_id="vmeas")
        tab = self.make_tab(polled, sp)
        tile = tab.grid.tile("sp")
        assert isinstance(tile, SetpointTileWidget)

        self.session.transport.queue_response(b"5.50\r\n")
        tab.bind_to_session(1)
        tab._tick()
        self.assertTrue(wait_for(lambda: not tab.result_queue.empty()))
        tab._tick()
        # Exactly the polled tile's poll — no second MEAS:VOLT? from a
        # follow-mode "readback" transaction.
        self.assertEqual(
            self.session.transport.sent_text,
            [("MEAS:VOLT?", None)],
        )
        # Fan-out still seeded the spinbox + readback box.
        self.assertEqual(tile.readback_field.text(), "5.5 V")
        self.assertAlmostEqual(tile.spin.value(), 5.5, places=4)

    def test_setpoint_never_scheduled(self) -> None:
        tab = self.make_tab(setpoint_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(60_000)
        tab._tick()
        tab._tick()
        self.assertEqual(self.session.transport.sent_text, [])
        self.assertFalse(tab.poll_now("sp"))

    def test_edit_mode_makes_widgets_inert_but_draggable(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        tab = self.make_tab(setpoint_entry())
        tile = tab.grid.tile("sp")
        assert isinstance(tile, SetpointTileWidget)
        tab.grid.set_edit_mode(True)
        self.assertFalse(tile.send_button.isEnabled())
        for widget in (tile.spin, tile.readback_field, tile.send_button):
            self.assertTrue(
                widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            )
        tab.grid.set_edit_mode(False)
        self.assertTrue(tile.send_button.isEnabled())
        for widget in (tile.spin, tile.readback_field, tile.send_button):
            self.assertFalse(
                widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            )

    def test_setpoint_kind_change_recreates_tile(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        tab = self.make_tab(setpoint_entry())
        self.assertIsInstance(tab.grid.tile("sp"), SetpointTileWidget)
        edited = setpoint_entry()
        edited.tile.kind = "value"
        edited.command = "MEAS?"
        edited.parse.value_type = "number"
        tab.apply_entry_edit(edited)
        self.assertIsInstance(tab.grid.tile("sp"), ValueTileWidget)


def enum_entry(
    *,
    options=None,
    watch_entry_id: str = "",
    confirm: bool = False,
) -> ControlPanelEntry:
    from ComPort_Zone.control_panel_models import EnumOption, EnumSpec

    if options is None:
        options = [
            EnumOption(label="CV", command="MODE CV", match_value="CV"),
            EnumOption(label="CC", command="MODE CC", match_value="CC"),
            EnumOption(label="OFF", command="OUTP OFF"),
        ]
    return ControlPanelEntry(
        id="mode",
        label="Mode",
        tile=TilePlacement(col=0, row=3, kind="enum"),
        enum_spec=EnumSpec(
            options=options,
            watch_entry_id=watch_entry_id,
            confirm=confirm,
        ),
    )


class EnumTileTests(ControlPanelTabTestBase):
    """Enum/dropdown widget end-to-end (v3, FR-68..FR-71)."""

    def setUp(self) -> None:
        super().setUp()
        self.status_messages: list[str] = []
        self.coordinator._set_status = self.status_messages.append

    def make_tab(self, *args, **kwargs):
        tab = super().make_tab(*args, **kwargs)
        tab.set_armed(True)  # see ControlTileTests.make_tab
        return tab

    def test_combo_lists_options_send_routes_selected_command(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import EnumTileWidget

        tab = self.make_tab(enum_entry())
        tab.bind_to_session(1)
        tile = tab.grid.tile("mode")
        assert isinstance(tile, EnumTileWidget)
        # Combo carries one item per option.
        self.assertEqual(
            [tile.combo.itemText(i) for i in range(tile.combo.count())],
            ["CV", "CC", "OFF"],
        )
        tile.combo.setCurrentIndex(1)  # CC
        self.assertTrue(tab._activate_control("mode"))
        self.assertTrue(tile.pending)
        self.assertTrue(wait_for(lambda: len(self.session.transport.sent_text) >= 1))
        self.assertEqual(self.session.transport.sent_text, [("MODE CC", None)])
        self.assertEqual(self.session.transport.sent_sources, ["control_panel"])

    def test_send_button_click_path(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import EnumTileWidget

        tab = self.make_tab(enum_entry())
        tab.bind_to_session(1)
        tile = tab.grid.tile("mode")
        assert isinstance(tile, EnumTileWidget)
        tile.combo.setCurrentIndex(2)  # OFF
        tile.send_button.click()
        self.assertTrue(wait_for(lambda: len(self.session.transport.sent_text) >= 1))
        self.assertEqual(self.session.transport.sent_text, [("OUTP OFF", None)])

    def test_indicator_follows_watched_entry(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import EnumTileWidget

        polled = volt_entry()
        polled.id = "modepoll"
        polled.label = "Measured mode"
        polled.parse.value_type = "text"
        en = enum_entry(watch_entry_id="modepoll")
        tab = self.make_tab(polled, en)
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"CC\r\n")
        tile = tab.grid.tile("mode")
        assert isinstance(tile, EnumTileWidget)
        self.assertEqual(tile.indicated_index, 1)
        # Watched value changes -> indicator follows.
        self.clock.advance_ms(1100)
        self.run_poll_round(tab, b"cv\r\n")  # case-insensitive match
        self.assertEqual(tile.indicated_index, 0)
        # Combo selection is independent of indicator.
        tile.combo.setCurrentIndex(2)
        self.assertEqual(tile.indicated_index, 0)

    def test_indicator_misses_unknown_value(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import EnumTileWidget

        polled = volt_entry()
        polled.id = "modepoll"
        polled.parse.value_type = "text"
        en = enum_entry(watch_entry_id="modepoll")
        tab = self.make_tab(polled, en)
        tab.bind_to_session(1)
        self.clock.advance_ms(50)
        self.run_poll_round(tab, b"UNKNOWN\r\n")
        tile = tab.grid.tile("mode")
        assert isinstance(tile, EnumTileWidget)
        self.assertEqual(tile.indicated_index, -1)

    def test_send_blocks_during_batch_and_disconnect(self) -> None:
        tab = self.make_tab(enum_entry())
        tab.bind_to_session(1)
        self.session.batch_running = True
        tab._tick()
        self.assertFalse(tab._activate_control("mode"))
        self.assertEqual(self.session.transport.sent_text, [])
        self.session.batch_running = False
        self.session.transport.disconnect()
        tab._tick()
        self.assertFalse(tab._activate_control("mode"))
        self.assertEqual(self.session.transport.sent_text, [])

    def test_confirm_no_blocks_send(self) -> None:
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        tab = self.make_tab(enum_entry(confirm=True))
        tab.bind_to_session(1)
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.No
        ):
            self.assertFalse(tab._activate_control("mode"))
        self.assertEqual(self.session.transport.sent_text, [])

    def test_enum_never_scheduled(self) -> None:
        tab = self.make_tab(enum_entry())
        tab.bind_to_session(1)
        self.clock.advance_ms(60_000)
        tab._tick()
        tab._tick()
        self.assertEqual(self.session.transport.sent_text, [])
        self.assertFalse(tab.poll_now("mode"))

    def test_edit_mode_makes_widgets_inert(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import EnumTileWidget

        tab = self.make_tab(enum_entry())
        tile = tab.grid.tile("mode")
        assert isinstance(tile, EnumTileWidget)
        tab.grid.set_edit_mode(True)
        self.assertFalse(tile.send_button.isEnabled())
        for widget in (tile.combo, tile.send_button):
            self.assertTrue(
                widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            )

    def test_enum_kind_change_recreates_tile(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import EnumTileWidget

        tab = self.make_tab(enum_entry())
        self.assertIsInstance(tab.grid.tile("mode"), EnumTileWidget)
        edited = enum_entry()
        edited.tile.kind = "value"
        edited.command = "MODE?"
        tab.apply_entry_edit(edited)
        self.assertIsInstance(tab.grid.tile("mode"), ValueTileWidget)


class MasterArmTests(ControlPanelTabTestBase):
    """Master-arm transient gate (v3, FR-72..FR-75 + NFR-15).

    These tests deliberately use the base class's make_tab (no
    auto-arm) so they exercise the disarmed-by-default invariant.
    """

    def setUp(self) -> None:
        super().setUp()
        self.status_messages: list[str] = []
        self.coordinator._set_status = self.status_messages.append

    def test_panel_boots_disarmed(self) -> None:
        tab = self.make_tab(control_entry())
        self.assertFalse(tab.is_armed)
        self.assertFalse(tab.arm_button.isChecked())

    def test_disarmed_click_refused_with_status(self) -> None:
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)
        self.assertFalse(tab._activate_control("ctrl"))
        self.assertEqual(self.session.transport.sent_text, [])
        self.assertTrue(any("disarmed" in t for t in self.status_messages))

    def test_set_armed_emits_signal_and_lets_click_through(self) -> None:
        seen: list[bool] = []
        tab = self.make_tab(control_entry())
        tab.armingChanged.connect(seen.append)
        tab.set_armed(True)
        self.assertEqual(seen, [True])
        self.assertTrue(tab.is_armed)
        # Click is now permitted.
        tab.bind_to_session(1)
        self.assertTrue(tab._activate_control("ctrl"))

    def test_set_armed_idempotent(self) -> None:
        seen: list[bool] = []
        tab = self.make_tab(control_entry())
        tab.armingChanged.connect(seen.append)
        tab.set_armed(False)  # already disarmed
        self.assertEqual(seen, [])
        tab.set_armed(True)
        tab.set_armed(True)  # idempotent
        self.assertEqual(seen, [True])

    def test_arm_button_toggle_drives_state(self) -> None:
        tab = self.make_tab(control_entry())
        tab.arm_button.setChecked(True)
        self.assertTrue(tab.is_armed)
        tab.arm_button.setChecked(False)
        self.assertFalse(tab.is_armed)

    def test_unbind_force_disarms(self) -> None:
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)
        tab.set_armed(True)
        self.assertTrue(tab.is_armed)
        tab.unbind(notice="closing")
        self.assertFalse(tab.is_armed)
        self.assertTrue(any("disarmed" in t for t in self.status_messages))

    def test_session_close_force_disarms(self) -> None:
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)
        tab.set_armed(True)
        # Pretend the terminal tab closed: the session falls out of the
        # is_widget_open check.
        self.open_widgets = set()
        tab._tick()
        self.assertFalse(tab.is_armed)
        self.assertIsNone(tab.bound_session_id)

    def test_shutdown_force_disarms(self) -> None:
        tab = self.make_tab(control_entry())
        tab.bind_to_session(1)
        tab.set_armed(True)
        tab.shutdown()
        self.assertFalse(tab.is_armed)

    def test_writing_tiles_render_disarmed_visual(self) -> None:
        from ComPort_Zone.ui.control_panel_tiles import (
            ControlTileWidget,
            EnumTileWidget,
            SetpointTileWidget,
        )

        tab = self.make_tab(control_entry(), setpoint_entry(), enum_entry())
        for entry_id in ("ctrl", "sp", "mode"):
            tile = tab.grid.tile(entry_id)
            self.assertEqual(tile.property("panelArmed"), "false")
        # All three writing-tile send buttons disabled.
        ctrl = tab.grid.tile("ctrl")
        sp = tab.grid.tile("sp")
        en = tab.grid.tile("mode")
        assert isinstance(ctrl, ControlTileWidget)
        assert isinstance(sp, SetpointTileWidget)
        assert isinstance(en, EnumTileWidget)
        self.assertFalse(ctrl.button.isEnabled())
        self.assertFalse(sp.send_button.isEnabled())
        self.assertFalse(en.send_button.isEnabled())

        tab.set_armed(True)
        for entry_id in ("ctrl", "sp", "mode"):
            tile = tab.grid.tile(entry_id)
            self.assertEqual(tile.property("panelArmed"), "true")
        # Send buttons unlock when armed (gating on enabled + not pending).
        self.assertTrue(ctrl.button.isEnabled())
        self.assertTrue(sp.send_button.isEnabled())
        self.assertTrue(en.send_button.isEnabled())

    def test_value_tile_unaffected_by_arming(self) -> None:
        tab = self.make_tab(volt_entry())
        # Non-writing tiles get the default no-op set_panel_armed and
        # have no panelArmed property.
        value_tile = tab.grid.tile("volts")
        self.assertIsNone(value_tile.property("panelArmed"))
        tab.set_armed(True)
        self.assertIsNone(value_tile.property("panelArmed"))

    def test_confirm_still_fires_when_armed(self) -> None:
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        tab = self.make_tab(control_entry(confirm=True))
        tab.bind_to_session(1)
        tab.set_armed(True)
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ) as q:
            self.assertTrue(tab._activate_control("ctrl"))
        # Arming does not bypass the per-tile confirm prompt.
        q.assert_called_once()


class ControlPanelTabBindingTests(ControlPanelTabTestBase):
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
        state = ControlPanelTabState(control_panel_id="x", target_endpoint="COM7")
        tab = self.make_tab(volt_entry(), tab_state=state)
        tab.resolve_persisted_binding()
        self.assertEqual(tab.bound_session_id, 1)

    def test_resolve_persisted_binding_ambiguous_stays_unbound(self) -> None:
        self.sessions.append(FakeTerminalSession(2, endpoint="COM7"))
        state = ControlPanelTabState(control_panel_id="x", target_endpoint="COM7")
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


class ControlPanelTabConfigTests(ControlPanelTabTestBase):
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


class ControlPanelEntryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_values_round_trip(self) -> None:
        entry = volt_entry()
        dialog = ControlPanelEntryDialog(entry)
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

    def test_preview_aspect_ratio_tracks_span(self) -> None:
        # The preview tile should be roughly square for 1×1, taller for
        # tall tiles, wider for wide tiles, and uniformly scaled for
        # large spans so the dialog can fit them.
        entry = volt_entry()
        dialog = ControlPanelEntryDialog(entry)
        sizes: dict[tuple[int, int], tuple[int, int]] = {}
        for span_w, span_h in [(1, 1), (1, 5), (5, 1), (3, 3), (5, 5)]:
            # QComboBox.findData() compares wrapped Python tuples by
            # identity, so dialogs select by data via a manual scan.
            target = (span_w, span_h)
            matched = False
            for idx in range(dialog.span_combo.count()):
                if dialog.span_combo.itemData(idx) == target:
                    dialog.span_combo.setCurrentIndex(idx)
                    matched = True
                    break
            self.assertTrue(matched, f"span {span_w}×{span_h} not offered")
            assert dialog.preview_tile is not None
            sizes[(span_w, span_h)] = (
                dialog.preview_tile.width(),
                dialog.preview_tile.height(),
            )
        w11, h11 = sizes[(1, 1)]
        w15, h15 = sizes[(1, 5)]
        w51, h51 = sizes[(5, 1)]
        w33, h33 = sizes[(3, 3)]
        w55, h55 = sizes[(5, 5)]
        # Tall tile must be visibly taller than 1×1; wide must be wider.
        self.assertGreater(h15, h11)
        self.assertGreater(w51, w11)
        # 1×5 reads as a tall column; 5×1 reads as a wide row.
        self.assertGreater(h15, w15)
        self.assertGreater(w51, h51)
        # Square spans (3×3, 5×5) preserve the per-cell aspect ratio
        # (matching what a real cell looks like) — both must therefore
        # share the same width/height ratio as 1×1, within rounding.
        ratio_11 = w11 / h11
        self.assertAlmostEqual(w33 / h33, ratio_11, delta=0.15)
        self.assertAlmostEqual(w55 / h55, ratio_11, delta=0.15)
        # Neither dimension exceeds the configured preview cap, so the
        # tile always fits in the dialog header strip.
        from ComPort_Zone.ui.dialogs.control_panel_entry import (
            PREVIEW_MAX_H,
            PREVIEW_MAX_W,
        )

        for (sw, sh), (w, h) in sizes.items():
            with self.subTest(span=f"{sw}x{sh}"):
                self.assertLessEqual(w, PREVIEW_MAX_W)
                self.assertLessEqual(h, PREVIEW_MAX_H)
        # 3×3 must be at least as big as 1×1 along both axes (a 1×1
        # tile only fills one cell while 3×3 fills nine).
        self.assertGreaterEqual(w33, w11)
        self.assertGreaterEqual(h33, h11)
        dialog.deleteLater()

    def test_ok_gated_on_validation(self) -> None:
        dialog = ControlPanelEntryDialog()
        dialog.command_input.setText("")
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 0)
        self.assertTrue(dialog.error_label.isVisible() or dialog.error_label.text())
        self.assertIn("Command must not be empty", dialog.error_label.text())
        dialog.deleteLater()

    def test_bad_regex_blocks_accept(self) -> None:
        dialog = ControlPanelEntryDialog()
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
        dialog = ControlPanelEntryDialog(entry)
        dialog.sample_input.setPlainText("13.5\r\n")
        self.assertIn("13.5 V", dialog.tester_result.text())
        self.assertIn("WARN", dialog.tester_result.text())
        dialog.deleteLater()

    def test_live_tester_reports_waiting(self) -> None:
        dialog = ControlPanelEntryDialog(volt_entry())
        dialog.sample_input.setPlainText("13.5")  # no line terminator
        self.assertIn("keep waiting", dialog.tester_result.text())
        dialog.deleteLater()

    def test_live_tester_reports_rule_error(self) -> None:
        dialog = ControlPanelEntryDialog()
        index = dialog.parse_kind_combo.findData("regex")
        dialog.parse_kind_combo.setCurrentIndex(index)
        dialog.pattern_input.setText("(bad")
        dialog.sample_input.setPlainText("anything")
        self.assertIn("Rule error", dialog.tester_result.text())
        dialog.deleteLater()

    def test_hex_mode_validation(self) -> None:
        dialog = ControlPanelEntryDialog()
        dialog.command_input.setText("ABC")
        dialog.mode_combo.setCurrentText("Hex Bytes")
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 0)
        self.assertIn("even", dialog.error_label.text())
        dialog.deleteLater()

    def test_target_combo_lists_sessions_and_stale_override(self) -> None:
        from ComPort_Zone.ui.dialogs.control_panel_entry import EntryDialogContext

        entry = volt_entry()
        entry.target_endpoint = "COM77"  # not among the open terminals
        context = EntryDialogContext(
            bind_targets=[("COM7", "Terminal 1 · Serial", True), ("COM9", "Terminal 2 · Serial", False)]
        )
        dialog = ControlPanelEntryDialog(entry, context=context)
        labels = [dialog.target_combo.itemText(i) for i in range(dialog.target_combo.count())]
        self.assertEqual(labels[0], "Control panel binding (default)")
        self.assertIn("Terminal 1 · Serial", labels)
        self.assertIn("Terminal 2 · Serial (disconnected)", labels)
        self.assertIn("COM77 (not open)", labels)
        # The stored override is preselected, and values() keeps it.
        self.assertEqual(dialog.target_combo.currentData(), "COM77")
        self.assertEqual(dialog.values().target_endpoint, "COM77")
        dialog.deleteLater()

    def test_poll_mode_round_trip_and_interval_enablement(self) -> None:
        entry = volt_entry()
        entry.poll_mode = "on_connect"
        dialog = ControlPanelEntryDialog(entry)
        self.assertEqual(dialog.poll_mode_combo.currentData(), "on_connect")
        self.assertFalse(dialog.interval_spin.isEnabled())
        self.assertEqual(dialog.values().poll_mode, "on_connect")
        index = dialog.poll_mode_combo.findData("interval")
        dialog.poll_mode_combo.setCurrentIndex(index)
        self.assertTrue(dialog.interval_spin.isEnabled())
        dialog.deleteLater()

    @staticmethod
    def derived_context() -> "EntryDialogContext":
        from ComPort_Zone.ui.dialogs.control_panel_entry import EntryDialogContext

        return EntryDialogContext(
            expression_resolver={"volts": ["volts"], "amps": ["amps"]},
            expression_sources={"volts": "poll", "amps": "poll"},
            reference_labels=["Volts", "Amps"],
        )

    def test_source_switch_to_derived_hides_poll_rows(self) -> None:
        dialog = ControlPanelEntryDialog(volt_entry(), context=self.derived_context())
        self.assertTrue(dialog._is_row_visible(dialog.command_input))
        self.assertFalse(dialog._is_row_visible(dialog.expression_container))
        self.assertTrue(dialog.tabs.isTabVisible(dialog.POLLING_TAB))

        index = dialog.source_combo.findData("derived")
        dialog.source_combo.setCurrentIndex(index)
        self.assertFalse(dialog._is_row_visible(dialog.command_input))
        self.assertFalse(dialog._is_row_visible(dialog.interval_spin))
        self.assertFalse(dialog._is_row_visible(dialog.target_combo))
        self.assertTrue(dialog._is_row_visible(dialog.expression_container))
        self.assertTrue(dialog._parse_box.isHidden())
        # A derived entry has no polling page at all.
        self.assertFalse(dialog.tabs.isTabVisible(dialog.POLLING_TAB))
        self.assertTrue(dialog.tabs.isTabVisible(dialog.RESPONSE_TAB))
        self.assertEqual(dialog.enabled_check.text(), "Update this tile")
        dialog.deleteLater()

    def test_values_for_derived_clear_poll_fields(self) -> None:
        entry = volt_entry()
        entry.target_endpoint = "COM9"
        entry.poll_mode = "on_connect"
        dialog = ControlPanelEntryDialog(entry, context=self.derived_context())
        index = dialog.source_combo.findData("derived")
        dialog.source_combo.setCurrentIndex(index)
        dialog.expression_input.setText("{Amps} * 2")

        result = dialog.values()
        self.assertEqual(result.source, "derived")
        self.assertEqual(result.expression, "{Amps} * 2")
        self.assertEqual(result.command, "")
        self.assertEqual(result.target_endpoint, "")
        self.assertEqual(result.poll_mode, "interval")

        # Switching back restores the (still typed-in) poll fields and
        # drops the expression.
        index = dialog.source_combo.findData("poll")
        dialog.source_combo.setCurrentIndex(index)
        result = dialog.values()
        self.assertEqual(result.source, "poll")
        self.assertEqual(result.command, "MEAS:VOLT?")
        self.assertEqual(result.expression, "")
        dialog.deleteLater()

    def test_derived_round_trip(self) -> None:
        entry = ControlPanelEntry(
            id="power", label="Power", source="derived", expression="{Volts} * {Amps}"
        )
        dialog = ControlPanelEntryDialog(entry, context=self.derived_context())
        self.assertEqual(dialog.source_combo.currentData(), "derived")
        self.assertEqual(dialog.expression_input.text(), "{Volts} * {Amps}")
        result = dialog.values()
        self.assertEqual(result.id, "power")
        self.assertEqual(result.source, "derived")
        self.assertEqual(result.expression, "{Volts} * {Amps}")
        dialog.deleteLater()

    def test_expression_errors_block_accept(self) -> None:
        entry = ControlPanelEntry(label="Power", source="derived", expression="")
        dialog = ControlPanelEntryDialog(entry, context=self.derived_context())
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 0)
        self.assertIn("Expression must not be empty", dialog.error_label.text())

        dialog.expression_input.setText("{Ghost} + 1")
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 0)
        self.assertIn("Unknown reference {Ghost}", dialog.error_label.text())

        dialog.expression_input.setText("{Volts} * {Amps}")
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 1)
        dialog.deleteLater()

    def test_expression_hint_validates_live(self) -> None:
        entry = ControlPanelEntry(label="Power", source="derived", expression="")
        dialog = ControlPanelEntryDialog(entry, context=self.derived_context())
        self.assertIn("Available: {Volts}, {Amps}", dialog.expression_hint.text())

        dialog.expression_input.setText("{Ghost} + 1")
        self.assertIn("Unknown reference {Ghost}", dialog.expression_hint.text())

        dialog.expression_input.setText("{Volts} * {Amps}")
        self.assertIn("Valid — uses 2 input tile(s)", dialog.expression_hint.text())
        dialog.deleteLater()

    @staticmethod
    def control_context() -> "EntryDialogContext":
        from ComPort_Zone.ui.dialogs.control_panel_entry import EntryDialogContext

        return EntryDialogContext(watch_candidates=[("outp", "Output state")])

    def test_control_kind_shows_control_shape(self) -> None:
        entry = control_entry("toggle", confirm=True, watch_entry_id="outp")
        dialog = ControlPanelEntryDialog(entry, context=self.control_context())
        self.assertEqual(dialog.tile_kind_combo.currentData(), "control")
        self.assertFalse(dialog.control_box.isHidden())
        self.assertFalse(dialog._is_row_visible(dialog.command_input))
        self.assertFalse(dialog._is_row_visible(dialog.source_combo))
        self.assertFalse(dialog._is_row_visible(dialog.interval_spin))
        self.assertTrue(dialog._is_row_visible(dialog.mode_combo))
        self.assertTrue(dialog._is_row_visible(dialog.target_combo))
        self.assertTrue(dialog._parse_box.isHidden())
        self.assertTrue(dialog._rules_box.isHidden())
        # No response page for controls; sending details stay on Polling.
        self.assertFalse(dialog.tabs.isTabVisible(dialog.RESPONSE_TAB))
        self.assertTrue(dialog.tabs.isTabVisible(dialog.POLLING_TAB))
        self.assertEqual(dialog.enabled_check.text(), "Enable this control")
        self.assertEqual(dialog.control_mode_combo.currentData(), "toggle")
        self.assertFalse(dialog._control_form.isRowVisible(dialog.watch_combo))
        self.assertFalse(dialog.readback_box.isHidden())
        self.assertEqual(dialog.readback_source_combo.currentData(), "entry")
        self.assertEqual(dialog.readback_watch_combo.currentData(), "outp")
        self.assertTrue(dialog.confirm_check.isChecked())
        dialog.deleteLater()

    def test_control_values_round_trip(self) -> None:
        entry = control_entry("toggle", confirm=True, watch_entry_id="outp")
        dialog = ControlPanelEntryDialog(entry, context=self.control_context())
        result = dialog.values()
        self.assertTrue(result.is_control())
        self.assertEqual(result.control.mode, "toggle")
        self.assertEqual(result.control.on_command, "OUTP ON")
        self.assertEqual(result.control.off_command, "OUTP OFF")
        self.assertTrue(result.control.confirm)
        self.assertEqual(result.control.watch_entry_id, "")
        self.assertEqual(result.readback.source, "entry")
        self.assertEqual(result.readback.watch_entry_id, "outp")
        self.assertEqual(result.command, "")
        self.assertEqual(result.rules, [])
        self.assertEqual(result.source, "poll")
        dialog.deleteLater()

    def test_control_validation_blocks_empty_command(self) -> None:
        dialog = ControlPanelEntryDialog(context=self.control_context())
        index = dialog.tile_kind_combo.findData("control")
        dialog.tile_kind_combo.setCurrentIndex(index)
        self.assertFalse(dialog.control_box.isHidden())
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 0)
        self.assertIn("Command must not be empty", dialog.error_label.text())

        dialog.on_command_input.setText("OUTP ON")
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 1)
        dialog.deleteLater()

    def test_setpoint_kind_shows_setpoint_shape(self) -> None:
        from ComPort_Zone.control_panel_models import SetpointSpec
        from ComPort_Zone.ui.control_panel_tiles import SetpointTileWidget

        entry = ControlPanelEntry(
            label="Voltage",
            tile=TilePlacement(kind="setpoint"),
            setpoint=SetpointSpec(command_template="VOLT {value}"),
        )
        dialog = ControlPanelEntryDialog(entry, context=self.control_context())
        self.assertEqual(dialog.tile_kind_combo.currentData(), "setpoint")
        self.assertFalse(dialog.setpoint_box.isHidden())
        # Other writing groups stay hidden.
        self.assertTrue(dialog.control_box.isHidden())
        # Source row + response/rules tab hidden because writing tile.
        self.assertFalse(dialog._is_row_visible(dialog.source_combo))
        self.assertFalse(dialog.tabs.isTabVisible(dialog.RESPONSE_TAB))
        # The preview tile is the real SetpointTileWidget.
        self.assertIsInstance(dialog.preview_tile, SetpointTileWidget)
        self.assertEqual(dialog.enabled_check.text(), "Enable this setpoint")
        dialog.deleteLater()

    def test_setpoint_values_round_trip(self) -> None:
        from ComPort_Zone.control_panel_models import SetpointSpec

        entry = ControlPanelEntry(
            label="Voltage",
            tile=TilePlacement(kind="setpoint"),
            setpoint=SetpointSpec(
                min_value=0.0,
                max_value=24.0,
                step=0.5,
                decimals=1,
                unit="V",
                command_template="VOLT {value}",
                watch_entry_id="vmeas",
                confirm=True,
            ),
        )
        context = self.control_context()  # carries the candidate
        dialog = ControlPanelEntryDialog(entry, context=context)
        result = dialog.values()
        self.assertTrue(result.is_setpoint())
        self.assertEqual(result.setpoint.command_template, "VOLT {value}")
        self.assertEqual(result.setpoint.max_value, 24.0)
        self.assertEqual(result.setpoint.step, 0.5)
        self.assertEqual(result.setpoint.decimals, 1)
        self.assertEqual(result.setpoint.unit, "V")
        self.assertEqual(result.setpoint.watch_entry_id, "")
        self.assertEqual(result.readback.source, "entry")
        self.assertEqual(result.readback.watch_entry_id, "vmeas")
        # No control spec leaked.
        self.assertEqual(result.control, ControlSpec())
        # Polling fields cleared.
        self.assertEqual(result.command, "")
        self.assertEqual(result.rules, [])
        dialog.deleteLater()

    def test_setpoint_command_readback_uses_response_tab(self) -> None:
        from ComPort_Zone.control_panel_models import SetpointSpec

        entry = ControlPanelEntry(
            label="Voltage",
            tile=TilePlacement(kind="setpoint"),
            setpoint=SetpointSpec(command_template="VOLT {value}", unit="V"),
            readback=ReadbackSpec(
                source="command",
                command="MEAS:VOLT?",
                delay_ms=20,
                parse=ParseRule(kind="line", value_type="number"),
                rules=[ColorRule(op="gt", operand="1", state="ok")],
            ),
        )
        dialog = ControlPanelEntryDialog(entry, context=self.control_context())
        self.assertFalse(dialog.readback_box.isHidden())
        self.assertEqual(dialog.readback_source_combo.currentData(), "command")
        self.assertEqual(dialog.readback_command_input.text(), "MEAS:VOLT?")
        self.assertTrue(dialog.tabs.isTabVisible(dialog.RESPONSE_TAB))
        self.assertFalse(dialog._parse_box.isHidden())
        self.assertFalse(dialog._rules_box.isHidden())
        result = dialog.values()
        self.assertEqual(result.readback.source, "command")
        self.assertEqual(result.readback.command, "MEAS:VOLT?")
        self.assertEqual(result.readback.parse.value_type, "number")
        self.assertEqual(len(result.readback.rules), 1)
        dialog.deleteLater()

    def test_setpoint_command_readback_dialog_scrolls_tab_pages(self) -> None:
        from PySide6.QtWidgets import QDialogButtonBox, QScrollArea

        from ComPort_Zone.control_panel_models import SetpointSpec

        entry = ControlPanelEntry(
            label="Voltage",
            tile=TilePlacement(kind="setpoint"),
            setpoint=SetpointSpec(command_template="VOLT {value}", unit="V"),
            readback=ReadbackSpec(
                source="command",
                command="MEAS:VOLT?",
                parse=ParseRule(kind="line", value_type="number"),
                rules=[ColorRule(op="gt", operand="1", state="ok")],
            ),
        )
        dialog = ControlPanelEntryDialog(entry, context=self.control_context())
        general_page = dialog.tabs.widget(dialog.GENERAL_TAB)
        response_page = dialog.tabs.widget(dialog.RESPONSE_TAB)
        buttons = dialog.findChild(QDialogButtonBox)
        self.assertIsInstance(general_page, QScrollArea)
        self.assertIsInstance(response_page, QScrollArea)
        self.assertTrue(general_page.widgetResizable())
        self.assertTrue(response_page.widgetResizable())
        self.assertEqual(
            general_page.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.assertIsNotNone(buttons)
        self.assertGreaterEqual(dialog.layout().indexOf(buttons), 0)
        dialog.deleteLater()

    def test_setpoint_validation_blocks_bad_template(self) -> None:
        dialog = ControlPanelEntryDialog(context=self.control_context())
        index = dialog.tile_kind_combo.findData("setpoint")
        dialog.tile_kind_combo.setCurrentIndex(index)
        # Empty template — OK gated.
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 0)
        self.assertIn("Command template", dialog.error_label.text())
        # Missing placeholder.
        dialog.setpoint_template_input.setText("VOLT")
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 0)
        # Fix and re-validate.
        dialog.setpoint_template_input.setText("VOLT {value}")
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 1)
        dialog.deleteLater()

    def test_enum_kind_shows_enum_shape(self) -> None:
        from ComPort_Zone.control_panel_models import EnumOption, EnumSpec
        from ComPort_Zone.ui.control_panel_tiles import EnumTileWidget

        entry = ControlPanelEntry(
            label="Mode",
            tile=TilePlacement(kind="enum"),
            enum_spec=EnumSpec(
                options=[
                    EnumOption(label="CV", command="MODE CV"),
                    EnumOption(label="CC", command="MODE CC"),
                ]
            ),
        )
        dialog = ControlPanelEntryDialog(entry, context=self.control_context())
        self.assertEqual(dialog.tile_kind_combo.currentData(), "enum")
        self.assertFalse(dialog.enum_box.isHidden())
        # Other writing groups stay hidden.
        self.assertTrue(dialog.control_box.isHidden())
        self.assertTrue(dialog.setpoint_box.isHidden())
        # Options table pre-loaded.
        self.assertEqual(dialog.enum_table.rowCount(), 2)
        self.assertEqual(dialog.enum_table.item(0, 0).text(), "CV")
        # Preview tile is the real EnumTileWidget.
        self.assertIsInstance(dialog.preview_tile, EnumTileWidget)
        self.assertEqual(dialog.enabled_check.text(), "Enable this selector")
        dialog.deleteLater()

    def test_enum_values_round_trip(self) -> None:
        from ComPort_Zone.control_panel_models import EnumOption, EnumSpec

        entry = ControlPanelEntry(
            label="Mode",
            tile=TilePlacement(kind="enum"),
            enum_spec=EnumSpec(
                options=[
                    EnumOption(label="CV", command="MODE CV", match_value="CV"),
                    EnumOption(label="CC", command="MODE CC", match_value="CC"),
                ],
                watch_entry_id="modepoll",
                confirm=True,
            ),
        )
        dialog = ControlPanelEntryDialog(entry, context=self.control_context())
        result = dialog.values()
        self.assertTrue(result.is_enum())
        self.assertEqual(len(result.enum_spec.options), 2)
        self.assertEqual(result.enum_spec.options[0].label, "CV")
        self.assertEqual(result.enum_spec.options[0].command, "MODE CV")
        self.assertEqual(result.enum_spec.options[0].match_value, "CV")
        self.assertTrue(result.enum_spec.confirm)
        # Polling and other writing fields cleared.
        self.assertEqual(result.command, "")
        self.assertEqual(result.rules, [])
        self.assertEqual(result.setpoint.command_template, "")
        dialog.deleteLater()

    def test_enum_validation_requires_options(self) -> None:
        # No options yet -> OK gated.
        dialog = ControlPanelEntryDialog(context=self.control_context())
        index = dialog.tile_kind_combo.findData("enum")
        dialog.tile_kind_combo.setCurrentIndex(index)
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 0)
        self.assertIn("at least one option", dialog.error_label.text())
        # Add an option.
        dialog._append_enum_row("CV", "MODE CV", "")
        dialog._accept_if_valid()
        self.assertEqual(dialog.result(), 1)
        dialog.deleteLater()

    def test_button_mode_drops_off_command_and_watch(self) -> None:
        entry = control_entry("toggle", watch_entry_id="outp")
        dialog = ControlPanelEntryDialog(entry, context=self.control_context())
        # Toggle-only rows hide when the mode flips to button…
        index = dialog.control_mode_combo.findData("button")
        dialog.control_mode_combo.setCurrentIndex(index)
        self.assertFalse(dialog._control_form.isRowVisible(dialog.off_command_input))
        self.assertFalse(dialog._control_form.isRowVisible(dialog.watch_combo))
        # …and values() drops what the user can no longer see.
        result = dialog.values()
        self.assertEqual(result.control.mode, "button")
        self.assertEqual(result.control.off_command, "")
        self.assertEqual(result.control.watch_entry_id, "")
        dialog.deleteLater()

    def test_preview_tile_follows_kind_and_sample(self) -> None:
        dialog = ControlPanelEntryDialog(volt_entry())
        assert dialog.preview_tile is not None
        self.assertIsInstance(dialog.preview_tile, ValueTileWidget)
        self.assertEqual(dialog.preview_tile.value_label.text(), "—")

        dialog.sample_input.setPlainText("13.5\r\n")
        self.assertEqual(dialog.preview_tile.value_label.text(), "13.5 V")
        self.assertEqual(dialog.preview_tile.property("tileState"), "warn")

        index = dialog.tile_kind_combo.findData("led")
        dialog.tile_kind_combo.setCurrentIndex(index)
        from ComPort_Zone.ui.control_panel_tiles import LedTileWidget

        self.assertIsInstance(dialog.preview_tile, LedTileWidget)

        index = dialog.tile_kind_combo.findData("control")
        dialog.tile_kind_combo.setCurrentIndex(index)
        self.assertIsInstance(dialog.preview_tile, ControlTileWidget)
        dialog.deleteLater()

    def test_preview_reflects_label_and_span(self) -> None:
        dialog = ControlPanelEntryDialog(volt_entry())
        assert dialog.preview_tile is not None
        self.assertEqual(dialog.preview_tile.title_label.text(), "Volts")
        dialog.label_input.setText("Rail A")
        self.assertEqual(dialog.preview_tile.title_label.text(), "Rail A")

        # setFixedSize applies to the size constraints; geometry only
        # follows once the (unshown) dialog runs a layout pass.
        narrow = dialog.preview_tile.minimumWidth()
        dialog._select_data(dialog.span_combo, (2, 1))
        self.assertEqual(dialog.span_combo.currentData(), (2, 1))
        self.assertGreater(dialog.preview_tile.minimumWidth(), narrow)
        dialog.deleteLater()

    def test_wide_tile_span_preselected_in_dialog(self) -> None:
        # Regression: Qt's findData compares Python tuples by identity, so
        # editing a wide tile used to silently show (and save) 1×1.
        entry = volt_entry()
        entry.tile.span_w = 2
        dialog = ControlPanelEntryDialog(entry)
        self.assertEqual(dialog.span_combo.currentData(), (2, 1))
        result = dialog.values()
        self.assertEqual((result.tile.span_w, result.tile.span_h), (2, 1))
        dialog.deleteLater()

    def test_preview_cancel_leaves_original_placement_untouched(self) -> None:
        entry = volt_entry()  # tile kind "value", span 1×1
        dialog = ControlPanelEntryDialog(entry)
        index = dialog.tile_kind_combo.findData("led")
        dialog.tile_kind_combo.setCurrentIndex(index)  # preview refreshes via values()
        dialog._select_data(dialog.span_combo, (2, 2))
        # The dialog was not accepted: the entry must be unchanged.
        self.assertEqual(entry.tile.kind, "value")
        self.assertEqual((entry.tile.span_w, entry.tile.span_h), (1, 1))
        dialog.deleteLater()

    def test_rule_color_round_trip_and_preview(self) -> None:
        entry = volt_entry()
        entry.rules = [ColorRule(op="gt", operand="13.0", state="warn", color="#12ab34")]
        dialog = ControlPanelEntryDialog(entry)
        # Round-trip through the table's swatch column (FR-62).
        button = dialog.rules_table.cellWidget(0, 4)
        self.assertEqual(button.property("ruleColor"), "#12ab34")
        self.assertEqual(dialog.values().rules[0].color, "#12ab34")
        # Matching sample -> the custom color reaches the preview tile.
        dialog.sample_input.setPlainText("14.0\r\n")
        assert isinstance(dialog.preview_tile, ValueTileWidget)
        self.assertIn("#12ab34", dialog.preview_tile.value_label.styleSheet())
        # Resetting the swatch clears it everywhere.
        dialog._set_rule_color(button, "")
        self.assertEqual(dialog.values().rules[0].color, "")
        self.assertEqual(dialog.preview_tile.value_label.styleSheet(), "")
        dialog.deleteLater()

    def test_dialog_stays_compact(self) -> None:
        # The pre-tabs layout grew past screen height (OK off-screen).
        # Tabs + preview must fit a 1366x768 work area (~730 px).
        dialog = ControlPanelEntryDialog(volt_entry())
        self.assertLess(dialog.sizeHint().height(), 740)
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
