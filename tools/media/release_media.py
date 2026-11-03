"""Plan, package, upload and verify documentation on an existing GitHub Release.

Planning/packaging are local unless --online retrieves the previous receipt.
Only the upload command mutates GitHub; it never creates a tag or app release.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.media.common import (
    CHECKSUM_ASSET, MANUAL_ASSET, RECEIPT_ASSET, REPOSITORY, VIDEO_ASSETS,
    app_version, asset_info, manual_fingerprint, manual_metadata, sha256,
    source_commit, video_fingerprint,
)

WORK = Path(os.environ.get("COMPORT_ZONE_MEDIA_WORK", ROOT / "artifacts/user-guide")).resolve()
ALLOWED_ASSETS = {MANUAL_ASSET, RECEIPT_ASSET, CHECKSUM_ASSET, *VIDEO_ASSETS}
NOTES_BEGIN = "<!-- comport-zone-media:start -->"
NOTES_END = "<!-- comport-zone-media:end -->"


def gh(*args) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"GitHub CLI failed: {args[0]}")
    return result.stdout


def repository_name(value: str) -> str:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", value):
        raise ValueError("Repository must be owner/name.")
    return value


def validate_previous(receipt: dict, repository: str) -> dict:
    if receipt.get("schema_version") != 1 or receipt.get("repository") != repository:
        raise ValueError("Previous media receipt has the wrong schema or repository.")
    video = receipt["video"]
    version = video["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Previous recording has an invalid version.")
    if not re.fullmatch(r"[a-f0-9]{64}", video["inputs_sha256"]):
        raise ValueError("Previous recording has an invalid source fingerprint.")
    assets = video["assets"]
    if {a["name"] for a in assets} != set(VIDEO_ASSETS) or len(assets) != len(VIDEO_ASSETS):
        raise ValueError("Previous recording is missing video/caption/transcript assets.")
    for asset in assets:
        expected = f"https://github.com/{repository}/releases/download/v{version}/{asset['name']}"
        if asset.get("url") != expected or not re.fullmatch(r"[a-f0-9]{64}", asset.get("sha256", "")):
            raise ValueError("Previous video asset URL or checksum is invalid.")
        if not isinstance(asset.get("bytes"), int) or asset["bytes"] <= 0:
            raise ValueError("Previous video asset size is invalid.")
    return receipt


def previous_online(repository: str, work: Path) -> dict | None:
    releases = json.loads(gh("api", f"repos/{repository}/releases?per_page=30"))
    # Includes the current tag on reruns, so unchanged reruns are idempotent.
    for release in releases:
        if release["draft"] or release["prerelease"]:
            continue
        if any(asset["name"] == RECEIPT_ASSET for asset in release["assets"]):
            destination = work / "previous-media.json"
            work.mkdir(parents=True, exist_ok=True)
            gh("release", "download", release["tag_name"], "--repo", repository,
               "--pattern", RECEIPT_ASSET, "--output", str(destination), "--clobber")
            return validate_previous(json.loads(destination.read_text(encoding="utf-8")), repository)
    return None


def make_plan(root: Path, repository: str, previous: dict | None = None, force=False) -> dict:
    metadata = manual_metadata(root)
    current = video_fingerprint(root)
    if previous is not None:
        validate_previous(previous, repository)
    rebuild = force or previous is None or previous["video"]["inputs_sha256"] != current
    return {"schema_version": 1, "repository": repository, "version": metadata["version"],
            "video_action": "rebuild" if rebuild else "reuse",
            "video_inputs_sha256": current,
            "previous_video": None if rebuild else previous["video"]}


def checked_build(root: Path, work: Path, kind: str, fingerprint: str) -> dict:
    path = work / f"{kind}-build.json"
    if not path.is_file():
        raise ValueError(f"Missing {kind} build receipt. Run tools/media/build.py {'pdf' if kind == 'manual' else 'video'}.")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("inputs_sha256") != fingerprint or result.get("version") != app_version(root):
        raise ValueError(f"Stale {kind}: source/version changed after the build. Rebuild before upload.")
    return result


def package(root: Path, work: Path, plan: dict) -> dict:
    version, repository = app_version(root), repository_name(plan["repository"])
    if plan["version"] != version:
        raise ValueError("Release plan version changed; plan again.")
    manual = checked_build(root, work, "manual", manual_fingerprint(root))
    output = root / "docs/media"
    if sha256(output / MANUAL_ASSET) != manual["asset"]["sha256"]:
        raise ValueError("PDF changed after its verified build.")
    manual["asset"] = asset_info(output / MANUAL_ASSET, version, repository)
    names = [MANUAL_ASSET]
    if plan["video_action"] == "rebuild":
        build = checked_build(root, work, "video", video_fingerprint(root))
        for asset in build["assets"]:
            if asset["name"] not in VIDEO_ASSETS or sha256(output / asset["name"]) != asset["sha256"]:
                raise ValueError("Recording changed after its verified build.")
        if {a["name"] for a in build["assets"]} != set(VIDEO_ASSETS):
            raise ValueError("Incomplete recording build.")
        video = {"version": version, "inputs_sha256": build["inputs_sha256"],
                 "narrator": build["narrator"],
                 "assets": [asset_info(output / name, version, repository) for name in VIDEO_ASSETS]}
        for key in ("format", "fps", "duration_seconds", "recording_sha256", "interaction_count"):
            if key in build:
                video[key] = build[key]
        names.extend(VIDEO_ASSETS)
    else:
        if plan["video_inputs_sha256"] != video_fingerprint(root):
            raise ValueError("Video inputs changed after the reuse plan; plan again.")
        video = plan["previous_video"]
        validate_previous({"schema_version": 1, "repository": repository, "video": video}, repository)
    staging = work / "publish"
    staging.mkdir(parents=True, exist_ok=True)
    # Only remove our specifically named old staging files, never whole directories.
    for name in ALLOWED_ASSETS:
        (staging / name).unlink(missing_ok=True)
    for name in names:
        shutil.copyfile(output / name, staging / name)
    receipt = {"schema_version": 1, "repository": repository, "app_version": version,
               "source_commit": source_commit(root), "manual": manual, "video": video,
               "video_rebuilt": plan["video_action"] == "rebuild",
               "uploads": names + [RECEIPT_ASSET, CHECKSUM_ASSET]}
    (staging / RECEIPT_ASSET).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    sums = "".join(f"{sha256(staging / name)}  {name}\n" for name in names + [RECEIPT_ASSET])
    (staging / CHECKSUM_ASSET).write_text(sums, encoding="utf-8")
    return receipt


def checked_package(staging: Path) -> dict:
    receipt = json.loads((staging / RECEIPT_ASSET).read_text(encoding="utf-8"))
    validate_previous(receipt, repository_name(receipt["repository"]))
    names = receipt["uploads"]
    if len(names) != len(set(names)) or not set(names) <= ALLOWED_ASSETS or not {MANUAL_ASSET, RECEIPT_ASSET, CHECKSUM_ASSET} <= set(names):
        raise ValueError("Unexpected release upload filenames.")
    checksums = {}
    for line in (staging / CHECKSUM_ASSET).read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        checksums[name] = digest
    if set(checksums) != set(names) - {CHECKSUM_ASSET}:
        raise ValueError("Incomplete release checksum file.")
    for name, expected in checksums.items():
        if sha256(staging / name) != expected:
            raise ValueError(f"Release checksum mismatch: {name}")
    return receipt


def notes_block(receipt: dict) -> str:
    video = {asset["name"]: asset["url"] for asset in receipt["video"]["assets"]}
    return "\n".join([
        NOTES_BEGIN, "## User manual and tutorial", "",
        f"- [PDF user manual for v{receipt['app_version']}]({receipt['manual']['asset']['url']})",
        f"- [English narrated walkthrough, recorded for v{receipt['video']['version']}]({video[VIDEO_ASSETS[0]]})",
        f"- [English captions]({video[VIDEO_ASSETS[1]]}) and [transcript]({video[VIDEO_ASSETS[3]]})",
        "", "The walkthrough is reused when its demonstrated workflows have not changed.", NOTES_END,
    ])


def updated_notes(body: str, receipt: dict) -> str:
    block = notes_block(receipt)
    if NOTES_BEGIN in body or NOTES_END in body:
        if body.count(NOTES_BEGIN) != 1 or body.count(NOTES_END) != 1:
            raise ValueError("Malformed media block in release notes; refusing to overwrite notes.")
        return re.sub(re.escape(NOTES_BEGIN) + r".*?" + re.escape(NOTES_END), lambda _: block, body, flags=re.S)
    return body.rstrip() + "\n\n" + block + "\n"


def remote_release(repository: str, tag: str) -> dict:
    release = json.loads(gh("api", f"repos/{repository}/releases/tags/{tag}"))
    if isinstance(release.get("body"), str):
        release["body"] = release["body"].replace("\r\n", "\n")
    return release


def verify(staging: Path, tag: str) -> dict:
    receipt = checked_package(staging)
    if tag != "v" + receipt["app_version"]:
        raise ValueError("Release tag does not match this manual/package version.")
    remote = remote_release(receipt["repository"], tag)
    releases = {tag: remote}
    expected = [(tag, name, (staging / name).stat().st_size, sha256(staging / name)) for name in receipt["uploads"]]
    if not receipt["video_rebuilt"]:
        video_tag = "v" + receipt["video"]["version"]
        if video_tag not in releases:
            releases[video_tag] = remote_release(receipt["repository"], video_tag)
        expected += [(video_tag, a["name"], a["bytes"], a["sha256"]) for a in receipt["video"]["assets"]]
    for asset_tag, name, size, digest in expected:
        assets = {a["name"]: a for a in releases[asset_tag]["assets"]}
        asset = assets.get(name)
        if not asset or asset["size"] != size:
            raise ValueError(f"Missing/wrong-sized release asset: {name}")
        if asset.get("digest"):
            if asset["digest"] != "sha256:" + digest:
                raise ValueError(f"Remote checksum mismatch: {name}")
        else:
            downloaded = staging.parent / f"verify-{name}"
            gh("release", "download", asset_tag, "--repo", receipt["repository"], "--pattern", name,
               "--output", str(downloaded), "--clobber")
            if sha256(downloaded) != digest:
                raise ValueError(f"Downloaded checksum mismatch: {name}")
    return remote


def upload(staging: Path, tag: str, replace=False) -> None:
    receipt = checked_package(staging)
    if tag != "v" + receipt["app_version"]:
        raise ValueError("Release tag does not match this manual/package version.")
    remote = remote_release(receipt["repository"], tag)
    if remote.get("immutable"):
        raise ValueError("Release is immutable. Publish the new media with a new release.")
    assets = {a["name"]: a for a in remote["assets"]}
    pending = []
    for name in receipt["uploads"]:
        asset = assets.get(name)
        if asset and asset.get("digest") == "sha256:" + sha256(staging / name):
            continue
        if asset and not replace:
            raise ValueError(f"Asset {name} already exists. Use --replace for an intentional media revision.")
        pending.append(str(staging / name))
    if pending:
        args = ["release", "upload", tag, *pending, "--repo", receipt["repository"]]
        if replace:
            args.append("--clobber")
        gh(*args)
    verify(staging, tag)
    body = updated_notes(remote.get("body") or "", receipt)
    notes_path = staging.parent / "release-notes-with-media.md"
    notes_path.write_text(body, encoding="utf-8", newline="\n")
    gh("release", "edit", tag, "--repo", receipt["repository"], "--notes-file", str(notes_path))
    if notes_block(receipt) not in (remote_release(receipt["repository"], tag).get("body") or ""):
        raise ValueError("Uploaded assets are verified, but the release download links did not persist.")
    print(f"Uploaded and checksum-verified media: {remote['html_url']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "package", "upload", "verify"])
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", REPOSITORY))
    parser.add_argument("--online", action="store_true", help="Read the previous published media receipt")
    parser.add_argument("--previous", type=Path, help="Local previous receipt, for offline planning")
    parser.add_argument("--video", choices=["auto", "always"], default="auto")
    parser.add_argument("--tag")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    repository = repository_name(args.repo)
    WORK.mkdir(parents=True, exist_ok=True)
    plan_path = WORK / "release-plan.json"
    if args.command == "plan":
        previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
        if args.online:
            previous = previous_online(repository, WORK)
        plan = make_plan(ROOT, repository, previous, force=args.video == "always")
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        print(f"PDF: rebuild from current Markdown. Video: {plan['video_action']}.")
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as stream:
                stream.write(f"rebuild_video={str(plan['video_action'] == 'rebuild').lower()}\n")
    elif args.command == "package":
        receipt = package(ROOT, WORK, json.loads(plan_path.read_text(encoding="utf-8")))
        print(f"Packaged {len(receipt['uploads'])} files for v{receipt['app_version']} in {WORK / 'publish'}")
    else:
        if not args.tag:
            parser.error("--tag is required for upload/verify")
        if args.command == "upload":
            upload(WORK / "publish", args.tag, args.replace)
        else:
            remote = verify(WORK / "publish", args.tag)
            print(f"Verified release assets: {remote['html_url']}")


if __name__ == "__main__":
    main()
