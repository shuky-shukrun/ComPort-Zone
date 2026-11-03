"""Resume large pinned downloads in bounded HTTP ranges; verify SHA-256."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, path, size, sha256, workers=4, chunk_size=8 * 1024 * 1024):
    path = Path(path)
    if path.is_file() and path.stat().st_size == size and digest(path) == sha256:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(json.dumps([url, size, sha256, chunk_size]).encode()).hexdigest()[:16]
    pieces = path.with_name(path.name + ".chunks-" + identity)
    pieces.mkdir(exist_ok=True)
    count = (size + chunk_size - 1) // chunk_size

    def fetch(index):
        start, end = index * chunk_size, min(size, (index + 1) * chunk_size) - 1
        target = pieces / f"{index:06d}"
        if target.is_file() and target.stat().st_size == end - start + 1:
            return target
        error = None
        for attempt in range(3):
            partial = target.with_suffix(".part")
            try:
                request = Request(url, headers={"Range": f"bytes={start}-{end}", "User-Agent": "ComPort-Zone-media"})
                with urlopen(request, timeout=30) as response, partial.open("wb") as stream:
                    if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{size}":
                        raise ValueError("Server did not honor the exact requested byte range")
                    remaining = end - start + 1
                    while remaining:
                        block = response.read(min(1024 * 1024, remaining))
                        if not block:
                            raise ValueError("Truncated range response")
                        stream.write(block)
                        remaining -= len(block)
                partial.replace(target)
                return target
            except (OSError, ValueError) as exc:
                error = exc
                time.sleep(attempt + 1)
        raise RuntimeError(f"Range {index} failed") from error

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for completed, _ in enumerate(pool.map(fetch, range(count)), 1):
            if completed % 16 == 0 or completed == count:
                print(f"{path.name}: {min(size, completed * chunk_size) / 1024**2:.0f}/{size / 1024**2:.0f} MiB", flush=True)
    assembled = path.with_name(path.name + ".verified-part")
    with assembled.open("wb") as output:
        for index in range(count):
            with (pieces / f"{index:06d}").open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    output.write(block)
    if assembled.stat().st_size != size or digest(assembled) != sha256:
        assembled.unlink(missing_ok=True)
        # A wrong complete digest can include a corrupt cached piece. Remove
        # only this download's explicitly numbered pieces before the next run.
        for index in range(count):
            (pieces / f"{index:06d}").unlink(missing_ok=True)
        raise ValueError("Completed download failed SHA-256 verification")
    assembled.replace(path)
    for index in range(count):
        (pieces / f"{index:06d}").unlink(missing_ok=True)
    pieces.rmdir()
    print(f"Verified SHA-256: {path.name}", flush=True)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("path", type=Path)
    parser.add_argument("--bytes", type=int, required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    download(args.url, args.path, args.bytes, args.sha256)
