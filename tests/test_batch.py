import unittest
from queue import Queue

from ComPort_Zone.batch import (
    BatchParseError,
    BatchRunner,
    batch_parameter_input_lines,
    find_batch_parameters,
    parse_batch_line,
    parse_batch_script,
    parse_batch_template,
    parse_hex_payload,
    substitute_batch_parameters,
)


class RecordingStopEvent:
    def __init__(self) -> None:
        self.wait_calls: list[float] = []

    def wait(self, timeout: float) -> bool:
        self.wait_calls.append(timeout)
        return False

    def is_set(self) -> bool:
        return False


class BatchParserTests(unittest.TestCase):
    def test_parse_batch_script_supports_wait_send_hex_and_plain_lines(self) -> None:
        steps = parse_batch_script(
            "\n".join(
                [
                    "# comment",
                    "// C-style comment",
                    "SEND version",
                    "WAIT 250 // pause before payload",
                    "HEX 55 AA 01 0D // wake bytes",
                    "reset // plain command",
                ]
            )
        )
        self.assertEqual([step.kind for step in steps], ["send", "wait", "hex", "send"])
        self.assertEqual(steps[0].payload, "version")
        self.assertEqual(steps[1].payload, 250)
        self.assertEqual(steps[2].payload, bytes.fromhex("55AA010D"))
        self.assertEqual(steps[3].payload, "reset")

    def test_parse_batch_script_rejects_odd_hex_length(self) -> None:
        with self.assertRaises(BatchParseError) as context:
            parse_batch_script("HEX ABC")
        self.assertEqual(context.exception.line_number, 1)

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
            event_queue=Queue(),
            send_text=lambda text: None,
            send_bytes=lambda data: None,
            connected_supplier=lambda: True,
        )
        stop_event = RecordingStopEvent()
        runner._stop_event = stop_event

        self.assertTrue(runner._sleep_interruptible(0.005))
        self.assertEqual(stop_event.wait_calls, [])


if __name__ == "__main__":
    unittest.main()
