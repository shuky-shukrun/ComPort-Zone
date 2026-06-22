"""Tests for the control_panel run coordinator (binding + dispatcher refcounts)."""

from __future__ import annotations

import threading
import unittest

from PySide6.QtWidgets import QApplication, QMenu

from ComPort_Zone.control_panel_engine import DISPATCHER_THREAD_NAME
from ComPort_Zone.ui.control_panel_targets import ControlPanelRunCoordinator

from tests.fakes.fake_serial_transport import FakeSerialTransport
from tests.fakes.fake_terminal_session import FakeTerminalSession as FakeSession


class FakeControlPanelTab:
    def __init__(self) -> None:
        self.refresh_count = 0

    def refresh_binding_state(self) -> None:
        self.refresh_count += 1


class ControlPanelRunCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.sessions: list[FakeSession] = []
        self.control_panels: list[FakeControlPanelTab] = []
        self.statuses: list[str] = []
        self.open_widgets: set[object] | None = None
        self.coordinator = ControlPanelRunCoordinator(
            sessions_supplier=lambda: self.sessions,
            control_panels_supplier=lambda: self.control_panels,
            is_widget_open=self._is_open,
            set_status=self.statuses.append,
            target_icon_color=lambda: "#9cdcfe",
        )

    def tearDown(self) -> None:
        self.coordinator.shutdown()
        names = [thread.name for thread in threading.enumerate()]
        self.assertNotIn(DISPATCHER_THREAD_NAME, names)

    def _is_open(self, widget: object) -> bool:
        if self.open_widgets is None:
            return True
        return widget in self.open_widgets

    def test_bind_targets_include_disconnected_sessions(self) -> None:
        self.sessions = [FakeSession(1), FakeSession(2, connected=False)]
        targets = self.coordinator.bind_targets()
        self.assertEqual(len(targets), 2)
        self.assertTrue(targets[0].connected)
        self.assertFalse(targets[1].connected)
        self.assertEqual(targets[1].endpoint, "COM2")

    def test_session_by_id(self) -> None:
        session = FakeSession(7)
        self.sessions = [session]
        self.assertIs(self.coordinator.session_by_id(7), session)
        self.assertIsNone(self.coordinator.session_by_id(8))

    def test_resolve_endpoint_unique_match(self) -> None:
        first = FakeSession(1, endpoint="COM7")
        second = FakeSession(2, endpoint="COM8")
        self.sessions = [first, second]
        self.assertIs(self.coordinator.resolve_endpoint("COM7"), first)

    def test_resolve_endpoint_ambiguous_or_missing(self) -> None:
        self.sessions = [FakeSession(1, endpoint="COM7"), FakeSession(2, endpoint="COM7")]
        self.assertIsNone(self.coordinator.resolve_endpoint("COM7"))
        self.assertIsNone(self.coordinator.resolve_endpoint("COM9"))
        self.assertIsNone(self.coordinator.resolve_endpoint("  "))

    def test_session_health_reflects_connection_and_batch(self) -> None:
        session = FakeSession(1)
        self.sessions = [session]
        health = self.coordinator.session_health(1)
        self.assertEqual((health.open, health.connected, health.batch_running), (True, True, False))
        session.transport.disconnect()
        self.assertFalse(self.coordinator.session_health(1).connected)
        session.batch_running = True
        self.assertTrue(self.coordinator.session_health(1).batch_running)

    def test_session_health_closed_widget(self) -> None:
        session = FakeSession(1)
        self.sessions = [session]
        self.open_widgets = set()
        self.assertFalse(self.coordinator.session_health(1).open)
        self.assertFalse(self.coordinator.session_health(99).open)

    def test_dispatcher_refcounting(self) -> None:
        session = FakeSession(1)
        self.sessions = [session]
        first = self.coordinator.acquire_dispatcher(session)
        second = self.coordinator.acquire_dispatcher(session)
        self.assertIs(first, second)
        self.assertEqual(self.coordinator.dispatcher_count(), 1)

        self.coordinator.release_dispatcher(1)
        self.assertTrue(first.is_running)
        self.assertEqual(self.coordinator.dispatcher_count(), 1)

        self.coordinator.release_dispatcher(1)
        self.assertFalse(first.is_running)
        self.assertEqual(self.coordinator.dispatcher_count(), 0)

    def test_release_unknown_session_is_noop(self) -> None:
        self.coordinator.release_dispatcher(123)

    def test_transport_swap_detected_and_replaced(self) -> None:
        session = FakeSession(1)
        self.sessions = [session]
        stale = self.coordinator.acquire_dispatcher(session)
        old_transport = session.transport
        session.transport = FakeSerialTransport()
        session.transport.connect(object())
        session.serial_client = session.transport

        health = self.coordinator.session_health(1)
        self.assertTrue(health.transport_changed)

        fresh = self.coordinator.acquire_dispatcher(session)
        self.assertIsNot(fresh, stale)
        self.assertFalse(stale.is_running)
        self.assertFalse(self.coordinator.session_health(1).transport_changed)
        self.coordinator.release_dispatcher(1)

    def test_shutdown_stops_everything(self) -> None:
        first = FakeSession(1)
        second = FakeSession(2)
        self.sessions = [first, second]
        dispatcher_one = self.coordinator.acquire_dispatcher(first)
        dispatcher_two = self.coordinator.acquire_dispatcher(second)
        self.coordinator.shutdown()
        self.assertFalse(dispatcher_one.is_running)
        self.assertFalse(dispatcher_two.is_running)
        self.assertEqual(self.coordinator.dispatcher_count(), 0)

    def test_refresh_control_panels_notifies_tabs(self) -> None:
        self.control_panels = [FakeControlPanelTab(), FakeControlPanelTab()]
        self.coordinator.refresh_control_panels()
        self.assertEqual([tab.refresh_count for tab in self.control_panels], [1, 1])

    def test_populate_bind_menu_lists_sessions(self) -> None:
        self.sessions = [FakeSession(1), FakeSession(2, connected=False)]
        menu = QMenu()
        chosen: list[int] = []
        self.coordinator.populate_bind_menu(menu, chosen.append)
        actions = menu.actions()
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0].text(), "Terminal 1 · Serial")
        self.assertEqual(actions[1].text(), "Terminal 2 · Serial (disconnected)")
        self.assertTrue(actions[1].isEnabled())
        actions[1].trigger()
        self.assertEqual(chosen, [2])
        menu.deleteLater()

    def test_populate_bind_menu_empty_state(self) -> None:
        menu = QMenu()
        self.coordinator.populate_bind_menu(menu, lambda _session_id: None)
        actions = menu.actions()
        self.assertEqual(len(actions), 1)
        self.assertFalse(actions[0].isEnabled())
        self.assertEqual(actions[0].text(), "No terminal tabs open")
        menu.deleteLater()


if __name__ == "__main__":
    unittest.main()
