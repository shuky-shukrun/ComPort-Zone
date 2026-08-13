from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from pathlib import Path
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
    # Release notes as sanitized HTML (see :func:`sanitize_release_notes_html`),
    # and the release date as an ISO ``YYYY-MM-DD`` string. Both are empty when
    # the source did not carry them.
    notes_html: str = ""
    published: str = ""


@dataclass(frozen=True, slots=True)
class VersionCheckResult:
    current_version: str
    latest_version: str
    release_name: str
    release_url: str
    update_available: bool
    tag_name: str = ""
    # Every release newer than ``current_version``, newest first. When the local
    # build is more than one version behind, this holds all the skipped releases
    # so the update dialog can show their accumulated notes.
    releases: tuple[ReleaseInfo, ...] = ()


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


# Tags kept when sanitizing GitHub's rendered release notes. Limited to what
# Qt's rich-text engine actually renders, which is a small subset of HTML.
_ALLOWED_NOTE_TAGS = frozenset(
    {
        "a", "b", "blockquote", "br", "code", "dd", "del", "div", "dl", "dt",
        "em", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "li", "ol", "p",
        "pre", "s", "span", "strong", "sub", "sup", "table", "tbody", "td",
        "tfoot", "th", "thead", "tr", "u", "ul",
    }
)
_VOID_NOTE_TAGS = frozenset({"br", "hr", "img", "input", "meta", "link"})
# Tags whose *content* is dropped as well, not just their markup.
_DROPPED_NOTE_SUBTREES = frozenset({"script", "style", "head", "svg", "iframe", "object"})


class _ReleaseNotesSanitizer(HTMLParser):
    """Reduce GitHub's release-notes HTML to a safe, Qt-renderable subset.

    The notes come off the network, so nothing is passed through verbatim:
    every tag is either whitelisted or dropped (keeping its text), every
    attribute is discarded except ``href`` on links with an http(s) scheme,
    and images/scripts/styles are removed outright.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        # (source tag, emitted tag or None) for every open non-void element, so
        # a dropped tag's end tag is dropped too.
        self._open: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROPPED_NOTE_SUBTREES:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in _VOID_NOTE_TAGS:
            if tag in _ALLOWED_NOTE_TAGS:
                self._parts.append(f"<{tag}>")
            return
        emitted: str | None = tag if tag in _ALLOWED_NOTE_TAGS else None
        if emitted == "a":
            href = self._safe_href(attrs)
            if href:
                self._parts.append(f'<a href="{escape(href, quote=True)}">')
            else:
                emitted = None
        elif emitted is not None:
            self._parts.append(f"<{emitted}>")
        self._open.append((tag, emitted))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_NOTE_TAGS and tag not in _DROPPED_NOTE_SUBTREES:
            self.handle_endtag(tag)
        elif tag in _DROPPED_NOTE_SUBTREES:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROPPED_NOTE_SUBTREES:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth or tag in _VOID_NOTE_TAGS:
            return
        for index in range(len(self._open) - 1, -1, -1):
            if self._open[index][0] != tag:
                continue
            # Close the unclosed elements nested inside it as well.
            for _, emitted in reversed(self._open[index:]):
                if emitted:
                    self._parts.append(f"</{emitted}>")
            del self._open[index:]
            return

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(escape(data))

    @staticmethod
    def _safe_href(attrs: list[tuple[str, str | None]]) -> str:
        for name, value in attrs:
            if name.lower() != "href" or not value:
                continue
            href = value.strip()
            if href.lower().startswith(("http://", "https://")):
                return href
        return ""

    def result(self) -> str:
        for _, emitted in reversed(self._open):
            if emitted:
                self._parts.append(f"</{emitted}>")
        self._open.clear()
        return "".join(self._parts).strip()


def sanitize_release_notes_html(html: str) -> str:
    """Return ``html`` reduced to the tag/attribute subset the app will render.

    Release notes are remote content, so they are re-serialized from scratch
    rather than filtered in place: unknown tags lose their markup but keep
    their text, and only http(s) link targets survive.
    """
    if not html.strip():
        return ""
    parser = _ReleaseNotesSanitizer()
    parser.feed(html)
    parser.close()
    return parser.result()


def release_date_from_timestamp(value: str) -> str:
    """Extract the ``YYYY-MM-DD`` date from an Atom ``<updated>`` timestamp."""
    text = value.strip()
    return text[:10] if len(text) >= 10 and text[4] == "-" and text[7] == "-" else ""


def release_heading(release: ReleaseInfo) -> str:
    """Human-readable heading for one release section."""
    return release.name.strip() or release.tag_name.strip() or f"Version {release.version}"


# Each release's own headings are pushed below the per-release section heading
# the document adds, so the version banners stay the most prominent thing in an
# accumulated document. Qt sizes h1..h6 from the tag alone and ignores any CSS
# font-size for them, so the level itself is the only lever.
_NOTES_HEADING_LEVELS = {"h1": "h4", "h2": "h4", "h3": "h5", "h4": "h5", "h5": "h5", "h6": "h5"}
_HEADING_TAG_PATTERN = re.compile(r"<(/?)(h[1-6])>")


def _demote_note_headings(html: str) -> str:
    return _HEADING_TAG_PATTERN.sub(
        lambda match: f"<{match.group(1)}{_NOTES_HEADING_LEVELS[match.group(2)]}>", html
    )


def build_release_notes_document(releases: Sequence[ReleaseInfo]) -> str:
    """Accumulate the notes of every release in ``releases`` into one document.

    ``releases`` is expected newest-first, so a build that is several versions
    behind reads its way down through each skipped release in turn. The result
    is a rich-text fragment (already sanitized) for a scrollable viewer.
    """
    sections: list[str] = []
    for index, release in enumerate(releases):
        if index:
            sections.append("<hr/>")
        sections.append(f"<h3>{escape(release_heading(release))}</h3>")
        date = release_date_from_timestamp(release.published)
        meta = f"Released {escape(date)}" if date else ""
        if release.html_url:
            link = f'<a href="{escape(release.html_url, quote=True)}">Release page</a>'
            meta = f"{meta} &middot; {link}" if meta else link
        if meta:
            sections.append(f'<p class="releaseMeta">{meta}</p>')
        notes = _demote_note_headings(release.notes_html.strip())
        sections.append(notes or "<p><i>No release notes were published for this version.</i></p>")
    return "\n".join(sections)


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
        published=str(payload.get("published_at") or "").strip(),
    )


def release_info_from_json(data: bytes | str) -> ReleaseInfo:
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("Latest release response must be a JSON object.")
    return release_info_from_payload(payload)


def _release_info_from_atom_entry(entry: ET.Element) -> ReleaseInfo:
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
        notes_html=sanitize_release_notes_html(entry.findtext(f"{_ATOM_NS}content") or ""),
        published=(entry.findtext(f"{_ATOM_NS}updated") or "").strip(),
    )


def releases_from_atom(data: bytes | str) -> list[ReleaseInfo]:
    """Parse every release in a GitHub releases Atom feed, newest first.

    Each ``<entry>`` carries the release name in ``<title>``, the ``vX.Y.Z``
    tag in its alternate ``<link>`` / ``<id>``, and — the reason this reads the
    whole feed rather than just the first entry — the rendered release notes in
    ``<content type="html">``. Fetching them all lets a build that is several
    versions behind show every release it skipped. No GitHub REST API call (and
    therefore no API rate limit) is involved.
    """
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    root = ET.fromstring(raw)
    releases = [
        _release_info_from_atom_entry(entry) for entry in root.findall(f"{_ATOM_NS}entry")
    ]
    if not releases:
        raise ValueError("Releases feed contained no entries.")
    return releases


def release_info_from_atom(data: bytes | str) -> ReleaseInfo:
    """Parse the most recent release (the feed's first entry) from an Atom feed."""
    return releases_from_atom(data)[0]


def build_version_check_result(
    current_version: str, release: ReleaseInfo | Sequence[ReleaseInfo]
) -> VersionCheckResult:
    """Compare ``current_version`` against one release or a feed's worth of them.

    Given a sequence, the highest version wins the "latest" slot and *every*
    newer release is kept in :attr:`VersionCheckResult.releases` (newest first)
    so the update dialog can accumulate the notes of each skipped version.
    """
    releases = (release,) if isinstance(release, ReleaseInfo) else tuple(release)
    if not releases:
        raise ValueError("No releases to compare against.")
    ordered = sorted(releases, key=lambda item: version_segments(item.version), reverse=True)
    latest = ordered[0]
    newer = tuple(item for item in ordered if is_newer_version(item.version, current_version))
    return VersionCheckResult(
        current_version=clean_version_label(current_version),
        latest_version=latest.version,
        release_name=latest.name or latest.tag_name or f"Version {latest.version}",
        release_url=latest.html_url or GITHUB_RELEASES_URL,
        update_available=bool(newer),
        tag_name=latest.tag_name,
        releases=newer,
    )


def installer_asset_name(version: str) -> str:
    """Filename of the Windows installer asset published by the release workflow.

    Must track the naming in ``.github/workflows/release.yml``
    (``ComPort_Zone-$version-win64-setup.exe``).
    """
    return f"ComPort_Zone-{clean_version_label(version)}-win64-setup.exe"


def installer_download_url(tag_name: str, version: str) -> str:
    """Direct-download URL for the release's Windows installer asset.

    GitHub release asset URLs follow a predictable
    ``/releases/download/<tag>/<asset>`` shape, so this needs no REST API call
    (and therefore no API rate limit) beyond the Atom feed already used to
    learn ``tag_name``.
    """
    tag = tag_name.strip() or f"v{clean_version_label(version)}"
    return f"{GITHUB_REPOSITORY_URL}/releases/download/{tag}/{installer_asset_name(version)}"


class DownloadCancelled(Exception):
    """Raised when a caller-supplied cancel event is set mid-download."""


def download_installer(
    url: str,
    destination: Path,
    *,
    user_agent: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    chunk_size: int = 262_144,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Stream a GitHub release asset to ``destination``.

    Uses Python's own SSL stack (``urllib``), off Qt's network path, for the
    same reason as :func:`fetch_latest_release`. Call this on a worker
    thread. Writes to a ``.part`` sibling and renames on success so a failed
    or cancelled download never leaves a half-written file at ``destination``.
    ``progress_callback``, if given, is called as ``(bytes_downloaded,
    total_bytes)`` after each chunk; ``total_bytes`` is ``0`` when the server
    did not send a ``Content-Length``.
    """
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    part_path = destination.with_name(destination.name + ".part")
    downloaded = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            with open(part_path, "wb") as handle:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise DownloadCancelled("Download cancelled.")
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback is not None:
                        progress_callback(downloaded, total)
    except BaseException:
        part_path.unlink(missing_ok=True)
        raise
    part_path.replace(destination)
    return destination


def fetch_releases(
    *,
    user_agent: str,
    url: str = GITHUB_RELEASES_ATOM_URL,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> list[ReleaseInfo]:
    """Fetch + parse the published GitHub releases (newest first) over HTTPS
    using Python's own SSL stack (``urllib``), from the releases **Atom feed**.

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
    return releases_from_atom(body)


def fetch_latest_release(
    *,
    user_agent: str,
    url: str = GITHUB_RELEASES_ATOM_URL,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> ReleaseInfo:
    """Fetch just the most recent release. See :func:`fetch_releases`."""
    return fetch_releases(user_agent=user_agent, url=url, timeout=timeout)[0]


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
