"""Mux continuous GUI footage with narration aligned to actual action times."""
from __future__ import annotations

import json
import subprocess
import textwrap

from tools.media.common import app_version, asset_info, fingerprint, sha256, video_fingerprint
from tools.media.live_timing import rebased_captions, recording_errors


def assemble(root, work, story, pilot=False):
    import imageio_ffmpeg
    import numpy as np
    import soundfile as sf
    from tools.media.build import timestamp

    suffix = "-pilot" if pilot else ""
    # Pilots use the full narration timeline but record only its first eight steps.
    timeline = json.loads((work / "timeline.json").read_text())
    narration = json.loads((work / "narration-manifest.json").read_text())
    expected = story["scenes"]
    if (narration.get("app_version") != app_version(root)
        or narration.get("storyboard_sha256") != fingerprint(root, ["tools/media/storyboard.json"])
        or narration.get("audio_sha256") != sha256(work / "narration.wav")
        or narration.get("timeline_sha256") != sha256(work / "timeline.json")
        or len(timeline) != len(expected)
        or any(any(scene.get(k) != v for k, v in source.items()) for scene, source in zip(timeline, expected))
        or any(narration.get("scene_audio", {}).get(s["id"]) != sha256(work / f"{s['id']}.wav") for s in timeline)):
        raise ValueError("Narration/timeline changed. Run build.py narrate, then record again.")
    timeline = timeline[:8] if pilot else timeline
    live = work / ("live-pilot" if pilot else "live")
    record = json.loads((live / "recording.json").read_text())
    errors = recording_errors(record, [s["id"] for s in timeline], app_version(root),
                              video_fingerprint(root), sha256(work / "narration-manifest.json"))
    footage = live / "silent.mp4"
    if record.get("rehearsal") or record.get("recording_sha256") != sha256(footage):
        errors.append("Continuous footage is missing or changed.")
    if errors:
        raise ValueError("\n".join(errors))
    rate = narration["sample_rate"]
    audio = np.zeros(round(record["duration"] * rate), dtype=np.float32)
    captions, chapters = [], []
    previous_chapter = None
    for scene, actual in zip(timeline, record["steps"]):
        samples, sr = sf.read(work / f"{scene['id']}.wav", dtype="float32")
        if sr != rate or actual["duration"] + 0.05 < len(samples) / rate:
            raise ValueError(f"Recording cut off narration: {scene['id']}")
        start = round(actual["start"] * rate)
        if start + len(samples) > len(audio):
            raise ValueError("Narration extends beyond the recording.")
        audio[start:start + len(samples)] = samples
        captions.extend(rebased_captions(scene, actual["start"]))
        if scene["chapter"] != previous_chapter:
            chapters.append((0.0 if not chapters else actual["start"], scene["chapter"]))
            previous_chapter = scene["chapter"]
    aligned = live / "aligned-narration.wav"
    sf.write(aligned, audio, rate, subtype="PCM_16")
    metadata = live / "chapters.ffmeta"
    metadata.write_text(";FFMETADATA1\ntitle=ComPort Zone hands-on tutorial\n" + "".join(
        f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={round(start*1000)}\n"
        f"END={round((chapters[i+1][0] if i+1<len(chapters) else record['duration'])*1000)}\ntitle={title}\n"
        for i, (start, title) in enumerate(chapters)), encoding="utf-8")
    destination = root / f"docs/media/comport-zone-walkthrough{suffix}.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-v", "error", "-i", str(footage),
                    "-i", str(aligned), "-i", str(metadata), "-map", "0:v", "-map", "1:a",
                    "-map_metadata", "2", "-map_chapters", "2", "-metadata:s:a:0", "language=eng",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-af", "loudnorm=I=-19:TP=-1.5:LRA=9",
                    "-ar", "48000", "-t", str(record["duration"]), "-movflags", "+faststart", str(destination)], check=True)
    srt = "".join(f"{i}\n{timestamp(c['start'])} --> {timestamp(c['end'])}\n" +
                  "\n".join(textwrap.wrap(c["text"], width=46, break_long_words=False)) + "\n\n"
                  for i, c in enumerate(captions, 1))
    destination.with_suffix(".srt").write_text(srt.rstrip() + "\n", encoding="utf-8")
    destination.with_suffix(".chapters.txt").write_text("".join(
        f"{int(t)//60:02}:{int(t)%60:02} {title}\n" for t, title in chapters), encoding="utf-8")
    destination.with_suffix(".transcript.md").write_text("# ComPort Zone hands-on tutorial transcript\n\n" +
        "\n\n".join(f"## {s['title']}\n\n{s['narration']}" for s in timeline) + "\n", encoding="utf-8")
    info = {"version": app_version(root), "inputs_sha256": video_fingerprint(root),
            "narrator": story["narrator"], "format": "live-gui", "fps": 30,
            "duration_seconds": record["duration"], "recording_sha256": sha256(footage),
            "interaction_count": len(record["events"]),
            "assets": [asset_info(destination.with_suffix(ext), app_version(root))
                       for ext in (".mp4", ".srt", ".chapters.txt", ".transcript.md")]}
    (work / f"video-build{suffix}.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"Created {destination}: {record['duration']:.1f}s, {len(record['events'])} interactions", flush=True)
