"""Drive the actual app with visible clicks/typing and record continuous footage.

Run in the app environment after build.py narrate:
  python tools/media/walkthrough.py --ffmpeg <ffmpeg.exe>
  python tools/media/walkthrough.py --rehearse

Qt mouse/key events drive real widgets, dialogs and services. Only the separate
localhost demo is simulated. A configured offscreen screen isolates the user's
desktop. The compositor records every frame, popup, pointer and input hint.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("COMPORT_ZONE_MEDIA_WORK", ROOT / "artifacts/user-guide")).resolve()
LIVE = WORK / "live"
SOURCE_W, SOURCE_H = 1600, 820
WIDTH, HEIGHT, APP_H, FPS = 1920, 1080, 984, 30
LIVE.mkdir(parents=True, exist_ok=True)
screen_config = LIVE / "screen.json"
screen_config.write_text(json.dumps({"windowFrameMargins": False, "screens": [{"name": "Tutorial", "x": 0, "y": 0, "width": SOURCE_W, "height": SOURCE_H, "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}), encoding="utf-8")
# Qt separates platform options on ':', so a Windows drive letter would be
# parsed as another option. Pass a path relative to the working directory.
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + Path(os.path.relpath(screen_config)).as_posix()
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QProcess, QProcessEnvironment, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QContextMenuEvent, QFont, QFontDatabase, QImage, QKeySequence, QPainter, QPen, QPolygonF
from PySide6.QtTest import QTest
from shiboken6 import isValid
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ComPort_Zone import app as app_module
from ComPort_Zone.models import AppSettings, LanProfile, TerminalSessionState
from ComPort_Zone.settings_service import SettingsService
from ComPort_Zone.storage import SettingsStore
from tools.media.common import app_version, fingerprint, sha256, video_fingerprint
from tools.media.demo_device import running_demo
from tools.media.live_timing import camera_rect, ease, frame_count


def text_of(text):
    return text.replace("&", "").replace("…", "...").split("\t")[0].strip()


class LiveRecorder:
    def __init__(self, app, window, ffmpeg, rehearse=False):
        self.app, self.window = app, window
        self.rehearse = rehearse
        self.started = time.perf_counter()
        self.scene = None
        self.scene_start = 0.0
        self.pointer = QPointF(780, 400)
        self.focus = QPointF(800, 410)
        self.clicks = []
        self.key_hint, self.key_until = "", 0.0
        self.zoom = self.target_zoom = 1.0
        self.cx, self.cy = 800.0, 410.0
        self.last_frame_time = 0.0
        self.frames, self.max_gap = 0, 0.0
        self.steps, self.events, self.errors = [], [], []
        self.source_fingerprint = video_fingerprint(ROOT)
        self.process = None
        self.timer = QTimer()
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(1000 // FPS)
        self.timer.timeout.connect(self.capture)
        if not rehearse:
            self.process = subprocess.Popen([
                ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}",
                "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", str(LIVE / "silent.mp4"),
            ], stdin=subprocess.PIPE)
            self.timer.start()

    def now(self):
        return time.perf_counter() - self.started

    def begin(self, scene):
        self.scene = scene
        self.scene_start = self.now()
        self.target_zoom = scene.get("zoom", 1.0)
        self.steps.append({"id": scene["id"], "start": self.scene_start, "duration": 0.0})

    def end(self):
        self.steps[-1]["duration"] = self.now() - self.scene_start
        if self.rehearse:
            self.render().save(str(LIVE / f"rehearsal-{self.scene['id']}.png"))

    def event(self, kind, **values):
        self.events.append({"time": self.now(), "step": self.scene["id"] if self.scene else None, "kind": kind, **values})

    def render(self):
        now = self.now()
        dt = min(max(now - self.last_frame_time, 0.001), 0.1)
        self.zoom = ease(self.zoom, self.target_zoom, dt, 0.35)
        self.cx = ease(self.cx, self.focus.x(), dt, 0.30)
        self.cy = ease(self.cy, self.focus.y(), dt, 0.30)
        source = self.window.grab().toImage()
        painter = QPainter(source)
        origin = self.window.mapToGlobal(QPoint())
        tops = [w for w in self.app.topLevelWidgets() if w is not self.window and w.isVisible() and w.width() > 10]
        # Active popup/modal last: dialog contents and menus are separate windows.
        active = self.app.activePopupWidget() or self.app.activeModalWidget()
        tops.sort(key=lambda w: (w is active, isinstance(w, QMenu)))
        for widget in tops:
            position = widget.mapToGlobal(QPoint()) - origin
            painter.drawPixmap(position, widget.grab())
        painter.end()
        frame = QImage(WIDTH, HEIGHT, QImage.Format.Format_RGB888)
        frame.fill(QColor("#0c1220"))
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        x, y, w, h = camera_rect(SOURCE_W, SOURCE_H, self.zoom, self.cx, self.cy)
        painter.drawImage(QRectF(0, 0, WIDTH, APP_H), source, QRectF(x, y, w, h))
        px, py = (self.pointer.x() - x) * WIDTH / w, (self.pointer.y() - y) * APP_H / h
        for click in self.clicks:
            age = now - click[0]
            if 0 <= age < 0.65:
                qx, qy = (click[1] - x) * WIDTH / w, (click[2] - y) * APP_H / h
                color = QColor("#50d69b")
                color.setAlpha(round(210 * (1 - age / 0.65)))
                painter.setPen(QPen(color, 4))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                radius = 10 + 34 * age
                painter.drawEllipse(QPointF(qx, qy), radius, radius)
        cursor = QPolygonF([QPointF(px, py), QPointF(px + 2, py + 29), QPointF(px + 10, py + 22), QPointF(px + 17, py + 35), QPointF(px + 23, py + 32), QPointF(px + 16, py + 19), QPointF(px + 27, py + 18)])
        painter.setPen(QPen(QColor("#07101a"), 2))
        painter.setBrush(QColor("#ffffff"))
        painter.drawPolygon(cursor)
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        if self.scene:
            chapter = self.scene["chapter"]
            box_width = painter.fontMetrics().horizontalAdvance(chapter) + 34
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(8, 15, 24, 210))
            painter.drawRoundedRect(QRectF(WIDTH - box_width - 28, 22, box_width, 42), 8, 8)
            painter.setPen(QColor("#86e4b6"))
            painter.drawText(QRectF(WIDTH - box_width - 28, 22, box_width, 42), Qt.AlignmentFlag.AlignCenter, chapter)
            elapsed = now - self.scene_start
            nominal = self.scene["start"] + elapsed
            caption = next((c["text"] for c in self.scene["captions"] if c["start"] <= nominal < c["end"]), "")
            painter.fillRect(0, APP_H, WIDTH, HEIGHT - APP_H, QColor("#0c1220"))
            painter.setFont(QFont("Segoe UI", 17))
            painter.setPen(QColor("#f3f6fb"))
            painter.drawText(QRectF(100, APP_H + 8, WIDTH - 200, HEIGHT - APP_H - 16), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, caption)
            if self.scene["id"] == "welcome" and elapsed < 3.5:
                painter.fillRect(QRectF(0, 0, WIDTH, APP_H), QColor(5, 12, 22, max(0, round(200 * (1 - max(elapsed - 2.5, 0))))))
                painter.setFont(QFont("Segoe UI", 40, QFont.Weight.Bold))
                painter.setPen(QColor("#f3f6fb"))
                painter.drawText(QRectF(100, 330, WIDTH - 200, 110), Qt.AlignmentFlag.AlignCenter, "ComPort Zone")
                painter.setFont(QFont("Segoe UI", 22))
                painter.setPen(QColor("#70e1a7"))
                painter.drawText(QRectF(100, 445, WIDTH - 200, 70), Qt.AlignmentFlag.AlignCenter, "A hands-on walkthrough")
        if now < self.key_until:
            painter.setFont(QFont("Consolas", 16, QFont.Weight.Bold))
            width = painter.fontMetrics().horizontalAdvance(self.key_hint) + 36
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(6, 13, 24, 230))
            painter.drawRoundedRect(QRectF(WIDTH - width - 34, APP_H - 84, width, 46), 9, 9)
            painter.setPen(QColor("#f3f6fb"))
            painter.drawText(QRectF(WIDTH - width - 34, APP_H - 84, width, 46), Qt.AlignmentFlag.AlignCenter, self.key_hint)
        painter.end()
        return frame

    def capture(self):
        if not self.process:
            return
        now = self.now()
        wanted = frame_count(now, FPS)
        if wanted <= self.frames:
            return
        self.max_gap = max(self.max_gap, now - self.last_frame_time)
        image = self.render()
        raw = image.bits().tobytes()
        repeat = wanted - self.frames
        for _ in range(repeat):
            self.process.stdin.write(raw)
        self.frames = wanted
        self.last_frame_time = now

    def stop(self, narration_hash):
        self.timer.stop()
        if self.process:
            self.capture()
            self.process.stdin.close()
            if self.process.wait() != 0:
                self.errors.append("FFmpeg recording failed.")
        result = {"version": app_version(ROOT), "source_fingerprint": self.source_fingerprint,
                  "narration_sha256": narration_hash, "steps": self.steps, "events": self.events,
                  "errors": self.errors, "fps": FPS, "frames": self.frames,
                  "duration": self.frames / FPS, "max_frame_gap_seconds": self.max_gap,
                  "rehearsal": self.rehearse, "format": "live-gui"}
        if self.process:
            result["recording_sha256"] = sha256(LIVE / "silent.mp4")
        (LIVE / ("rehearsal.json" if self.rehearse else "recording.json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


class Driver:
    def __init__(self, app, window, recorder, instrument, rehearse=False):
        self.app, self.window, self.recorder, self.instrument = app, window, recorder, instrument
        self.rehearse = rehearse
        self.jobs = queue.Queue()
        self.timer = QTimer()
        self.timer.setInterval(5)
        self.timer.timeout.connect(self._run_jobs)
        self.timer.start()
        self.session = window.current_session()
        self.editor = self.panel = self.shell = None

    def _run_jobs(self):
        while not self.jobs.empty():
            fn, result, done = self.jobs.get()
            try:
                result["value"] = fn()
            except BaseException as exc:
                result["error"] = exc
            done.set()

    def ui(self, fn):
        result, done = {}, threading.Event()
        self.jobs.put((fn, result, done))
        if not done.wait(12):
            raise TimeoutError("GUI action did not return.")
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def pause(self, seconds):
        time.sleep(seconds * (0.15 if self.rehearse else 1))

    def wait_for(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.ui(predicate)
            if result:
                return result
            time.sleep(0.04)
        raise TimeoutError("Expected UI state did not appear.")

    def move(self, widget, point=None, seconds=0.45):
        end = self.ui(lambda: widget.mapToGlobal(point or widget.rect().center()) - self.window.mapToGlobal(QPoint()))
        start = self.ui(lambda: QPointF(self.recorder.pointer))
        count = max(3, round(seconds * (10 if self.rehearse else FPS)))
        for index in range(1, count + 1):
            t = index / count
            e = t * t * (3 - 2 * t)
            position = QPointF(start.x() + (end.x() - start.x()) * e, start.y() + (end.y() - start.y()) * e)
            def update(p=position):
                self.recorder.pointer = p
                self.recorder.focus = p
                global_pos = self.window.mapToGlobal(QPoint(round(p.x()), round(p.y())))
                local = widget.mapFromGlobal(global_pos)
                QTest.mouseMove(widget, local)
            self.ui(update)
            self.pause(seconds / count)

    def click(self, widget, point=None, double=False, button=Qt.MouseButton.LeftButton):
        self.move(widget, point)
        def post():
            if not widget.isVisible():
                raise ValueError(f"Cannot click hidden widget: {type(widget).__name__}")
            pos = point or widget.rect().center()
            self.recorder.clicks.append((self.recorder.now(), self.recorder.pointer.x(), self.recorder.pointer.y()))
            self.recorder.event("double-click" if double else "click", widget=type(widget).__name__, text=getattr(widget, "text", lambda: "")()[:60])
            # Defer the input so modal exec() never blocks the job-pump callback.
            QTimer.singleShot(0, lambda: (QTest.mouseDClick if double else QTest.mouseClick)(widget, button, Qt.KeyboardModifier.NoModifier, pos))
        self.ui(post)
        self.pause(0.35)

    def key(self, sequence, widget=None):
        def post():
            target = widget or self.app.focusWidget() or self.window
            self.recorder.key_hint = sequence
            self.recorder.key_until = self.recorder.now() + 1.5
            self.recorder.event("key", sequence=sequence)
            QTimer.singleShot(0, lambda: QTest.keySequence(target, QKeySequence(sequence)))
        self.ui(post)
        self.pause(0.2)

    def type(self, widget, value, replace=True, delay=0.035, focus=True):
        if focus:
            self.click(widget)
        if replace:
            if widget is self.session.command_input:
                self.key("Ctrl+End", widget)
                self.key("Shift+Home", widget)
                self.key("Backspace", widget)
            else:
                self.key("Ctrl+A", widget)
        self.ui(lambda: self.recorder.event("type", text=value, widget=type(widget).__name__))
        for character in value:
            if character == "\n":
                self.key("Return", widget)
            else:
                self.ui(lambda c=character: QTest.keyClicks(widget, c))
            self.pause(delay)

    def modal(self, name=None):
        def find():
            widget = self.app.activeModalWidget()
            if widget is None:
                widget = next((w for w in self.app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()), None)
            if widget is not None and (name is None or type(widget).__name__ == name):
                return widget
            return None
        return self.wait_for(find)

    def button(self, parent, text):
        return self.ui(lambda: next(b for b in parent.findChildren(QAbstractButton) if b.isVisible() and text_of(b.text()) == text))

    def accept(self, dialog, text=None):
        if text:
            button = self.button(dialog, text)
        else:
            button = self.ui(lambda: next(b for b in dialog.findChildren(QAbstractButton) if b.isVisible() and text_of(b.text()) in {"OK", "Save", "Open", "Start"}))
        self.click(button)

    def choose(self, combo, text):
        self.click(combo)
        view = self.ui(combo.view)
        index = self.ui(lambda: combo.findText(text, Qt.MatchFlag.MatchContains))
        if index < 0:
            raise ValueError(f"No combo choice: {text}")
        model_index = self.ui(lambda: combo.model().index(index, 0))
        rect = self.ui(lambda: view.visualRect(model_index))
        self.click(self.ui(view.viewport), rect.center())

    def menu(self, title, *items):
        bar = self.ui(self.window.menuBar)
        action = self.ui(lambda: next(a for a in bar.actions() if text_of(a.text()) == title))
        self.click(bar, self.ui(lambda: bar.actionGeometry(action).center()))
        menu = self.wait_for(lambda: self.app.activePopupWidget() if isinstance(self.app.activePopupWidget(), QMenu) else action.menu() if action.menu().isVisible() else None)
        for number, item in enumerate(items):
            child = self.ui(lambda: next(a for a in menu.actions() if text_of(a.text()) == item))
            self.click(menu, self.ui(lambda: menu.actionGeometry(child).center()))
            if number + 1 < len(items):
                menu = self.wait_for(lambda: child.menu() if child.menu().isVisible() else None)

    def popup(self, item, contains=False):
        menu = self.wait_for(lambda: self.app.activePopupWidget() if isinstance(self.app.activePopupWidget(), QMenu) else None)
        action = self.ui(lambda: next(a for a in menu.actions() if (item in text_of(a.text()) if contains else text_of(a.text()) == item)))
        self.click(menu, self.ui(lambda: menu.actionGeometry(action).center()))

    def file_dialog(self, path, save=False):
        dialog = self.modal("QFileDialog")
        field = self.ui(lambda: dialog.findChild(QLineEdit, "fileNameEdit"))
        self.type(field, Path(path).as_posix(), delay=0.012)
        self.accept(dialog, "Save" if save else "Open")
        self.wait_for(lambda: not isValid(dialog) or not dialog.isVisible())

    def tab(self, widget):
        def location():
            for pane in self.window.tabs.panes():
                index = pane.indexOf(widget)
                if index >= 0:
                    return pane.tabBar(), pane.tabBar().tabRect(index).center()
            raise LookupError("Workspace tab not found")
        bar, pos = self.ui(location)
        self.click(bar, pos)

    def send(self, command):
        self.type(self.session.command_input, command)
        self.key("Return", self.session.command_input)
        self.pause(0.5)

    def assert_rx(self, text):
        self.wait_for(lambda: text in self.session.command_input.toPlainText())

    def rail(self, text):
        button = self.ui(lambda: next(b for b in self.window.shared_drawer.rail_buttons if text.lower() in b.toolTip().lower()))
        self.click(button)

    def row(self, listing, number=0, action=None):
        item = self.ui(lambda: listing.item(number))
        rect = self.ui(lambda: listing.visualItemRect(item))
        pos = rect.center() if action is None else QPoint(rect.right() - (12 if action == "send" else 36), rect.center().y())
        self.click(self.ui(listing.viewport), pos)

    def context(self, widget):
        self.click(widget, button=Qt.MouseButton.RightButton)
        if not self.ui(lambda: isinstance(self.app.activePopupWidget(), QMenu)):
            def post():
                pos = widget.rect().center()
                event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, widget.mapToGlobal(pos))
                QTimer.singleShot(0, lambda: QCoreApplication.sendEvent(widget, event))
            self.ui(post)
        self.wait_for(lambda: isinstance(self.app.activePopupWidget(), QMenu))

    def action(self, name):
        method = getattr(self, "step_" + name)
        method()

    def step_welcome(self):
        self.move(self.session.command_input, QPoint(550, 350), 0.7)

    def step_connection_menu(self):
        self.menu("Connection", "Connection Settings")
        self.modal("ConnectionSettingsDialog")

    def step_tcp_fields(self):
        dialog = self.modal("ConnectionSettingsDialog")
        self.choose(dialog.connection_type_combo, "TCP")
        self.type(dialog.lan_host_input, "127.0.0.1")
        self.type(self.ui(dialog.lan_port_spin.lineEdit), "5025")
        self.choose(dialog.lan_line_ending_combo, "CRLF")

    def step_connect(self):
        self.accept(self.modal("ConnectionSettingsDialog"))
        self.wait_for(lambda: self.session.transport.is_connected)
        self.move(self.session.connection_button)

    def step_identity(self):
        self.send("*IDN?")
        self.assert_rx("DEMO-001")
        self.move(self.session.command_input, QPoint(600, 105))

    def step_measurements(self):
        for command in ("MEAS:VOLT?", "MEAS:CURR?", "STAT?"):
            self.send(command)
        self.assert_rx("READY")
        self.move(self.session.command_input, QPoint(650, 225))

    def step_history(self):
        self.click(self.session.command_input)
        self.key("Up", self.session.command_input)
        self.wait_for(lambda: self.session.command_input.text().strip() == "STAT?")
        self.key("Return", self.session.command_input)

    def step_autocomplete(self):
        self.type(self.session.command_input, "MEAS:")
        self.key("Ctrl+Space", self.session.command_input)
        self.wait_for(lambda: self.session.command_input._completer.popup().isVisible())
        self.pause(2)
        self.key("Escape", self.session.command_input)
        self.key("Ctrl+End", self.session.command_input)
        self.key("Shift+Home", self.session.command_input)
        self.key("Backspace", self.session.command_input)

    def step_find(self):
        self.key("Ctrl+F", self.session.command_input)
        field = self.wait_for(lambda: next((w for w in self.session.findChildren(QLineEdit) if w.isVisible()), None))
        self.type(field, "MEAS")
        self.pause(1)
        self.key("Escape", field)

    def step_hex(self):
        self.choose(self.session.mode_combo, "Hex Bytes")
        self.send("70 69 6E 67 0D 0A")
        self.assert_rx("PONG")
        self.choose(self.session.mode_combo, "Text")

    def step_readback(self):
        self.send("VOLT 15")
        self.send("VOLT?")
        self.assert_rx("15.000")
        self.send("*RST")

    def step_saved_menu(self):
        self.menu("Tools", "Add Saved Command...")
        self.modal("QuickCommandDialog")

    def step_saved_fields(self):
        dialog = self.modal("QuickCommandDialog")
        self.type(dialog.label_input, "Identify")
        self.type(dialog.command_input, "*IDN?")
        self.type(dialog.group_input, "Tutorial")
        self.accept(dialog)
        self.wait_for(lambda: len(self.window.settings.quick_commands) == 1)

    def step_saved_send(self):
        self.rail("Saved Commands")
        self.row(self.window.shared_drawer.quick_command_list, action="send")
        self.assert_rx("Demo PSU")

    def step_favorite(self):
        self.row(self.window.shared_drawer.quick_command_list, action="star")
        self.wait_for(lambda: self.window.settings.quick_commands[0].favorite)
        self.rail("Favorites")

    def step_export_csv(self):
        self.menu("File", "Import / Export", "Export Saved Commands (CSV)...")
        self.file_dialog(LIVE / "saved-commands.csv", save=True)
        self.wait_for(lambda: (LIVE / "saved-commands.csv").exists())
        assert "*IDN?" in (LIVE / "saved-commands.csv").read_text(encoding="utf-8-sig")

    def step_open_editor(self):
        self.menu("File", "Open Command File Editor")
        self.file_dialog(LIVE / "files/first-check.cpz")
        self.editor = self.wait_for(self.window.current_command_file_editor)

    def step_edit_script(self):
        self.click(self.editor.editor)
        self.key("Ctrl+End", self.editor.editor)
        self.type(self.editor.editor, "\n# Repeatable voltage checks", replace=False)
        self.key("Ctrl+S", self.editor.editor)
        self.wait_for(lambda: not self.editor.is_dirty())

    def step_run_target(self):
        target = self.ui(lambda: self.editor.run_target_combo.currentText())
        self.choose(self.editor.run_target_combo, target)
        self.click(self.editor.run_button)
        self.modal("CommandFileParametersDialog")

    def step_parameter_pause(self):
        dialog = self.modal("CommandFileParametersDialog")
        self.type(dialog.inputs["COUNT"], "5")
        self.accept(dialog, "Start")
        self.wait_for(lambda: self.session.batch_runner.is_running)
        self.tab(self.session)
        self.click(self.session.script_pause_button)
        self.wait_for(lambda: self.session.script_resume_button.isVisible())

    def step_resume(self):
        self.click(self.session.script_resume_button)
        self.wait_for(lambda: not self.session.batch_runner.is_running, timeout=12)
        self.assert_rx("Completed 5 passing checks")

    def step_script_result(self):
        self.move(self.session.command_input, QPoint(650, 420))
        self.assert_rx("Completed 5 passing checks")

    def step_split(self):
        self.tab(self.editor)
        self.menu("View", "Split Right")
        self.wait_for(lambda: self.window.tabs.pane_count() == 2)
        handle = self.ui(lambda: self.window.tabs.splitter.handle(1))
        self.move(handle)
        self.ui(lambda: QTest.mousePress(handle, Qt.MouseButton.LeftButton))
        self.move(handle, self.ui(lambda: handle.rect().center() + QPoint(-80, 0)), 0.65)
        self.ui(lambda: QTest.mouseRelease(handle, Qt.MouseButton.LeftButton))
        self.ui(lambda: self.recorder.event("drag", widget="QSplitterHandle"))

    def step_palette(self):
        self.menu("Tools", "Command Palette")
        dialog = self.modal("CommandPaletteDialog")
        self.type(dialog.search_input, "Join Tabs")
        self.key("Return", dialog.search_input)
        self.wait_for(lambda: self.window.tabs.pane_count() == 1)

    def step_panel_manager(self):
        self.menu("Tools", "Control Panels...")
        self.modal("ControlPanelManagerDialog")

    def step_import_panel(self):
        dialog = self.modal("ControlPanelManagerDialog")
        self.click(dialog.import_button)
        self.file_dialog(ROOT / "examples/tutorial/control-panel.json")
        self.wait_for(lambda: len(self.window.settings.control_panels) == 1)

    def step_open_panel(self):
        dialog = self.modal("ControlPanelManagerDialog")
        self.row(dialog.list_widget)
        self.click(dialog.open_button)
        self.panel = self.wait_for(self.window.current_control_panel)
        self.wait_for(lambda: self.panel.grid._tiles["voltage"]._runtime is not None and self.panel.grid._tiles["voltage"]._runtime.value_text not in {"", "—"})

    def step_bind_panel(self):
        self.click(self.panel.bind_button)
        self.popup("Tutorial device", contains=True)
        self.wait_for(lambda: "Polling" in self.panel.bind_chip.text())

    def step_edit_tile(self):
        self.context(self.panel.grid._tiles["voltage"])
        self.popup("Edit", contains=True)
        self.modal("ControlPanelEntryDialog")

    def step_tile_fields(self):
        dialog = self.modal("ControlPanelEntryDialog")
        bar = self.ui(dialog.tabs.tabBar)
        self.click(bar, self.ui(lambda: bar.tabRect(dialog.POLLING_TAB).center()))
        self.type(self.ui(dialog.interval_spin.lineEdit), "750")
        self.accept(dialog)
        self.wait_for(lambda: self.panel.config.entries[0].interval_ms == 750)

    def step_poll(self):
        self.move(self.panel.grid._tiles["voltage"])
        self.pause(1)
        self.move(self.panel.grid._tiles["power"])

    def step_chart(self):
        self.click(self.panel.grid._tiles["voltage"], double=True)
        self.wait_for(lambda: self.panel.chart_entry_id == "voltage")
        self.choose(self.panel.chart_page.span_combo, "Last 1 minute")

    def step_chart_hover(self):
        chart = self.panel.chart_page.chart_view
        rect = self.ui(chart.rect)
        for fraction in (0.3, 0.5, 0.7, 0.9):
            self.move(chart, QPoint(round(rect.width() * fraction), round(rect.height() * 0.5)), 0.9)
        self.click(self.panel.chart_page.back_button)

    def step_fault(self):
        self.tab(self.session)
        self.send("DEMO:FAULT ON")
        self.tab(self.panel)
        self.wait_for(lambda: self.panel.grid._tiles["status"]._runtime.state == "fail")
        self.move(self.panel.grid._tiles["temperature"])

    def step_alerts(self):
        self.click(self.panel.bell_button)
        self.pause(1)
        self.click(self.panel.bell_button)

    def step_recover(self):
        self.tab(self.session)
        self.send("DEMO:FAULT OFF")
        self.tab(self.panel)
        self.wait_for(lambda: self.panel.grid._tiles["status"]._runtime.state == "ok")

    def step_arm(self):
        if self.ui(lambda: self.panel.arm_button.isChecked()):
            self.click(self.panel.arm_button)
            self.wait_for(lambda: not self.panel.arm_button.isChecked())
            self.pause(1)
        self.click(self.panel.arm_button)
        self.wait_for(lambda: self.panel.arm_button.isChecked())

    def step_output_off(self):
        tile = self.panel.grid._tiles["output-control"]
        self.click(tile.button)
        self.wait_for(lambda: not self.instrument.output)
        self.wait_for(lambda: self.panel.grid._tiles["output-state"]._runtime.value_number == 0)
        self.wait_for(lambda: not tile.pending and not tile.is_on and tile.button.isEnabled())

    def step_output_on(self):
        tile = self.panel.grid._tiles["output-control"]
        self.click(tile.button)
        self.wait_for(lambda: self.instrument.output)
        self.wait_for(lambda: self.panel.grid._tiles["output-state"]._runtime.value_number == 1)
        self.wait_for(lambda: not tile.pending and tile.is_on and tile.button.isEnabled())

    def step_setpoint(self):
        tile = self.panel.grid._tiles["set-voltage"]
        # Hit the actual text child, as a physical click does. Sending a click
        # directly to the outer spinbox can bubble into the tile's long-press
        # handler and enter layout editing before slower typing has finished.
        line = self.ui(tile.spin.lineEdit)
        self.click(line)
        self.key("Home", line)
        self.key("Shift+End", line)
        self.type(line, "15.0", replace=False, focus=False)
        self.wait_for(lambda: tile.spin.cleanText() == "15.0")
        self.key("Return", tile.spin)
        self.wait_for(lambda: self.instrument.voltage == 15.0)
        self.wait_for(lambda: not self.panel.edit_layout_button.isChecked())

    def step_disarm(self):
        self.click(self.panel.arm_button)
        self.wait_for(lambda: not self.panel.arm_button.isChecked())
        self.move(self.panel.grid._tiles["output-control"].button)

    def step_csv_log(self):
        self.click(self.panel.csv_log_button)
        self.file_dialog(LIVE / "measurements.csv", save=True)
        self.wait_for(lambda: self.panel.csv_log_button.isChecked())

    def step_csv_stop(self):
        # In a fast rehearsal leave enough real time for at least one poll cycle.
        time.sleep(1)
        self.click(self.panel.csv_log_button)
        self.wait_for(lambda: not self.panel.csv_log_button.isChecked())
        content = (LIVE / "measurements.csv").read_text(encoding="utf-8-sig")
        assert "kind" in content and "poll" in content

    def shell_command(self, text):
        if self.shell is None:
            def create():
                shell = ShellConsole(self.window)
                shell.setGeometry(0, 0, SOURCE_W, SOURCE_H)
                shell.show()
                shell.activateWindow()
                return shell
            self.shell = self.ui(create)
        self.type(self.shell.input, text, replace=False, delay=0.022)
        self.key("Return", self.shell.input)
        self.wait_for(lambda: not self.shell.running, timeout=20)
        assert self.ui(lambda: self.shell.exit_code) == 0

    def step_cli_query(self):
        self.shell_command('comport-zone --no-color send "*IDN?" --host 127.0.0.1 --read-after 500')
        self.wait_for(lambda: "DEMO-001" in self.shell.output.toPlainText())

    def step_cli_validate(self):
        self.shell_command("comport-zone --no-color validate examples/tutorial/first-check.cpz")

    def step_cli_run(self):
        self.shell_command("comport-zone --no-color run examples/tutorial/first-check.cpz --host 127.0.0.1 --param COUNT=3 --non-interactive")
        self.wait_for(lambda: "Completed 3 passing checks" in self.shell.output.toPlainText())

    def step_cli_udp(self):
        self.shell_command("comport-zone --no-color send ping --udp-host 127.0.0.1 --expect PONG")
        self.wait_for(lambda: "PONG" in self.shell.output.toPlainText())

    def step_return_app(self):
        self.click(self.shell.close_button)
        self.tab(self.session)
        self.send("*RST")
        self.tab(self.panel)

    def step_finish(self):
        self.tab(self.session)
        self.click(self.session.connection_button)
        self.wait_for(lambda: not self.session.transport.is_connected)


class ShellConsole(QDialog):
    """Recording terminal frontend; every entered line runs real PowerShell/CLI."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Windows PowerShell")
        self.setStyleSheet("QDialog { background:#0c1220; color:#edf2fb; } QPlainTextEdit,QLineEdit { background:#0c1220; color:#edf2fb; border:0; } QPushButton { color:#edf2fb; background:#192436; border:0; padding:8px; }")
        header = QHBoxLayout()
        title = QLabel("Windows PowerShell  /  ComPort Zone CLI", self)
        title.setFont(QFont("Segoe UI", 13))
        self.close_button = QPushButton("×", self)
        self.close_button.setAutoDefault(False)
        self.close_button.setDefault(False)
        self.close_button.clicked.connect(self.hide)
        header.addWidget(title, 1)
        header.addWidget(self.close_button)
        self.output = QPlainTextEdit(self)
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Consolas", 17))
        self.output.setPlainText("Windows PowerShell\nLocal tutorial device: 127.0.0.1:5025\n")
        self.input = QLineEdit(self)
        self.input.setFont(QFont("Consolas", 17))
        self.input.setPlaceholderText("Enter a command")
        row = QHBoxLayout()
        prompt = QLabel("PS> ", self)
        prompt.setFont(QFont("Consolas", 17))
        row.addWidget(prompt)
        row.addWidget(self.input, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 30)
        layout.addLayout(header)
        layout.addWidget(self.output, 1)
        layout.addLayout(row)
        self.process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONPATH", str(ROOT / "src"))
        environment.insert("PYTHONUTF8", "1")
        environment.insert("LOCALAPPDATA", str(LIVE / "cli-profile"))
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(ROOT))
        self.process.readyReadStandardOutput.connect(lambda: self.append(self.process.readAllStandardOutput()))
        self.process.readyReadStandardError.connect(lambda: self.append(self.process.readAllStandardError()))
        self.process.finished.connect(self.finished_command)
        self.input.returnPressed.connect(self.execute)
        self.running = False
        self.exit_code = 0

    def append(self, data):
        cursor = self.output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(bytes(data).decode("utf-8", errors="replace"))
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def execute(self):
        command = self.input.text()
        if not command or self.running:
            return
        self.output.appendPlainText("\nPS> " + command + "\n")
        self.input.clear()
        self.running = True
        self.input.setEnabled(False)
        # Bind the familiar command name to this checkout's actual CLI without
        # changing PATH, PowerShell profiles, or the user's application settings.
        executable = sys.executable.replace("'", "''")
        script = f"function comport-zone {{ & '{executable}' -m ComPort_Zone @args; exit $LASTEXITCODE }}\n{command}"
        self.process.start("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script])

    def finished_command(self, exit_code, _status):
        self.exit_code = exit_code
        self.running = False
        self.input.setEnabled(True)
        self.input.setFocus()


def ffmpeg_path(explicit):
    if explicit:
        return explicit
    if os.environ.get("COMPORT_ZONE_FFMPEG"):
        return os.environ["COMPORT_ZONE_FFMPEG"]
    if found := shutil.which("ffmpeg"):
        return found
    for folder in (WORK / "deps/imageio_ffmpeg/binaries", WORK / "venv/Lib/site-packages/imageio_ffmpeg/binaries"):
        found = list(folder.glob("ffmpeg*.exe"))
        if found:
            return str(found[0])
    raise ValueError("Pass --ffmpeg or set COMPORT_ZONE_FFMPEG to the media environment's FFmpeg binary.")


def main():
    global LIVE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rehearse", action="store_true", help="Drive every step quickly without recording")
    parser.add_argument("--pilot", action="store_true", help="Record the first eight actions")
    parser.add_argument("--check-step", help="Rehearse prerequisites quickly, then check one step at recording input speed")
    parser.add_argument("--ffmpeg")
    args = parser.parse_args()
    if args.check_step:
        args.rehearse = True
    if args.pilot:
        LIVE = WORK / "live-pilot"
        LIVE.mkdir(parents=True, exist_ok=True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)
    app = QApplication([])
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf", "consolab.ttf", "seguisym.ttf"):
        if QFontDatabase.addApplicationFont(str(fonts / name)) < 0:
            raise RuntimeError(f"Missing capture font: {name}")
    app.setFont(QFont("Segoe UI", 10))
    app.setQuitOnLastWindowClosed(False)
    if app.primaryScreen().geometry().width() < SOURCE_W:
        raise RuntimeError("The Qt offscreen screen configuration was not loaded; upgrade the app's PySide6 for recording.")
    if args.rehearse:
        story = json.loads((ROOT / "tools/media/storyboard.json").read_text(encoding="utf-8"))
        timeline = [{**s, "start": 0, "duration": 1, "captions": []} for s in story["scenes"]]
    else:
        timeline = json.loads((WORK / "timeline.json").read_text(encoding="utf-8"))
        narration = json.loads((WORK / "narration-manifest.json").read_text(encoding="utf-8"))
        if (narration.get("storyboard_sha256") != fingerprint(ROOT, ["tools/media/storyboard.json"])
            or narration.get("timeline_sha256") != sha256(WORK / "timeline.json")):
            raise RuntimeError("Narration is stale. Run build.py narrate before recording.")
    if args.pilot:
        timeline = timeline[:8]
    if args.check_step:
        ids = [s["id"] for s in timeline]
        if args.check_step not in ids:
            parser.error("Unknown step: " + args.check_step)
        timeline = timeline[:ids.index(args.check_step) + 1]
    files = LIVE / "files"
    files.mkdir(exist_ok=True)
    for name in ("saved-commands.csv", "measurements.csv"):
        (LIVE / name).unlink(missing_ok=True)
    shutil.copyfile(ROOT / "examples/tutorial/first-check.cpz", files / "first-check.cpz")
    settings_path = LIVE / "settings.json"
    app_module.default_config_path = lambda: settings_path
    settings = AppSettings(
        check_for_updates_on_launch=False, quick_commands=[], quick_files=[], control_panels=[],
        drawer_collapsed=False, drawer_width=275, terminal_font_size=14,
        control_panel_alert_sound=False,
        restored_tabs=[TerminalSessionState(title="Tutorial device", title_is_custom=True,
                                            transport_kind="lan", lan=LanProfile(host="127.0.0.1", port=5025, line_ending="CRLF"))],
    )
    assert SettingsService(SettingsStore(settings_path)).save(settings)
    with running_demo(5025) as (instrument, _):
        window = app_module.MainWindow(defer_startup_actions=True)
        window.setGeometry(0, 0, SOURCE_W, SOURCE_H)
        window.show()
        window.activateWindow()
        app.processEvents()
        recorder = LiveRecorder(app, window, None if args.rehearse else ffmpeg_path(args.ffmpeg), args.rehearse)
        driver = Driver(app, window, recorder, instrument, args.rehearse)
        def run():
            try:
                for scene in timeline:
                    driver.ui(lambda s=scene: recorder.begin(s))
                    print(f"Action {scene['id']}: {scene['title']}", flush=True)
                    driver.pause(0.7)
                    if scene["id"] == args.check_step:
                        driver.rehearse = False
                    driver.action(scene["id"])
                    if not args.rehearse:
                        remaining = scene["duration"] - driver.ui(lambda: recorder.now() - recorder.scene_start)
                        if remaining > 0:
                            time.sleep(remaining)
                    else:
                        driver.pause(0.4)
                    driver.ui(recorder.end)
            except BaseException:
                error = traceback.format_exc()
                print(error, flush=True)
                driver.ui(lambda: recorder.errors.append(error))
                driver.ui(lambda: recorder.render().save(str(LIVE / "failed-step.png")))
            finally:
                driver.ui(lambda: recorder.stop(sha256(WORK / "narration-manifest.json")))
                driver.ui(lambda: QTimer.singleShot(0, app.quit))
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        app.exec()
        thread.join(timeout=2)
        for panel in window.iter_control_panels():
            panel.shutdown()
        window.control_panel_runs.shutdown()
        for session in window.iter_sessions():
            session.shutdown()
        window.deleteLater()
        app.processEvents()
        if recorder.errors:
            raise SystemExit(1)
        print(f"Walkthrough complete: {len(recorder.steps)} actions; {recorder.frames} frames.", flush=True)


if __name__ == "__main__":
    main()
