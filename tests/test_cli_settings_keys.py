"""Unit tests for ``ComPort_Zone.cli.settings_keys``.

The dotted-key get/set helpers are exercised end-to-end by the
``settings`` subcommand tests, but a focused suite makes the GUI-only /
read-only / library-only refusals easy to extend and protect.
"""

from __future__ import annotations

import unittest

from ComPort_Zone.cli.settings_keys import (
    GuiOnlyKeyError,
    LibraryManagedKeyError,
    ReadOnlyKeyError,
    SettingsValueError,
    UnknownKeyError,
    get_value,
    is_gui_only,
    is_library_key,
    is_read_only,
    set_value,
)


def _sample_payload() -> dict:
    """A representative slice of the schema-v2 settings payload."""
    return {
        "schema_version": 2,
        "minimum_compatible_schema_version": 1,
        "transport": {
            "kind": "serial",
            "profile": {
                "port": "COM3",
                "baudrate": 115200,
                "stopbits": 1.0,
                "dtr": True,
                "rts": False,
            },
        },
        "app": {
            "theme": "VS Code Dark",
            "timestamps_enabled": True,
            "drawer": {"collapsed": True, "width": 260, "page_index": 0},
        },
        "libraries": {"quick_command_sort_mode": "Custom"},
        "workspace": {"terminal_tabs": []},
    }


class PredicateTests(unittest.TestCase):
    def test_gui_only_paths_recognised(self) -> None:
        for key in (
            "app.theme",
            "app.terminal_font.size",
            "app.drawer.width",
            "app.window.height",
            "workspace.terminal_tabs",
        ):
            with self.subTest(key=key):
                self.assertTrue(is_gui_only(key))

    def test_non_gui_keys_not_flagged(self) -> None:
        for key in (
            "transport.profile.port",
            "transport.profile.baudrate",
            "app.timestamps_enabled",
            "app.updates.check_on_launch",
        ):
            with self.subTest(key=key):
                self.assertFalse(is_gui_only(key))

    def test_library_prefix_flagged(self) -> None:
        self.assertTrue(is_library_key("libraries.quick_command_sort_mode"))
        self.assertFalse(is_library_key("transport.profile.port"))

    def test_read_only_keys(self) -> None:
        self.assertTrue(is_read_only("schema_version"))
        self.assertTrue(is_read_only("minimum_compatible_schema_version"))
        self.assertFalse(is_read_only("transport.profile.port"))


class GetValueTests(unittest.TestCase):
    def test_returns_scalar_leaf(self) -> None:
        payload = _sample_payload()
        self.assertEqual(get_value(payload, "transport.profile.port"), "COM3")
        self.assertEqual(get_value(payload, "transport.profile.baudrate"), 115200)

    def test_returns_nested_dict(self) -> None:
        payload = _sample_payload()
        self.assertEqual(
            get_value(payload, "transport.profile")["baudrate"], 115200
        )

    def test_returns_top_level_dict_for_empty_key(self) -> None:
        payload = _sample_payload()
        self.assertIs(get_value(payload, ""), payload)

    def test_missing_key_raises_unknown(self) -> None:
        with self.assertRaises(UnknownKeyError):
            get_value(_sample_payload(), "transport.profile.nonsense")


class SetValueTests(unittest.TestCase):
    def test_coerces_string_to_int(self) -> None:
        payload = _sample_payload()
        coerced = set_value(payload, "transport.profile.baudrate", "9600")
        self.assertEqual(coerced, 9600)
        self.assertEqual(payload["transport"]["profile"]["baudrate"], 9600)

    def test_coerces_string_to_float(self) -> None:
        payload = _sample_payload()
        set_value(payload, "transport.profile.stopbits", "1.5")
        self.assertEqual(payload["transport"]["profile"]["stopbits"], 1.5)

    def test_coerces_truthy_strings_to_bool(self) -> None:
        payload = _sample_payload()
        for raw, expected in [
            ("true", True),
            ("false", False),
            ("on", True),
            ("off", False),
            ("1", True),
            ("0", False),
            ("yes", True),
            ("no", False),
        ]:
            with self.subTest(raw=raw):
                set_value(payload, "transport.profile.dtr", raw)
                self.assertEqual(payload["transport"]["profile"]["dtr"], expected)

    def test_string_passthrough(self) -> None:
        payload = _sample_payload()
        set_value(payload, "transport.profile.port", "COM9")
        self.assertEqual(payload["transport"]["profile"]["port"], "COM9")

    def test_invalid_int_raises_value_error(self) -> None:
        with self.assertRaises(SettingsValueError):
            set_value(_sample_payload(), "transport.profile.baudrate", "fast")

    def test_invalid_bool_raises_value_error(self) -> None:
        with self.assertRaises(SettingsValueError):
            set_value(_sample_payload(), "transport.profile.dtr", "maybe")

    def test_gui_only_key_refused(self) -> None:
        with self.assertRaises(GuiOnlyKeyError):
            set_value(_sample_payload(), "app.theme", "Bench Light")

    def test_library_key_refused(self) -> None:
        with self.assertRaises(LibraryManagedKeyError):
            set_value(
                _sample_payload(), "libraries.quick_command_sort_mode", "Title"
            )

    def test_read_only_key_refused(self) -> None:
        with self.assertRaises(ReadOnlyKeyError):
            set_value(_sample_payload(), "schema_version", "3")

    def test_unknown_key_raises_unknown(self) -> None:
        with self.assertRaises(UnknownKeyError):
            set_value(_sample_payload(), "transport.profile.bogus", "x")


if __name__ == "__main__":
    unittest.main()
