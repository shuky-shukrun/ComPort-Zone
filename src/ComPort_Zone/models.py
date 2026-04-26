from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

LINE_ENDINGS = {
    "None": "",
    "CR": "\r",
    "LF": "\n",
    "CRLF": "\r\n",
}

FLOW_CONTROL_OPTIONS = ("None", "RTS/CTS", "XON/XOFF", "DSR/DTR")
THEME_OPTIONS = ("VS Code Dark", "Windows Terminal", "Bench Light", "Scope Amber")
RECEIVE_DISPLAY_MODES = ("Text", "Hex", "Text + Hex")
QUICK_COMMAND_SORT_MODES = ("Custom", "Title", "Group")
DEFAULT_SNIPPETS = ["status", "help", "reset"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def apply_line_ending(text: str, line_ending: str) -> bytes:
    suffix = LINE_ENDINGS.get(line_ending, "")
    return f"{text}{suffix}".encode("utf-8")


@dataclass(slots=True)
class SerialProfile:
    port: str = ""
    baudrate: int = 115200
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1.0
    flow_control: str = "None"
    line_ending: str = "CRLF"
    timeout_ms: int = 100
    auto_reconnect: bool = True
    reconnect_initial_delay_ms: int = 1000
    reconnect_max_delay_ms: int = 10000
    dtr: bool = True
    rts: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "baudrate": self.baudrate,
            "bytesize": self.bytesize,
            "parity": self.parity,
            "stopbits": self.stopbits,
            "flow_control": self.flow_control,
            "line_ending": self.line_ending,
            "timeout_ms": self.timeout_ms,
            "auto_reconnect": self.auto_reconnect,
            "reconnect_initial_delay_ms": self.reconnect_initial_delay_ms,
            "reconnect_max_delay_ms": self.reconnect_max_delay_ms,
            "dtr": self.dtr,
            "rts": self.rts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SerialProfile":
        if not data:
            return cls()
        return cls(
            port=str(data.get("port", "")),
            baudrate=int(data.get("baudrate", 115200)),
            bytesize=int(data.get("bytesize", 8)),
            parity=str(data.get("parity", "N")),
            stopbits=float(data.get("stopbits", 1.0)),
            flow_control=str(data.get("flow_control", "None")),
            line_ending=str(data.get("line_ending", "CRLF")),
            timeout_ms=int(data.get("timeout_ms", 100)),
            auto_reconnect=bool(data.get("auto_reconnect", True)),
            reconnect_initial_delay_ms=int(data.get("reconnect_initial_delay_ms", 1000)),
            reconnect_max_delay_ms=int(data.get("reconnect_max_delay_ms", 10000)),
            dtr=bool(data.get("dtr", True)),
            rts=bool(data.get("rts", True)),
        )


@dataclass(slots=True)
class QuickCommand:
    id: str = field(default_factory=lambda: uuid4().hex)
    label: str = ""
    command: str = ""
    description: str = ""
    send_mode: str = "Text"
    group: str = "General"
    line_ending_override: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def display_label(self) -> str:
        return self.label or self.command

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "command": self.command,
            "description": self.description,
            "send_mode": self.send_mode,
            "group": self.group,
            "line_ending_override": self.line_ending_override,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | str) -> "QuickCommand":
        if isinstance(data, str):
            value = data.strip()
            return cls(label=value, command=value)
        command = str(data.get("command", "")).strip()
        label = str(data.get("label", command)).strip()
        return cls(
            id=str(data.get("id", uuid4().hex)),
            label=label,
            command=command,
            description=str(data.get("description", "")).strip(),
            send_mode=str(data.get("send_mode", "Text")),
            group=str(data.get("group", "General")) or "General",
            line_ending_override=str(data.get("line_ending_override", "")),
            created_at=str(data.get("created_at", utc_now_iso())),
            updated_at=str(data.get("updated_at", utc_now_iso())),
        )


@dataclass(slots=True)
class QuickFile:
    id: str = field(default_factory=lambda: uuid4().hex)
    label: str = ""
    path: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def display_label(self) -> str:
        return self.label or self.path

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "path": self.path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | str) -> "QuickFile":
        if isinstance(data, str):
            value = data.strip()
            return cls(label="", path=value)
        path = str(data.get("path", "")).strip()
        label = str(data.get("label", "")).strip()
        return cls(
            id=str(data.get("id", uuid4().hex)),
            label=label,
            path=path,
            created_at=str(data.get("created_at", utc_now_iso())),
            updated_at=str(data.get("updated_at", utc_now_iso())),
        )


@dataclass(slots=True)
class TerminalSessionState:
    title: str = "Terminal"
    serial: SerialProfile | None = None
    connected_on_launch: bool = False
    terminal_text: str = ""
    command_draft: str = ""
    send_mode: str = "Text"

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "title": self.title,
            "connected_on_launch": self.connected_on_launch,
            "terminal_text": self.terminal_text,
            "command_draft": self.command_draft,
            "send_mode": self.send_mode,
        }
        if self.serial is not None:
            payload["serial"] = self.serial.to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TerminalSessionState":
        if not data:
            return cls()
        send_mode = str(data.get("send_mode", "Text"))
        if send_mode not in {"Text", "Hex Bytes"}:
            send_mode = "Text"
        serial_data = data.get("serial", data.get("serial_profile"))
        return cls(
            title=str(data.get("title", "Terminal")) or "Terminal",
            serial=SerialProfile.from_dict(serial_data) if serial_data else None,
            connected_on_launch=bool(data.get("connected_on_launch", False)),
            terminal_text=str(data.get("terminal_text", "")),
            command_draft=str(data.get("command_draft", "")),
            send_mode=send_mode,
        )


@dataclass(slots=True)
class AppSettings:
    serial: SerialProfile = field(default_factory=SerialProfile)
    command_history: list[str] = field(default_factory=list)
    quick_snippets: list[str] = field(default_factory=lambda: list(DEFAULT_SNIPPETS))
    quick_commands: list[QuickCommand] = field(
        default_factory=lambda: [QuickCommand(label=item, command=item) for item in DEFAULT_SNIPPETS]
    )
    quick_files: list[QuickFile] = field(default_factory=list)
    quick_command_sort_mode: str = "Custom"
    quick_command_hidden_groups: list[str] = field(default_factory=list)
    restored_tabs: list[TerminalSessionState] = field(default_factory=list)
    theme: str = "VS Code Dark"
    timestamps_enabled: bool = True
    terminal_font_size: int = 10
    terminal_font_family: str = ""
    line_wrap_enabled: bool = False
    scrollback_size: int = 10000
    receive_display_mode: str = "Text"
    drawer_collapsed: bool = True
    drawer_width: int = 260
    log_path: str = ""
    last_script_path: str = ""
    window_width: int = 1320
    window_height: int = 860

    def to_dict(self) -> dict[str, Any]:
        return {
            "serial": self.serial.to_dict(),
            "command_history": list(self.command_history),
            "quick_snippets": list(self.quick_snippets),
            "quick_commands": [command.to_dict() for command in self.quick_commands],
            "quick_files": [quick_file.to_dict() for quick_file in self.quick_files],
            "quick_command_sort_mode": self.quick_command_sort_mode,
            "quick_command_hidden_groups": list(self.quick_command_hidden_groups),
            "restored_tabs": [session.to_dict() for session in self.restored_tabs],
            "theme": self.theme,
            "timestamps_enabled": self.timestamps_enabled,
            "terminal_font_size": self.terminal_font_size,
            "terminal_font_family": self.terminal_font_family,
            "line_wrap_enabled": self.line_wrap_enabled,
            "scrollback_size": self.scrollback_size,
            "receive_display_mode": self.receive_display_mode,
            "drawer_collapsed": self.drawer_collapsed,
            "drawer_width": self.drawer_width,
            "log_path": self.log_path,
            "last_script_path": self.last_script_path,
            "window_width": self.window_width,
            "window_height": self.window_height,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AppSettings":
        if not data:
            return cls()
        serial_data = data.get("serial", data.get("serial_profile"))
        quick_commands_data = data.get("quick_commands")
        if quick_commands_data is None:
            quick_commands_data = data.get("quick_snippets", DEFAULT_SNIPPETS)
        quick_commands = []
        for item in quick_commands_data:
            quick_command = QuickCommand.from_dict(item)
            if quick_command.command:
                quick_commands.append(quick_command)
        quick_files = []
        for item in data.get("quick_files", []):
            quick_file = QuickFile.from_dict(item)
            if quick_file.path:
                quick_files.append(quick_file)
        receive_display_mode = str(data.get("receive_display_mode", "Text"))
        if receive_display_mode not in RECEIVE_DISPLAY_MODES:
            receive_display_mode = "Text"
        quick_command_sort_mode = str(data.get("quick_command_sort_mode", "Custom"))
        if quick_command_sort_mode not in QUICK_COMMAND_SORT_MODES:
            quick_command_sort_mode = "Custom"
        settings = cls(
            serial=SerialProfile.from_dict(serial_data),
            command_history=[str(item) for item in data.get("command_history", [])],
            quick_snippets=[
                str(item).strip()
                for item in data.get("quick_snippets", DEFAULT_SNIPPETS)
                if str(item).strip()
            ]
            or list(DEFAULT_SNIPPETS),
            quick_commands=quick_commands
            or [QuickCommand(label=item, command=item) for item in DEFAULT_SNIPPETS],
            quick_files=quick_files,
            quick_command_sort_mode=quick_command_sort_mode,
            quick_command_hidden_groups=[
                str(group).strip()
                for group in data.get("quick_command_hidden_groups", [])
                if str(group).strip()
            ],
            restored_tabs=[
                TerminalSessionState.from_dict(item)
                for item in data.get("restored_tabs", [])
            ],
            theme="VS Code Dark"
            if str(data.get("theme", "VS Code Dark")) == "Workshop Dark"
            else str(data.get("theme", "VS Code Dark")),
            timestamps_enabled=bool(data.get("timestamps_enabled", True)),
            terminal_font_size=int(data.get("terminal_font_size", 10)),
            terminal_font_family=str(data.get("terminal_font_family", "")),
            line_wrap_enabled=bool(data.get("line_wrap_enabled", False)),
            scrollback_size=int(data.get("scrollback_size", 10000)),
            receive_display_mode=receive_display_mode,
            drawer_collapsed=bool(data.get("drawer_collapsed", True)),
            drawer_width=int(data.get("drawer_width", 260)),
            log_path=str(data.get("log_path", "")),
            last_script_path=str(data.get("last_script_path", "")),
            window_width=int(data.get("window_width", 1320)),
            window_height=int(data.get("window_height", 860)),
        )
        return settings
