import unittest
from pathlib import Path
from queue import Queue
from threading import Event, Thread

from ComPort_Zone.batch import BatchRunSnapshot
from ComPort_Zone.models import QuickCommand, SerialProfile
from ComPort_Zone.serial_core import SerialEvent
from ComPort_Zone.terminal_session_controller import TerminalSessionController


class FakeTransport:
    def __init__(self) -> None:
        self.events: Queue[SerialEvent] = Queue()
        self.connected = False
        self.reconnecting = False
        self.connected_profiles: list[SerialProfile] = []
        self.sent_text: list[tuple[str, str | None]] = []
        self.sent_bytes: list[bytes] = []
        self.disconnected = False
        self.subscribers: list[Queue[SerialEvent]] = []

    @property
    def is_connected(self) -> bool:
        return self.connected

    @property
    def is_reconnecting(self) -> bool:
        return self.reconnecting

    def list_endpoints(self) -> list[object]:
        return []

    def connect(self, profile) -> bool:
        self.connected = True
        self.connected_profiles.append(profile)
        return True

    def disconnect(self) -> None:
        self.connected = False
        self.reconnecting = False
        self.disconnected = True

    def send_text(self, text: str, line_ending_override: str | None = None, **kwargs) -> None:
        self.sent_text.append((text, line_ending_override))

    def send_bytes(self, data: bytes, **kwargs) -> None:
        self.sent_bytes.append(data)

    def subscribe_monitor(self) -> Queue[SerialEvent]:
        queue: Queue[SerialEvent] = Queue()
        self.subscribers.append(queue)
        return queue

    def unsubscribe_monitor(self, queue: Queue[SerialEvent]) -> None:
        self.subscribers = [subscriber for subscriber in self.subscribers if subscriber is not queue]

    def emit_event(self, event: SerialEvent) -> None:
        self.events.put(event)
        for subscriber in list(self.subscribers):
            subscriber.put(event)


def make_controller(transport: FakeTransport | None = None) -> TerminalSessionController:
    return TerminalSessionController(
        SerialProfile(port="COM9", baudrate=57600),
        history_commands=["status"],
        parameter_prompt=lambda _name, _line_number, _line_text: "prompted",
        transport=transport or FakeTransport(),  # type: ignore[arg-type]
    )


class TerminalSessionControllerTests(unittest.TestCase):
    def test_send_input_records_text_and_hex_payloads(self) -> None:
        transport = FakeTransport()
        controller = make_controller(transport)
        recorded: list[str] = []

        self.assertTrue(
            controller.send_input(
                " status \n read ",
                "Text",
                record_command=recorded.append,
            )
        )
        controller.send_input("AA 55", "Hex Bytes", record_command=recorded.append)

        self.assertEqual(transport.sent_text, [("status", None), ("read", None)])
        self.assertEqual(transport.sent_bytes, [bytes.fromhex("AA55")])
        self.assertEqual(recorded, ["status \n read", "AA 55"])

    def test_send_quick_command_uses_saved_mode_and_line_ending(self) -> None:
        transport = FakeTransport()
        controller = make_controller(transport)
        recorded: list[str] = []

        controller.send_quick_command(
            QuickCommand(command="*IDN?", send_mode="Text", line_ending_override="LF"),
            record_command=recorded.append,
        )
        controller.send_quick_command(
            QuickCommand(command="AA 00", send_mode="Hex Bytes"),
            record_command=recorded.append,
        )

        self.assertEqual(transport.sent_text, [("*IDN?", "LF")])
        self.assertEqual(transport.sent_bytes, [bytes.fromhex("AA00")])
        self.assertEqual(recorded, ["*IDN?", "AA 00"])

    def test_toggle_connection_handles_connect_and_retry_stop(self) -> None:
        transport = FakeTransport()
        controller = make_controller(transport)
        statuses: list[str] = []
        updates: list[bool] = []
        appended: list[str] = []
        saves: list[str] = []

        controller.toggle_connection(
            open_connection_settings=lambda **_kwargs: statuses.append("settings"),
            set_status=statuses.append,
            update_connection_ui=updates.append,
            append_status=appended.append,
            save_settings=lambda: saves.append("save"),
        )

        self.assertTrue(transport.connected)
        self.assertEqual(transport.connected_profiles[0].port, "COM9")
        self.assertEqual(statuses, ["Connecting to COM9..."])
        self.assertEqual(updates, [True])
        self.assertEqual(saves, ["save"])

        transport.reconnecting = True
        controller.toggle_connection(
            open_connection_settings=lambda **_kwargs: statuses.append("settings"),
            set_status=statuses.append,
            update_connection_ui=updates.append,
            append_status=appended.append,
            save_settings=lambda: saves.append("save"),
        )

        self.assertTrue(transport.disconnected)
        self.assertEqual(appended, ["Auto-reconnect stopped."])
        self.assertEqual(updates[-1], False)

    def test_handle_event_buffers_rx_while_paused_and_flushes_on_resume(self) -> None:
        controller = make_controller()
        rx_event = SerialEvent(kind="rx", message="OK", raw=b"OK")

        paused, pending = controller.toggle_pause()
        decision = controller.handle_event(rx_event)
        resumed, flushed = controller.toggle_pause()

        self.assertTrue(paused)
        self.assertEqual(pending, [])
        self.assertIsNone(decision.event_to_render)
        self.assertEqual(decision.paused_count, 1)
        self.assertFalse(resumed)
        self.assertEqual(flushed, [rx_event])
        self.assertEqual(controller.pending_events, [])

    def test_handle_event_reports_status_and_connection_refresh(self) -> None:
        transport = FakeTransport()
        transport.connected = True
        controller = make_controller(transport)
        event = SerialEvent(kind="error", message="Port failed")

        decision = controller.handle_event(event)

        self.assertIs(decision.event_to_render, event)
        self.assertEqual(decision.status_message, "Port failed")
        self.assertTrue(decision.connection_state)
        self.assertFalse(decision.connection_update_footer)

    def test_handle_connection_event_notifies_batch_runner(self) -> None:
        controller = make_controller()
        notified: list[bool] = []
        controller.batch_runner.notify_connection_state = notified.append  # type: ignore[method-assign]

        decision = controller.handle_event(SerialEvent(kind="connection", message="connected"))

        self.assertTrue(decision.connection_state)
        self.assertEqual(notified, [True])
        self.assertIsNone(decision.event_to_render)

    def test_script_lifecycle_methods_delegate_to_batch_runner(self) -> None:
        controller = make_controller()
        calls: list[str] = []
        controller.batch_runner.pause = lambda: calls.append("pause") or True  # type: ignore[method-assign]
        controller.batch_runner.resume = lambda: calls.append("resume") or True  # type: ignore[method-assign]
        controller.batch_runner.stop = lambda: calls.append("stop")  # type: ignore[method-assign]
        controller.batch_runner.snapshot = lambda: BatchRunSnapshot(  # type: ignore[method-assign]
            is_running=True,
            is_paused=True,
            pause_reason="user",
            can_resume=True,
        )

        self.assertTrue(controller.pause_script())
        self.assertTrue(controller.resume_script())
        controller.stop_script()
        snapshot = controller.script_snapshot()

        self.assertEqual(calls, ["pause", "resume", "stop"])
        self.assertTrue(snapshot.is_paused)
        self.assertEqual(snapshot.pause_reason, "user")

    def test_render_plan_formats_rx_display_modes(self) -> None:
        controller = make_controller()
        event = SerialEvent(kind="rx", message="fallback", raw=b"\xffOK")

        text_plan = controller.render_plan(event, "Text")
        hex_plan = controller.render_plan(event, "Hex")
        combined_plan = controller.render_plan(event, "Text + Hex")
        tx_plan = controller.render_plan(SerialEvent(kind="tx", message="*IDN?"), "Text")
        progress_plan = controller.render_plan(SerialEvent(kind="progress", message="."), "Text")

        self.assertTrue(text_plan.stream_text)
        self.assertEqual(text_plan.message, "\ufffdOK")
        self.assertTrue(hex_plan.stream_text)
        self.assertEqual(hex_plan.message, "FF 4F 4B")
        self.assertEqual(hex_plan.stream_separator, " ")
        self.assertEqual(combined_plan.message, "\ufffdOK\nHEX FF 4F 4B")
        self.assertEqual(tx_plan.prefix, "TX> ")
        self.assertTrue(tx_plan.ensure_line_break)
        self.assertTrue(progress_plan.stream_text)
        self.assertFalse(progress_plan.ensure_line_break)
        self.assertEqual(progress_plan.color_role, "status")
        self.assertEqual(progress_plan.prefix, "SYS ")

    def test_run_script_text_starts_plain_script_and_updates_last_path(self) -> None:
        controller = make_controller()
        started_steps: list[object] = []
        last_paths: list[Path] = []
        controller.batch_runner.start = lambda steps: started_steps.append(steps)  # type: ignore[method-assign]

        result = controller.run_script_text(
            "SEND *IDN?\nWAIT 5\n",
            source_label="C:/scripts/check.txt",
            source_path=Path("C:/scripts/check.txt"),
            collect_parameter_values=lambda _occurrences: self.fail("unexpected parameter prompt"),
            parameter_prompt=lambda _name, _line_number, _line_text: None,
            set_last_script_path=last_paths.append,
        )

        self.assertTrue(result.started)
        self.assertEqual(result.status_text, "Running command file: C:/scripts/check.txt")
        self.assertEqual(last_paths, [Path("C:/scripts")])
        self.assertEqual([step.kind for step in started_steps[0]], ["send", "wait"])

    def test_run_script_text_rejects_replacing_active_script(self) -> None:
        controller = make_controller()
        hold = Event()
        thread = Thread(target=hold.wait, daemon=True)
        thread.start()
        controller.batch_runner._thread = thread
        try:
            result = controller.run_script_text(
                "SEND *IDN?\n",
                collect_parameter_values=lambda _occurrences: self.fail("unexpected parameter prompt"),
                parameter_prompt=lambda _name, _line_number, _line_text: None,
                set_last_script_path=lambda _path: None,
            )

            self.assertFalse(result.started)
            self.assertTrue(result.busy)
            self.assertIn("already running", result.status_text)
        finally:
            hold.set()
            thread.join(timeout=1)

    def test_run_script_text_starts_parameterized_template(self) -> None:
        controller = make_controller()
        started_templates: list[tuple[list[object], object]] = []
        controller.batch_runner.start_template = lambda steps, resolver: started_templates.append((steps, resolver))  # type: ignore[method-assign]

        result = controller.run_script_text(
            "SEND VOLT {{VALUE=3.3}}\n",
            collect_parameter_values=lambda _occurrences: ({"VALUE": "5"}, set()),
            parameter_prompt=lambda _name, _line_number, _line_text: None,
            set_last_script_path=lambda _path: None,
        )

        steps, resolver = started_templates[0]
        self.assertTrue(result.started)
        self.assertEqual(resolver(steps[0].line, steps[0].line_number), "SEND VOLT 5")


if __name__ == "__main__":
    unittest.main()
