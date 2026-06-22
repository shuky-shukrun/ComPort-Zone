from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .control_panel_models import (
    ControlPanelConfig,
    ControlPanelTabState,
    control_panel_uses_v2_features,
    control_panel_uses_v3_features,
    control_panel_uses_v4_features,
    default_control_panels,
)

LINE_ENDINGS = {
    "None": "",
    "CR": "\r",
    "LF": "\n",
    "CRLF": "\r\n",
}

FLOW_CONTROL_OPTIONS = ("None", "RTS/CTS", "XON/XOFF", "DSR/DTR")
THEME_OPTIONS = (
    "ComPort Zone Dark",
    "ComPort Zone Light",
    "VS Code Dark",
    "Windows Terminal",
    "Bench Light",
    "Scope Amber",
)
RECEIVE_DISPLAY_MODES = ("Text", "Hex", "Text + Hex")
QUICK_COMMAND_SORT_MODES = ("Custom", "Title", "Group")
QUICK_FILE_SORT_MODES = ("Custom", "Title", "Path")
CONTROL_PANEL_SORT_MODES = ("Custom", "Name")
DEFAULT_SNIPPETS = ["*IDN?", "SYST:ERR:ALL?", "SYST:FIRM?"]
# Example command files shipped alongside the package (installation folder).
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
EXAMPLE_COMMAND_FILE = _ASSETS_DIR / "example-commands.cpz"
# Two richer samples: one driving EXPECT response-matching, one with {{parameters}}.
EXAMPLE_SELF_TEST_FILE = _ASSETS_DIR / "example-self-test.cpz"
EXAMPLE_MEASUREMENT_FILE = _ASSETS_DIR / "example-measurement.cpz"
SETTINGS_SCHEMA_VERSION = 8
MINIMUM_COMPATIBLE_SETTINGS_SCHEMA_VERSION = 2
# Feature floors: a saved payload declares the highest floor of any
# feature it actually contains, so files without LAN/Control Panel
# content stay readable by older builds (FR-39 in
# docs/control-panel-requirements.md).
LAN_SCHEMA_FLOOR = 4
CONTROL_PANEL_SCHEMA_FLOOR = 5
# ControlPanel v2 capabilities (poll modes, per-entry targets, derived/control
# entries, rule colors, CSV logging) — a v1-shaped library keeps floor 5.
CONTROL_PANEL_V2_SCHEMA_FLOOR = 6
# Control Panel v3 capabilities (setpoint tiles, enum/dropdown tiles) — a
# v1/v2-shaped library keeps its prior floor; only a panel that actually
# uses a v3 widget pushes the floor to 7 (FR-39 v3).
CONTROL_PANEL_V3_SCHEMA_FLOOR = 7
# Control Panel v4 capabilities (static text / separator tiles) — only a
# panel that actually uses one pushes the floor to 8 (FR-39 v4).
CONTROL_PANEL_V4_SCHEMA_FLOOR = 8


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
    favorite: bool = False
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
            "favorite": self.favorite,
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
            favorite=bool(data.get("favorite", False)),
            created_at=str(data.get("created_at", utc_now_iso())),
            updated_at=str(data.get("updated_at", utc_now_iso())),
        )


@dataclass(slots=True)
class QuickFile:
    id: str = field(default_factory=lambda: uuid4().hex)
    label: str = ""
    path: str = ""
    favorite: bool = False
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def display_label(self) -> str:
        return self.label or self.path

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "path": self.path,
            "favorite": self.favorite,
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
            favorite=bool(data.get("favorite", False)),
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
    control_panel: ControlPanelTabState | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind}
        if self.kind == "command_file":
            payload["command_file"] = (self.command_file or CommandFileTabState()).to_dict()
        elif self.kind == "control_panel":
            payload["control_panel"] = (self.control_panel or ControlPanelTabState()).to_dict()
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
        if kind == "control_panel":
            return cls(
                kind="control_panel",
                control_panel=ControlPanelTabState.from_dict(_dict_value(data.get("control_panel"))),
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


def default_quick_commands() -> list[QuickCommand]:
    """Saved commands seeded on first run — two are favourited by default."""
    return [
        QuickCommand(
            label="*IDN?",
            command="*IDN?",
            description="Identify the instrument (vendor, model, serial, firmware)",
            favorite=True,
        ),
        QuickCommand(
            label="SYST:ERR:ALL?",
            command="SYST:ERR:ALL?",
            description="Read and clear all queued errors",
            favorite=True,
        ),
        QuickCommand(
            label="SYST:FIRM?",
            command="SYST:FIRM?",
            description="Query the firmware version",
        ),
    ]


def default_quick_files() -> list[QuickFile]:
    """Quick files seeded on first run — the bundled example command files.

    Only the basic example is favourited by default; the richer EXPECT /
    parameter samples are saved but left for the user to star."""
    return [
        QuickFile(label="Example Commands", path=str(EXAMPLE_COMMAND_FILE), favorite=True),
        QuickFile(label="Self-Test (EXPECT)", path=str(EXAMPLE_SELF_TEST_FILE)),
        QuickFile(label="Measurement (parameters)", path=str(EXAMPLE_MEASUREMENT_FILE)),
    ]


# Maximum number of recently-opened command files remembered for File › Open Recent.
RECENT_FILES_LIMIT = 10


@dataclass(slots=True)
class AppSettings:
    transport_kind: str = "serial"
    transport_profile: dict[str, Any] = field(default_factory=dict)
    serial: SerialProfile = field(default_factory=SerialProfile)
    lan: LanProfile = field(default_factory=LanProfile)
    command_history: list[str] = field(default_factory=list)
    quick_commands: list[QuickCommand] = field(default_factory=default_quick_commands)
    quick_files: list[QuickFile] = field(default_factory=default_quick_files)
    quick_command_sort_mode: str = "Custom"
    quick_command_hidden_groups: list[str] = field(default_factory=list)
    quick_file_sort_mode: str = "Custom"
    # Favourites keep an independent order + sort mode, separate from the full
    # Saved Commands / Files lists (a curated arrangement the user controls).
    favorite_command_order: list[str] = field(default_factory=list)
    favorite_file_order: list[str] = field(default_factory=list)
    favorite_command_sort_mode: str = "Custom"
    favorite_file_sort_mode: str = "Custom"
    # Control Panels keep their own sort mode + favourites order, mirroring files.
    # Default "Name" preserves the historical alphabetical display; dragging a row
    # (or picking "Custom order") switches to the saved manual order.
    control_panel_sort_mode: str = "Name"
    favorite_control_panel_order: list[str] = field(default_factory=list)
    favorite_control_panel_sort_mode: str = "Name"
    # Favorites page layout: per-panel collapse + the resize splitter sizes.
    favorite_command_collapsed: bool = False
    favorite_file_collapsed: bool = False
    favorites_splitter_sizes: list[int] = field(default_factory=list)
    restored_tabs: list[TerminalSessionState] = field(default_factory=list)
    restored_command_files: list[CommandFileTabState] = field(default_factory=list)
    restored_control_panels: list[ControlPanelTabState] = field(default_factory=list)
    control_panels: list[ControlPanelConfig] = field(default_factory=default_control_panels)
    workspace_layout: WorkspaceLayoutState = field(default_factory=WorkspaceLayoutState)
    theme: str = "ComPort Zone Dark"
    timestamps_enabled: bool = True
    terminal_font_size: int = 10
    terminal_font_family: str = ""
    terminal_line_spacing: int = 115
    line_wrap_enabled: bool = True
    scrollback_size: int = 10000
    receive_display_mode: str = "Text"
    drawer_collapsed: bool = False
    drawer_width: int = 260
    drawer_page_index: int = 0
    check_for_updates_on_launch: bool = True
    clear_history_on_exit: bool = False
    # ControlPanel alerts (FR-58). Master enable defaults on so the feature
    # is discoverable; sound defaults off so the app stays quiet without
    # an explicit opt-in. Per-entry alerts_enabled gates contribution.
    control_panel_alerts_enabled: bool = True
    control_panel_alert_sound: bool = False
    log_path: str = ""
    last_script_path: str = ""
    recent_files: list[str] = field(default_factory=list)
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

    def _uses_control_panels(self) -> bool:
        if self.control_panels or self.restored_control_panels:
            return True
        return any(
            tab.kind == "control_panel"
            for pane in self.workspace_layout.panes
            for tab in pane.tabs
        )

    def minimum_compatible_schema_version(self) -> int:
        floors = [MINIMUM_COMPATIBLE_SETTINGS_SCHEMA_VERSION]
        if self._uses_lan_transport():
            floors.append(LAN_SCHEMA_FLOOR)
        if self._uses_control_panels():
            floors.append(CONTROL_PANEL_SCHEMA_FLOOR)
        if any(control_panel_uses_v2_features(config) for config in self.control_panels):
            floors.append(CONTROL_PANEL_V2_SCHEMA_FLOOR)
        if any(control_panel_uses_v3_features(config) for config in self.control_panels):
            floors.append(CONTROL_PANEL_V3_SCHEMA_FLOOR)
        if any(control_panel_uses_v4_features(config) for config in self.control_panels):
            floors.append(CONTROL_PANEL_V4_SCHEMA_FLOOR)
        return max(floors)

    def to_dict(self) -> dict[str, Any]:
        transport_kind = self.transport_kind or "serial"
        transport_profile = dict(self.transport_profile or self._default_transport_profile(transport_kind))
        minimum_compatible_schema = self.minimum_compatible_schema_version()
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
                    "line_spacing": self.terminal_line_spacing,
                },
                "line_wrap_enabled": self.line_wrap_enabled,
                "scrollback_size": self.scrollback_size,
                "receive_display_mode": self.receive_display_mode,
                "drawer": {
                    "collapsed": self.drawer_collapsed,
                    "width": self.drawer_width,
                    "page_index": self.drawer_page_index,
                },
                "favorites_layout": {
                    "command_collapsed": self.favorite_command_collapsed,
                    "file_collapsed": self.favorite_file_collapsed,
                    "splitter_sizes": list(self.favorites_splitter_sizes),
                },
                "updates": {
                    "check_on_launch": self.check_for_updates_on_launch,
                },
                "clear_history_on_exit": self.clear_history_on_exit,
                "control_panel_alerts": {
                    "enabled": self.control_panel_alerts_enabled,
                    "sound": self.control_panel_alert_sound,
                },
                "paths": {
                    "log": self.log_path,
                    "last_script": self.last_script_path,
                    "recent_files": list(self.recent_files),
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
                "favorite_command_order": list(self.favorite_command_order),
                "favorite_file_order": list(self.favorite_file_order),
                "favorite_command_sort_mode": self.favorite_command_sort_mode,
                "favorite_file_sort_mode": self.favorite_file_sort_mode,
                "control_panels": [control_panel.to_dict() for control_panel in self.control_panels],
                "control_panel_sort_mode": self.control_panel_sort_mode,
                "favorite_control_panel_order": list(self.favorite_control_panel_order),
                "favorite_control_panel_sort_mode": self.favorite_control_panel_sort_mode,
            },
            "workspace": {
                "terminal_tabs": [session.to_dict() for session in self.restored_tabs],
                "command_file_tabs": [
                    command_file.to_dict()
                    for command_file in self.restored_command_files
                ],
                "control_panel_tabs": [
                    control_panel_tab.to_dict()
                    for control_panel_tab in self.restored_control_panels
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
        favorites_layout = _dict_value(app.get("favorites_layout"))
        updates = _dict_value(app.get("updates"))
        control_panel_alerts = _dict_value(app.get("control_panel_alerts"))
        paths = _dict_value(app.get("paths"))
        window = _dict_value(app.get("window"))
        history = _dict_value(data.get("history"))
        libraries = _dict_value(data.get("libraries"))
        workspace = _dict_value(data.get("workspace"))
        quick_commands_present = "quick_commands" in libraries
        quick_commands_data = (
            _list_value(libraries.get("quick_commands"))
            if quick_commands_present
            else [command.to_dict() for command in default_quick_commands()]
        )
        quick_commands = []
        for item in quick_commands_data:
            quick_command = QuickCommand.from_dict(item)
            if quick_command.command:
                quick_commands.append(quick_command)
        quick_files_data = (
            _list_value(libraries.get("quick_files"))
            if "quick_files" in libraries
            else [quick_file.to_dict() for quick_file in default_quick_files()]
        )
        quick_files = []
        for item in quick_files_data:
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
        favorite_command_sort_mode = str(libraries.get("favorite_command_sort_mode", "Custom"))
        if favorite_command_sort_mode not in QUICK_COMMAND_SORT_MODES:
            favorite_command_sort_mode = "Custom"
        favorite_file_sort_mode = str(libraries.get("favorite_file_sort_mode", "Custom"))
        if favorite_file_sort_mode not in QUICK_FILE_SORT_MODES:
            favorite_file_sort_mode = "Custom"
        control_panel_sort_mode = str(libraries.get("control_panel_sort_mode", "Name"))
        if control_panel_sort_mode not in CONTROL_PANEL_SORT_MODES:
            control_panel_sort_mode = "Name"
        favorite_control_panel_sort_mode = str(libraries.get("favorite_control_panel_sort_mode", "Name"))
        if favorite_control_panel_sort_mode not in CONTROL_PANEL_SORT_MODES:
            favorite_control_panel_sort_mode = "Name"
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
            favorite_command_order=[
                str(item).strip()
                for item in _list_value(libraries.get("favorite_command_order"))
                if str(item).strip()
            ],
            favorite_file_order=[
                str(item).strip()
                for item in _list_value(libraries.get("favorite_file_order"))
                if str(item).strip()
            ],
            favorite_command_sort_mode=favorite_command_sort_mode,
            favorite_file_sort_mode=favorite_file_sort_mode,
            control_panel_sort_mode=control_panel_sort_mode,
            favorite_control_panel_sort_mode=favorite_control_panel_sort_mode,
            favorite_control_panel_order=[
                str(item).strip()
                for item in _list_value(libraries.get("favorite_control_panel_order"))
                if str(item).strip()
            ],
            favorite_command_collapsed=bool(favorites_layout.get("command_collapsed", False)),
            favorite_file_collapsed=bool(favorites_layout.get("file_collapsed", False)),
            favorites_splitter_sizes=[
                int(size)
                for size in _list_value(favorites_layout.get("splitter_sizes"))
                if str(size).strip().lstrip("-").isdigit()
            ],
            restored_tabs=[
                TerminalSessionState.from_dict(item)
                for item in _list_value(workspace.get("terminal_tabs"))
            ],
            restored_command_files=[
                CommandFileTabState.from_dict(item)
                for item in _list_value(workspace.get("command_file_tabs"))
            ],
            restored_control_panels=[
                ControlPanelTabState.from_dict(_dict_value(item))
                for item in _list_value(workspace.get("control_panel_tabs"))
            ],
            # Mirror the quick-commands seeding: a missing key (first run or
            # a pre-control_panel settings file) gets the shipped example; a
            # present-but-empty list stays empty (the user deleted it).
            control_panels=[
                ControlPanelConfig.from_dict(_dict_value(item))
                for item in (
                    _list_value(libraries.get("control_panels"))
                    if "control_panels" in libraries
                    else [config.to_dict() for config in default_control_panels()]
                )
            ],
            workspace_layout=WorkspaceLayoutState.from_dict(_dict_value(workspace.get("layout"))),
            theme=str(app.get("theme", "ComPort Zone Dark")),
            timestamps_enabled=bool(app.get("timestamps_enabled", True)),
            terminal_font_size=int(terminal_font.get("size", 10)),
            terminal_font_family=str(terminal_font.get("family", "")),
            terminal_line_spacing=int(terminal_font.get("line_spacing", 115)),
            line_wrap_enabled=bool(app.get("line_wrap_enabled", False)),
            scrollback_size=int(app.get("scrollback_size", 10000)),
            receive_display_mode=receive_display_mode,
            drawer_collapsed=bool(drawer.get("collapsed", True)),
            drawer_width=int(drawer.get("width", 260)),
            drawer_page_index=max(0, min(int(drawer.get("page_index", 0)), 4)),
            check_for_updates_on_launch=bool(updates.get("check_on_launch", True)),
            clear_history_on_exit=bool(app.get("clear_history_on_exit", False)),
            control_panel_alerts_enabled=bool(control_panel_alerts.get("enabled", True)),
            control_panel_alert_sound=bool(control_panel_alerts.get("sound", False)),
            log_path=str(paths.get("log", "")),
            last_script_path=str(paths.get("last_script", "")),
            recent_files=[
                str(item).strip()
                for item in _list_value(paths.get("recent_files"))
                if str(item).strip()
            ][:RECENT_FILES_LIMIT],
            window_width=int(window.get("width", 1320)),
            window_height=int(window.get("height", 860)),
        )
        return settings
