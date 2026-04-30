from __future__ import annotations

import unittest
from dataclasses import dataclass

from PySide6.QtWidgets import QStyle

from ComPort_Zone.ui.command_palette_entries import workspace_tab_palette_entries


@dataclass
class FakeProfile:
    port: str


class FakeSession:
    title = "Bench PSU"
    tab_title = "COM7"
    profile = FakeProfile("COM7")

    def connection_status_text(self) -> str:
        return "Connected | COM7 | 115200 8N1"


class FakeEditor:
    def tab_title(self) -> str:
        return "power-sequence.cpf"

    def status_summary(self) -> str:
        return "Command file | Saved"


class CommandPaletteEntriesTests(unittest.TestCase):
    def test_builds_terminal_and_editor_tab_switch_entries(self) -> None:
        session = FakeSession()
        editor = FakeEditor()
        activated: list[int] = []

        entries = workspace_tab_palette_entries(
            tab_count=2,
            session_at=lambda index: session if index == 0 else None,
            command_file_editor_at=lambda index: editor if index == 1 else None,
            tab_text=lambda index: f"Tab {index + 1}",
            activate_tab=activated.append,
        )

        self.assertEqual(
            [entry.title for entry in entries],
            [
                "Switch to Tab 1: COM7",
                "Switch to Tab 2: power-sequence.cpf",
            ],
        )
        self.assertEqual(entries[0].subtitle, "Connected | COM7 | 115200 8N1")
        self.assertEqual(entries[0].icon, QStyle.StandardPixmap.SP_ComputerIcon)
        self.assertIn("Bench PSU", entries[0].keywords)
        self.assertEqual(entries[1].subtitle, "Command file | Saved")
        self.assertEqual(entries[1].icon, QStyle.StandardPixmap.SP_FileIcon)
        self.assertIn("command file editor", entries[1].keywords)

        entries[0].callback()
        entries[1].callback()

        self.assertEqual(activated, [0, 1])

    def test_falls_back_to_tab_text_when_tab_type_is_unknown(self) -> None:
        activated: list[int] = []

        entries = workspace_tab_palette_entries(
            tab_count=1,
            session_at=lambda _index: None,
            command_file_editor_at=lambda _index: None,
            tab_text=lambda _index: "Raw Widget",
            activate_tab=activated.append,
        )

        self.assertEqual(entries[0].title, "Switch to Tab 1: Raw Widget")
        self.assertEqual(entries[0].subtitle, "No port")
        self.assertEqual(entries[0].icon, QStyle.StandardPixmap.SP_FileIcon)
        self.assertIn("Raw Widget", entries[0].keywords)

        entries[0].callback()

        self.assertEqual(activated, [0])


if __name__ == "__main__":
    unittest.main()
