"""Standard-library metadata and fingerprints shared by media/release tools."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "shuky-shukrun/ComPort-Zone"
MANUAL_ASSET = "comport-zone-user-manual.pdf"
VIDEO_ASSETS = (
    "comport-zone-walkthrough.mp4",
    "comport-zone-walkthrough.srt",
    "comport-zone-walkthrough.chapters.txt",
    "comport-zone-walkthrough.transcript.md",
)
RECEIPT_ASSET = "comport-zone-media.json"
CHECKSUM_ASSET = "comport-zone-media.sha256"


def app_version(root: Path = ROOT) -> str:
    version = (root / "src/ComPort_Zone/VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise ValueError(f"Invalid application version: {version!r}")
    return version


def manual_metadata(root: Path = ROOT) -> dict:
    source = (root / "docs/USER_MANUAL.md").read_text(encoding="utf-8")
    match = re.search(r"\*\*English edition \| ComPort Zone ([0-9.]+) \| Reviewed (\d{4}-\d{2}-\d{2})\*\*", source)
    if not match:
        raise ValueError("Manual needs its version and ISO review date in the English edition header.")
    version, reviewed = match.groups()
    date.fromisoformat(reviewed)
    if version != app_version(root):
        raise ValueError(f"Manual describes {version}, but app VERSION is {app_version(root)}. Review and update the manual before release.")
    return {"version": version, "reviewed_on": reviewed}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fingerprint(root: Path, paths) -> str:
    records = []
    for relative in sorted(set(str(p).replace("\\", "/") for p in paths)):
        path = root / relative
        # Match Windows Git checkouts and LF checkouts for source text.
        if path.name == "pyproject.toml":
            project = tomllib.loads(path.read_text(encoding="utf-8"))
            project.get("project", {}).pop("version", None)
            digest = hashlib.sha256(json.dumps(project, sort_keys=True).encode()).hexdigest()
        elif path.suffix.lower() in {".py", ".md", ".json", ".txt", ".csv", ".cpz", ".toml"} or path.name == "VERSION":
            content = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode()
            digest = hashlib.sha256(content).hexdigest()
        else:
            digest = sha256(path)
        records.append([relative, digest])
    return hashlib.sha256(json.dumps(records, separators=(",", ":")).encode()).hexdigest()


def capture_paths(root: Path = ROOT) -> list[str]:
    paths = [p.relative_to(root).as_posix() for p in (root / "src/ComPort_Zone").rglob("*.py")]
    paths += [p.relative_to(root).as_posix() for p in (root / "src/ComPort_Zone/assets").glob("*") if p.is_file()]
    paths += [p.relative_to(root).as_posix() for p in (root / "examples/tutorial").glob("*") if p.is_file()]
    return paths + ["tools/media/capture.py", "tools/media/demo_device.py", "pyproject.toml"]


def capture_fingerprint(root: Path = ROOT) -> str:
    return fingerprint(root, capture_paths(root))


def video_fingerprint(root: Path = ROOT) -> str:
    # Runtime timestamps/measurements in newly captured PNGs are intentionally
    # excluded. Source changes trigger new captures; a version-only bump can reuse
    # a recording whose original version remains explicit in its release receipt.
    return fingerprint(root, capture_paths(root) + [
        "tools/media/build.py", "tools/media/common.py", "tools/media/storyboard.json",
        "tools/media/requirements.txt", "tools/media/requirements-pdf.txt", "tools/media/download_models.py",
    ])


def manual_fingerprint(root: Path = ROOT) -> str:
    source = (root / "docs/USER_MANUAL.md").read_text(encoding="utf-8")
    images = ["docs/" + p for p in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", source)]
    return fingerprint(root, images + [
        "docs/USER_MANUAL.md", "src/ComPort_Zone/VERSION",
        "tools/media/manual_pdf.py", "tools/media/common.py", "tools/media/requirements-pdf.txt",
    ])


def source_commit(root: Path = ROOT) -> str | None:
    result = subprocess.run(["git", "-c", f"safe.directory={root.as_posix()}", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def asset_info(path: Path, version: str, repository: str = REPOSITORY) -> dict:
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path),
            "url": f"https://github.com/{repository}/releases/download/v{version}/{path.name}"}
