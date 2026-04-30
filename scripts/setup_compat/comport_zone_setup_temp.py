"""Setup-only compatibility for Python 3.12 Windows temp directory ACLs."""

from __future__ import annotations

import errno
import os
import sys
import tempfile
from collections.abc import Iterable
from typing import Any


def _candidate_names(output_type: type[str] | type[bytes]) -> Iterable[str] | Iterable[bytes]:
    names = tempfile._get_candidate_names()  # type: ignore[attr-defined]
    if output_type is bytes:
        return map(os.fsencode, names)
    return names


def _mkdtemp_with_inherited_acl(suffix: Any = None, prefix: Any = None, dir: Any = None) -> str | bytes:
    prefix, suffix, dir, output_type = tempfile._sanitize_params(prefix, suffix, dir)  # type: ignore[attr-defined]
    names = _candidate_names(output_type)

    for _ in range(tempfile.TMP_MAX):
        name = next(names)
        path = os.path.join(dir, prefix + name + suffix)
        sys.audit("tempfile.mkdtemp", path)
        try:
            os.mkdir(path)
        except FileExistsError:
            continue
        except PermissionError:
            if os.name == "nt" and os.path.isdir(dir) and os.access(dir, os.W_OK):
                continue
            raise
        return os.path.abspath(path)

    raise FileExistsError(errno.EEXIST, "No usable temporary directory name found")


def enable_inherited_temp_acl() -> None:
    tempfile.mkdtemp = _mkdtemp_with_inherited_acl  # type: ignore[assignment]
