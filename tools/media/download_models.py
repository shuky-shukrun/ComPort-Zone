"""Fetch the exact Kokoro v1.0 files used by the RDT reference workflow."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("COMPORT_ZONE_MEDIA_WORK", ROOT / "artifacts/user-guide")).resolve()
BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODELS = {
    "kokoro-v1.0.onnx": (325532387, "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5"),
    "voices-v1.0.bin": (28214398, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"),
}


def valid(path: Path, size: int, digest: str) -> bool:
    if not path.is_file() or path.stat().st_size != size:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == digest


def main() -> None:
    directory = WORK / "voice"
    directory.mkdir(parents=True, exist_ok=True)
    for name, (size, digest) in MODELS.items():
        destination = directory / name
        if valid(destination, size, digest):
            print(f"Verified {name}", flush=True)
            continue
        partial = directory / f"{name}.part"
        try:
            with urlopen(BASE + name, timeout=60) as response, partial.open("wb") as stream:
                while block := response.read(1024 * 1024):
                    stream.write(block)
            if not valid(partial, size, digest):
                raise RuntimeError(f"Model integrity check failed: {name}")
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)
        print(f"Downloaded and verified {name}", flush=True)


if __name__ == "__main__":
    main()
