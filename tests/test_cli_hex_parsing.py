"""Edge cases for ``ComPort_Zone.cli.commands.send._parse_hex_payload``.

The function accepts three input forms documented in the CLI spec and a
fourth that's a natural fallback (continuous hex). Bad input must raise
``click.BadParameter`` so Click reports a USAGE_ERROR.
"""

from __future__ import annotations

import unittest

import click

from ComPort_Zone.cli.commands.send import _parse_hex_payload


class ValidHexTests(unittest.TestCase):
    def test_space_separated(self) -> None:
        self.assertEqual(_parse_hex_payload("55 AA"), b"\x55\xaa")

    def test_continuous(self) -> None:
        self.assertEqual(_parse_hex_payload("55AA"), b"\x55\xaa")

    def test_0x_prefix(self) -> None:
        self.assertEqual(_parse_hex_payload("0x55 0xAA"), b"\x55\xaa")

    def test_comma_separated(self) -> None:
        self.assertEqual(_parse_hex_payload("55,AA"), b"\x55\xaa")

    def test_mixed_case(self) -> None:
        self.assertEqual(_parse_hex_payload("aB Cd Ef"), b"\xab\xcd\xef")

    def test_internal_whitespace_collapsed(self) -> None:
        self.assertEqual(_parse_hex_payload("55    AA"), b"\x55\xaa")


class InvalidHexTests(unittest.TestCase):
    def test_empty_string_raises(self) -> None:
        with self.assertRaises(click.BadParameter):
            _parse_hex_payload("")

    def test_only_whitespace_raises(self) -> None:
        with self.assertRaises(click.BadParameter):
            _parse_hex_payload("   ")

    def test_odd_nibble_count_raises(self) -> None:
        with self.assertRaises(click.BadParameter) as cm:
            _parse_hex_payload("5")
        self.assertIn("even", str(cm.exception.message).lower())

    def test_non_hex_character_raises(self) -> None:
        with self.assertRaises(click.BadParameter):
            _parse_hex_payload("GG")

    def test_odd_with_0x_prefix_raises(self) -> None:
        # 0x5 → "5" after prefix strip → odd → BadParameter.
        with self.assertRaises(click.BadParameter):
            _parse_hex_payload("0x5")


if __name__ == "__main__":
    unittest.main()
