import unittest
from queue import Queue
from threading import Event
from time import perf_counter, sleep

from ComPort_Zone.batch import (
    BatchParseError,
    BatchRunner,
    batch_parameter_input_lines,
    find_batch_parameters,
    evaluate_condition,
    parse_batch_line,
    parse_batch_script,
    parse_batch_template,
    parse_hex_payload,
    resolve_runtime_step,
    substitute_runtime_variables,
    substitute_batch_parameters,
)
from ComPort_Zone.serial_core import SerialEvent


def wait_until(predicate, timeout: float = 1.0) -> bool:
    deadline = perf_counter() + timeout
    while perf_counter() < deadline:
        if predicate():
            return True
        sleep(0.01)
    return predicate()


class RecordingStopEvent:
    def __init__(self) -> None:
        self.wait_calls: list[float] = []

    def wait(self, timeout: float) -> bool:
        self.wait_calls.append(timeout)
        return False

    def is_set(self) -> bool:
        return False


class BatchParserTests(unittest.TestCase):
    def test_parse_batch_script_supports_break_set_and_log(self) -> None:
        steps = parse_batch_script(
            "SET MODE FAST\nLOG Mode=$MODE\nLOOP 2\nBREAK\nENDLOOP"
        )

        self.assertEqual(
            [step.kind for step in steps],
            ["set", "log", "loop", "break", "endloop"],
        )
        self.assertEqual(steps[0].payload, ("MODE", "FAST"))
        self.assertEqual(steps[1].payload, "Mode=$MODE")

    def test_parse_pause_with_optional_message(self) -> None:
        steps = parse_batch_script("PAUSE\nPAUSE Check voltage $VOLTAGE")

        self.assertEqual([step.kind for step in steps], ["pause", "pause"])
        self.assertEqual(steps[0].payload, "")
        self.assertEqual(steps[1].payload, "Check voltage $VOLTAGE")

    def test_parse_variable_actions_with_explicit_and_default_amounts(self) -> None:
        steps = parse_batch_script("volt:increment 1.5\ncurr:DECREMENT")

        self.assertEqual([step.kind for step in steps], ["variable_action", "variable_action"])
        self.assertEqual(steps[0].payload, ("volt", "increment", "1.5"))
        self.assertEqual(steps[1].payload, ("curr", "decrement", "1"))

    def test_variable_actions_reject_invalid_static_amounts(self) -> None:
        for line in ("volt:increment nope", "volt:decrement -1", "volt:increment NaN"):
            with self.subTest(line=line), self.assertRaises(BatchParseError):
                parse_batch_script(line)

    def test_break_must_be_inside_loop(self) -> None:
        with self.assertRaises(BatchParseError) as context:
            parse_batch_script("IF 1 == 1\nBREAK\nENDIF")

        self.assertEqual(context.exception.line_number, 2)
        self.assertIn("inside a LOOP", str(context.exception))

    def test_break_set_and_log_reject_malformed_syntax(self) -> None:
        for line in ("BREAK now", "SET NAME", "SET 1NAME value", "LOG"):
            with self.subTest(line=line), self.assertRaises(BatchParseError):
                parse_batch_script(line)

    def test_parse_batch_script_supports_capture(self) -> None:
        step = parse_batch_script(r"CAPTURE VOLTAGE REGEX VOLT:\s*([0-9.]+)\s+V")[0]

        self.assertEqual(step.kind, "capture")
        self.assertEqual(step.payload, ("VOLTAGE", r"VOLT:\s*([0-9.]+)\s+V"))

    def test_parse_batch_script_rejects_invalid_capture_regex(self) -> None:
        with self.assertRaises(BatchParseError):
            parse_batch_script("CAPTURE VALUE REGEX ([0-9]+")

    def test_runtime_variable_substitution_supports_escape_and_missing_error(self) -> None:
        self.assertEqual(
            substitute_runtime_variables("SET $VALUE $$LITERAL", {"VALUE": "12.5"}, 1),
            "SET 12.5 $LITERAL",
        )
        with self.assertRaises(BatchParseError):
            substitute_runtime_variables("SET $MISSING", {}, 4)

    def test_capture_regex_is_revalidated_after_runtime_substitution(self) -> None:
        step = parse_batch_line(r"CAPTURE SECOND REGEX $FIRST", 7)

        with self.assertRaises(BatchParseError) as context:
            resolve_runtime_step(step, {"FIRST": "("})

        self.assertEqual(context.exception.line_number, 7)
        self.assertIn("after variable substitution", str(context.exception))

    def test_parse_batch_script_supports_condition_blocks(self) -> None:
        steps = parse_batch_script("IF 12.5 > 10\nSEND high\nELSE\nSEND low\nENDIF")

        self.assertEqual([step.kind for step in steps], ["if", "send", "else", "send", "endif"])
        self.assertEqual(steps[0].payload, ("12.5", ">", "10"))

    def test_condition_evaluator_supports_numeric_and_text_operators(self) -> None:
        self.assertTrue(evaluate_condition("12.0", "==", "12"))
        self.assertTrue(evaluate_condition("12.5", ">", "12"))
        self.assertTrue(evaluate_condition('"DEVICE READY"', "CONTAINS", "READY"))
        self.assertTrue(evaluate_condition("ERROR", "NOT CONTAINS", "READY"))
        self.assertFalse(evaluate_condition("FAST", "==", "SLOW"))
        with self.assertRaises(ValueError):
            evaluate_condition("FAST", ">", "SLOW")

    def test_condition_parser_ignores_operators_inside_quoted_operands(self) -> None:
        cases = (
            ('IF "A > B" == "A > B"', ('"A > B"', "==", '"A > B"')),
            (
                "IF 'X CONTAINS Y' == 'X CONTAINS Y'",
                ("'X CONTAINS Y'", "==", "'X CONTAINS Y'"),
            ),
            ('IF "ALPHA CONTAINS BETA" CONTAINS "BETA"', ('"ALPHA CONTAINS BETA"', "CONTAINS", '"BETA"')),
            ('IF "ALPHA > BETA" NOT CONTAINS "GAMMA"', ('"ALPHA > BETA"', "NOT CONTAINS", '"GAMMA"')),
        )

        for line, expected in cases:
            with self.subTest(line=line):
                self.assertEqual(parse_batch_line(line, 1).payload, expected)

    def test_parse_batch_script_rejects_unmatched_condition_markers(self) -> None:
        for script, line_number in (("IF 1 == 1\nSEND ping", 1), ("SEND ping\nELSE", 2), ("ENDIF", 1)):
            with self.assertRaises(BatchParseError) as context:
                parse_batch_script(script)
            self.assertEqual(context.exception.line_number, line_number)

    def test_parse_batch_script_rejects_crossed_control_blocks(self) -> None:
        with self.assertRaises(BatchParseError) as context:
            parse_batch_script("LOOP 2\nIF 1 == 1\nENDLOOP\nENDIF")
        self.assertEqual(context.exception.line_number, 3)
        self.assertIn("currently open IF", str(context.exception))

    def test_parse_batch_script_supports_finite_and_forever_loops(self) -> None:
        steps = parse_batch_script("LOOP 3\nSEND ping\nENDLOOP\nLOOP FOREVER\nWAIT 1\nENDLOOP")

        self.assertEqual([step.kind for step in steps], ["loop", "send", "endloop", "loop", "wait", "endloop"])
        self.assertEqual(steps[0].payload, 3)
        self.assertIsNone(steps[3].payload)

    def test_parse_batch_script_rejects_unmatched_loop_markers(self) -> None:
        for script, line_number in (("LOOP 2\nSEND ping", 1), ("SEND ping\nENDLOOP", 2)):
            with self.assertRaises(BatchParseError) as context:
                parse_batch_script(script)
            self.assertEqual(context.exception.line_number, line_number)

    def test_parse_batch_script_rejects_invalid_loop_count(self) -> None:
        for script in ("LOOP 0\nENDLOOP", "LOOP many\nENDLOOP"):
            with self.assertRaises(BatchParseError):
                parse_batch_script(script)

    def test_parse_batch_script_supports_wait_send_hex_and_plain_lines(self) -> None:
        steps = parse_batch_script(
            "\n".join(
                [
                    "# comment",
                    "// C-style comment",
                    "SEND version",
                    "WAIT 250 // pause before payload",
                    "EXPECT ComPort Zone",
                    "HEX 55 AA 01 0D // wake bytes",
                    "reset // plain command",
                ]
            )
        )
        self.assertEqual([step.kind for step in steps], ["send", "wait", "expect", "hex", "send"])
        self.assertEqual(steps[0].payload, "version")
        self.assertEqual(steps[1].payload, 250)
        self.assertEqual(steps[2].payload, "ComPort Zone")
        self.assertEqual(steps[3].payload, bytes.fromhex("55AA010D"))
        self.assertEqual(steps[4].payload, "reset")

    def test_parse_batch_script_rejects_odd_hex_length(self) -> None:
        with self.assertRaises(BatchParseError) as context:
            parse_batch_script("HEX ABC")
        self.assertEqual(context.exception.line_number, 1)

    def test_parse_settings_directives(self) -> None:
        steps = parse_batch_script(
            "@@wait 100\n@@expect-timeout 2000\n@@on-error continue\n@@send-mode hex"
        )
        self.assertEqual([step.kind for step in steps], ["setting"] * 4)
        self.assertEqual(steps[0].payload, ("wait", 100))
        self.assertEqual(steps[1].payload, ("expect-timeout", 2000))
        self.assertEqual(steps[2].payload, ("on-error", "continue"))
        self.assertEqual(steps[3].payload, ("send-mode", "hex"))

    def test_parse_setting_name_is_case_insensitive(self) -> None:
        self.assertEqual(parse_batch_script("@@WAIT 5")[0].payload, ("wait", 5))

    def test_parse_rejects_unknown_and_malformed_settings(self) -> None:
        for bad in (
            "@@nope 1",
            "@@wait -1",
            "@@wait abc",
            "@@expect-timeout 0",
            "@@send-mode sideways",
        ):
            with self.assertRaises(BatchParseError, msg=bad):
                parse_batch_script(bad)

    def test_parse_hex_payload_accepts_spaces_commas_and_prefixes(self) -> None:
        payload = parse_hex_payload("0xAA, 55 01-0D")
        self.assertEqual(payload, bytes.fromhex("AA55010D"))

    def test_batch_parameters_report_first_line_that_needs_input(self) -> None:
        script = "\n".join(
            [
                "VOLT {{VOLT_VALUE}}",
                "CURR {{CURR_VALUE=1.5}}",
                "READ {{VOLT_VALUE}} {{MODE}}",
                "MODE {{MODE}}",
            ]
        )

        occurrences = find_batch_parameters(script)
        self.assertEqual([occ.name for occ in occurrences], ["VOLT_VALUE", "CURR_VALUE", "VOLT_VALUE", "MODE", "MODE"])

        prompt_lines = batch_parameter_input_lines(script)
        self.assertEqual([line.line_number for line in prompt_lines], [1, 3])
        self.assertEqual(prompt_lines[0].parameters, ("VOLT_VALUE",))
        self.assertEqual(prompt_lines[1].parameters, ("MODE",))

    def test_substitute_batch_parameters_uses_defaults_and_reuses_first_input(self) -> None:
        values: dict[str, str] = {}
        prompts: list[str] = []

        def prompt(name: str, line_number: int, line_text: str) -> str:
            prompts.append(f"{line_number}:{name}:{line_text}")
            return "12.5"

        first = substitute_batch_parameters("VOLT {{VOLT_VALUE}}", values, prompt, 1)
        second = substitute_batch_parameters("READ {{VOLT_VALUE}} {{MODE=FAST}}", values, prompt, 2)

        self.assertEqual(first, "VOLT 12.5")
        self.assertEqual(second, "READ 12.5 FAST")
        self.assertEqual(prompts, ["1:VOLT_VALUE:VOLT {{VOLT_VALUE}}"])

    def test_substitute_batch_parameters_can_ignore_deleted_default(self) -> None:
        values: dict[str, str] = {}
        prompts: list[str] = []

        def prompt(name: str, line_number: int, line_text: str) -> str:
            prompts.append(name)
            return "25"

        line = substitute_batch_parameters(
            "WAIT {{DELAY=10}}",
            values,
            prompt,
            1,
            ignored_defaults={"DELAY"},
        )

        self.assertEqual(line, "WAIT 25")
        self.assertEqual(prompts, ["DELAY"])

    def test_parameterized_template_lines_parse_after_substitution(self) -> None:
        template = parse_batch_template("WAIT {{DELAY=5}}\nHEX {{PAYLOAD=55 AA}}\nSEND {{TEXT=go}}")
        values: dict[str, str] = {}
        parsed = [
            parse_batch_line(
                substitute_batch_parameters(step.line, values, lambda *_: None, step.line_number) or "",
                step.line_number,
            )
            for step in template
        ]

        self.assertEqual([step.kind for step in parsed], ["wait", "hex", "send"])
        self.assertEqual(parsed[0].payload, 5)
        self.assertEqual(parsed[1].payload, bytes.fromhex("55AA"))
        self.assertEqual(parsed[2].payload, "go")

    def test_wait_uses_requested_short_delay_without_fixed_minimum(self) -> None:
        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=lambda text, **kw: None,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        stop_event = RecordingStopEvent()
        runner._stop_event = stop_event
        runner._resume_event.set()

        self.assertTrue(runner._sleep_interruptible(0.005))
        self.assertEqual(stop_event.wait_calls, [])

    def test_expect_matches_fragmented_rx_without_consuming_ui_queue(self) -> None:
        output_events: Queue = Queue()
        rx_events: Queue = Queue()
        sent: list[str] = []

        def send_text(text: str, **kw) -> None:
            sent.append(text)
            rx_events.put_nowait(SerialEvent(kind="rx", message="Com"))
            rx_events.put_nowait(SerialEvent(kind="rx", message="Port Zone"))

        runner = BatchRunner(
            emit_event=output_events.put_nowait,
            send_text=send_text,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._rx_event_queue = rx_events
        runner._resume_event.set()

        runner._run_steps(parse_batch_script("SEND *IDN?\nEXPECT ComPort Zone"))

        self.assertEqual(sent, ["*IDN?"])
        events = [output_events.get_nowait() for _ in range(output_events.qsize())]
        messages = [event.message for event in events]
        self.assertFalse(any(message.startswith("EXPECT matched") for message in messages))
        self.assertIn("Batch run completed.", messages)

    def test_expect_ignores_control_panel_poll_rx(self) -> None:
        # A resumed control panel may poll during a command file; its replies
        # (source="control_panel") must never satisfy/pollute an EXPECT.
        output_events: Queue = Queue()
        rx_events: Queue = Queue()

        def send_text(text: str, **kw) -> None:
            rx_events.put_nowait(
                SerialEvent(kind="rx", message="ComPort Zone", source="control_panel")
            )
            rx_events.put_nowait(SerialEvent(kind="rx", message="unrelated"))

        runner = BatchRunner(
            emit_event=output_events.put_nowait,
            send_text=send_text,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
            expect_timeout_ms=80,
        )
        runner._rx_event_queue = rx_events
        runner._resume_event.set()

        runner._run_steps(parse_batch_script("SEND *IDN?\nEXPECT ComPort Zone"))

        messages = [output_events.get_nowait().message for _ in range(output_events.qsize())]
        self.assertTrue(any(m.startswith("EXPECT timed out") for m in messages))
        self.assertNotIn("EXPECT matched on line 2: ComPort Zone", messages)

    def test_expect_times_out_when_response_is_missing(self) -> None:
        output_events: Queue = Queue()
        runner = BatchRunner(
            emit_event=output_events.put_nowait,
            send_text=lambda text, **kw: None,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
            expect_timeout_ms=1,
        )
        runner._rx_event_queue = Queue()
        runner._resume_event.set()

        runner._run_steps(parse_batch_script("SEND *IDN?\nEXPECT missing"))

        messages = [output_events.get_nowait().message for _ in range(output_events.qsize())]
        self.assertTrue(any(message.startswith("EXPECT timed out on line 2") for message in messages))
        self.assertNotIn("Batch run completed.", messages)

    def test_wait_setting_delays_before_each_command(self) -> None:
        sleeps: list[float] = []
        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=lambda text, **kw: None,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()
        runner._sleep_interruptible = lambda seconds: (sleeps.append(seconds) or True)

        runner._run_steps(parse_batch_script("@@wait 50\nSEND a\nSEND b"))

        # The setting step doesn't sleep; each following command does.
        self.assertEqual(sleeps, [0.05, 0.05])

    def test_expect_timeout_setting_overrides_runner_default(self) -> None:
        output_events: Queue = Queue()
        runner = BatchRunner(  # runner default is DEFAULT_EXPECT_TIMEOUT_MS (1000)
            emit_event=output_events.put_nowait,
            send_text=lambda text, **kw: None,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._rx_event_queue = Queue()
        runner._resume_event.set()

        runner._run_steps(parse_batch_script("@@expect-timeout 5\nSEND x\nEXPECT missing"))

        messages = [output_events.get_nowait().message for _ in range(output_events.qsize())]
        self.assertTrue(any("after 5 ms" in message for message in messages))

    def test_on_error_continue_proceeds_after_failed_expect(self) -> None:
        sent: list[str] = []
        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
            expect_timeout_ms=1,
        )
        runner._rx_event_queue = Queue()
        runner._resume_event.set()

        runner._run_steps(parse_batch_script("SEND a\n@@on-error continue\nEXPECT missing\nSEND b"))

        self.assertEqual(sent, ["a", "b"])

    def test_send_mode_hex_routes_bare_lines_to_bytes(self) -> None:
        sent_text: list[str] = []
        sent_bytes: list[bytes] = []
        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=lambda text, **kw: sent_text.append(text),
            send_bytes=lambda data, **kw: sent_bytes.append(data),
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()

        runner._run_steps(parse_batch_script("@@send-mode hex\n55 AA\n@@send-mode text\nhello"))

        self.assertEqual(sent_bytes, [bytes.fromhex("55AA")])
        self.assertEqual(sent_text, ["hello"])

    def test_user_pause_blocks_next_step_until_resume(self) -> None:
        output_events: Queue = Queue()
        first_sent = Event()
        release_first_send = Event()
        sent: list[str] = []

        def send_text(text: str, **kw) -> None:
            sent.append(text)
            if text == "one":
                first_sent.set()
                release_first_send.wait(1)

        runner = BatchRunner(
            emit_event=output_events.put_nowait,
            send_text=send_text,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner.start(parse_batch_script("SEND one\nSEND two"))
        try:
            self.assertTrue(first_sent.wait(1))
            self.assertTrue(runner.pause())
            release_first_send.set()
            sleep(0.1)
            self.assertEqual(sent, ["one"])
            snapshot = runner.snapshot()
            self.assertTrue(snapshot.is_paused)
            self.assertEqual(snapshot.pause_reason, "user")

            self.assertTrue(runner.resume())
            self.assertTrue(wait_until(lambda: sent == ["one", "two"]))
        finally:
            runner.stop(emit_message=False)

    def test_user_pause_blocks_plain_control_steps_until_resume(self) -> None:
        first_sent = Event()
        release_first_send = Event()
        events: list[SerialEvent] = []
        sent: list[str] = []

        def send_text(text: str, **kw) -> None:
            sent.append(text)
            if text == "one":
                first_sent.set()
                release_first_send.wait(1)

        runner = BatchRunner(
            emit_event=events.append,
            send_text=send_text,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner.start(parse_batch_script("SEND one\nLOOP 1\nLOG still-running\nENDLOOP\nSEND two"))
        try:
            self.assertTrue(first_sent.wait(1))
            self.assertTrue(runner.pause())
            release_first_send.set()
            sleep(0.1)
            self.assertFalse(any(event.kind == "script" for event in events))
            self.assertEqual(sent, ["one"])

            self.assertTrue(runner.resume())
            self.assertTrue(wait_until(lambda: sent == ["one", "two"]))
            self.assertTrue(any(event.kind == "script" for event in events))
        finally:
            runner.stop(emit_message=False)

    def test_user_pause_blocks_template_control_steps_until_resume(self) -> None:
        first_sent = Event()
        release_first_send = Event()
        events: list[SerialEvent] = []
        sent: list[str] = []

        def send_text(text: str, **kw) -> None:
            sent.append(text)
            if text == "one":
                first_sent.set()
                release_first_send.wait(1)

        runner = BatchRunner(
            emit_event=events.append,
            send_text=send_text,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner.start_template(
            parse_batch_template("SEND one\nSET STATE READY\nLOG $STATE\nSEND two"),
            lambda line, line_number: line,
        )
        try:
            self.assertTrue(first_sent.wait(1))
            self.assertTrue(runner.pause())
            release_first_send.set()
            sleep(0.1)
            self.assertFalse(any(event.kind == "script" for event in events))
            self.assertEqual(sent, ["one"])

            self.assertTrue(runner.resume())
            self.assertTrue(wait_until(lambda: sent == ["one", "two"]))
            self.assertTrue(any(event.kind == "script" and event.message == "READY" for event in events))
        finally:
            runner.stop(emit_message=False)

    def test_reconnect_requires_manual_resume(self) -> None:
        output_events: Queue = Queue()
        first_sent = Event()
        release_first_send = Event()
        connected = True
        sent: list[str] = []

        def is_connected() -> bool:
            return connected

        def send_text(text: str, **kw) -> None:
            sent.append(text)
            if text == "one":
                first_sent.set()
                release_first_send.wait(1)

        runner = BatchRunner(
            emit_event=output_events.put_nowait,
            send_text=send_text,
            send_bytes=lambda data, **kw: None,
            connected_supplier=is_connected,
        )
        runner.start(parse_batch_script("SEND one\nSEND two"))
        try:
            self.assertTrue(first_sent.wait(1))
            connected = False
            runner.notify_connection_state(False)
            connected = True
            runner.notify_connection_state(True)
            release_first_send.set()
            sleep(0.1)
            self.assertEqual(sent, ["one"])
            snapshot = runner.snapshot()
            self.assertTrue(snapshot.is_paused)
            self.assertEqual(snapshot.pause_reason, "connection")
            self.assertTrue(snapshot.can_resume)

            self.assertTrue(runner.resume())
            self.assertTrue(wait_until(lambda: sent == ["one", "two"]))
        finally:
            runner.stop(emit_message=False)

    def test_connection_pause_blocks_control_steps_until_manual_resume(self) -> None:
        first_sent = Event()
        release_first_send = Event()
        connected = True
        events: list[SerialEvent] = []

        def send_text(text: str, **kw) -> None:
            if text == "one":
                first_sent.set()
                release_first_send.wait(1)

        runner = BatchRunner(
            emit_event=events.append,
            send_text=send_text,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: connected,
        )
        runner.start(parse_batch_script("SEND one\nLOG after-reconnect"))
        try:
            self.assertTrue(first_sent.wait(1))
            connected = False
            runner.notify_connection_state(False)
            connected = True
            runner.notify_connection_state(True)
            release_first_send.set()
            sleep(0.1)
            self.assertFalse(any(event.kind == "script" for event in events))
            self.assertEqual(runner.snapshot().pause_reason, "connection")

            self.assertTrue(runner.resume())
            self.assertTrue(
                wait_until(
                    lambda: any(
                        event.kind == "script" and event.message == "after-reconnect"
                        for event in events
                    )
                )
            )
        finally:
            runner.stop(emit_message=False)

    def test_stop_works_while_control_only_loop_is_paused(self) -> None:
        first_log = Event()
        events: list[SerialEvent] = []

        def emit_event(event: SerialEvent) -> None:
            events.append(event)
            if event.kind == "script" and not first_log.is_set():
                first_log.set()
                runner.pause(emit_message=False)

        runner = BatchRunner(
            emit_event=emit_event,
            send_text=lambda text, **kw: None,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner.start(parse_batch_script("LOOP FOREVER\nLOG spinning\nENDLOOP"))
        try:
            self.assertTrue(first_log.wait(1))
            self.assertTrue(wait_until(lambda: runner.snapshot().is_paused))
            runner.stop(emit_message=False)
            self.assertFalse(runner.is_running)
            self.assertEqual(sum(event.kind == "script" for event in events), 1)
        finally:
            runner.stop(emit_message=False)

    def test_stop_works_while_connection_paused(self) -> None:
        output_events: Queue = Queue()
        runner = BatchRunner(
            emit_event=output_events.put_nowait,
            send_text=lambda text, **kw: None,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: False,
        )

        runner.start(parse_batch_script("SEND never"))
        try:
            self.assertTrue(wait_until(lambda: runner.snapshot().is_paused))
            self.assertEqual(runner.snapshot().pause_reason, "connection")
            runner.stop()
            self.assertFalse(runner.is_running)
        finally:
            runner.stop(emit_message=False)

    def test_paused_wait_does_not_count_pause_time(self) -> None:
        output_events: Queue = Queue()
        sent: list[str] = []
        runner = BatchRunner(
            emit_event=output_events.put_nowait,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )

        runner.start(parse_batch_script("WAIT 120\nSEND done"))
        try:
            sleep(0.02)
            self.assertTrue(runner.pause())
            sleep(0.16)
            self.assertEqual(sent, [])
            self.assertTrue(runner.resume())
            self.assertTrue(wait_until(lambda: sent == ["done"], timeout=0.5))
        finally:
            runner.stop(emit_message=False)

    def test_finite_loop_repeats_enclosed_steps(self) -> None:
        sent: list[str] = []
        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()

        runner._run_steps(parse_batch_script("LOOP 3\nSEND ping\nENDLOOP"))

        self.assertEqual(sent, ["ping", "ping", "ping"])

    def test_nested_loops_repeat_independently(self) -> None:
        sent: list[str] = []
        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()

        runner._run_steps(parse_batch_script("LOOP 2\nLOOP 3\nSEND ping\nENDLOOP\nENDLOOP"))

        self.assertEqual(sent, ["ping"] * 6)

    def test_break_exits_only_the_innermost_loop(self) -> None:
        sent: list[str] = []
        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()

        runner._run_steps(
            parse_batch_script(
                "LOOP 2\n"
                "SEND outer\n"
                "LOOP FOREVER\nSEND inner\nBREAK\nSEND skipped\nENDLOOP\n"
                "SEND after-inner\n"
                "ENDLOOP"
            )
        )

        self.assertEqual(sent, ["outer", "inner", "after-inner"] * 2)

    def test_set_and_log_resolve_and_overwrite_runtime_variables(self) -> None:
        sent: list[str] = []
        events: list[SerialEvent] = []
        runner = BatchRunner(
            emit_event=events.append,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()

        runner._run_steps(
            parse_batch_script(
                '@@wait 0\nSET MODE "SAFE MODE"\nLOG Selected $MODE\n'
                'SET MODE FAST\nSEND MODE=$MODE'
            )
        )

        self.assertEqual(sent, ["MODE=FAST"])
        self.assertTrue(
            any(event.kind == "script" and event.message == "Selected SAFE MODE" for event in events)
        )
        self.assertFalse(any(event.message.startswith("SET ") for event in events))
        self.assertFalse(any(event.message.startswith("Setting @@") for event in events))

    def test_increment_and_decrement_mutate_variables_without_sending(self) -> None:
        sent: list[str] = []
        events: list[SerialEvent] = []
        runner = BatchRunner(
            emit_event=events.append,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()

        runner._run_steps(
            parse_batch_script(
                "SET volt 10.5\nSET curr 4\nSET step 0.25\n"
                "volt:increment\ncurr:decrement 2\nvolt:increment $step\n"
                "SEND VOLT=$volt CURR=$curr"
            )
        )

        self.assertEqual(sent, ["VOLT=11.75 CURR=2"])
        self.assertFalse(any(event.kind == "error" for event in events))

    def test_variable_action_errors_for_missing_or_non_numeric_target(self) -> None:
        events: list[SerialEvent] = []
        runner = BatchRunner(
            emit_event=events.append,
            send_text=lambda text, **kw: None,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()

        runner._run_steps(parse_batch_script("missing:increment 1"))
        self.assertTrue(any("not set" in event.message for event in events if event.kind == "error"))

        events.clear()
        runner._run_steps(parse_batch_script("SET mode FAST\nmode:decrement 1"))
        self.assertTrue(any("must be finite numbers" in event.message for event in events if event.kind == "error"))

    def test_variable_action_error_obeys_stop_and_continue_policies(self) -> None:
        for directive, expected_sent in (
            ("@@on-error stop", []),
            ("@@on-error continue", ["after-FAST"]),
        ):
            with self.subTest(directive=directive):
                sent: list[str] = []
                events: list[SerialEvent] = []
                runner = BatchRunner(
                    emit_event=events.append,
                    send_text=lambda text, **kw: sent.append(text),
                    send_bytes=lambda data, **kw: None,
                    connected_supplier=lambda: True,
                )
                runner._resume_event.set()

                runner._run_steps(
                    parse_batch_script(
                        f"{directive}\nSET mode FAST\nmode:INCREMENT\nSEND after-$mode"
                    )
                )

                self.assertEqual(sent, expected_sent)
                errors = [event.message for event in events if event.kind == "error"]
                self.assertEqual(len(errors), 1)
                self.assertIn("must be finite numbers", errors[0])

    def test_pause_directive_waits_for_resume_and_resolves_message(self) -> None:
        sent: list[str] = []
        events: list[SerialEvent] = []
        pause_notifications: list[tuple[str, int]] = []
        runner = BatchRunner(
            emit_event=events.append,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
            pause_notifier=lambda message, line: pause_notifications.append((message, line)),
        )

        runner.start(
            parse_batch_script(
                "SET VOLTAGE 7\nSEND before\nPAUSE Check $VOLTAGE volts\nSEND after"
            )
        )
        try:
            self.assertTrue(
                wait_until(
                    lambda: runner.snapshot().is_paused
                    and runner.snapshot().pause_reason == "script"
                )
            )
            self.assertEqual(sent, ["before"])
            self.assertEqual(pause_notifications, [("Check 7 volts", 3)])
            self.assertTrue(
                any(
                    event.kind == "status" and "Check 7 volts" in event.message
                    for event in events
                )
            )

            self.assertTrue(runner.resume())
            self.assertTrue(wait_until(lambda: sent == ["before", "after"]))
            self.assertTrue(wait_until(lambda: not runner.is_running))
        finally:
            runner.stop(emit_message=False)

    def test_parameterized_variable_action_runs_in_template_runner(self) -> None:
        sent: list[str] = []
        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()
        values: dict[str, str] = {}

        runner._run_template_steps(
            parse_batch_template("SET volt 1\nvolt:increment {{STEP=2.5}}\nSEND $volt"),
            lambda line, line_number: substitute_batch_parameters(
                line, values, lambda *_: None, line_number
            ),
        )

        self.assertEqual(sent, ["3.5"])

    def test_parameterized_loop_count_is_resolved_before_execution(self) -> None:
        sent: list[str] = []
        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()
        values: dict[str, str] = {}

        runner._run_template_steps(
            parse_batch_template("LOOP {{COUNT=3}}\nSEND ping\nENDLOOP"),
            lambda line, line_number: substitute_batch_parameters(
                line, values, lambda *_: None, line_number
            ),
        )

        self.assertEqual(sent, ["ping"] * 3)

    def test_condition_executes_only_the_selected_branch(self) -> None:
        sent: list[str] = []
        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()

        runner._run_steps(
            parse_batch_script(
                "IF 15 > 12\nSEND high\nELSE\nSEND low\nENDIF\n"
                "IF FAST == SLOW\nSEND wrong\nELSE\nSEND right\nENDIF"
            )
        )

        self.assertEqual(sent, ["high", "right"])

    def test_quoted_condition_operators_select_expected_plain_runner_branches(self) -> None:
        sent: list[str] = []
        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()

        runner._run_steps(
            parse_batch_script(
                'IF "A > B" == "A > B"\nSEND symbol\nELSE\nSEND wrong-symbol\nENDIF\n'
                "IF 'X CONTAINS Y' == 'X CONTAINS Y'\nSEND word\nELSE\nSEND wrong-word\nENDIF\n"
                'IF "ALPHA BETA" CONTAINS "BETA"\nSEND contains\nELSE\nSEND wrong-contains\nENDIF\n'
                'IF "ALPHA BETA" NOT CONTAINS "GAMMA"\nSEND not-contains\nELSE\nSEND wrong-not-contains\nENDIF'
            )
        )

        self.assertEqual(sent, ["symbol", "word", "contains", "not-contains"])

    def test_quoted_condition_operators_select_expected_template_runner_branches(self) -> None:
        sent: list[str] = []
        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()

        runner._run_template_steps(
            parse_batch_template(
                'IF "A > B" == "A > B"\nSEND symbol\nELSE\nSEND wrong-symbol\nENDIF\n'
                "IF 'X CONTAINS Y' == 'X CONTAINS Y'\nSEND word\nELSE\nSEND wrong-word\nENDIF\n"
                'IF "ALPHA BETA" CONTAINS "BETA"\nSEND contains\nELSE\nSEND wrong-contains\nENDIF\n'
                'IF "ALPHA BETA" NOT CONTAINS "GAMMA"\nSEND not-contains\nELSE\nSEND wrong-not-contains\nENDIF'
            ),
            lambda line, line_number: line,
        )

        self.assertEqual(sent, ["symbol", "word", "contains", "not-contains"])

    def test_missing_if_variable_aborts_plain_runner_even_when_continuing(self) -> None:
        sent: list[str] = []
        events: list[SerialEvent] = []
        runner = BatchRunner(
            emit_event=events.append,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()

        runner._run_steps(
            parse_batch_script(
                "@@on-error continue\nIF $STATE == READY\nSEND START\nELSE\nSEND STOP\nENDIF"
            )
        )

        self.assertEqual(sent, [])
        self.assertTrue(any("STATE" in event.message for event in events if event.kind == "error"))
        self.assertFalse(any(event.message == "Batch run completed." for event in events))

    def test_missing_if_variable_aborts_template_runner_even_when_continuing(self) -> None:
        sent: list[str] = []
        events: list[SerialEvent] = []
        runner = BatchRunner(
            emit_event=events.append,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()

        runner._run_template_steps(
            parse_batch_template(
                "@@on-error continue\nIF $STATE == READY\nSEND START\nELSE\nSEND STOP\nENDIF"
            ),
            lambda line, line_number: line,
        )

        self.assertEqual(sent, [])
        self.assertTrue(any("STATE" in event.message for event in events if event.kind == "error"))
        self.assertFalse(any(event.message == "Batch run completed." for event in events))

    def test_failed_capture_then_missing_if_variable_aborts_when_continuing(self) -> None:
        sent: list[str] = []
        events: list[SerialEvent] = []
        runner = BatchRunner(
            emit_event=events.append,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
            expect_timeout_ms=1,
        )
        runner._rx_event_queue = Queue()
        runner._resume_event.set()

        runner._run_steps(
            parse_batch_script(
                "@@on-error continue\nCAPTURE STATE REGEX READY\n"
                "IF $STATE == READY\nSEND START\nENDIF"
            )
        )

        self.assertEqual(sent, [])
        error_messages = [event.message for event in events if event.kind == "error"]
        self.assertTrue(any(message.startswith("CAPTURE timed out") for message in error_messages))
        self.assertTrue(any("STATE" in message for message in error_messages))

    def test_capture_joins_fragmented_rx_and_drives_condition_and_send(self) -> None:
        sent: list[str] = []
        rx_events: Queue = Queue()

        def send_text(text: str, **kwargs) -> None:
            sent.append(text)
            if text == "MEASURE?":
                rx_events.put_nowait(SerialEvent(kind="rx", message="VOLT: 13."))
                rx_events.put_nowait(SerialEvent(kind="rx", message="7 V\r\n"))

        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=send_text,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()
        runner._rx_event_queue = rx_events

        runner._run_steps(
            parse_batch_script(
                "SEND MEASURE?\n"
                r"CAPTURE VOLTAGE REGEX VOLT:\s*([0-9.]+)\s+V" "\n"
                "IF $VOLTAGE > 12\nSEND OUTPUT:OFF\nELSE\nSEND OUTPUT:ON\nENDIF\n"
                "SEND RECORDED=$VOLTAGE"
            )
        )

        self.assertEqual(sent, ["MEASURE?", "OUTPUT:OFF", "RECORDED=13.7"])

    def test_nested_condition_inside_loop_uses_parameter_value(self) -> None:
        sent: list[str] = []
        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=lambda text, **kw: sent.append(text),
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()
        values: dict[str, str] = {}

        runner._run_template_steps(
            parse_batch_template(
                "LOOP 2\nIF {{VOLTAGE=13.5}} >= 12\nSEND high\nELSE\nSEND low\nENDIF\nENDLOOP"
            ),
            lambda line, line_number: substitute_batch_parameters(
                line, values, lambda *_: None, line_number
            ),
        )

        self.assertEqual(sent, ["high", "high"])

    def test_forever_loop_runs_until_stopped(self) -> None:
        sent: list[str] = []

        def send_text(text: str, **kwargs) -> None:
            sent.append(text)
            if len(sent) == 4:
                runner._stop_event.set()

        runner = BatchRunner(
            emit_event=lambda event: None,
            send_text=send_text,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
        )
        runner._resume_event.set()

        runner._run_steps(parse_batch_script("LOOP FOREVER\nSEND ping\nENDLOOP"))

        self.assertEqual(sent, ["ping"] * 4)

    def test_paused_expect_does_not_timeout_until_resumed(self) -> None:
        output_events: Queue = Queue()
        rx_events: Queue = Queue()
        runner = BatchRunner(
            emit_event=output_events.put_nowait,
            send_text=lambda text, **kw: None,
            send_bytes=lambda data, **kw: None,
            connected_supplier=lambda: True,
            event_queue_factory=lambda: rx_events,
            expect_timeout_ms=80,
        )

        runner.start(parse_batch_script("EXPECT OK"))
        try:
            sleep(0.02)
            self.assertTrue(runner.pause())
            sleep(0.12)
            rx_events.put_nowait(SerialEvent(kind="rx", message="OK"))
            self.assertTrue(runner.resume())
            self.assertTrue(wait_until(lambda: not runner.is_running))
            messages = [output_events.get_nowait().message for _ in range(output_events.qsize())]
            self.assertFalse(any(message.startswith("EXPECT matched") for message in messages))
            self.assertIn("Batch run completed.", messages)
            self.assertFalse(any(message.startswith("EXPECT timed out") for message in messages))
        finally:
            runner.stop(emit_message=False)


if __name__ == "__main__":
    unittest.main()
