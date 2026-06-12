"""Tests for the dashboard poll scheduler and session dispatcher."""

from __future__ import annotations

import threading
import unittest
from queue import Queue

from ComPort_Zone.dashboard_engine import (
    DASHBOARD_TX_SOURCE,
    DISPATCHER_THREAD_NAME,
    POLL_CANCELLED,
    POLL_OK,
    POLL_SEND_ERROR,
    POLL_TIMEOUT,
    ControlRequest,
    ControlResult,
    DashboardPollScheduler,
    PollRequest,
    PollResult,
    PollTrafficJournal,
    SessionPollDispatcher,
)
from ComPort_Zone.dashboard_models import DashboardEntry, ParseRule
from ComPort_Zone.dashboard_parse import CompiledParseRule, MAX_RX_WINDOW_CHARS
from ComPort_Zone.serial_core import SerialEvent

from tests.fakes.fake_serial_transport import FakeSerialTransport


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance_ms(self, milliseconds: float) -> None:
        self.now += milliseconds / 1000


def make_entry(
    entry_id: str,
    *,
    command: str | None = None,
    interval_ms: int = 1000,
    timeout_ms: int = 200,
    send_mode: str = "Text",
    value_type: str = "number",
    enabled: bool = True,
) -> DashboardEntry:
    return DashboardEntry(
        id=entry_id,
        label=entry_id,
        command=command if command is not None else f"READ:{entry_id}?",
        send_mode=send_mode,
        interval_ms=interval_ms,
        timeout_ms=timeout_ms,
        parse=ParseRule(kind="line", value_type=value_type),
        enabled=enabled,
    )


def make_request(
    entry: DashboardEntry,
    result_queue: Queue[PollResult] | None = None,
    dashboard_id: str = "dash",
) -> PollRequest:
    return PollRequest(
        dashboard_id=dashboard_id,
        entry=entry,
        compiled=CompiledParseRule.compile(entry.parse),
        result_queue=result_queue if result_queue is not None else Queue(),
    )


def due_ids(scheduler: DashboardPollScheduler) -> list[str]:
    return [entry.id for entry in scheduler.collect_due()]


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.scheduler = DashboardPollScheduler(clock=self.clock)

    def test_initial_configure_staggers_entries(self) -> None:
        self.scheduler.configure([make_entry("a"), make_entry("b"), make_entry("c")])
        self.assertEqual(due_ids(self.scheduler), ["a"])
        self.clock.advance_ms(25)
        self.assertEqual(due_ids(self.scheduler), ["b"])
        self.clock.advance_ms(25)
        self.assertEqual(due_ids(self.scheduler), ["c"])

    def test_not_due_before_interval(self) -> None:
        self.scheduler.configure([make_entry("a", interval_ms=1000)])
        self.scheduler.collect_due()
        self.scheduler.complete("a")
        self.clock.advance_ms(999)
        self.assertEqual(due_ids(self.scheduler), [])

    def test_due_exactly_at_boundary(self) -> None:
        self.scheduler.configure([make_entry("a", interval_ms=1000)])
        self.scheduler.collect_due()
        self.scheduler.complete("a")
        self.clock.advance_ms(1000)
        self.assertEqual(due_ids(self.scheduler), ["a"])

    def test_in_flight_suppression(self) -> None:
        self.scheduler.configure([make_entry("a")])
        self.assertEqual(due_ids(self.scheduler), ["a"])
        self.clock.advance_ms(5000)
        self.assertEqual(due_ids(self.scheduler), [])

    def test_fixed_delay_reschedules_from_completion(self) -> None:
        self.scheduler.configure([make_entry("a", interval_ms=1000)])
        self.scheduler.collect_due()
        # Slow device: the transaction takes 2.5 s. No backlog builds up;
        # the next poll lands one interval after completion.
        self.clock.advance_ms(2500)
        self.scheduler.complete("a")
        self.assertEqual(due_ids(self.scheduler), [])
        self.clock.advance_ms(999)
        self.assertEqual(due_ids(self.scheduler), [])
        self.clock.advance_ms(1)
        self.assertEqual(due_ids(self.scheduler), ["a"])

    def test_skip_retries_next_tick(self) -> None:
        self.scheduler.configure([make_entry("a")])
        self.assertEqual(due_ids(self.scheduler), ["a"])
        self.scheduler.skip("a")
        self.assertEqual(due_ids(self.scheduler), ["a"])

    def test_pause_blocks_collect_due(self) -> None:
        self.scheduler.configure([make_entry("a")])
        self.scheduler.set_paused("connection", True)
        self.assertEqual(due_ids(self.scheduler), [])

    def test_resume_requires_clearing_all_reasons(self) -> None:
        self.scheduler.configure([make_entry("a")])
        self.scheduler.set_paused("connection", True)
        self.scheduler.set_paused("user", True)
        self.scheduler.set_paused("connection", False)
        self.assertEqual(due_ids(self.scheduler), [])
        self.assertEqual(self.scheduler.paused_reasons, frozenset({"user"}))
        self.scheduler.set_paused("user", False)
        self.assertEqual(due_ids(self.scheduler), ["a"])

    def test_resume_restaggers_overdue_entries(self) -> None:
        self.scheduler.configure([make_entry("a"), make_entry("b"), make_entry("c")])
        self.scheduler.set_paused("connection", True)
        self.clock.advance_ms(60_000)
        self.scheduler.set_paused("connection", False)
        self.assertEqual(due_ids(self.scheduler), ["a"])
        self.clock.advance_ms(25)
        self.assertEqual(due_ids(self.scheduler), ["b"])
        self.clock.advance_ms(25)
        self.assertEqual(due_ids(self.scheduler), ["c"])

    def test_unknown_pause_reason_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.scheduler.set_paused("coffee", True)

    def test_configure_preserves_unchanged_entries(self) -> None:
        entry = make_entry("a", interval_ms=1000)
        self.scheduler.configure([entry])
        self.scheduler.collect_due()
        self.scheduler.complete("a")
        self.scheduler.configure([make_entry("a", interval_ms=1000)])
        self.assertEqual(due_ids(self.scheduler), [])
        self.clock.advance_ms(1000)
        self.assertEqual(due_ids(self.scheduler), ["a"])

    def test_configure_resets_changed_interval(self) -> None:
        self.scheduler.configure([make_entry("a", interval_ms=1000)])
        self.scheduler.collect_due()
        self.scheduler.complete("a")
        self.scheduler.configure([make_entry("a", interval_ms=250)])
        self.assertEqual(due_ids(self.scheduler), ["a"])

    def test_configure_drops_removed_entries(self) -> None:
        self.scheduler.configure([make_entry("a"), make_entry("b")])
        self.scheduler.configure([make_entry("b")])
        self.clock.advance_ms(1000)
        self.assertEqual(due_ids(self.scheduler), ["b"])

    def test_configure_preserves_in_flight(self) -> None:
        self.scheduler.configure([make_entry("a")])
        self.scheduler.collect_due()
        self.scheduler.configure([make_entry("a")])
        self.clock.advance_ms(5000)
        self.assertEqual(due_ids(self.scheduler), [])
        self.scheduler.complete("a")
        self.clock.advance_ms(1000)
        self.assertEqual(due_ids(self.scheduler), ["a"])

    def test_disabled_entries_never_due(self) -> None:
        self.scheduler.configure([make_entry("a", enabled=False)])
        self.clock.advance_ms(10_000)
        self.assertEqual(due_ids(self.scheduler), [])

    def test_release_all_in_flight(self) -> None:
        self.scheduler.configure([make_entry("a")])
        self.scheduler.collect_due()
        self.scheduler.release_all_in_flight()
        self.assertEqual(due_ids(self.scheduler), ["a"])

    def test_complete_unknown_id_is_noop(self) -> None:
        self.scheduler.complete("ghost")
        self.scheduler.skip("ghost")

    def test_on_connect_never_time_due(self) -> None:
        entry = make_entry("a")
        entry.poll_mode = "on_connect"
        self.scheduler.configure([entry])
        self.clock.advance_ms(3_600_000)
        self.assertEqual(due_ids(self.scheduler), [])

    def test_trigger_now_arms_on_connect_entry_once(self) -> None:
        entry = make_entry("a")
        entry.poll_mode = "on_connect"
        self.scheduler.configure([entry])
        self.assertTrue(self.scheduler.trigger_now("a"))
        self.assertEqual(due_ids(self.scheduler), ["a"])
        # Completion re-arms to "never": no follow-up poll.
        self.scheduler.complete("a")
        self.clock.advance_ms(3_600_000)
        self.assertEqual(due_ids(self.scheduler), [])

    def test_trigger_now_respects_in_flight_and_disabled(self) -> None:
        entry = make_entry("a")
        self.scheduler.configure([entry])
        self.scheduler.collect_due()  # in flight
        self.assertFalse(self.scheduler.trigger_now("a"))
        disabled = make_entry("b", enabled=False)
        self.scheduler.configure([disabled])
        self.assertFalse(self.scheduler.trigger_now("b"))
        self.assertFalse(self.scheduler.trigger_now("ghost"))

    def test_trigger_now_on_interval_entry_polls_immediately_then_fixed_delay(self) -> None:
        self.scheduler.configure([make_entry("a", interval_ms=1000)])
        self.scheduler.collect_due()
        self.scheduler.complete("a")  # next due in 1 s
        self.assertTrue(self.scheduler.trigger_now("a"))
        self.assertEqual(due_ids(self.scheduler), ["a"])
        self.scheduler.complete("a")
        self.clock.advance_ms(999)
        self.assertEqual(due_ids(self.scheduler), [])
        self.clock.advance_ms(1)
        self.assertEqual(due_ids(self.scheduler), ["a"])

    def test_trigger_now_delay_staggers(self) -> None:
        first = make_entry("a")
        second = make_entry("b")
        first.poll_mode = "on_connect"
        second.poll_mode = "on_connect"
        self.scheduler.configure([first, second])
        self.scheduler.trigger_now("a", delay_s=0.0)
        self.scheduler.trigger_now("b", delay_s=0.025)
        self.assertEqual(due_ids(self.scheduler), ["a"])
        self.clock.advance_ms(25)
        self.assertEqual(due_ids(self.scheduler), ["b"])

    def test_restagger_subset_spaces_only_given_ids(self) -> None:
        self.scheduler.configure([make_entry("a"), make_entry("b"), make_entry("c")])
        self.scheduler.set_paused("user", True)
        self.clock.advance_ms(60_000)
        # Manually restagger only a and c (e.g. one session's entries).
        self.scheduler.set_paused("user", False)
        # All were restaggered on resume; force them overdue again:
        self.clock.advance_ms(60_000)
        self.scheduler.restagger(["a", "c"])
        due = due_ids(self.scheduler)
        # b stayed overdue (due immediately); a is due now; c is +25ms.
        self.assertIn("a", due)
        self.assertIn("b", due)
        self.assertNotIn("c", due)
        self.clock.advance_ms(25)
        self.assertEqual(due_ids(self.scheduler), ["c"])

    def test_configure_poll_mode_change_resets_slot(self) -> None:
        entry = make_entry("a", interval_ms=1000)
        self.scheduler.configure([entry])
        self.scheduler.collect_due()
        self.scheduler.complete("a")
        switched = make_entry("a", interval_ms=1000)
        switched.poll_mode = "on_connect"
        self.scheduler.configure([switched])
        self.clock.advance_ms(3_600_000)
        self.assertEqual(due_ids(self.scheduler), [])


class ExplodingTransport(FakeSerialTransport):
    def send_text(
        self, text: str, line_ending_override: str | None = None, *, source: str = ""
    ) -> None:
        raise RuntimeError("port gone")


class ScriptedTransport(FakeSerialTransport):
    """Delivers a scripted list of SerialEvents to subscribers on send.

    The engine drains stale RX immediately before sending, so events
    staged into the subscriber queue ahead of the transaction would be
    discarded; scripting them onto the send call models a device that
    responds to the command, deterministically and without sleeps.
    """

    def __init__(self) -> None:
        super().__init__()
        self.scripted_events: list[SerialEvent] = []

    def _deliver_next_response(self) -> None:
        events, self.scripted_events = self.scripted_events, []
        for event in events:
            for subscriber in self._subscribers:
                subscriber.put(event)


class PollTrafficJournalTests(unittest.TestCase):
    @staticmethod
    def _now():
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).astimezone()

    def test_open_window_covers_now(self) -> None:
        journal = PollTrafficJournal()
        self.assertFalse(journal.covers(self._now()))
        journal.open_window()
        self.assertTrue(journal.covers(self._now()))

    def test_closed_window_keeps_grace_tail(self) -> None:
        from datetime import timedelta

        journal = PollTrafficJournal()
        journal.open_window()
        journal.close_window()
        self.assertTrue(journal.covers(self._now()))  # inside the grace tail
        late = self._now() + timedelta(seconds=PollTrafficJournal.GRACE_S + 1)
        self.assertFalse(journal.covers(late))

    def test_timestamp_before_window_not_covered(self) -> None:
        from datetime import timedelta

        before = self._now() - timedelta(seconds=1)
        journal = PollTrafficJournal()
        journal.open_window()
        self.assertFalse(journal.covers(before))

    def test_window_history_is_bounded(self) -> None:
        journal = PollTrafficJournal()
        for _ in range(100):
            journal.open_window()
            journal.close_window()
        self.assertLessEqual(len(journal._windows), PollTrafficJournal._KEEP_CLOSED)


class DispatcherTransactionTests(unittest.TestCase):
    """Threadless tests driving _execute_transaction synchronously."""

    def setUp(self) -> None:
        self.fake = FakeSerialTransport()
        self.fake.connect(object())
        self.dispatcher = SessionPollDispatcher(transport=self.fake)
        self.rx_queue = self.fake.subscribe_events()

    def test_successful_transaction(self) -> None:
        self.fake.queue_response(b"13.2\r\n")
        result = self.dispatcher._execute_transaction(make_request(make_entry("a")), self.rx_queue)
        self.assertEqual(result.status, POLL_OK)
        assert result.outcome is not None
        self.assertEqual(result.outcome.value_number, 13.2)
        self.assertEqual(self.fake.sent_text, [("READ:a?", None)])

    def test_sends_are_tagged_with_dashboard_source(self) -> None:
        self.fake.queue_response(b"1\r\n")
        self.dispatcher._execute_transaction(make_request(make_entry("a")), self.rx_queue)
        self.assertEqual(self.fake.sent_sources, [DASHBOARD_TX_SOURCE])

    def test_transaction_opens_and_closes_journal_window(self) -> None:
        from datetime import datetime, timedelta, timezone

        journal = self.dispatcher.traffic_journal
        self.fake.queue_response(b"1\r\n")
        before = datetime.now(timezone.utc).astimezone()
        self.dispatcher._execute_transaction(make_request(make_entry("a")), self.rx_queue)
        # RX that arrived during the transaction is covered...
        self.assertTrue(journal.covers(before + timedelta(milliseconds=1)))
        # ...and the window was closed, so far-future RX is not.
        far = datetime.now(timezone.utc).astimezone() + timedelta(seconds=60)
        self.assertFalse(journal.covers(far))

    def test_journal_closed_even_on_send_error(self) -> None:
        from datetime import datetime, timedelta, timezone

        exploding = ExplodingTransport()
        exploding.connect(object())
        dispatcher = SessionPollDispatcher(transport=exploding)
        rx_queue = exploding.subscribe_events()
        dispatcher._execute_transaction(make_request(make_entry("a")), rx_queue)
        far = datetime.now(timezone.utc).astimezone() + timedelta(seconds=60)
        self.assertFalse(dispatcher.traffic_journal.covers(far))

    def test_line_ending_override_passed_through(self) -> None:
        entry = make_entry("a")
        entry.line_ending_override = "LF"
        self.fake.queue_response(b"1\r\n")
        self.dispatcher._execute_transaction(make_request(entry), self.rx_queue)
        self.assertEqual(self.fake.sent_text, [("READ:a?", "LF")])

    def test_timeout_with_no_response(self) -> None:
        entry = make_entry("a", timeout_ms=60)
        result = self.dispatcher._execute_transaction(make_request(entry), self.rx_queue)
        self.assertEqual(result.status, POLL_TIMEOUT)
        self.assertIsNone(result.outcome)

    def test_stale_rx_drained_before_send(self) -> None:
        self.rx_queue.put(SerialEvent(kind="rx", message="99.9\r\n"))
        self.fake.queue_response(b"13.2\r\n")
        result = self.dispatcher._execute_transaction(make_request(make_entry("a")), self.rx_queue)
        assert result.outcome is not None
        self.assertEqual(result.outcome.value_number, 13.2)

    def test_non_rx_events_ignored_in_window(self) -> None:
        scripted = ScriptedTransport()
        scripted.connect(object())
        dispatcher = SessionPollDispatcher(transport=scripted)
        rx_queue = scripted.subscribe_events()
        scripted.scripted_events = [
            SerialEvent(kind="status", message="noise"),
            SerialEvent(kind="rx", message="42\r\n"),
        ]
        result = dispatcher._execute_transaction(make_request(make_entry("a", timeout_ms=300)), rx_queue)
        self.assertEqual(result.status, POLL_OK)
        assert result.outcome is not None
        self.assertEqual(result.outcome.value_number, 42.0)

    def test_send_error_reported(self) -> None:
        exploding = ExplodingTransport()
        exploding.connect(object())
        dispatcher = SessionPollDispatcher(transport=exploding)
        rx_queue = exploding.subscribe_events()
        result = dispatcher._execute_transaction(make_request(make_entry("a")), rx_queue)
        self.assertEqual(result.status, POLL_SEND_ERROR)
        self.assertIn("port gone", result.error)

    def test_hex_entry_sends_bytes(self) -> None:
        entry = make_entry("a", command="AB CD", send_mode="Hex Bytes")
        self.fake.queue_response(b"OK\r\n")
        entry.parse = ParseRule(kind="line", value_type="text")
        result = self.dispatcher._execute_transaction(make_request(entry), self.rx_queue)
        self.assertEqual(result.status, POLL_OK)
        self.assertEqual(self.fake.sent_bytes, [b"\xab\xcd"])

    def test_invalid_hex_is_send_error(self) -> None:
        entry = make_entry("a", command="XYZ", send_mode="Hex Bytes", timeout_ms=100)
        result = self.dispatcher._execute_transaction(make_request(entry), self.rx_queue)
        self.assertEqual(result.status, POLL_SEND_ERROR)
        self.assertIn("HEX", result.error)

    def test_window_is_capped_during_flood(self) -> None:
        scripted = ScriptedTransport()
        scripted.connect(object())
        dispatcher = SessionPollDispatcher(transport=scripted)
        rx_queue = scripted.subscribe_events()
        entry = make_entry("a", timeout_ms=500)
        entry.parse = ParseRule(kind="regex", pattern=r"V=([\d.]+)", group=1, value_type="number")
        scripted.scripted_events = [
            SerialEvent(kind="rx", message="noise " * 200) for _ in range(10)
        ] + [SerialEvent(kind="rx", message="V=13.2\r\n")]
        result = dispatcher._execute_transaction(make_request(entry), rx_queue)
        self.assertEqual(result.status, POLL_OK)
        assert result.outcome is not None
        self.assertEqual(result.outcome.value_number, 13.2)
        self.assertLessEqual(len(result.raw_window), MAX_RX_WINDOW_CHARS)


def make_control_request(
    entry_id: str = "ctl",
    command: str = "OUTP ON",
    results: Queue | None = None,
    dashboard_id: str = "dash",
    send_mode: str = "Text",
) -> ControlRequest:
    return ControlRequest(
        dashboard_id=dashboard_id,
        entry_id=entry_id,
        command=command,
        send_mode=send_mode,
        result_queue=results if results is not None else Queue(),
    )


class ControlExecutionTests(unittest.TestCase):
    """Threadless tests driving _execute_control synchronously."""

    def setUp(self) -> None:
        self.fake = FakeSerialTransport()
        self.fake.connect(object())
        self.dispatcher = SessionPollDispatcher(transport=self.fake)

    def test_control_send_ok(self) -> None:
        result = self.dispatcher._execute_control(make_control_request())
        self.assertEqual(result.status, POLL_OK)
        self.assertEqual(self.fake.sent_text, [("OUTP ON", None)])
        self.assertEqual(self.fake.sent_sources, [DASHBOARD_TX_SOURCE])

    def test_control_hex_send(self) -> None:
        request = make_control_request(command="AB CD", send_mode="Hex Bytes")
        result = self.dispatcher._execute_control(request)
        self.assertEqual(result.status, POLL_OK)
        self.assertEqual(self.fake.sent_bytes, [b"\xab\xcd"])

    def test_control_send_error(self) -> None:
        exploding = ExplodingTransport()
        exploding.connect(object())
        dispatcher = SessionPollDispatcher(transport=exploding)
        result = dispatcher._execute_control(make_control_request())
        self.assertEqual(result.status, POLL_SEND_ERROR)
        self.assertIn("port gone", result.error)

    def test_control_opens_and_closes_journal_window(self) -> None:
        from datetime import datetime, timedelta, timezone

        before = datetime.now(timezone.utc).astimezone()
        self.dispatcher._execute_control(make_control_request())
        journal = self.dispatcher.traffic_journal
        self.assertTrue(journal.covers(before + timedelta(milliseconds=1)))
        far = datetime.now(timezone.utc).astimezone() + timedelta(seconds=60)
        self.assertFalse(journal.covers(far))


class DispatcherThreadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeSerialTransport()
        self.fake.connect(object())
        self.dispatcher = SessionPollDispatcher(transport=self.fake)

    def tearDown(self) -> None:
        self.dispatcher.stop()
        names = [thread.name for thread in threading.enumerate()]
        self.assertNotIn(DISPATCHER_THREAD_NAME, names)

    def test_requests_execute_strictly_in_order(self) -> None:
        self.dispatcher.start()
        results: Queue[PollResult] = Queue()
        self.fake.queue_response(b"1\r\n")
        self.fake.queue_response(b"2\r\n")
        first = make_request(make_entry("a", command="CMD1"), results)
        second = make_request(make_entry("b", command="CMD2"), results)
        self.assertTrue(self.dispatcher.submit(first))
        self.assertTrue(self.dispatcher.submit(second))
        outcomes = [results.get(timeout=1.0), results.get(timeout=1.0)]
        self.assertEqual([result.status for result in outcomes], [POLL_OK, POLL_OK])
        self.assertEqual([result.entry_id for result in outcomes], ["a", "b"])
        self.assertEqual(self.fake.sent_text, [("CMD1", None), ("CMD2", None)])

    def test_submit_rejected_when_not_running(self) -> None:
        self.assertFalse(self.dispatcher.submit(make_request(make_entry("a"))))

    def test_cancel_dashboard_drops_queued_requests(self) -> None:
        self.dispatcher.start()
        results: Queue[PollResult] = Queue()
        blocker = make_request(make_entry("slow", timeout_ms=200), results, dashboard_id="keep")
        queued = make_request(make_entry("queued"), results, dashboard_id="drop")
        self.assertTrue(self.dispatcher.submit(blocker))
        self.assertTrue(self.dispatcher.submit(queued))
        self.dispatcher.cancel_dashboard("drop")
        by_id = {
            result.entry_id: result.status
            for result in (results.get(timeout=1.0), results.get(timeout=1.0))
        }
        self.assertEqual(by_id["queued"], POLL_CANCELLED)
        self.assertEqual(by_id["slow"], POLL_TIMEOUT)
        # The cancelled dashboard's request was dropped before sending anything.
        self.assertEqual(self.fake.sent_text, [("READ:slow?", None)])

    def test_stop_cancels_in_flight_and_queued(self) -> None:
        self.dispatcher.start()
        results: Queue[PollResult] = Queue()
        in_flight = make_request(make_entry("slow", timeout_ms=2000), results)
        queued = make_request(make_entry("queued"), results)
        self.assertTrue(self.dispatcher.submit(in_flight))
        self.assertTrue(self.dispatcher.submit(queued))
        self.dispatcher.stop(timeout=1.5)
        self.assertFalse(self.dispatcher.is_running)
        statuses = {results.get(timeout=1.0).status, results.get(timeout=1.0).status}
        self.assertEqual(statuses, {POLL_CANCELLED})
        self.assertEqual(self.fake._subscribers, [])

    def test_stop_unsubscribes_event_queue(self) -> None:
        self.dispatcher.start()
        self.assertEqual(len(self.fake._subscribers), 1)
        self.dispatcher.stop()
        self.assertEqual(self.fake._subscribers, [])

    def test_restart_after_stop(self) -> None:
        self.dispatcher.start()
        self.dispatcher.stop()
        self.dispatcher.start()
        self.assertTrue(self.dispatcher.is_running)
        results: Queue[PollResult] = Queue()
        self.fake.queue_response(b"5\r\n")
        self.assertTrue(self.dispatcher.submit(make_request(make_entry("a"), results)))
        self.assertEqual(results.get(timeout=1.0).status, POLL_OK)

    def test_polls_and_controls_share_one_fifo(self) -> None:
        self.dispatcher.start()
        results: Queue = Queue()
        self.fake.queue_response(b"1\r\n")
        self.assertTrue(self.dispatcher.submit(make_request(make_entry("a", command="POLL1"), results)))
        self.assertTrue(self.dispatcher.submit_control(make_control_request(command="CTL", results=results)))
        self.fake.queue_response(b"2\r\n")
        self.assertTrue(self.dispatcher.submit(make_request(make_entry("b", command="POLL2"), results)))
        received = [results.get(timeout=1.0) for _ in range(3)]
        self.assertEqual(
            [type(result).__name__ for result in received],
            ["PollResult", "ControlResult", "PollResult"],
        )
        self.assertEqual(
            self.fake.sent_text,
            [("POLL1", None), ("CTL", None), ("POLL2", None)],
        )

    def test_cancelled_control_is_answered_with_control_result(self) -> None:
        self.dispatcher.start()
        results: Queue = Queue()
        blocker = make_request(make_entry("slow", timeout_ms=200), results, dashboard_id="keep")
        control = make_control_request(results=results, dashboard_id="drop")
        self.assertTrue(self.dispatcher.submit(blocker))
        self.assertTrue(self.dispatcher.submit_control(control))
        self.dispatcher.cancel_dashboard("drop")
        received = [results.get(timeout=1.0) for _ in range(2)]
        control_results = [r for r in received if isinstance(r, ControlResult)]
        self.assertEqual(len(control_results), 1)
        self.assertEqual(control_results[0].status, POLL_CANCELLED)
        # The cancelled control never reached the wire.
        self.assertEqual(self.fake.sent_text, [("READ:slow?", None)])

    def test_stop_flushes_queued_control_as_cancelled(self) -> None:
        self.dispatcher.start()
        results: Queue = Queue()
        blocker = make_request(make_entry("slow", timeout_ms=2000), results)
        control = make_control_request(results=results)
        self.assertTrue(self.dispatcher.submit(blocker))
        self.assertTrue(self.dispatcher.submit_control(control))
        self.dispatcher.stop(timeout=1.5)
        received = [results.get(timeout=1.0) for _ in range(2)]
        statuses = {result.status for result in received}
        self.assertEqual(statuses, {POLL_CANCELLED})
        self.assertTrue(any(isinstance(result, ControlResult) for result in received))


if __name__ == "__main__":
    unittest.main()
