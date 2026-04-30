"""Run pip during development setup with Windows temp-directory compatibility.

Python 3.12 creates ``tempfile.mkdtemp()`` directories on Windows with a
restricted 0o700 ACL. Some OneDrive/sandboxed workspaces can create those
directories but then fail to write inside them. The setup script invokes pip
through this helper so pip temp directories inherit the parent temp ACL.
"""

from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys


def _enable_setup_compat() -> None:
    compat_path = Path(__file__).with_name("setup_compat")
    sys.path.insert(0, str(compat_path))
    from comport_zone_setup_temp import enable_inherited_temp_acl

    enable_inherited_temp_acl()


def main() -> int:
    if os.name == "nt" and os.environ.get("COMPORT_ZONE_SETUP_INHERIT_TEMP_ACL") == "1":
        _enable_setup_compat()

    sys.argv = ["pip", *sys.argv[1:]]
    runpy.run_module("pip", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
