"""Rebuild the manual PDF and captioned tutorial using local Kokoro narration.

python tools/media/build.py narrate
python tools/media/build.py video
python tools/media/build.py pdf

Use a Python 3.12 environment with requirements.txt. The app environment is used
separately by capture.py and walkthrough.py. All intermediates and models stay in MEDIA_WORK.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.media.common import app_version, fingerprint, sha256
WORK = Path(os.environ.get("COMPORT_ZONE_MEDIA_WORK", ROOT / "artifacts/user-guide")).resolve()
OUT = ROOT / "docs/media"
STORY = Path(__file__).with_name("storyboard.json")
SR = 24000
FPS = 30


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


def video(pilot=False):
    from tools.media.assemble_live import assemble
    assemble(ROOT, WORK, data(), pilot=pilot)


def pdf():
    from tools.media.manual_pdf import build_pdf
    build_pdf()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["narrate", "video", "pdf"])
    parser.add_argument("--pilot", action="store_true", help="Build a short preview (record the first eight steps with walkthrough.py --pilot)")
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    if args.command == "narrate":
        if args.pilot:
            parser.error("Generate full narration first; --pilot applies only to video assembly.")
        narrate()
    elif args.command == "video":
        video(args.pilot)
    else:
        pdf()


if __name__ == "__main__":
    main()
