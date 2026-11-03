"""Check manual currency, links, binary policy, and the PR's explicit review.

python tools/media/check_docs.py
python tools/media/check_docs.py --event <GitHub event JSON>
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.media.common import manual_metadata

USER_DOCS = {"docs/USER_MANUAL.md", "docs/CLI_REFERENCE.md", "docs/COMMAND_FILES.md"}


def forbidden_asset(name: str) -> bool:
    path = Path(name)
    return (
        path.suffix.lower() in {".mp4", ".webm", ".mov", ".onnx"}
        or name == "docs/media/comport-zone-user-manual.pdf"
        or path.name == "voices-v1.0.bin"
        or (name.startswith("docs/media/") and path.suffix.lower() in {".wav", ".mp3"})
    )


def review_errors(body: str, changed: list[str]) -> list[str]:
    errors = []
    # Comments in the template must not satisfy the checked review or notes.
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    if not re.search(r"(?im)^\s*-\s*\[[xX]\]\s*User manual reviewed\s*$", body):
        errors.append("Check 'User manual reviewed' after reviewing the affected workflows.")
    impact = re.search(r"(?im)^Manual impact:\s*(updated|none)\s*$", body)
    notes = re.search(r"(?im)^Manual review notes:\s*(.+)$", body)
    if not impact:
        errors.append("Set 'Manual impact: updated' or 'Manual impact: none' in the PR body.")
    if not notes or len(notes.group(1).strip()) < 15 or "<" in notes.group(1):
        errors.append("Add meaningful 'Manual review notes:' describing the updated sections or why behavior is unchanged.")
    if impact and impact.group(1).lower() == "updated" and not any(p in USER_DOCS for p in changed):
        errors.append("Manual impact is 'updated', but no user-manual, scripting-guide, or CLI-reference changes are in the PR.")
    return errors


def local_link_errors(root: Path, name: str) -> list[str]:
    errors = []
    text = (root / name).read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^)]+)\)", text):
        if target.startswith(("https://", "http://", "#", "mailto:")):
            continue
        path = target.split("#", 1)[0]
        if path and not (root / name).parent.joinpath(path).exists():
            errors.append(f"{name}: missing local link target {target}")
    return errors


def git_lines(root: Path, *args) -> list[str]:
    result = subprocess.run(["git", "-c", f"safe.directory={root.as_posix()}", *args], cwd=root, capture_output=True, text=True, check=True)
    return [line for line in result.stdout.split("\0") if line]


def verify_pdf(path: Path, root: Path = ROOT) -> None:
    from pypdf import PdfReader
    reader = PdfReader(path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    version = manual_metadata(root)["version"]
    if len(reader.pages) < 10 or len(text) < 10000 or f"v{version}" not in text:
        raise ValueError("PDF is incomplete, unreadable, or stamped with the wrong version.")
    if len(reader.outline) < 12 or not any(page.images for page in reader.pages):
        raise ValueError("PDF is missing chapter bookmarks or illustrations.")
    print(f"Verified searchable, illustrated PDF: {len(reader.pages)} pages, version {version}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", type=Path)
    parser.add_argument("--pdf", type=Path)
    args = parser.parse_args()
    errors = []
    try:
        metadata = manual_metadata(ROOT)
        print(f"Manual reviewed for v{metadata['version']} on {metadata['reviewed_on']}")
    except ValueError as exc:
        errors.append(str(exc))
    for name in ("README.md", "docs/USER_MANUAL.md", "tools/media/README.md"):
        errors.extend(local_link_errors(ROOT, name))
    tracked = git_lines(ROOT, "ls-files", "-z")
    errors += [f"Generated release asset must not be committed: {name}" for name in tracked if forbidden_asset(name)]
    if args.event:
        event = json.loads(args.event.read_text(encoding="utf-8"))
        if pr := event.get("pull_request"):
            # The base comes from GitHub's event, and goes to git as an argument,
            # never to a shell. Diff the PR head even on edited-body events.
            base, head = pr["base"]["sha"], pr["head"]["sha"]
            if not all(re.fullmatch(r"[0-9a-fA-F]{40,64}", ref) for ref in (base, head)):
                raise ValueError("Invalid PR commit SHA in event.")
            changed = git_lines(ROOT, "diff", "--name-only", "-z", f"{base}...{head}")
            errors.extend(review_errors(pr.get("body") or "", changed))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    if args.pdf:
        verify_pdf(args.pdf)
    print("Documentation links, version, and tracked-asset policy passed.")


if __name__ == "__main__":
    main()
