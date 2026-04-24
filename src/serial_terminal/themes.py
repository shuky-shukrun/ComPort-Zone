from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ThemePalette:
    name: str
    window: str
    window_alt: str
    surface: str
    surface_alt: str
    field: str
    text: str
    muted: str
    border: str
    accent: str
    accent_soft: str
    chip: str
    search_highlight: str
    tx: str
    rx: str
    error: str
    status: str


VS_CODE_DARK = ThemePalette(
    name="VS Code Dark",
    window="#1e1e1e",
    window_alt="#252526",
    surface="#252526",
    surface_alt="#2d2d30",
    field="#1f1f1f",
    text="#d4d4d4",
    muted="#9da5b4",
    border="#3c3c3c",
    accent="#007acc",
    accent_soft="#09395b",
    chip="#13334c",
    search_highlight="#264f78",
    tx="#4fc1ff",
    rx="#89d185",
    error="#f14c4c",
    status="#d7ba7d",
)

WINDOWS_TERMINAL = ThemePalette(
    name="Windows Terminal",
    window="#0c0c0c",
    window_alt="#181818",
    surface="#1b1b1b",
    surface_alt="#2b2b2b",
    field="#151515",
    text="#cccccc",
    muted="#8a8a8a",
    border="#303030",
    accent="#4cc2ff",
    accent_soft="#06344a",
    chip="#102a38",
    search_highlight="#264f78",
    tx="#6cb6ff",
    rx="#b5cea8",
    error="#f44747",
    status="#dcdcaa",
)

THEMES = {
    "VS Code Dark": VS_CODE_DARK,
    # Legacy name from the earlier prototype. Loading it now lands on the new default.
    "Workshop Dark": VS_CODE_DARK,
    "Windows Terminal": WINDOWS_TERMINAL,
    "Bench Light": ThemePalette(
        name="Bench Light",
        window="#eef4ff",
        window_alt="#f7f9fc",
        surface="#ffffff",
        surface_alt="#f4f7fb",
        field="#ffffff",
        text="#112031",
        muted="#5f6f82",
        border="#d2ddec",
        accent="#0f766e",
        accent_soft="#d7f3ef",
        chip="#e7f5f3",
        search_highlight="#b9ddff",
        tx="#0f62fe",
        rx="#0f8a4b",
        error="#c2410c",
        status="#9a6700",
    ),
    "Scope Amber": ThemePalette(
        name="Scope Amber",
        window="#120d09",
        window_alt="#1b130d",
        surface="#24180f",
        surface_alt="#2c1d12",
        field="#1a120c",
        text="#ffe7c2",
        muted="#c8a97d",
        border="#6f4b2f",
        accent="#ff9f1c",
        accent_soft="#4e2f10",
        chip="#412812",
        search_highlight="#7b4a1a",
        tx="#ffd166",
        rx="#95d5b2",
        error="#ff7b72",
        status="#ffb703",
    ),
}
