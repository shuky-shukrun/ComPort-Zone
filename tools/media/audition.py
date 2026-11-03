"""Create comparable local narration samples without changing release media.

Python 3.12, requirements-audition.txt, and CUDA PyTorch for Qwen are required.
Commands: download (stdlib only), kokoro, qwen, report. See README.md.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.media.build import configure_temp, spoken
from tools.media.common import sha256

WORK = Path(os.environ.get("COMPORT_ZONE_MEDIA_WORK", ROOT / "artifacts/user-guide")).resolve()
OUTPUT = WORK / "audition"
CONFIG = Path(__file__).with_name("audition.json")


def configuration():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def model_directory(config):
    return OUTPUT / "models" / config["qwen"]["revision"]


def download():
    """Pin the whole checkpoint and verify LFS SHA-256 before atomic rename."""
    config = configuration()
    model = config["qwen"]
    directory = model_directory(config)
    directory.mkdir(parents=True, exist_ok=True)
    api = f"https://huggingface.co/api/models/{model['repository']}/revision/{model['revision']}?blobs=true"
    with urlopen(Request(api, headers={"User-Agent": "ComPort-Zone-media"}), timeout=60) as response:
        metadata = json.load(response)
    if metadata["sha"] != model["revision"]:
        raise ValueError("Unexpected Qwen model revision")
    files = []
    for entry in metadata["siblings"]:
        name = entry["rfilename"]
        if name.startswith("."):
            continue
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        expected = entry.get("lfs", {}).get("sha256")
        size = entry.get("size")
        if path.is_file() and path.stat().st_size == size and (not expected or sha256(path) == expected):
            print(f"Verified {name}", flush=True)
        else:
            url = f"https://huggingface.co/{model['repository']}/resolve/{model['revision']}/{name}"
            print(f"Downloading {name}: {size or 0:,} bytes", flush=True)
            if expected and size:
                from tools.media.download_range import download as range_download
                range_download(url, path, size, expected)
            else:
                partial = path.with_name(path.name + ".part")
                with urlopen(Request(url, headers={"User-Agent": "ComPort-Zone-media"}), timeout=60) as response, partial.open("wb") as stream:
                    while block := response.read(1024 * 1024):
                        stream.write(block)
                if size and partial.stat().st_size != size:
                    raise ValueError(f"Qwen checkpoint failed integrity check: {name}")
                partial.replace(path)
        files.append({"name": name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    (directory / "download-receipt.json").write_text(json.dumps({**model, "files": files}, indent=2), encoding="utf-8")
    print("Qwen checkpoint download and verification complete", flush=True)


def candidate_identity(config, candidate):
    # Includes pronunciation code and renderer identity, not just visible text.
    return hashlib.sha256(json.dumps({"config": config, "candidate": candidate,
        "script": sha256(Path(__file__)), "pronunciation": sha256(ROOT / "tools/media/build.py")}, sort_keys=True).encode()).hexdigest()


def cached(config, candidate):
    path = OUTPUT / f"{candidate['id']}.json"
    if not path.is_file():
        return False
    receipt = json.loads(path.read_text())
    return (receipt.get("inputs_sha256") == candidate_identity(config, candidate)
            and {a["name"] for a in receipt.get("assets", [])} == {candidate["id"] + ".wav", candidate["id"] + ".mp3"}
            and all((OUTPUT / a["name"]).is_file() and sha256(OUTPUT / a["name"]) == a["sha256"] for a in receipt.get("assets", [])))


def save_sample(config, candidate, parts, rate, started, details):
    import imageio_ffmpeg
    import numpy as np
    import soundfile as sf

    audio = []
    for part in parts:
        part = np.asarray(part, dtype=np.float32).reshape(-1)
        if len(part) < rate or not np.isfinite(part).all() or np.max(np.abs(part)) < 0.001:
            raise ValueError("Empty or invalid speech output")
        audio.extend([part, np.zeros(round(rate * 0.3), dtype=np.float32)])
    joined = np.concatenate([np.zeros(round(rate * 0.3), dtype=np.float32), *audio])
    raw = OUTPUT / f"{candidate['id']}-raw.wav"
    final = OUTPUT / f"{candidate['id']}.wav"
    mp3 = final.with_suffix(".mp3")
    sf.write(raw, joined, rate, subtype="PCM_16")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(raw), "-af", "loudnorm=I=-19:TP=-1.5:LRA=9",
                    "-ar", "48000", "-ac", "1", str(final)], check=True)
    subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(final), "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)], check=True)
    info = sf.info(final)
    duration = info.frames / info.samplerate
    receipt = {"candidate": candidate, "inputs_sha256": candidate_identity(config, candidate),
               "duration_seconds": duration, "generation_seconds": time.perf_counter() - started,
               "target_seconds": config["target_seconds"], "within_target": config["target_seconds"][0] <= duration <= config["target_seconds"][1],
               "loudness_target_lufs": -19, "sample_rate": info.samplerate, "time_stretch": False,
               "details": details, "assets": [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha256(p)} for p in (final, mp3)]}
    (OUTPUT / f"{candidate['id']}.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(f"Created {candidate['id']}: {duration:.1f}s", flush=True)


def kokoro():
    import onnxruntime as ort
    from kokoro_onnx import Kokoro
    from tools.media.download_models import main as verify_models

    config = configuration()
    verify_models()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(WORK / "voice/kokoro-v1.0.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
    model = Kokoro.from_session(session, str(WORK / "voice/voices-v1.0.bin"))
    for candidate in (c for c in config["candidates"] if c["provider"] == "kokoro"):
        if cached(config, candidate):
            print(f"Cached {candidate['id']}", flush=True)
            continue
        started = time.perf_counter()
        parts = [model.create(spoken(p), voice=candidate["voice"], speed=candidate["speed"], lang="en-us")[0] for p in config["paragraphs"]]
        save_sample(config, candidate, parts, 24000, started, {"kokoro-onnx": importlib.metadata.version("kokoro-onnx"),
                    "model_sha256": sha256(WORK / "voice/kokoro-v1.0.onnx"), "voices_sha256": sha256(WORK / "voice/voices-v1.0.bin")})


def qwen():
    import torch
    from qwen_tts import Qwen3TTSModel

    config = configuration()
    directory = model_directory(config)
    receipt = json.loads((directory / "download-receipt.json").read_text())
    if receipt["revision"] != config["qwen"]["revision"] or any(sha256(directory / f["name"]) != f["sha256"] for f in receipt["files"]):
        raise ValueError("Qwen checkpoint changed; run the download command again")
    if not torch.cuda.is_available():
        raise RuntimeError("The Qwen audition requires CUDA PyTorch; follow README.md")
    torch.set_num_threads(4)
    print(f"Loading Qwen on {torch.cuda.get_device_name()}", flush=True)
    model = Qwen3TTSModel.from_pretrained(str(directory), device_map="cuda:0", dtype=torch.bfloat16,
                                       attn_implementation=config["qwen"]["attention"], local_files_only=True)
    for candidate in (c for c in config["candidates"] if c["provider"] == "qwen"):
        if cached(config, candidate):
            print(f"Cached {candidate['id']}", flush=True)
            continue
        torch.manual_seed(config["seed"])
        torch.cuda.reset_peak_memory_stats()
        started, parts, rate = time.perf_counter(), [], 24000
        for number, paragraph in enumerate(config["paragraphs"], 1):
            print(f"Generating {candidate['voice']}, paragraph {number}", flush=True)
            with torch.inference_mode():
                waves, rate = model.generate_custom_voice(text=spoken(paragraph), language="English", speaker=candidate["voice"],
                    instruct=config["qwen"]["instruction"], non_streaming_mode=True, max_new_tokens=1200)
            parts.append(waves[0])
        save_sample(config, candidate, parts, rate, started, {"model": config["qwen"], "gpu": torch.cuda.get_device_name(),
                    "peak_vram_bytes": torch.cuda.max_memory_allocated(), "torch": torch.__version__,
                    "qwen-tts": importlib.metadata.version("qwen-tts"), "seed": config["seed"]})


def report():
    config = configuration()
    lines = ["# English narration audition", "", "Same text for every candidate. Natural durations; no time stretching. Audio normalized to -19 LUFS.", "",
             "| Candidate | Seconds | Generation seconds | Target 45–60s |", "| --- | ---: | ---: | --- |"]
    for candidate in config["candidates"]:
        if not cached(config, candidate):
            raise ValueError(f"Missing or stale sample: {candidate['id']}")
        info = json.loads((OUTPUT / f"{candidate['id']}.json").read_text())
        lines.append(f"| {candidate['label']} | {info['duration_seconds']:.1f} | {info['generation_seconds']:.1f} | {info['within_target']} |")
    lines.extend(["", "## Passage", "", "\n\n".join(config["paragraphs"]), "", "## Listening notes", "",
                  "Compare clarity, acronym pronunciation, pauses, warmth, and consistency. These samples do not select a new production narrator.", ""])
    (OUTPUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["download", "kokoro", "qwen", "report"])
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    configure_temp()
    os.environ["HF_HOME"] = str(OUTPUT / "hf-cache")
    os.environ["HF_HUB_OFFLINE"] = "1"
    {"download": download, "kokoro": kokoro, "qwen": qwen, "report": report}[args.command]()


if __name__ == "__main__":
    main()
