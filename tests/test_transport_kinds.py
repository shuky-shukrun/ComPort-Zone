"""The one table that decides what each transport kind is *called*.

Worth pinning: these strings are the whole reason a fourth transport is a row
rather than a grep, and a regression here is invisible until someone reads a
status bar.
"""

from __future__ import annotations

import unittest

from ComPort_Zone.transport_kinds import (
    TRANSPORT_KIND_ORDER,
    TRANSPORT_KINDS,
    transport_kind_info,
)


class TransportKindTests(unittest.TestCase):
    def test_raw_tcp_is_never_labelled_lan(self) -> None:
        """TCP and UDP are both LAN transports, so "LAN" named the network
        instead of the protocol and read as a third category beside UDP. Only
        the persisted discriminator still says ``lan``."""
        info = transport_kind_info("lan")

        self.assertEqual(info.kind, "lan")
        for label in (
            info.ui_label,
            info.short_label,
            info.status_prefix,
            info.choose_hint,
            info.no_endpoint_label,
            info.set_endpoint_action,
        ):
            self.assertNotIn("LAN", label.upper())

        self.assertEqual(info.ui_label, "TCP")
        self.assertEqual(info.status_prefix, "TCP")

    def test_persisted_kinds_are_frozen(self) -> None:
        """Renaming a key silently orphans every settings.json already on
        disk — there is no migration path, only a compatibility gate."""
        self.assertEqual(TRANSPORT_KIND_ORDER, ("serial", "lan", "udp"))
        self.assertEqual(set(TRANSPORT_KINDS), {"serial", "lan", "udp"})
        for kind, info in TRANSPORT_KINDS.items():
            self.assertEqual(info.kind, kind)

    def test_labels_are_distinct_per_kind(self) -> None:
        for field in ("ui_label", "short_label", "rx_transport"):
            values = [getattr(info, field) for info in TRANSPORT_KINDS.values()]
            self.assertEqual(len(set(values)), len(values), msg=f"{field}: {values}")

    def test_only_udp_is_datagram_oriented(self) -> None:
        self.assertEqual(
            {kind for kind, info in TRANSPORT_KINDS.items() if info.datagram},
            {"udp"},
        )

    def test_unknown_kind_falls_back_to_serial(self) -> None:
        """Matches create_transport_adapter, so a settings file written by a
        newer build still opens instead of crashing on load."""
        self.assertEqual(transport_kind_info("carrier-pigeon").kind, "serial")
        self.assertEqual(transport_kind_info("").kind, "serial")


if __name__ == "__main__":
    unittest.main()
