"""Capture the actual Qt app against the tutorial device, with isolated settings.

Use the app's Python environment: python tools/media/capture.py
No desktop interaction or physical device is needed. The Qt offscreen platform
renders real widgets; only the separate localhost tutorial instrument is used.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("COMPORT_ZONE_MEDIA_WORK", ROOT / "artifacts/user-guide")).resolve()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ComPort_Zone import app as app_module
from ComPort_Zone.control_panel_models import ControlPanelConfig
from ComPort_Zone.models import AppSettings, LanProfile, QuickCommand, QuickFile, TerminalSessionState
from ComPort_Zone.settings_service import SettingsService
from ComPort_Zone.storage import SettingsStore
from ComPort_Zone.ui.dialogs.connection import ConnectionSettingsDialog
from tools.media.demo_device import running_demo
from tools.media.common import app_version, capture_fingerprint


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    shots = ROOT / "docs/media"
    frames = WORK / "frames"
    frames.mkdir(exist_ok=True)
    app = QApplication.instance() or QApplication([])
    # The Windows offscreen plugin does not populate the system font database.
    if sys.platform == "win32":
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf", "consolab.ttf", "seguisym.ttf"):
            if QFontDatabase.addApplicationFont(str(fonts / name)) < 0:
                raise RuntimeError(f"Could not load capture font: {fonts / name}")
    app.setFont(QFont("Segoe UI", 10))
    config_path = WORK / "capture-settings.json"
    app_module.default_config_path = lambda: config_path
    panel_data = json.loads((ROOT / "examples/tutorial/control-panel.json").read_text())
    panel_config = ControlPanelConfig.from_dict(panel_data["control_panels"][0])
    commands = []
    with (ROOT / "examples/tutorial/quick-commands.csv").open(newline="") as stream:
        for index, row in enumerate(csv.DictReader(stream)):
            commands.append(QuickCommand(id=f"tutorial-{index}", favorite=index < 3, **row))
    with running_demo(5025) as (_, port):
        profile = LanProfile(host="127.0.0.1", port=port, line_ending="CRLF")
        settings = AppSettings(
            check_for_updates_on_launch=False,
            quick_commands=commands,
            quick_files=[QuickFile(label="First check", path=str(ROOT / "examples/tutorial/first-check.cpz"), favorite=True)],
            control_panels=[panel_config],
            restored_tabs=[TerminalSessionState(title="Tutorial device", title_is_custom=True, transport_kind="lan", lan=profile)],
            drawer_collapsed=False,
            drawer_width=290,
            terminal_font_size=13,
        )
        assert SettingsService(SettingsStore(config_path)).save(settings)
        window = app_module.MainWindow(defer_startup_actions=True)
        window.resize(1600, 900)
        window.show()

        def wait(seconds=0.25):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                app.processEvents()
                QTest.qWait(20)

        manifest = {}

        def capture(name, widget=None):
            wait()
            path = shots / f"tutorial-{name}.png"
            assert (widget or window).grab().save(str(path))
            manifest[name] = str(path.relative_to(ROOT))
            print(f"Captured {name}", flush=True)

        session = window.current_session()
        assert session is not None

        def send(command):
            window.tabs.setCurrentWidget(session)
            session.command_input.setText(command)
            QTest.keyClick(session.command_input, Qt.Key.Key_Return)
            wait(0.2)

        try:
            wait()
            capture("overview")
            # Display the documented stable demo endpoint, not the ephemeral capture port.
            dialog = ConnectionSettingsDialog(LanProfile(host="127.0.0.1", port=5025, line_ending="CRLF"), [], window)
            dialog.show()
            capture("connection", dialog)
            dialog.close()
            serial = ConnectionSettingsDialog(settings.serial, [], window)
            serial.show()
            capture("serial", serial)
            serial.close()
            session.toggle_connection()
            wait(0.5)
            assert session.transport.is_connected
            for command in ("*IDN?", "MEAS:VOLT?", "MEAS:CURR?", "MEAS:TEMP?", "STAT?"):
                send(command)
            assert "DEMO-001" in session.command_input.toPlainText()
            capture("terminal")
            window.set_drawer_page(1)
            capture("saved-commands")
            window.set_drawer_page(3)
            capture("history")
            window.set_drawer_page(0)
            send("VOLT 15")
            send("VOLT?")
            capture("readback")
            send("*RST")
            editor = window.open_command_file_in_tab(ROOT / "examples/tutorial/first-check.cpz")
            capture("editor")
            # Resolve the parameter explicitly so captures never wait on an operator dialog.
            window.tabs.setCurrentWidget(session)
            script = (ROOT / "examples/tutorial/first-check.cpz").read_text().replace("{{COUNT=3}}", "3")
            assert session.run_script_text(script, source_label="First check")
            wait(3)
            assert "Completed 3 passing checks" in session.command_input.toPlainText()
            capture("script-result")
            window.tabs.setCurrentWidget(editor)
            window.split_current_tab_right()
            capture("split")
            window.join_workspace_panes()
            panel = window.open_control_panel_tab(panel_config.id)
            assert panel is not None and panel.bind_to_session(session.session_id)
            wait(3)
            capture("control-panel")
            # Store a short, genuine live poll sequence for the narrated panel scene.
            for index in range(48):
                wait(0.125)
                assert window.grab().save(str(frames / f"panel-{index:03d}.png"))
            assert panel.open_chart("voltage")
            wait(1)
            capture("chart")
            # Return via the chart page's normal back control.
            panel.close_chart()
            panel.set_armed(True)
            capture("armed")
            panel.set_armed(False)
            send("DEMO:FAULT ON")
            window.tabs.setCurrentWidget(panel)
            wait(2)
            capture("fault")
            send("DEMO:FAULT OFF")
            send("*RST")
            # Exercise the published CLI commands with a separate settings file.
            cli_env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
            cli_prefix = [sys.executable, "-m", "ComPort_Zone", "--config", str(WORK / "cli-settings.json"), "--no-color"]
            cli_commands = [
                ["send", "*IDN?", "--host", "127.0.0.1", "--tcp-port", str(port), "--line-ending", "CRLF", "--read-after", "500"],
                ["validate", "examples/tutorial/first-check.cpz"],
                ["run", "examples/tutorial/first-check.cpz", "--host", "127.0.0.1", "--tcp-port", str(port), "--line-ending", "CRLF", "--param", "COUNT=3", "--non-interactive"],
                ["send", "ping", "--udp-host", "127.0.0.1", "--udp-port", str(port), "--expect", "PONG"],
            ]
            results = []
            panel.set_polling_enabled(False)
            for args in cli_commands:
                result = subprocess.run(cli_prefix + args, cwd=ROOT, env=cli_env, capture_output=True, text=True, timeout=20)
                results.append({"args": args, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
                if result.returncode:
                    raise RuntimeError(f"Tutorial CLI failed: {args}: {result.stderr}")
            (WORK / "cli-validation.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            window.tabs.setCurrentWidget(session)
            capture("closing")
            (WORK / "captures.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            (WORK / "capture-validation.json").write_text(json.dumps({"connected": True, "identity_received": True, "script_passed": True, "hardware": False, "app_version": app_version(ROOT), "source_fingerprint": capture_fingerprint(ROOT)}, indent=2), encoding="utf-8")
        finally:
            for panel in window.iter_control_panels():
                panel.shutdown()
            window.control_panel_runs.shutdown()
            for session in window.iter_sessions():
                session.shutdown()
            window.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    main()
