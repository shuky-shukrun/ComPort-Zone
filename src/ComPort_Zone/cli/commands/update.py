"""`comport-zone update check` — query the GitHub releases API.

Mirrors the GUI's Help-menu update check using
:mod:`ComPort_Zone.core.version_check`. Per spec, the command always
exits 0 — network failures and stale builds are reported via output,
not exit code, so scripts that schedule a periodic check never crash.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import click

from ... import __version__ as APP_VERSION
from ...core.version_check import (
    GITHUB_LATEST_RELEASE_API_URL,
    GITHUB_RELEASES_URL,
    build_version_check_result,
    release_info_from_json,
)
from ..output import CliOutput


_USER_AGENT = f"ComPort-Zone-CLI/{APP_VERSION}"
_HTTP_TIMEOUT_SECONDS = 8


def _fetch_latest_release_body(url: str) -> bytes:
    """Fetch the GitHub Releases API response.

    Wrapped in a thin helper so tests can monkey-patch this one symbol
    instead of monkey-patching ``urllib`` at large.
    """
    request = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
        return response.read()


def _emit_network_error(output: CliOutput, exc: Exception) -> None:
    """Emit a friendly status / JSON record without exit-coding the run.

    Per spec, ``update check`` always exits 0 — a script polling for
    updates shouldn't crash because GitHub is briefly unreachable.
    """
    message = f"Could not reach GitHub: {exc}"
    payload: dict[str, Any] = {
        "current_version": APP_VERSION,
        "latest_version": "",
        "update_available": False,
        "release_url": GITHUB_RELEASES_URL,
        "network_error": str(exc),
    }
    if output.json_mode:
        output.object(payload)
    else:
        output.status(message)
        click.echo(f"current_version: {APP_VERSION}")


@click.group("update")
def update_group() -> None:
    """Check for new releases on GitHub."""


@update_group.command("check")
@click.pass_context
def update_check(ctx: click.Context) -> None:
    """Compare the local build against the latest GitHub release."""
    output: CliOutput = ctx.obj["output"]
    try:
        body = _fetch_latest_release_body(GITHUB_LATEST_RELEASE_API_URL)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        _emit_network_error(output, exc)
        return

    try:
        release = release_info_from_json(body)
    except (ValueError, json.JSONDecodeError) as exc:
        _emit_network_error(output, exc)
        return

    result = build_version_check_result(APP_VERSION, release)
    payload: dict[str, Any] = {
        "current_version": result.current_version,
        "latest_version": result.latest_version,
        "release_name": result.release_name,
        "release_url": result.release_url,
        "update_available": result.update_available,
    }
    output.object(payload)
