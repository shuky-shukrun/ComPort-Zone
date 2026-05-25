"""`comport-zone validate <file>` — parse-check a command file.

Reports BatchParseError occurrences (malformed HEX, EXPECT with no
argument, etc.). Parameter placeholders are substituted with their
defaults where present and a harmless stub string elsewhere so the
parser can run without prompting the user. Exit 0 when clean, 13 when
issues were found.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import click

from ...core.batch import (
    BatchParseError,
    find_batch_parameters,
    parse_batch_line,
    parse_batch_template,
    substitute_batch_parameters,
)
from ..exit_codes import ExitCode
from ..output import CliOutput


@dataclass(slots=True)
class _Issue:
    line_number: int
    line: str
    message: str

    def as_dict(self) -> dict[str, object]:
        return {
            "line_number": self.line_number,
            "line": self.line,
            "message": self.message,
        }


# Stand-in value substituted for required parameters that have no
# default. Anything non-empty keeps the parser happy so EXPECT/HEX
# malformations elsewhere on the same line still surface.
_PLACEHOLDER = "_"


def _build_substitution_values(text: str) -> dict[str, str]:
    """Pre-populate a values dict using defaults + placeholders so the
    no-prompt substitution always succeeds.
    """
    values: dict[str, str] = {}
    for occurrence in find_batch_parameters(text):
        if occurrence.name in values:
            continue
        values[occurrence.name] = occurrence.default if occurrence.default is not None else _PLACEHOLDER
    return values


def _silent_prompt(name: str, line_number: int, line_text: str) -> str | None:
    # Should never be called — _build_substitution_values prefills every name.
    return _PLACEHOLDER


def _collect_issues(text: str) -> list[_Issue]:
    values = _build_substitution_values(text)
    issues: list[_Issue] = []
    for template_step in parse_batch_template(text):
        try:
            resolved = substitute_batch_parameters(
                template_step.line,
                values,
                _silent_prompt,
                template_step.line_number,
            )
        except Exception as exc:  # pragma: no cover - defensive
            issues.append(_Issue(template_step.line_number, template_step.line, str(exc)))
            continue
        if resolved is None:
            # ``_silent_prompt`` never returns None, so this branch only
            # fires if a future change to substitute_batch_parameters can
            # cancel without prompting. Surface it as an issue.
            issues.append(
                _Issue(
                    template_step.line_number,
                    template_step.line,
                    "Parameter resolution cancelled.",
                )
            )
            continue
        try:
            parse_batch_line(resolved, template_step.line_number)
        except BatchParseError as exc:
            issues.append(_Issue(template_step.line_number, template_step.line, str(exc)))
    return issues


@click.command("validate")
@click.argument(
    "file_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    metavar="FILE",
)
@click.pass_context
def validate_command(ctx: click.Context, file_path: Path) -> None:
    """Parse a command file and report unknown commands or syntax errors."""
    output: CliOutput = ctx.obj["output"]
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        output.error(f"Could not read {file_path}: {exc}", code=ExitCode.GENERIC_ERROR)
        ctx.exit(int(ExitCode.GENERIC_ERROR))
        return

    issues = _collect_issues(text)
    if not issues:
        if output.json_mode:
            output.object({"file": str(file_path), "issues": []})
        else:
            output.status(f"{file_path}: OK")
        return

    if output.json_mode:
        output.object(
            {
                "file": str(file_path),
                "issues": [issue.as_dict() for issue in issues],
            }
        )
    else:
        for issue in issues:
            output.error(f"Line {issue.line_number}: {issue.message}")
    ctx.exit(int(ExitCode.PARSE_ERROR))
