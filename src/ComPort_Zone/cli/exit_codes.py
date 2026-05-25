"""Stable numeric exit codes for the CLI.

The values are part of the public contract - scripts and CI runners rely
on them. Don't renumber without coordinating with the documented CLI spec.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    GENERIC_ERROR = 1
    USAGE_ERROR = 2  # Click already exits with 2 on bad flags; we mirror.
    PORT_BUSY = 10
    EXPECT_FAILED = 11
    MISSING_PARAM = 12
    PARSE_ERROR = 13
    PORT_NOT_FOUND = 14
    SETTINGS_ERROR = 15
    INTERRUPTED = 130


# Symbolic names emitted in JSON error events. Mapping kept here so the
# numeric exit code and the JSON code string stay in lockstep.
EXIT_CODE_NAMES: dict[ExitCode, str] = {
    ExitCode.OK: "OK",
    ExitCode.GENERIC_ERROR: "GENERIC_ERROR",
    ExitCode.USAGE_ERROR: "USAGE_ERROR",
    ExitCode.PORT_BUSY: "PORT_BUSY",
    ExitCode.EXPECT_FAILED: "EXPECT_FAILED",
    ExitCode.MISSING_PARAM: "MISSING_PARAM",
    ExitCode.PARSE_ERROR: "PARSE_ERROR",
    ExitCode.PORT_NOT_FOUND: "PORT_NOT_FOUND",
    ExitCode.SETTINGS_ERROR: "SETTINGS_ERROR",
    ExitCode.INTERRUPTED: "INTERRUPTED",
}
