from __future__ import annotations

import unittest

from ComPort_Zone.library_lookup import (
    AmbiguousIdentifierError,
    EntryNotFoundError,
    resolve_entry,
)
from ComPort_Zone.models import QuickCommand, QuickFile


def _command(id: str, label: str) -> QuickCommand:
    return QuickCommand(id=id, label=label, command=label)


def _file(id: str, label: str) -> QuickFile:
    return QuickFile(id=id, label=label, path=f"C:/scripts/{label}.bat")


class ResolveEntryTests(unittest.TestCase):
    def test_resolves_by_exact_id(self) -> None:
        entries = [_command("aaa111", "Read ID"), _command("bbb222", "Reset")]
        self.assertIs(resolve_entry(entries, "bbb222"), entries[1])

    def test_resolves_by_exact_label(self) -> None:
        entries = [_command("aaa111", "Read ID"), _command("bbb222", "Reset")]
        self.assertIs(resolve_entry(entries, "Reset"), entries[1])

    def test_resolves_by_case_insensitive_label(self) -> None:
        entries = [_command("aaa111", "Read ID")]
        self.assertIs(resolve_entry(entries, "read id"), entries[0])

    def test_exact_label_wins_over_case_insensitive_match(self) -> None:
        # Two entries differ only in casing — exact match must take precedence
        # so the case-insensitive branch does not flag this as ambiguous.
        entries = [_command("aaa111", "reset"), _command("bbb222", "RESET")]
        self.assertIs(resolve_entry(entries, "RESET"), entries[1])

    def test_raises_when_no_match(self) -> None:
        with self.assertRaises(EntryNotFoundError) as cm:
            resolve_entry([_command("aaa111", "Read ID")], "unknown")
        self.assertEqual(cm.exception.identifier, "unknown")

    def test_raises_on_empty_identifier(self) -> None:
        with self.assertRaises(EntryNotFoundError):
            resolve_entry([_command("aaa111", "Read ID")], "")

    def test_raises_on_ambiguous_exact_labels(self) -> None:
        entries = [
            _command("aaa111", "Reset"),
            _command("bbb222", "Reset"),
        ]
        with self.assertRaises(AmbiguousIdentifierError) as cm:
            resolve_entry(entries, "Reset")
        self.assertEqual(cm.exception.identifier, "Reset")
        self.assertEqual(len(cm.exception.matches), 2)

    def test_raises_on_ambiguous_case_insensitive_labels(self) -> None:
        entries = [
            _command("aaa111", "Reset"),
            _command("bbb222", "RESET"),
        ]
        # "reset" matches both case-insensitively but neither exactly.
        with self.assertRaises(AmbiguousIdentifierError):
            resolve_entry(entries, "reset")

    def test_works_with_quick_files(self) -> None:
        entries = [_file("ccc333", "factory_test"), _file("ddd444", "smoke")]
        self.assertIs(resolve_entry(entries, "smoke"), entries[1])
        self.assertIs(resolve_entry(entries, "ccc333"), entries[0])


if __name__ == "__main__":
    unittest.main()
