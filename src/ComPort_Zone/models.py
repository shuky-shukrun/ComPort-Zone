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
DEFAULT_SNIPPETS = ["status", "help", "reset"]
DEFAULT_PROFILE_NAME = "Default"


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
            send_mode=str(data.get("send_mode", "Text")),
            group=str(data.get("group", "General")) or "General",
            line_ending_override=str(data.get("line_ending_override", "")),
            created_at=str(data.get("created_at", utc_now_iso())),
            updated_at=str(data.get("updated_at", utc_now_iso())),
        )


@dataclass(slots=True)
class TerminalSessionState:
    title: str = "Terminal"
    profile_name: str = "Default"
    serial: SerialProfile | None = None
    connected_on_launch: bool = False
    terminal_text: str = ""
    command_draft: str = ""
    send_mode: str = "Text"

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "title": self.title,
            "profile_name": self.profile_name,
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
            profile_name=str(data.get("profile_name", "Default")) or "Default",
            serial=SerialProfile.from_dict(serial_data) if serial_data else None,
            connected_on_launch=bool(data.get("connected_on_launch", False)),
            terminal_text=str(data.get("terminal_text", "")),
            command_draft=str(data.get("command_draft", "")),
            send_mode=send_mode,
        )


@dataclass(slots=True)
class UserProfile:
    serial: SerialProfile = field(default_factory=SerialProfile)
    command_history: list[str] = field(default_factory=list)
    quick_snippets: list[str] = field(default_factory=lambda: list(DEFAULT_SNIPPETS))
    quick_commands: list[QuickCommand] = field(
        default_factory=lambda: [QuickCommand(label=item, command=item) for item in DEFAULT_SNIPPETS]
    )
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "serial": self.serial.to_dict(),
            "command_history": list(self.command_history),
            "quick_snippets": list(self.quick_snippets),
            "quick_commands": [command.to_dict() for command in self.quick_commands],
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
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any] | None,
        fallback: "UserProfile | None" = None,
    ) -> "UserProfile":
        fallback = fallback or cls()
        if not data:
            return fallback.clone()
        serial_data = data.get("serial", data.get("serial_profile"))
        legacy_serial_only = serial_data is None and not any(
            key in data
            for key in (
                "command_history",
                "quick_snippets",
                "quick_commands",
                "theme",
                "terminal_font_size",
                "receive_display_mode",
                "drawer_collapsed",
            )
        )
        if serial_data is None:
            serial_data = data
        quick_commands_data = data.get("quick_commands")
        if quick_commands_data is None:
            quick_commands_data = (
                [command.to_dict() for command in fallback.quick_commands]
                if legacy_serial_only
                else data.get("quick_snippets", fallback.quick_snippets)
            )
        quick_commands = []
        for item in quick_commands_data:
            quick_command = QuickCommand.from_dict(item)
            if quick_command.command:
                quick_commands.append(quick_command)
        theme = str(data.get("theme", fallback.theme))
        if theme == "Workshop Dark":
            theme = "VS Code Dark"
        receive_display_mode = str(data.get("receive_display_mode", fallback.receive_display_mode))
        if receive_display_mode not in RECEIVE_DISPLAY_MODES:
            receive_display_mode = "Text"
        return cls(
            serial=SerialProfile.from_dict(serial_data),
            command_history=[
                str(item)
                for item in data.get("command_history", fallback.command_history)
            ],
            quick_snippets=[
                str(item).strip()
                for item in data.get("quick_snippets", fallback.quick_snippets)
                if str(item).strip()
            ]
            or list(DEFAULT_SNIPPETS),
            quick_commands=quick_commands
            or [QuickCommand.from_dict(command.to_dict()) for command in fallback.quick_commands],
            theme=theme,
            timestamps_enabled=bool(data.get("timestamps_enabled", fallback.timestamps_enabled)),
            terminal_font_size=int(data.get("terminal_font_size", fallback.terminal_font_size)),
            terminal_font_family=str(data.get("terminal_font_family", fallback.terminal_font_family)),
            line_wrap_enabled=bool(data.get("line_wrap_enabled", fallback.line_wrap_enabled)),
            scrollback_size=int(data.get("scrollback_size", fallback.scrollback_size)),
            receive_display_mode=receive_display_mode,
            drawer_collapsed=bool(data.get("drawer_collapsed", fallback.drawer_collapsed)),
            drawer_width=int(data.get("drawer_width", fallback.drawer_width)),
            log_path=str(data.get("log_path", fallback.log_path)),
            last_script_path=str(data.get("last_script_path", fallback.last_script_path)),
        )

    @classmethod
    def from_settings(
        cls,
        settings: "AppSettings",
        serial: SerialProfile | None = None,
    ) -> "UserProfile":
        return cls(
            serial=SerialProfile.from_dict((serial or SerialProfile()).to_dict()),
            command_history=list(settings.command_history),
            quick_snippets=list(settings.quick_snippets),
            quick_commands=[
                QuickCommand.from_dict(command.to_dict())
                for command in settings.quick_commands
            ],
            theme=settings.theme,
            timestamps_enabled=settings.timestamps_enabled,
            terminal_font_size=settings.terminal_font_size,
            terminal_font_family=settings.terminal_font_family,
            line_wrap_enabled=settings.line_wrap_enabled,
            scrollback_size=settings.scrollback_size,
            receive_display_mode=settings.receive_display_mode,
            drawer_collapsed=settings.drawer_collapsed,
            drawer_width=settings.drawer_width,
            log_path=settings.log_path,
            last_script_path=settings.last_script_path,
        )

    def clone(self) -> "UserProfile":
        return UserProfile.from_dict(self.to_dict())


@dataclass(slots=True)
class AppSettings:
    active_profile: str = DEFAULT_PROFILE_NAME
    profiles: dict[str, UserProfile] = field(
        default_factory=lambda: {DEFAULT_PROFILE_NAME: UserProfile()}
    )
    command_history: list[str] = field(default_factory=list)
    quick_snippets: list[str] = field(default_factory=lambda: list(DEFAULT_SNIPPETS))
    quick_commands: list[QuickCommand] = field(
        default_factory=lambda: [QuickCommand(label=item, command=item) for item in DEFAULT_SNIPPETS]
    )
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

    def ensure_active_profile(self) -> None:
        if not self.profiles:
            self.profiles = {DEFAULT_PROFILE_NAME: UserProfile.from_settings(self)}
        elif DEFAULT_PROFILE_NAME not in self.profiles:
            self.profiles[DEFAULT_PROFILE_NAME] = UserProfile.from_settings(self)
        if self.active_profile not in self.profiles:
            self.active_profile = next(iter(self.profiles))

    def active_user_profile(self) -> UserProfile:
        self.ensure_active_profile()
        return self.profiles[self.active_profile]

    def capture_user_profile(self, serial: SerialProfile | None = None) -> UserProfile:
        if serial is None:
            serial = self.active_user_profile().serial
        return UserProfile.from_settings(self, serial)

    def apply_user_profile(self, name: str) -> None:
        profile = self.profiles.get(name)
        if not profile:
            return
        self.active_profile = name
        self.command_history = list(profile.command_history)
        self.quick_snippets = list(profile.quick_snippets)
        self.quick_commands = [
            QuickCommand.from_dict(command.to_dict())
            for command in profile.quick_commands
        ]
        self.theme = profile.theme
        self.timestamps_enabled = profile.timestamps_enabled
        self.terminal_font_size = profile.terminal_font_size
        self.terminal_font_family = profile.terminal_font_family
        self.line_wrap_enabled = profile.line_wrap_enabled
        self.scrollback_size = profile.scrollback_size
        self.receive_display_mode = profile.receive_display_mode
        self.drawer_collapsed = profile.drawer_collapsed
        self.drawer_width = profile.drawer_width
        self.log_path = profile.log_path
        self.last_script_path = profile.last_script_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_profile": self.active_profile,
            "profiles": {name: profile.to_dict() for name, profile in self.profiles.items()},
            "command_history": list(self.command_history),
            "quick_snippets": list(self.quick_snippets),
            "quick_commands": [command.to_dict() for command in self.quick_commands],
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
        quick_commands_data = data.get("quick_commands")
        if quick_commands_data is None:
            quick_commands_data = data.get("quick_snippets", DEFAULT_SNIPPETS)
        quick_commands = []
        for item in quick_commands_data:
            quick_command = QuickCommand.from_dict(item)
            if quick_command.command:
                quick_commands.append(quick_command)
        receive_display_mode = str(data.get("receive_display_mode", "Text"))
        if receive_display_mode not in RECEIVE_DISPLAY_MODES:
            receive_display_mode = "Text"
        settings = cls(
            active_profile=str(data.get("active_profile", DEFAULT_PROFILE_NAME)),
            profiles={},
            command_history=[str(item) for item in data.get("command_history", [])],
            quick_snippets=[
                str(item).strip()
                for item in data.get("quick_snippets", DEFAULT_SNIPPETS)
                if str(item).strip()
            ]
            or list(DEFAULT_SNIPPETS),
            quick_commands=quick_commands
            or [QuickCommand(label=item, command=item) for item in DEFAULT_SNIPPETS],
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
        fallback_profile = UserProfile.from_settings(settings)
        profiles_data = data.get("profiles") or {DEFAULT_PROFILE_NAME: {}}
        settings.profiles = {
            str(name): UserProfile.from_dict(profile_data, fallback_profile)
            for name, profile_data in profiles_data.items()
        }
        settings.ensure_active_profile()
        settings.apply_user_profile(settings.active_profile)
        return settings
