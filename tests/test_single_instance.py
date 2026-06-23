"""Tests for the single-instance file forwarding (``ComPort_Zone.single_instance``).

A ``.cpz`` double-clicked while an instance is running should be handed to that
instance over a Qt local socket rather than launching a second process. These tests
exercise the forward → listener round-trip in-process.
"""

from __future__ import annotations

import os
import threading
import unittest
from uuid import uuid4

from PySide6.QtNetwork import QLocalServer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ComPort_Zone.single_instance import (
    SingleInstanceServer,
    default_instance_key,
    forward_open_request,
)


class SingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        # A unique name per test so concurrent/leftover sockets never collide.
        self.key = f"ComPortZone-test-{os.getpid()}-{uuid4().hex}"
        self.server: SingleInstanceServer | None = None

    def tearDown(self) -> None:
        if self.server is not None:
            self.server.close()
        QLocalServer.removeServer(self.key)

    def _pump_until(self, predicate, timeout_ms: int = 2000) -> None:
        waited = 0
        while waited < timeout_ms and not predicate():
            QTest.qWait(20)
            waited += 20

    def test_forward_delivers_paths_to_listener(self) -> None:
        received: list[list[str]] = []
        self.server = SingleInstanceServer()
        self.assertTrue(self.server.listen(self.key))
        self.server.openRequested.connect(lambda paths: received.append(paths))

        # Forwarding is inherently cross-process: a QLocalSocket write only completes
        # once the *server* reads it, which can't happen on the same thread. Run the
        # client on a worker thread while the main thread pumps the server's event loop
        # — the same independent-loops arrangement two real processes have.
        result: dict[str, bool] = {}

        def do_forward() -> None:
            result["ok"] = forward_open_request(
                self.key, ["C:/scripts/a.cpz", "C:/scripts/b.cpz"]
            )

        worker = threading.Thread(target=do_forward)
        worker.start()
        try:
            self._pump_until(lambda: bool(received))
        finally:
            worker.join(timeout=2)

        self.assertTrue(result.get("ok"))
        self.assertEqual(received, [["C:/scripts/a.cpz", "C:/scripts/b.cpz"]])

    def test_forward_returns_false_without_listener(self) -> None:
        self.assertFalse(forward_open_request(self.key, ["C:/scripts/a.cpz"]))

    def test_forward_empty_is_noop(self) -> None:
        self.assertFalse(forward_open_request(self.key, []))

    def test_second_listen_fails_while_primary_alive(self) -> None:
        self.server = SingleInstanceServer()
        self.assertTrue(self.server.listen(self.key))

        second = SingleInstanceServer()
        try:
            self.assertFalse(second.listen(self.key))
        finally:
            second.close()

    def test_default_key_is_stable_and_nonempty(self) -> None:
        self.assertTrue(default_instance_key())
        self.assertEqual(default_instance_key(), default_instance_key())


if __name__ == "__main__":
    unittest.main()
