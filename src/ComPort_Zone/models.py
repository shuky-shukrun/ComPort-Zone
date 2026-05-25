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
QUICK_FILE_SORT_MODES = ("Custom", "Title", "Path")
DEFAULT_SNIPPETS = ["*IDN?", "SYST:ERR:ALL?", "SYST:FIRM?"]
SETTINGS_SCHEMA_VERSION = 4
MINIMUM_COMPATIBLE_SETTINGS_SCHEMA_VERSION = 2


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


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
class LanProfile:
    host: str = ""
    port: int = 5025
    line_ending: str = "CRLF"
    timeout_ms: int = 100
    auto_reconnect: bool = True
    reconnect_initial_delay_ms: int = 1000
    reconnect_max_delay_ms: int = 10000

    def endpoint(self) -> str:
        return f"{self.host}:{self.port}" if self.host else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "line_ending": self.line_ending,
            "timeout_ms": self.timeout_ms,
            "auto_reconnect": self.auto_reconnect,
            "reconnect_initial_delay_ms": self.reconnect_initial_delay_ms,
            "reconnect_max_delay_ms": self.reconnect_max_delay_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "LanProfile":
        if not data:
            return cls()
        return cls(
            host=str(data.get("host", "")).strip(),
            port=int(data.get("port", 5025)),
            line_ending=str(data.get("line_ending", "CRLF")),
            timeout_ms=int(data.get("timeout_ms", 100)),
            auto_reconnect=bool(data.get("auto_reconnect", True)),
            reconnect_initial_delay_ms=int(data.get("reconnect_initial_delay_ms", 1000)),
            reconnect_max_delay_ms=int(data.get("reconnect_max_delay_ms", 10000)),
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
    title_is_custom: bool = False
    transport_kind: str = "serial"
    transport_profile: dict[str, Any] = field(default_factory=dict)
    serial: SerialProfile | None = None
    lan: LanProfile | None = None
    connected_on_launch: bool = False
    terminal_text: str = ""
    command_draft: str = ""
    send_mode: str = "Text"

    def to_dict(self) -> dict[str, Any]:
        transport_profile = dict(self.transport_profile)
        transport_kind = self.transport_kind or "serial"
        if not transport_profile and transport_kind == "serial" and self.serial is not None:
            transport_profile = self.serial.to_dict()
        if not transport_profile and transport_kind == "lan" and self.lan is not None:
            transport_profile = self.lan.to_dict()
        payload = {
            "title": self.title,
            "title_is_custom": self.title_is_custom,
            "transport": {
                "kind": transport_kind,
                "profile": transport_profile,
            },
            "connected_on_launch": self.connected_on_launch,
            "terminal_text": self.terminal_text,
            "command_draft": self.command_draft,
            "send_mode": self.send_mode,
        }
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TerminalSessionState":
        if not data:
            return cls()
        send_mode = str(data.get("send_mode", "Text"))
        if send_mode not in {"Text", "Hex Bytes"}:
            send_mode = "Text"
        transport = _dict_value(data.get("transport"))
        transport_kind = str(transport.get("kind", "serial")) or "serial"
        transport_profile = _dict_value(transport.get("profile"))
        title = str(data.get("title", "Terminal")) or "Terminal"
        serial = SerialProfile.from_dict(transport_profile) if transport_kind == "serial" else None
        lan = LanProfile.from_dict(transport_profile) if transport_kind == "lan" else None
        return cls(
            title=title,
            title_is_custom=bool(
                data.get(
                    "title_is_custom",
                    not title.startswith("Terminal") and title not in {"No port", "No endpoint"},
                )
            ),
            transport_kind=transport_kind,
            transport_profile=dict(transport_profile),
            serial=serial,
            lan=lan,
            connected_on_launch=bool(data.get("connected_on_launch", False)),
            terminal_text=str(data.get("terminal_text", "")),
            command_draft=str(data.get("command_draft", "")),
            send_mode=send_mode,
        )


@dataclass(slots=True)
class CommandFileTabState:
    path: str = ""
    text: str = ""
    dirty: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "text": self.text,
            "dirty": self.dirty,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CommandFileTabState":
        if not data:
            return cls()
        return cls(
            path=str(data.get("path", "")),
            text=str(data.get("text", "")),
            dirty=bool(data.get("dirty", False)),
        )


@dataclass(slots=True)
class WorkspaceTabState:
    kind: str = "terminal"
    terminal: TerminalSessionState | None = None
    command_file: CommandFileTabState | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind}
        if self.kind == "command_file":
            payload["command_file"] = (self.command_file or CommandFileTabState()).to_dict()
        else:
            payload["terminal"] = (self.terminal or TerminalSessionState()).to_dict()
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "WorkspaceTabState":
        if not data:
            return cls()
        kind = str(data.get("kind", "terminal"))
        if kind == "command_file":
            return cls(
                kind="command_file",
                command_file=CommandFileTabState.from_dict(_dict_value(data.get("command_file"))),
            )
        return cls(
            kind="terminal",
            terminal=TerminalSessionState.from_dict(_dict_value(data.get("terminal"))),
        )


@dataclass(slots=True)
class WorkspacePaneState:
    tabs: list[WorkspaceTabState] = field(default_factory=list)
    active_tab: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tabs": [tab.to_dict() for tab in self.tabs],
            "active_tab": self.active_tab,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "WorkspacePaneState":
        if not data:
            return cls()
        return cls(
            tabs=[
                WorkspaceTabState.from_dict(item)
                for item in _list_value(data.get("tabs"))
            ],
            active_tab=max(0, int(data.get("active_tab", 0))),
        )


@dataclass(slots=True)
class WorkspaceLayoutState:
    orientation: str = "horizontal"
    panes: list[WorkspacePaneState] = field(default_factory=list)
    active_pane: int = 0
    splitter_sizes: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        orientation = self.orientation if self.orientation in {"horizontal", "vertical"} else "horizontal"
        return {
            "orientation": orientation,
            "panes": [pane.to_dict() for pane in self.panes],
            "active_pane": self.active_pane,
            "splitter_sizes": [int(size) for size in self.splitter_sizes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "WorkspaceLayoutState":
        if not data:
            return cls()
        orientation = str(data.get("orientation", "horizontal"))
        if orientation not in {"horizontal", "vertical"}:
            orientation = "horizontal"
        return cls(
            orientation=orientation,
            panes=[
                WorkspacePaneState.from_dict(item)
                for item in _list_value(data.get("panes"))
            ],
            active_pane=max(0, int(data.get("active_pane", 0))),
            splitter_sizes=[int(size) for size in _list_value(data.get("splitter_sizes"))],
        )


@dataclass(slots=True)
class AppSettings:
    transport_kind: str = "serial"
    transport_profile: dict[str, Any] = field(default_factory=dict)
    serial: SerialProfile = field(default_factory=SerialProfile)
    lan: LanProfile = field(default_factory=LanProfile)
    command_history: list[str] = field(default_factory=list)
    quick_commands: list[QuickCommand] = field(
        default_factory=lambda: [QuickCommand(label=item, command=item) for item in DEFAULT_SNIPPETS]
    )
    quick_files: list[QuickFile] = field(default_factory=list)
    quick_command_sort_mode: str = "Custom"
    quick_command_hidden_groups: list[str] = field(default_factory=list)
    quick_file_sort_mode: str = "Custom"
    restored_tabs: list[TerminalSessionState] = field(default_factory=list)
    restored_command_files: list[CommandFileTabState] = field(default_factory=list)
    workspace_layout: WorkspaceLayoutState = field(default_factory=WorkspaceLayoutState)
    theme: str = "VS Code Dark"
    timestamps_enabled: bool = True
    terminal_font_size: int = 10
    terminal_font_family: str = ""
    line_wrap_enabled: bool = False
    scrollback_size: int = 10000
    receive_display_mode: str = "Text"
    drawer_collapsed: bool = True
    drawer_width: int = 260
    drawer_page_index: int = 0
    check_for_updates_on_launch: bool = True
    log_path: str = ""
    last_script_path: str = ""
    window_width: int = 1320
    window_height: int = 860

    def _default_transport_profile(self, kind: str) -> dict[str, Any]:
        if kind == "lan":
            return self.lan.to_dict()
        return self.serial.to_dict()

    def _uses_lan_transport(self) -> bool:
        if self.transport_kind == "lan":
            return True
        return any(session.transport_kind == "lan" for session in self.restored_tabs)

    def to_dict(self) -> dict[str, Any]:
        transport_kind = self.transport_kind or "serial"
        transport_profile = dict(self.transport_profile or self._default_transport_profile(transport_kind))
        minimum_compatible_schema = (
            SETTINGS_SCHEMA_VERSION
            if self._uses_lan_transport()
            else MINIMUM_COMPATIBLE_SETTINGS_SCHEMA_VERSION
        )
        return {
            "schema_version": SETTINGS_SCHEMA_VERSION,
            "minimum_compatible_schema_version": minimum_compatible_schema,
            "transport": {
                "kind": transport_kind,
                "profile": transport_profile,
            },
            "app": {
                "theme": self.theme,
                "timestamps_enabled": self.timestamps_enabled,
                "terminal_font": {
                    "family": self.terminal_font_family,
                    "size": self.terminal_font_size,
                },
                "line_wrap_enabled": self.line_wrap_enabled,
                "scrollback_size": self.scrollback_size,
                "receive_display_mode": self.receive_display_mode,
                "drawer": {
                    "collapsed": self.drawer_collapsed,
                    "width": self.drawer_width,
                    "page_index": self.drawer_page_index,
                },
                "updates": {
                    "check_on_launch": self.check_for_updates_on_launch,
                },
                "paths": {
                    "log": self.log_path,
                    "last_script": self.last_script_path,
                },
                "window": {
                    "width": self.window_width,
                    "height": self.window_height,
                },
            },
            "history": {
                "commands": list(self.command_history),
            },
            "libraries": {
                "quick_commands": [command.to_dict() for command in self.quick_commands],
                "quick_files": [quick_file.to_dict() for quick_file in self.quick_files],
                "quick_command_sort_mode": self.quick_command_sort_mode,
                "quick_command_hidden_groups": list(self.quick_command_hidden_groups),
                "quick_file_sort_mode": self.quick_file_sort_mode,
            },
            "workspace": {
                "terminal_tabs": [session.to_dict() for session in self.restored_tabs],
                "command_file_tabs": [
                    command_file.to_dict()
                    for command_file in self.restored_command_files
                ],
                "layout": self.workspace_layout.to_dict(),
            },
        }

    def to_app_settings_dict(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload.pop("libraries", None)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AppSettings":
        if not data:
            return cls()
        transport = _dict_value(data.get("transport"))
        transport_kind = str(transport.get("kind", "serial")) or "serial"
        transport_profile = _dict_value(transport.get("profile"))
        serial = SerialProfile.from_dict(transport_profile if transport_kind == "serial" else {})
        lan = LanProfile.from_dict(transport_profile if transport_kind == "lan" else {})
        app = _dict_value(data.get("app"))
        terminal_font = _dict_value(app.get("terminal_font"))
        drawer = _dict_value(app.get("drawer"))
        updates = _dict_value(app.get("updates"))
        paths = _dict_value(app.get("paths"))
        window = _dict_value(app.get("window"))
        history = _dict_value(data.get("history"))
        libraries = _dict_value(data.get("libraries"))
        workspace = _dict_value(data.get("workspace"))
        quick_commands_present = "quick_commands" in libraries
        quick_commands_data = (
            _list_value(libraries.get("quick_commands"))
            if quick_commands_present
            else [QuickCommand(label=item, command=item).to_dict() for item in DEFAULT_SNIPPETS]
        )
        quick_commands = []
        for item in quick_commands_data:
            quick_command = QuickCommand.from_dict(item)
            if quick_command.command:
                quick_commands.append(quick_command)
        quick_files = []
        for item in _list_value(libraries.get("quick_files")):
            quick_file = QuickFile.from_dict(item)
            if quick_file.path:
                quick_files.append(quick_file)
        receive_display_mode = str(app.get("receive_display_mode", "Text"))
        if receive_display_mode not in RECEIVE_DISPLAY_MODES:
            receive_display_mode = "Text"
        quick_command_sort_mode = str(libraries.get("quick_command_sort_mode", "Custom"))
        if quick_command_sort_mode not in QUICK_COMMAND_SORT_MODES:
            quick_command_sort_mode = "Custom"
        quick_file_sort_mode = str(libraries.get("quick_file_sort_mode", "Custom"))
        if quick_file_sort_mode not in QUICK_FILE_SORT_MODES:
            quick_file_sort_mode = "Custom"
        settings = cls(
            transport_kind=transport_kind,
            transport_profile=dict(
                transport_profile
                or (lan.to_dict() if transport_kind == "lan" else serial.to_dict())
            ),
            serial=serial,
            lan=lan,
            command_history=[str(item) for item in _list_value(history.get("commands"))],
            quick_commands=quick_commands,
            quick_files=quick_files,
            quick_command_sort_mode=quick_command_sort_mode,
            quick_command_hidden_groups=[
                str(group).strip()
                for group in _list_value(libraries.get("quick_command_hidden_groups"))
                if str(group).strip()
            ],
            quick_file_sort_mode=quick_file_sort_mode,
            restored_tabs=[
                TerminalSessionState.from_dict(item)
                for item in _list_value(workspace.get("terminal_tabs"))
            ],
            restored_command_files=[
                CommandFileTabState.from_dict(item)
                for item in _list_value(workspace.get("command_file_tabs"))
            ],
            workspace_layout=WorkspaceLayoutState.from_dict(_dict_value(workspace.get("layout"))),
            theme=str(app.get("theme", "VS Code Dark")),
            timestamps_enabled=bool(app.get("timestamps_enabled", True)),
            terminal_font_size=int(terminal_font.get("size", 10)),
            terminal_font_family=str(terminal_font.get("family", "")),
            line_wrap_enabled=bool(app.get("line_wrap_enabled", False)),
            scrollback_size=int(app.get("scrollback_size", 10000)),
            receive_display_mode=receive_display_mode,
            drawer_collapsed=bool(drawer.get("collapsed", True)),
            drawer_width=int(drawer.get("width", 260)),
            drawer_page_index=max(0, min(int(drawer.get("page_index", 0)), 1)),
            check_for_updates_on_launch=bool(updates.get("check_on_launch", True)),
            log_path=str(paths.get("log", "")),
            last_script_path=str(paths.get("last_script", "")),
            window_width=int(window.get("width", 1320)),
            window_height=int(window.get("height", 860)),
        )
        return settings
