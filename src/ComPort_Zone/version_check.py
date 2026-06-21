from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_HTTP_TIMEOUT_SECONDS = 8

GITHUB_REPOSITORY_URL = "https://github.com/shuky-shukrun/ComPort-Zone"
GITHUB_RELEASES_URL = f"{GITHUB_REPOSITORY_URL}/releases"
GITHUB_ISSUES_URL = f"{GITHUB_REPOSITORY_URL}/issues"
GITHUB_LATEST_RELEASE_API_URL = "https://api.github.com/repos/shuky-shukrun/ComPort-Zone/releases/latest"

_VERSION_PATTERN = re.compile(r"\d+(?:\.\d+)*")


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    tag_name: str
    name: str
    version: str
    html_url: str


@dataclass(frozen=True, slots=True)
class VersionCheckResult:
    current_version: str
    latest_version: str
    release_name: str
    release_url: str
    update_available: bool


def clean_version_label(value: str) -> str:
    text = value.strip()
    if len(text) > 1 and text[0] in {"v", "V"} and text[1].isdigit():
        return text[1:]
    return text


def version_segments(value: str) -> tuple[int, ...]:
    match = _VERSION_PATTERN.search(value.strip())
    if match is None:
        return ()
    return tuple(int(part) for part in match.group(0).split("."))


def compare_versions(left: str, right: str) -> int:
    left_segments = version_segments(left)
    right_segments = version_segments(right)
    if not left_segments or not right_segments:
        return 0
    width = max(len(left_segments), len(right_segments))
    padded_left = left_segments + (0,) * (width - len(left_segments))
    padded_right = right_segments + (0,) * (width - len(right_segments))
    if padded_left > padded_right:
        return 1
    if padded_left < padded_right:
        return -1
    return 0


def is_newer_version(candidate: str, current: str) -> bool:
    return compare_versions(candidate, current) > 0


def release_info_from_payload(payload: dict[str, Any]) -> ReleaseInfo:
    tag_name = str(payload.get("tag_name") or "").strip()
    name = str(payload.get("name") or "").strip()
    version = clean_version_label(tag_name or name)
    if not version:
        raise ValueError("Latest release payload did not include a version tag.")
    return ReleaseInfo(
        tag_name=tag_name,
        name=name,
        version=version,
        html_url=(
            str(payload.get("html_url") or GITHUB_RELEASES_URL).strip()
            or GITHUB_RELEASES_URL
        ),
    )


def release_info_from_json(data: bytes | str) -> ReleaseInfo:
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("Latest release response must be a JSON object.")
    return release_info_from_payload(payload)


def build_version_check_result(current_version: str, release: ReleaseInfo) -> VersionCheckResult:
    return VersionCheckResult(
        current_version=clean_version_label(current_version),
        latest_version=release.version,
        release_name=release.name or release.tag_name or f"Version {release.version}",
        release_url=release.html_url or GITHUB_RELEASES_URL,
        update_available=is_newer_version(release.version, current_version),
    )


def fetch_latest_release(
    *,
    user_agent: str,
    url: str = GITHUB_LATEST_RELEASE_API_URL,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> ReleaseInfo:
    """Fetch + parse the latest GitHub release over HTTPS using Python's
    own SSL stack (``urllib``).

    Deliberately kept off Qt's network path: PySide6's ``QNetworkAccessManager``
    loads the system OpenSSL, which can differ from the version Qt was built
    against and crash an HTTPS request with a native access violation.
    Python's ``ssl`` uses its own consistent OpenSSL, so this is stable —
    and the call belongs on a worker thread, never the GUI thread.
    """
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    return release_info_from_json(body)
