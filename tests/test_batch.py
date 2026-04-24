import unittest

from serial_terminal.batch import BatchParseError, parse_batch_script, parse_hex_payload


class BatchParserTests(unittest.TestCase):
    def test_parse_batch_script_supports_wait_send_hex_and_plain_lines(self) -> None:
        steps = parse_batch_script(
            "\n".join(
                [
                    "# comment",
                    "SEND version",
                    "WAIT 250",
                    "HEX 55 AA 01 0D",
                    "reset",
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


if __name__ == "__main__":
    unittest.main()
