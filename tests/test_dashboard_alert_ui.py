"""Tests for the dashboard alert UI surfaces (FR-58).

Covers the Qt-side pieces of T13:
- ``AlertHistoryPanel`` renders records + clears on demand.
- ``QtAlertSounder`` debounces and falls back when QtMultimedia or the
  WAV file is missing.
- Preferences gets a Dashboards tab whose checkboxes round-trip into
  ``AppSettings``.
- ``AppSettings`` serializes the new fields and accepts a missing block
  on older config files.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget

from ComPort_Zone.dashboard_alerts import (
    ALERT_KIND,
    RECOVERY_KIND,
    AlertLog,
    AlertRecord,
)
from ComPort_Zone.models import AppSettings
from ComPort_Zone.ui.alert_sound import AlertSounder, QtAlertSounder
from ComPort_Zone.ui.dashboard_alert_panel import AlertHistoryPanel
from ComPort_Zone.ui.dialogs.preferences import PreferencesDialog


def _make_record(
    *,
    kind: str,
    entry_id: str = "volts",
    old_state: str = "ok",
    new_state: str = "fail",
    value_text: str = "14.5",
) -> AlertRecord:
    return AlertRecord(
        timestamp="14:02:11",
        entry_id=entry_id,
        entry_label=entry_id.upper(),
        old_state=old_state,
        new_state=new_state,
        value_text=value_text,
        kind=kind,
    )


class FakeSounder:
    """Test stub that counts plays — never touches QtMultimedia."""

    def __init__(self) -> None:
        self.play_count = 0

    def play(self) -> None:
        self.play_count += 1


class AlertHistoryPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_set_records_lists_with_subtitle(self) -> None:
        anchor = QWidget()
        panel = AlertHistoryPanel(anchor)
        records = [
            _make_record(kind=ALERT_KIND, entry_id="volts"),
            _make_record(
                kind=RECOVERY_KIND,
                entry_id="volts",
                old_state="fail",
                new_state="ok",
            ),
        ]
        panel.set_records(records)
        # Header summary counts alerts vs recoveries.
        self.assertIn("1 alert", panel.subtitle_label.text())
        self.assertIn("1 recovery", panel.subtitle_label.text())
        # Both records appear; first item carries entry_label + states.
        self.assertEqual(panel.list_widget.count(), 2)
        first = panel.list_widget.item(0).text()
        self.assertIn("VOLTS", first)
        self.assertIn("OK -> FAIL", first)
        panel.deleteLater()
        anchor.deleteLater()

    def test_empty_records_shows_placeholder(self) -> None:
        anchor = QWidget()
        panel = AlertHistoryPanel(anchor)
        panel.set_records([])
        self.assertEqual(panel.list_widget.count(), 1)
        self.assertIn("No alerts", panel.list_widget.item(0).text())
        panel.deleteLater()
        anchor.deleteLater()

    def test_open_with_marks_log_seen(self) -> None:
        anchor = QWidget()
        panel = AlertHistoryPanel(anchor)
        log = AlertLog()
        log.append(_make_record(kind=ALERT_KIND))
        log.append(_make_record(kind=ALERT_KIND, entry_id="amps"))
        self.assertEqual(log.unseen_count, 2)
        panel.open_with(log)
        self.assertEqual(log.unseen_count, 0)
        # Records are populated newest-first per AlertLog.records().
        self.assertEqual(panel.list_widget.count(), 2)
        panel.deleteLater()
        anchor.deleteLater()


class QtAlertSounderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_alert_wav_ships_with_package(self) -> None:
        # The build bundles assets/alert.wav; missing it would silently
        # degrade to QApplication.beep in production.
        from ComPort_Zone.ui.alert_sound import ALERT_WAV_PATH

        self.assertTrue(ALERT_WAV_PATH.exists(), msg=f"missing {ALERT_WAV_PATH}")

    def test_debounce_blocks_rapid_replays(self) -> None:
        # Inject a fake clock so a "fast" sequence stays inside the
        # debounce window; switching to "later" releases it.
        now = [0.0]
        sounder = QtAlertSounder(
            wav_path=Path("/no-such-file.wav"),
            clock=lambda: now[0],
            debounce_s=2.0,
        )
        # First play: lands (via the beep fallback because the WAV path
        # doesn't exist); subsequent plays inside the debounce window
        # don't even reach the fallback.
        played: list[float] = []

        class CountingFallback:
            def play(self) -> None:
                played.append(now[0])

        sounder._fallback = CountingFallback()
        sounder._initialized = True
        sounder.play()
        sounder.play()
        self.assertEqual(played, [0.0])
        now[0] = 1.0  # still inside the 2 s window
        sounder.play()
        self.assertEqual(played, [0.0])
        now[0] = 3.0  # debounce window cleared
        sounder.play()
        self.assertEqual(played, [0.0, 3.0])

    def test_missing_wav_falls_back_to_beep(self) -> None:
        sounder = QtAlertSounder(wav_path=Path("/no-such-file.wav"))
        sounder._initialize()
        # Fallback is a _BeepFallback; effect stays None.
        self.assertIsNone(sounder._effect)
        self.assertIsNotNone(sounder._fallback)

    def test_protocol_accepts_test_stub(self) -> None:
        # Compile-time check: the duck-typed stub satisfies AlertSounder.
        stub: AlertSounder = FakeSounder()
        stub.play()
        self.assertEqual(stub.play_count, 1)


class AppSettingsAlertsFieldsTests(unittest.TestCase):
    def test_defaults_are_on_with_sound_off(self) -> None:
        settings = AppSettings()
        self.assertTrue(settings.dashboard_alerts_enabled)
        self.assertFalse(settings.dashboard_alert_sound)

    def test_round_trip(self) -> None:
        original = AppSettings()
        original.dashboard_alerts_enabled = False
        original.dashboard_alert_sound = True
        restored = AppSettings.from_dict(original.to_dict())
        self.assertFalse(restored.dashboard_alerts_enabled)
        self.assertTrue(restored.dashboard_alert_sound)

    def test_missing_block_keeps_defaults(self) -> None:
        # An older settings file without the dashboard_alerts block must
        # not silently disable alerts on upgrade.
        payload = AppSettings().to_dict()
        del payload["app"]["dashboard_alerts"]
        restored = AppSettings.from_dict(payload)
        self.assertTrue(restored.dashboard_alerts_enabled)
        self.assertFalse(restored.dashboard_alert_sound)


class PreferencesDashboardsTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt = QApplication.instance() or QApplication([])

    def test_round_trip(self) -> None:
        settings = AppSettings()
        settings.dashboard_alerts_enabled = False
        settings.dashboard_alert_sound = True
        dialog = PreferencesDialog(settings)
        self.assertFalse(dialog.dashboard_alerts_checkbox.isChecked())
        self.assertTrue(dialog.dashboard_alert_sound_checkbox.isChecked())
        # Master toggle gates the sound checkbox so it's a clearly
        # secondary option.
        self.assertFalse(dialog.dashboard_alert_sound_checkbox.isEnabled())
        dialog.dashboard_alerts_checkbox.setChecked(True)
        self.assertTrue(dialog.dashboard_alert_sound_checkbox.isEnabled())

        dialog.dashboard_alerts_checkbox.setChecked(True)
        dialog.dashboard_alert_sound_checkbox.setChecked(False)
        dialog.apply_to(settings)
        self.assertTrue(settings.dashboard_alerts_enabled)
        self.assertFalse(settings.dashboard_alert_sound)
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
