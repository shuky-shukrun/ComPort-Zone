"""Pure timing/geometry helpers for the live tutorial recorder."""
from __future__ import annotations

import math


def camera_rect(width: int, height: int, zoom: float, x: float, y: float) -> tuple[float, float, float, float]:
    zoom = max(1.0, zoom)
    w, h = width / zoom, height / zoom
    return min(max(x - w / 2, 0), width - w), min(max(y - h / 2, 0), height - h), w, h


def ease(value: float, target: float, elapsed: float, time_constant: float = 0.22) -> float:
    return value + (target - value) * (1 - math.exp(-max(0, elapsed) / time_constant))


def frame_count(seconds: float, fps: int) -> int:
    return max(0, math.ceil(seconds * fps - 1e-8))


def rebased_captions(scene: dict, actual_start: float) -> list[dict]:
    shift = actual_start - scene["start"]
    return [{**cue, "start": cue["start"] + shift, "end": cue["end"] + shift} for cue in scene["captions"]]


def recording_errors(record: dict, scene_ids: list[str], version: str, fingerprint: str, narration_hash: str) -> list[str]:
    errors = list(record.get("errors", []))
    if record.get("version") != version or record.get("source_fingerprint") != fingerprint:
        errors.append("Recording source/version changed; record the walkthrough again.")
    if record.get("narration_sha256") != narration_hash:
        errors.append("Narration changed after recording; record again.")
    if [s["id"] for s in record.get("steps", [])] != scene_ids:
        errors.append("Recording is missing steps or has the wrong order.")
    previous_end = 0.0
    for step in record.get("steps", []):
        if step["start"] + 0.05 < previous_end or step["duration"] <= 0:
            errors.append(f"Invalid live timing: {step['id']}")
        previous_end = step["start"] + step["duration"]
    if record.get("frames", 0) <= 0 or record.get("fps", 0) != 30:
        errors.append("Recording must contain continuous 30 fps footage.")
    if record.get("duration", 0) + 1 / 30 < previous_end:
        errors.append("Recording ends before its final step.")
    return errors
