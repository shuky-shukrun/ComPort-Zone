"""Tests for the ``comport-zone`` entry-point dispatcher.

Verifies the GUI/CLI switch in :mod:`ComPort_Zone.__main__`:

* No args / ``gui`` arg → GUI launch path
* Any other arg → CLI dispatch through :mod:`ComPort_Zone.cli.main`

The GUI launch is mocked so the tests don't try to bring up Qt.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ComPort_Zone import __main__ as entry


class DispatchTests(unittest.TestCase):
    def test_no_args_runs_gui(self) -> None:
        with patch.object(entry, "_run_gui", return_value=0) as gui_mock, \
             patch.object(entry, "_run_cli", return_value=0) as cli_mock, \
             patch("sys.argv", new=["comport-zone"]):
            self.assertEqual(entry.main(), 0)
        gui_mock.assert_called_once_with(None)
        cli_mock.assert_not_called()

    def test_gui_arg_runs_gui(self) -> None:
        with patch.object(entry, "_run_gui", return_value=0) as gui_mock, \
             patch.object(entry, "_run_cli", return_value=0) as cli_mock, \
             patch("sys.argv", new=["comport-zone", "gui"]):
            self.assertEqual(entry.main(), 0)
        gui_mock.assert_called_once_with(None)
        cli_mock.assert_not_called()

    def test_command_file_arg_opens_gui_with_file(self) -> None:
        # The .cpz association launches the app with the file path; it opens in the GUI.
        with patch.object(entry, "_run_gui", return_value=0) as gui_mock, \
             patch.object(entry, "_run_cli", return_value=0) as cli_mock, \
             patch("sys.argv", new=["comport-zone", "C:/scripts/run.cpz"]):
            self.assertEqual(entry.main(), 0)
        gui_mock.assert_called_once_with("C:/scripts/run.cpz")
        cli_mock.assert_not_called()

    def test_subcommand_runs_cli(self) -> None:
        with patch.object(entry, "_run_gui", return_value=0) as gui_mock, \
             patch.object(entry, "_run_cli", return_value=0) as cli_mock, \
             patch("sys.argv", new=["comport-zone", "ports", "list"]):
            self.assertEqual(entry.main(), 0)
        cli_mock.assert_called_once_with(["ports", "list"])
        gui_mock.assert_not_called()

    def test_help_arg_routes_to_cli(self) -> None:
        # ``--help`` should hit Click so it can list subcommands; the GUI
        # entrypoint must not be invoked.
        with patch.object(entry, "_run_gui", return_value=0) as gui_mock, \
             patch.object(entry, "_run_cli", return_value=0) as cli_mock, \
             patch("sys.argv", new=["comport-zone", "--help"]):
            entry.main()
        cli_mock.assert_called_once_with(["--help"])
        gui_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
