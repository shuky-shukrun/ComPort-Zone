from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ThemePalette:
    name: str
    window: str
    panel: str
    field: str
    text: str
    muted: str
    border: str
    accent: str
    tx: str
    rx: str
    error: str
    status: str


THEMES = {
    "Workshop Dark": ThemePalette(
        name="Workshop Dark",
        window="#14181e",
        panel="#1b212b",
        field="#222a35",
        text="#f2f5f8",
        muted="#94a0ad",
        border="#314155",
        accent="#3ddc97",
        tx="#64d2ff",
        rx="#b7f774",
        error="#ff6b6b",
        status="#ffcc66",
    ),
    "Bench Light": ThemePalette(
        name="Bench Light",
        window="#f4f1e7",
        panel="#fffaf0",
        field="#ffffff",
        text="#1c232b",
        muted="#68727d",
        border="#d8caa4",
        accent="#0f766e",
        tx="#0f62fe",
        rx="#287d3c",
        error="#b42318",
        status="#9a6700",
    ),
    "Scope Amber": ThemePalette(
        name="Scope Amber",
        window="#150d08",
        panel="#22140a",
        field="#2a1c10",
        text="#ffd9a8",
        muted="#b89064",
        border="#704a28",
        accent="#ff9f1c",
        tx="#ffd166",
        rx="#80ed99",
        error="#ff7b72",
        status="#ffb703",
    ),
}
