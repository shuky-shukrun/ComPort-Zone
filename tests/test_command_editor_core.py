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

    def test_loop_blocks_validate_and_complete(self) -> None:
        sources = CommandEditorSources()

        self.assertEqual(sources.validation_issues("LOOP 3\nSEND *IDN?\nENDLOOP"), [])
        self.assertIn("LOOP", sources.suggestions("", "LOO"))
        self.assertIn("ENDLOOP", sources.suggestions("", "END"))
        issues = sources.validation_issues("LOOP FOREVER\nSEND *IDN?")
        self.assertTrue(any(issue.severity == "error" and "ENDLOOP" in issue.message for issue in issues))

    def test_condition_blocks_validate_and_complete(self) -> None:
        sources = CommandEditorSources()

        self.assertEqual(
            sources.validation_issues("IF {{MODE=FAST}} == FAST\nSEND *IDN?\nELSE\nWAIT 1\nENDIF"),
            [],
        )
        self.assertIn("IF", sources.suggestions("", "IF"))
        self.assertIn("ENDIF", sources.suggestions("", "ENDI"))
        issues = sources.validation_issues("IF 1 == 1\nSEND *IDN?")
        self.assertTrue(any(issue.severity == "error" and "ENDIF" in issue.message for issue in issues))

    def test_capture_validates_and_completes(self) -> None:
        sources = CommandEditorSources()

        self.assertEqual(
            sources.validation_issues(r"CAPTURE VOLTAGE REGEX VOLT:\s*([0-9.]+)"),
            [],
        )
        self.assertIn("CAPTURE", sources.suggestions("", "CAP"))
        issues = sources.validation_issues("CAPTURE VALUE REGEX ([0-9]+")
        self.assertTrue(any(issue.severity == "error" for issue in issues))

    def test_break_set_and_log_validate_and_complete(self) -> None:
        sources = CommandEditorSources()

        self.assertEqual(
            sources.validation_issues(
                "SET MODE FAST\nLOG Mode=$MODE\nLOOP FOREVER\nBREAK\nENDLOOP"
            ),
            [],
        )
        self.assertIn("BREAK", sources.suggestions("", "BRE"))
        self.assertIn("SET", sources.suggestions("", "SET"))
        self.assertIn("LOG", sources.suggestions("", "LOG"))
        issues = sources.validation_issues("BREAK")
        self.assertTrue(any(issue.severity == "error" and "LOOP" in issue.message for issue in issues))

    def test_pause_validates_and_completes(self) -> None:
        sources = CommandEditorSources()

        self.assertEqual(sources.validation_issues("PAUSE Check the output"), [])
        self.assertIn("PAUSE", sources.suggestions("", "PAU"))

    def test_variable_actions_validate_and_complete(self) -> None:
        sources = CommandEditorSources()

        self.assertEqual(
            sources.validation_issues("SET volt 1\nvolt:increment 2\nvolt:decrement"),
            [],
        )
        self.assertIn(":INCREMENT", sources.suggestions("", "INC"))
        self.assertIn(":DECREMENT", sources.suggestions("", "DEC"))
        issues = sources.validation_issues("volt:increment wrong")
        self.assertTrue(any(issue.severity == "error" for issue in issues))

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
