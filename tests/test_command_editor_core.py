import unittest

from ComPort_Zone.command_editor import CommandEditorSources as CompatCommandEditorSources
from ComPort_Zone.command_editor_core import CommandEditorSources, command_text_from_line, command_token
from ComPort_Zone.models import QuickCommand


class CommandEditorCoreTests(unittest.TestCase):
    def test_command_editor_reexports_source_model_for_compatibility(self) -> None:
        self.assertIs(CompatCommandEditorSources, CommandEditorSources)

    def test_command_text_helpers_extract_send_payloads(self) -> None:
        self.assertEqual(command_text_from_line("SEND *IDN?"), "*IDN?")
        self.assertEqual(command_text_from_line("HEX 55 AA"), "")
        self.assertEqual(command_token("SYST:ERR? 1"), "SYST:ERR?")

    def test_settings_directives_validate_and_complete(self) -> None:
        sources = CommandEditorSources()
        # A valid setting line is accepted (not mis-flagged as an unknown command).
        self.assertEqual(sources.validation_issues("@@wait 100"), [])
        # Unknown name and bad value are errors.
        self.assertTrue(
            any(issue.severity == "error" for issue in sources.validation_issues("@@nope 1"))
        )
        self.assertTrue(
            any(issue.severity == "error" for issue in sources.validation_issues("@@wait abc"))
        )
        # An indented setting is warned — it must start the line.
        indented = sources.validation_issues("   @@wait 100")
        self.assertTrue(
            any(issue.severity == "warning" and "beginning" in issue.message for issue in indented)
        )
        # Settings are offered as completions.
        suggestions = sources.suggestions()
        self.assertIn("@@wait", suggestions)
        self.assertIn("@@expect-timeout", suggestions)

    def test_sources_validate_and_suggest_without_qt_dependencies(self) -> None:
        sources = CommandEditorSources(
            history_commands=["MEAS:VOLT?"],
            quick_commands=[
                QuickCommand(label="Visible", command="SINK:POW 50", group="Shown"),
                QuickCommand(label="Hidden", command="POW 100", group="Hidden"),
            ],
            quick_command_hidden_groups=["Hidden"],
        )

        self.assertIn("SINK:POW 50", sources.suggestions("", "PO"))
        self.assertNotIn("POW 100", sources.suggestions("", "PO"))
        self.assertEqual(
            [issue.message for issue in sources.validation_issues("UNKNOWN:CMD 1")],
            ["Unknown command: UNKNOWN:CMD"],
        )


if __name__ == "__main__":
    unittest.main()
