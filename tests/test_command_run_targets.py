import unittest
from pathlib import Path

from ComPort_Zone.command_run_targets import (
    CommandRunRequest,
    CommandRunTarget,
    CommandRunTargetService,
    coerce_run_target,
)


class CommandRunTargetTests(unittest.TestCase):
    def test_coerce_accepts_dataclass_or_legacy_tuple(self) -> None:
        self.assertEqual(coerce_run_target(CommandRunTarget(7, "COM7")), CommandRunTarget(7, "COM7"))
        self.assertEqual(coerce_run_target((8, "COM8")), CommandRunTarget(8, "COM8"))

    def test_request_source_label_prefers_path(self) -> None:
        path = Path("C:/scripts/test.cmd")

        self.assertEqual(CommandRunRequest("SEND *IDN?", path=path, display_name="test.cmd").source_label, str(path))
        self.assertEqual(CommandRunRequest("SEND *IDN?", display_name="Untitled").source_label, "Untitled")

    def test_service_lists_targets_and_runs_request(self) -> None:
        calls: list[tuple[str, int]] = []
        service = CommandRunTargetService(
            targets_supplier=lambda: [(42, "Connected | COM42")],
            run_callback=lambda request, target_id: calls.append((request.text, target_id)),
        )

        self.assertTrue(service.is_configured())
        self.assertEqual(service.targets(), [CommandRunTarget(42, "Connected | COM42")])
        self.assertTrue(service.run(CommandRunRequest("SEND *IDN?"), 42))
        self.assertEqual(calls, [("SEND *IDN?", 42)])

    def test_unconfigured_service_is_empty_and_does_not_run(self) -> None:
        service = CommandRunTargetService()

        self.assertFalse(service.is_configured())
        self.assertEqual(service.targets(), [])
        self.assertFalse(service.run(CommandRunRequest("SEND *IDN?"), 1))


if __name__ == "__main__":
    unittest.main()
