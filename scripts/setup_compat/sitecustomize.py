"""Automatically apply setup compatibility patches to setup subprocesses."""

from __future__ import annotations

import os

if os.name == "nt" and os.environ.get("COMPORT_ZONE_SETUP_INHERIT_TEMP_ACL") == "1":
    from comport_zone_setup_temp import enable_inherited_temp_acl

    enable_inherited_temp_acl()
