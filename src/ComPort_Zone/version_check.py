from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

DEFAULT_HTTP_TIMEOUT_SECONDS = 8

GITHUB_REPOSITORY_URL = "https://github.com/shuky-shukrun/ComPort-Zone"
GITHUB_RELEASES_URL = f"{GITHUB_REPOSITORY_URL}/releases"
GITHUB_ISSUES_URL = f"{GITHUB_REPOSITORY_URL}/issues"
# REST API endpoint, kept for reference. Unauthenticated calls are capped at
# 60/hour/IP and return "HTTP 403: rate limit exceeded" once exceeded, so the
# app no longer uses it for the update check.
GITHUB_LATEST_RELEASE_API_URL = "https://api.github.com/repos/shuky-shukrun/ComPort-Zone/releases/latest"
# The releases Atom feed is served from github.com (not api.github.com) and is
# NOT subject to that per-IP API limit, so it is the default update-check source.
GITHUB_RELEASES_ATOM_URL = f"{GITHUB_REPOSITORY_URL}/releases.atom"

_VERSION_PATTERN = re.compile(r"\d+(?:\.\d+)*")
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


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


def release_info_from_atom(data: bytes | str) -> ReleaseInfo:
    """Parse the most recent release from a GitHub releases Atom feed.

    The feed's first ``<entry>`` is the latest release; its ``<title>`` is the
    release name and its alternate ``<link>`` / ``<id>`` carries the ``vX.Y.Z``
    tag. No GitHub REST API call (and therefore no API rate limit) is involved.
    """
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    root = ET.fromstring(raw)
    entry = root.find(f"{_ATOM_NS}entry")
    if entry is None:
        raise ValueError("Releases feed contained no entries.")
    name = (entry.findtext(f"{_ATOM_NS}title") or "").strip()
    link = entry.find(f"{_ATOM_NS}link")
    html_url = ((link.get("href") if link is not None else "") or "").strip()
    source = html_url or (entry.findtext(f"{_ATOM_NS}id") or "")
    tag_name = source.rstrip("/").rsplit("/", 1)[-1].strip() if source else ""
    version = clean_version_label(tag_name or name)
    if not version:
        raise ValueError("Latest release entry did not include a version tag.")
    return ReleaseInfo(
        tag_name=tag_name,
        name=name,
        version=version,
        html_url=html_url or GITHUB_RELEASES_URL,
    )


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
    url: str = GITHUB_RELEASES_ATOM_URL,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> ReleaseInfo:
    """Fetch + parse the latest GitHub release over HTTPS using Python's own
    SSL stack (``urllib``), from the releases **Atom feed**.

    Two deliberate choices:

    * **Atom feed, not the REST API.** ``api.github.com/.../releases/latest``
      caps unauthenticated requests at 60/hour/IP and then returns
      ``HTTP 403: rate limit exceeded``; the ``github.com/.../releases.atom``
      feed has no such per-IP cap, so the check can run on every launch.
    * **Off Qt's network path.** PySide6's ``QNetworkAccessManager`` loads the
      system OpenSSL, which can differ from the version Qt was built against and
      crash an HTTPS request with a native access violation. Python's ``ssl``
      uses its own consistent OpenSSL. Call this on a worker thread.
    """
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept": "application/atom+xml"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    return release_info_from_atom(body)


def describe_check_error(error: object) -> str:
    """Short, user-facing message for an update-check failure.

    Turns raw transport exceptions into plain language (rather than, e.g.,
    ``HTTP Error 403: rate limit exceeded``) for the GUI dialog.
    """
    if isinstance(error, urllib.error.HTTPError):
        if error.code == 403:
            return (
                "GitHub temporarily limited update checks from your network. "
                "Please try again in a little while."
            )
        if error.code == 404:
            return "No published release was found on GitHub."
        return f"GitHub returned HTTP {error.code}."
    if isinstance(error, urllib.error.URLError):
        return "Could not reach GitHub - check your internet connection."
    if isinstance(error, TimeoutError):
        return "The update check timed out. Please try again."
    text = str(error).strip()
    return text or "Unknown error."
