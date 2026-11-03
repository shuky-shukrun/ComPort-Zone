"""Rebuild the manual PDF and captioned tutorial using local Kokoro narration.

python tools/media/build.py narrate
python tools/media/build.py video
python tools/media/build.py pdf

Use a Python 3.12 environment with requirements.txt. The app environment is used
separately by capture.py. All intermediates and models stay in MEDIA_WORK.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.media.common import app_version, asset_info, capture_fingerprint, fingerprint, sha256, video_fingerprint
WORK = Path(os.environ.get("COMPORT_ZONE_MEDIA_WORK", ROOT / "artifacts/user-guide")).resolve()
OUT = ROOT / "docs/media"
STORY = Path(__file__).with_name("storyboard.json")
SR = 24000
WIDTH, HEIGHT = 1920, 1080
FPS = 12
BACKGROUND = "#0c1220"
INK = "#edf2fb"
MUTED = "#9badc9"
ACCENT = "#50d69b"


def data():
    return json.loads(STORY.read_text(encoding="utf-8"))


def spoken(text):
    text = text.replace("ComPort Zone", "Com Port Zone")
    for token in ("TCP", "UDP", "GUI", "CLI", "CSV", "DTR", "RTS", "USB", "PC"):
        text = re.sub(rf"\b{token}\b", " ".join(token), text)
    return re.sub(r"\bJSON\b", "jay son", text)


def sentences(text):
    return [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]


def timestamp(seconds):
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def configure_temp():
    import tempfile
    temp = WORK / "tmp"
    temp.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = os.environ["TEMP"] = str(temp)
    tempfile.tempdir = str(temp)


def narrate(pilot=False):
    import numpy as np
    import onnxruntime as ort
    import soundfile as sf
    from kokoro_onnx import Kokoro

    configure_temp()
    story = data()
    voice = story["narrator"]
    model = WORK / "voice" / voice["model"]
    voices = WORK / "voice/voices-v1.0.bin"
    if not model.is_file() or not voices.is_file():
        raise SystemExit("Kokoro model files missing. Follow tools/media/README.md.")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
    narrator = Kokoro.from_session(session, str(voices))
    cache = WORK / "speech"
    cache.mkdir(exist_ok=True)
    timeline = []
    full_audio = []
    current = 0.0
    scenes = story["scenes"][:2] if pilot else story["scenes"]
    for scene in scenes:
        start = current
        captions = []
        scene_audio = [np.zeros(int(0.6 * SR), dtype=np.float32)]
        current += 0.6
        for sentence in sentences(scene["narration"]):
            normalized = spoken(sentence)
            key = hashlib.sha256(json.dumps([voice, normalized], sort_keys=True).encode()).hexdigest()[:24]
            path = cache / f"{key}.wav"
            if not path.exists():
                audio, sample_rate = narrator.create(normalized, voice=voice["voice"], speed=voice["speed"], lang=story["language"])
                if sample_rate != SR or not len(audio) or not np.isfinite(audio).all():
                    raise RuntimeError(f"Invalid narration for {scene['id']}")
                sf.write(path, audio, SR, subtype="PCM_16")
            audio, sample_rate = sf.read(path, dtype="float32")
            assert sample_rate == SR
            duration = len(audio) / SR
            # Break long sentences into readable cues; preserve spelling from the script.
            chunks = textwrap.wrap(sentence, width=84, break_long_words=False, break_on_hyphens=False)
            total_chars = sum(len(chunk) for chunk in chunks)
            cue_time = current
            for chunk in chunks:
                cue_duration = duration * len(chunk) / total_chars
                captions.append({"start": cue_time, "end": cue_time + cue_duration, "text": chunk})
                cue_time += cue_duration
            scene_audio.extend([audio, np.zeros(int(0.22 * SR), dtype=np.float32)])
            current += duration + 0.22
        scene_audio.append(np.zeros(int(0.8 * SR), dtype=np.float32))
        joined = np.concatenate(scene_audio)
        # Pad each scene to an exact video-frame boundary, avoiding cumulative A/V drift.
        duration = math.ceil(len(joined) / SR * FPS) / FPS
        target_samples = round(duration * SR)
        joined = np.pad(joined, (0, target_samples - len(joined)))
        current = start + duration
        sf.write(WORK / f"{scene['id']}.wav", joined, SR, subtype="PCM_16")
        full_audio.append(joined)
        timeline.append({**scene, "start": start, "duration": duration, "captions": captions})
        print(f"Narrated {scene['id']}: {duration:.1f}s", flush=True)
    suffix = "-pilot" if pilot else ""
    sf.write(WORK / f"narration{suffix}.wav", np.concatenate(full_audio), SR, subtype="PCM_16")
    (WORK / f"timeline{suffix}.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    metadata = {"narrator": voice, "sample_rate": SR, "duration_seconds": current,
                "app_version": app_version(ROOT),
                "storyboard_sha256": fingerprint(ROOT, ["tools/media/storyboard.json"]),
                "audio_sha256": sha256(WORK / f"narration{suffix}.wav"),
                "timeline_sha256": sha256(WORK / f"timeline{suffix}.json"),
                "scene_audio": {s["id"]: sha256(WORK / f"{s['id']}.wav") for s in timeline},
                "models": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (model, voices)}}
    (WORK / f"narration-manifest{suffix}.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Narration complete: {current / 60:.1f} minutes", flush=True)


def font(size, bold=False, mono=False):
    from PIL import ImageFont
    directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    filename = "consola.ttf" if mono else ("segoeuib.ttf" if bold else "segoeui.ttf")
    candidates = [directory / filename, Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise SystemExit("No rendering font found. Install Segoe UI or DejaVu Sans.")


CARDS = {
    "demo-card": ["# PowerShell, from the repository folder", "python tools/media/demo_device.py", "", "Tutorial device:", "TCP + UDP 127.0.0.1:5025", "", "Queries: *IDN?  MEAS:VOLT?  STAT?", "Stop the server with Ctrl+C"],
    "hex-card": ["# Text mode", "ping", "# Line ending: CRLF", "", "# Hex Bytes mode: the same payload", "70 69 6E 67 0D 0A", "", "# Expected reply", "PONG"],
    "cli-card": ["# PowerShell: query the local tutorial device", 'comport-zone send "*IDN?" --host 127.0.0.1 `', "  --tcp-port 5025 --line-ending CRLF --read-after 500", "", "# Validate, then run", "comport-zone validate examples/tutorial/first-check.cpz", "comport-zone run examples/tutorial/first-check.cpz `", "  --host 127.0.0.1 --tcp-port 5025 --line-ending CRLF `", "  --param COUNT=3 --non-interactive", "", "Expected: three passing checks; exit code 0"],
    "sharing-card": ["APPLICATION SETTINGS    JSON export", "SAVED COMMANDS          CSV export", "COMMAND FILES           .cpz files", "CONTROL PANELS          JSON export", "TRAFFIC                 Terminal log", "MEASUREMENTS            CSV value log", "", "A shortcut stores a path. Copy the actual file too."],
    "trouble-card": ["NO REPLY", "  Command, endpoint, line ending, flow control", "", "BUSY COM PORT", "  Disconnect another tab or close its owner", "", "SCRIPT RESPONSE FAILURE", "  Inspect RX, regex, and timeout", "", "PANEL PAUSED", "  Check binding, connection, and active script"],
}


def render_frame(scene, caption="", index=0, progress=0.0):
    from PIL import Image, ImageDraw, ImageOps
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((56, 36, 64, 116), 4, fill=ACCENT)
    draw.text((88, 30), "COMPORT ZONE / USER TUTORIAL", font=font(20, bold=True), fill=ACCENT)
    draw.text((88, 64), scene["title"], font=font(41, bold=True), fill=INK)
    draw.text((1450, 42), scene["chapter"], font=font(21), fill=MUTED)
    draw.text((1450, 76), f"ENGLISH  /  v{app_version(ROOT)}", font=font(19), fill=MUTED)
    draw.rounded_rectangle((56, 146, 1430, 938), 20, fill="#141e30")
    shot = scene["shot"]
    if shot in CARDS:
        y = 228
        for line in CARDS[shot]:
            draw.text((100, y), line, font=font(25, mono=True), fill=ACCENT if line.startswith("#") else INK)
            y += 46
    else:
        path = OUT / f"tutorial-{shot}.png"
        if scene.get("live"):
            candidate = WORK / "frames" / f"panel-{index % 48:03d}.png"
            if candidate.exists():
                path = candidate
        with Image.open(path) as source:
            screenshot = source.convert("RGB")
            # Crop large blank lower areas for terminal/editor detail scenes.
            if shot in {"terminal", "readback", "script-result", "history", "saved-commands", "editor"}:
                screenshot = screenshot.crop((0, 0, screenshot.width, min(screenshot.height, 800)))
            fitted = ImageOps.contain(screenshot, (1350, 760), Image.Resampling.LANCZOS)
            canvas.paste(fitted, (68 + (1350 - fitted.width) // 2, 162 + (760 - fitted.height) // 2))
    draw.text((1480, 175), "TRY IT YOURSELF", font=font(18, bold=True), fill=ACCENT)
    y = 234
    for number, note in enumerate(scene["notes"], 1):
        draw.text((1480, y), f"0{number}", font=font(21, bold=True), fill=ACCENT)
        y += 42
        for line in textwrap.wrap(note, width=27, break_long_words=False):
            draw.text((1480, y), line, font=font(24), fill=INK)
            y += 36
        y += 54
    draw.text((1480, 845), "LOCAL DEMO", font=font(18, bold=True), fill=ACCENT)
    draw.text((1480, 876), "No physical device required", font=font(20), fill=MUTED)
    draw.rectangle((56, 957, 1864, 960), fill="#26344b")
    draw.rectangle((56, 957, 56 + round(1808 * progress), 960), fill=ACCENT)
    lines = textwrap.wrap(caption, width=91, break_long_words=False)
    for line_number, line in enumerate(lines[:2]):
        box = draw.textbbox((0, 0), line, font=font(30))
        draw.text(((WIDTH - box[2]) / 2, 976 + line_number * 39), line, font=font(30), fill=INK)
    return canvas


def video(pilot=False):
    import imageio_ffmpeg
    from PIL import Image
    suffix = "-pilot" if pilot else ""
    timeline = json.loads((WORK / f"timeline{suffix}.json").read_text())
    narration_info = json.loads((WORK / f"narration-manifest{suffix}.json").read_text())
    expected = data()["scenes"][:2] if pilot else data()["scenes"]
    if (narration_info.get("app_version") != app_version(ROOT)
        or narration_info.get("storyboard_sha256") != fingerprint(ROOT, ["tools/media/storyboard.json"])
        or narration_info.get("audio_sha256") != sha256(WORK / f"narration{suffix}.wav")
        or narration_info.get("timeline_sha256") != sha256(WORK / f"timeline{suffix}.json")
        or len(timeline) != len(expected)
        or any(any(scene.get(k) != v for k, v in source.items()) for scene, source in zip(timeline, expected))
        or any(narration_info.get("scene_audio", {}).get(s["id"]) != sha256(WORK / f"{s['id']}.wav") for s in timeline)):
        raise SystemExit("Narration/timeline is stale or changed. Run build.py narrate before building this recording.")
    capture = json.loads((WORK / "capture-validation.json").read_text())
    if capture.get("source_fingerprint") != capture_fingerprint(ROOT) or capture.get("app_version") != app_version(ROOT):
        raise SystemExit("Capture is stale. Run tools/media/capture.py before building this recording.")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    clips = []
    all_captions = []
    chapters = []
    previous_chapter = None
    for scene in timeline:
        if scene["chapter"] != previous_chapter:
            chapters.append((scene["start"], scene["chapter"]))
            previous_chapter = scene["chapter"]
        all_captions.extend(scene["captions"])
        clip = WORK / f"{scene['id']}.mp4"
        # Reuse an encoded scene only when its full input identity is unchanged.
        shot = OUT / f"tutorial-{scene['shot']}.png"
        identity = json.dumps(scene, sort_keys=True) + (hashlib.sha256(shot.read_bytes()).hexdigest() if shot.exists() else "card")
        identity += hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        identity += hashlib.sha256((WORK / f"{scene['id']}.wav").read_bytes()).hexdigest()
        if scene.get("live"):
            identity += "".join(hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((WORK / "frames").glob("panel-*.png")))
        key = hashlib.sha256(identity.encode()).hexdigest()
        stamp = WORK / f"{scene['id']}.video.sha256"
        if not clip.exists() or not stamp.exists() or stamp.read_text() != key:
            command = [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-t", str(scene["duration"]), str(clip)]
            process = subprocess.Popen(command, stdin=subprocess.PIPE)
            try:
                cached = {}
                previous_caption = None
                for frame_index in range(round(scene["duration"] * FPS)):
                    local = frame_index / FPS
                    global_time = scene["start"] + local
                    caption = next((c["text"] for c in scene["captions"] if c["start"] <= global_time < c["end"]), "")
                    if caption != previous_caption:
                        cached.clear()
                        previous_caption = caption
                    live_index = min(47, int(local * 8)) if scene.get("live") else 0
                    cache_key = caption, live_index
                    if cache_key not in cached:
                        frame = render_frame(scene, caption, live_index, progress=scene["start"] / (timeline[-1]["start"] + timeline[-1]["duration"]))
                        cached[cache_key] = frame.tobytes()
                    process.stdin.write(cached[cache_key])
                process.stdin.close()
                if process.wait() != 0:
                    raise RuntimeError(f"Video encoding failed for {scene['id']}")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            stamp.write_text(key)
            # A clean representative frame for visual QA and a contact sheet.
            render_frame(scene, scene["captions"][0]["text"]).save(WORK / f"preview-{scene['id']}.png")
        clips.append(clip)
        print(f"Encoded {scene['id']}", flush=True)
    listing = WORK / "concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\nduration {scene['duration']:.9f}\n" for p, scene in zip(clips, timeline)), encoding="utf-8")
    destination = OUT / f"comport-zone-walkthrough{suffix}.mp4"
    total_duration = timeline[-1]["start"] + timeline[-1]["duration"]
    metadata = WORK / "chapters.ffmeta"
    metadata.write_text(";FFMETADATA1\ntitle=ComPort Zone user tutorial\n" + "".join(
        f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={round(start*1000)}\nEND={round((chapters[i+1][0] if i+1<len(chapters) else total_duration)*1000)}\ntitle={title}\n"
        for i, (start, title) in enumerate(chapters)), encoding="utf-8")
    narration = WORK / f"narration{suffix}.wav"
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(narration), "-i", str(metadata), "-map", "0:v", "-map", "1:a", "-map_metadata", "2", "-map_chapters", "2", "-metadata:s:a:0", "language=eng", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-af", "loudnorm=I=-19:TP=-1.5:LRA=9", "-ar", "48000", "-t", str(total_duration), "-movflags", "+faststart", str(destination)], check=True)
    srt = "".join(f"{i}\n{timestamp(c['start'])} --> {timestamp(c['end'])}\n" + "\n".join(textwrap.wrap(c["text"], width=46, break_long_words=False)) + "\n\n" for i, c in enumerate(all_captions, 1))
    destination.with_suffix(".srt").write_text(srt.rstrip() + "\n", encoding="utf-8")
    chapter_text = "\n".join(f"{int(t)//60:02}:{int(t)%60:02} {title}" for t, title in chapters)
    destination.with_suffix(".chapters.txt").write_text(chapter_text + "\n", encoding="utf-8")
    transcript = "# ComPort Zone tutorial transcript\n\n" + "\n\n".join(f"## {s['title']}\n\n{s['narration']}" for s in timeline)
    destination.with_suffix(".transcript.md").write_text(transcript + "\n", encoding="utf-8")
    previews = sorted(WORK.glob("preview-*.png"))
    contact = Image.new("RGB", (1440, math.ceil(len(previews) / 3) * 290), "#fff")
    for i, path in enumerate(previews):
        with Image.open(path) as im:
            im.thumbnail((480, 270))
            contact.paste(im, ((i % 3) * 480, (i // 3) * 290))
    contact.save(WORK / "video-contact-sheet.png")
    info = {"version": app_version(ROOT), "inputs_sha256": video_fingerprint(ROOT), "narrator": data()["narrator"], "assets": [asset_info(destination.with_suffix(ext), app_version(ROOT)) for ext in (".mp4", ".srt", ".chapters.txt", ".transcript.md")]}
    (WORK / "video-build.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"Created {destination}", flush=True)


def pdf():
    from tools.media.manual_pdf import build_pdf
    build_pdf()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["narrate", "video", "pdf"])
    parser.add_argument("--pilot", action="store_true", help="Build the first two scenes only")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    if args.command == "narrate":
        narrate(args.pilot)
    elif args.command == "video":
        video(args.pilot)
    else:
        pdf()


if __name__ == "__main__":
    main()
