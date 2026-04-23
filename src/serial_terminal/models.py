from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LINE_ENDINGS = {
    "None": "",
    "CR": "\r",
    "LF": "\n",
    "CRLF": "\r\n",
}

FLOW_CONTROL_OPTIONS = ("None", "RTS/CTS", "XON/XOFF", "DSR/DTR")
THEME_OPTIONS = ("Workshop Dark", "Bench Light", "Scope Amber")


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
class AppSettings:
    active_profile: str = "Default"
    profiles: dict[str, SerialProfile] = field(
        default_factory=lambda: {"Default": SerialProfile()}
    )
    command_history: list[str] = field(default_factory=list)
    theme: str = "Workshop Dark"
    timestamps_enabled: bool = True
    log_path: str = ""
    last_script_path: str = ""
    window_width: int = 1320
    window_height: int = 860

    def ensure_active_profile(self) -> None:
        if not self.profiles:
            self.profiles = {"Default": SerialProfile()}
        if self.active_profile not in self.profiles:
            self.active_profile = next(iter(self.profiles))

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_profile": self.active_profile,
            "profiles": {name: profile.to_dict() for name, profile in self.profiles.items()},
            "command_history": list(self.command_history),
            "theme": self.theme,
            "timestamps_enabled": self.timestamps_enabled,
            "log_path": self.log_path,
            "last_script_path": self.last_script_path,
            "window_width": self.window_width,
            "window_height": self.window_height,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AppSettings":
        if not data:
            return cls()
        profiles_data = data.get("profiles") or {"Default": {}}
        profiles = {
            str(name): SerialProfile.from_dict(profile_data)
            for name, profile_data in profiles_data.items()
        }
        settings = cls(
            active_profile=str(data.get("active_profile", "Default")),
            profiles=profiles or {"Default": SerialProfile()},
            command_history=[str(item) for item in data.get("command_history", [])],
            theme=str(data.get("theme", "Workshop Dark")),
            timestamps_enabled=bool(data.get("timestamps_enabled", True)),
            log_path=str(data.get("log_path", "")),
            last_script_path=str(data.get("last_script_path", "")),
            window_width=int(data.get("window_width", 1320)),
            window_height=int(data.get("window_height", 860)),
        )
        settings.ensure_active_profile()
        return settings
