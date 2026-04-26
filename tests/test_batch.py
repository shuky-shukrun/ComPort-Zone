import unittest
from queue import Queue

from ComPort_Zone.batch import BatchParseError, BatchRunner, parse_batch_script, parse_hex_payload


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
        self.assertLess(max(stop_event.wait_calls), 0.01)


if __name__ == "__main__":
    unittest.main()
