from __future__ import annotations

from dataclasses import dataclass, field
import re

from .batch import BatchParseError, parse_batch_line, strip_c_style_comment
from .models import QuickCommand
from .quick_actions import quick_group_name

BATCH_KEYWORDS = ("SEND", "WAIT", "HEX", "EXPECT")
COMMENT_SNIPPETS = ("// ", "# ")
DEFAULT_KNOWN_COMMANDS = (
    "*IDN?",
    "SYST:FIRM?",
    "MEAS:CURR?",
    "MEAS:VOLT?",
    "CURR",
    "CURR?",
    "OUTP",
    "OUTP?",
    "POW",
    "POW?",
    "SINK:CURR",
    "SINK:CURR?",
    "SINK:POW",
    "SINK:POW?",
    "SYST:ERR?",
    "SYST:ERR:ALL?",
    "SYST:FIRM?",
    "VOLT",
    "VOLT?",
)
COMMAND_TOKEN_PATTERN = re.compile(r"^[^\s]+")
COMPLETION_TOKEN_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_:*?.-")


@dataclass(slots=True)
class CommandValidationIssue:
    line_number: int
    message: str
    start: int = 0
    length: int = 0
    severity: str = "warning"


def quick_command_group(command: QuickCommand) -> str:
    return quick_group_name(command.group)


def command_token(text: str) -> str:
    match = COMMAND_TOKEN_PATTERN.match(text.strip())
    return match.group(0).strip() if match else ""


def command_text_from_line(stripped_line: str) -> str:
    try:
        step = parse_batch_line(stripped_line, 1)
    except BatchParseError:
        if stripped_line.upper().startswith("SEND "):
            return stripped_line[5:].strip()
        return stripped_line
    if step.kind == "send":
        return str(step.payload).strip()
    return ""


def has_parameter(text: str) -> bool:
    return "{{" in text and "}}" in text


@dataclass(slots=True)
class CommandEditorSources:
    history_commands: list[str] = field(default_factory=list)
    quick_commands: list[QuickCommand] = field(default_factory=list)
    known_commands: list[str] = field(default_factory=lambda: list(DEFAULT_KNOWN_COMMANDS))
    quick_group_filter: str = "All"
    quick_command_hidden_groups: list[str] = field(default_factory=list)

    def groups(self) -> list[str]:
        names = {quick_command_group(command) for command in self.quick_commands}
        return sorted(names, key=str.casefold)

    def quick_command_texts(self) -> list[str]:
        selected = self.quick_group_filter.casefold()
        hidden = {group.casefold() for group in self.quick_command_hidden_groups}
        return [
            command.command
            for command in self.quick_commands
            if command.command
            and (selected == "all" or quick_command_group(command).casefold() == selected)
            and quick_command_group(command).casefold() not in hidden
        ]

    def known_command_tokens(self) -> set[str]:
        tokens = {item.strip().casefold() for item in self.known_commands if item.strip()}
        for text in [*self.history_commands, *[command.command for command in self.quick_commands]]:
            token = command_token(command_text_from_line(text))
            if token:
                tokens.add(token.casefold())
        return tokens

    def document_words(self, text: str) -> list[str]:
        words: set[str] = set()
        for raw_line in text.splitlines():
            stripped = strip_c_style_comment(raw_line)
            if not stripped or stripped.startswith("#"):
                continue
            for token in re.findall(r"[A-Za-z0-9_*][A-Za-z0-9_:*?.-]*", stripped):
                if len(token) > 1:
                    words.add(token)
        return sorted(words, key=str.casefold)

    def suggestions(self, document_text: str = "", prefix: str = "", exclude: str = "") -> list[str]:
        candidates: list[str] = []
        candidates.extend(BATCH_KEYWORDS)
        candidates.extend(COMMENT_SNIPPETS)
        candidates.extend(self.known_commands)
        candidates.extend(self.history_commands)
        candidates.extend(self.quick_command_texts())
        candidates.extend(self.document_words(document_text))
        seen: set[str] = set()
        prefix_key = prefix.casefold()
        exclude_key = exclude.casefold()
        result: list[str] = []
        for candidate in candidates:
            value = candidate.strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            if exclude_key and key == exclude_key:
                continue
            if prefix_key and prefix_key not in key:
                continue
            seen.add(key)
            result.append(value)
        if prefix_key:
            result.sort(key=lambda value: (0 if value.casefold().startswith(prefix_key) else 1, value.casefold()))
        return result[:200]

    def validation_issues(self, text: str, *, warn_unknown: bool = True) -> list[CommandValidationIssue]:
        known_tokens = self.known_command_tokens()
        issues: list[CommandValidationIssue] = []
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            stripped = strip_c_style_comment(raw_line)
            if not stripped or stripped.startswith("#"):
                continue
            if has_parameter(stripped):
                command_text = command_text_from_line(stripped)
            else:
                try:
                    step = parse_batch_line(stripped, line_number)
                except BatchParseError as exc:
                    issues.append(CommandValidationIssue(line_number, str(exc), 0, len(raw_line), "error"))
                    continue
                command_text = str(step.payload).strip() if step.kind == "send" else ""
            if not warn_unknown or not command_text or has_parameter(command_text):
                continue
            token = command_token(command_text)
            if token and token.casefold() not in known_tokens:
                start = raw_line.find(token)
                issues.append(
                    CommandValidationIssue(
                        line_number,
                        f"Unknown command: {token}",
                        max(start, 0),
                        len(token),
                        "warning",
                    )
                )
        return issues
