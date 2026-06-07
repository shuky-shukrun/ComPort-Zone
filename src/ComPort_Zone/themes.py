from __future__ import annotations

from dataclasses import dataclass


def _clamp8(value: float) -> int:
    return max(0, min(255, round(value)))


def _split_rgb(color: str) -> tuple[int, int, int]:
    color = color.strip().lstrip("#")
    if len(color) == 3:
        color = "".join(ch * 2 for ch in color)
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def mix_hex(color_a: str, color_b: str, weight: float) -> str:
    """Blend ``color_a`` over ``color_b`` by ``weight`` (0..1), returning ``#rrggbb``.

    Qt style sheets have no ``color-mix()``, so the design's blended tones (e.g. a TX
    line tinted 55% green over terminal ink) are precomputed here. A straight sRGB
    lerp is visually close enough to the design's oklab mixes for solid UI fills.
    """
    ar, ag, ab = _split_rgb(color_a)
    br, bg, bb = _split_rgb(color_b)
    weight = max(0.0, min(1.0, weight))
    r = _clamp8(ar * weight + br * (1 - weight))
    g = _clamp8(ag * weight + bg * (1 - weight))
    b = _clamp8(ab * weight + bb * (1 - weight))
    return f"#{r:02x}{g:02x}{b:02x}"


def rgba(color: str, alpha: float) -> str:
    """Return a Qt ``rgba(r, g, b, a)`` string for ``color`` at ``alpha`` (0..1).

    Used for the design's ``color-mix(..., transparent)`` overlays (hover washes,
    soft chip fills) where the backdrop should show through.
    """
    r, g, b = _split_rgb(color)
    return f"rgba({r}, {g}, {b}, {max(0.0, min(1.0, alpha)):.3f})"


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
    terminal_bg: str
    on_accent: str
    # Optional brand gradient for primary surfaces (connect button, status seg, tab
    # underline). When empty the UI falls back to the solid ``accent`` color so older
    # themes keep their original look. Format: any valid Qt qlineargradient stops
    # spec — e.g. ``"#57d98a, #38c4c0, #4a9bff"``.
    brand_gradient: str = ""
    # Modern-IDE design palette extensions. These default to neutral choices when a
    # legacy theme does not declare them so existing QSS keeps working unchanged.
    border_soft: str = ""
    border_strong: str = ""
    text_faint: str = ""
    # Hover wash for rows/rail/menu (design --bg-hover). Falls back to ``surface_alt``
    # when a legacy theme does not declare it.
    hover: str = ""


# ComPort Zone Modern-IDE design system.
# Source: design handoff bundle (Direction A — Tabbed Terminal, with B's left dock
# and per-file play buttons). Brand mark is a green→blue gradient; green = TX
# (outgoing), blue = RX (incoming).
COMPORT_DARK = ThemePalette(
    name="ComPort Zone Dark",
    window="#0d1017",
    window_alt="#141821",
    surface="#141821",
    surface_alt="#1a1f2b",
    field="#0a0d13",
    text="#e7ebf2",
    muted="#9aa6b8",
    border="#252c3a",
    accent="#4a9bff",
    accent_soft="#1a2740",
    chip="#13233a",
    search_highlight="#223049",
    tx="#57d98a",
    rx="#4a9bff",
    error="#f0596b",
    status="#f3b13b",
    terminal_bg="#0d1017",
    on_accent="#06131a",
    brand_gradient="#57d98a, #38c4c0, #4a9bff",
    border_soft="#1b212c",
    border_strong="#313a4c",
    text_faint="#5e6a7e",
    hover="#1f2533",
)

COMPORT_LIGHT = ThemePalette(
    name="ComPort Zone Light",
    window="#f4f6fa",
    window_alt="#ffffff",
    surface="#ffffff",
    surface_alt="#eef1f6",
    field="#ffffff",
    text="#1a2230",
    muted="#57637a",
    border="#d8dee8",
    accent="#2f74e0",
    accent_soft="#dfe9fb",
    chip="#e2ecfb",
    search_highlight="#b9ddff",
    tx="#1f9d57",
    rx="#2f74e0",
    error="#d83a52",
    status="#c47e08",
    terminal_bg="#ffffff",
    on_accent="#ffffff",
    brand_gradient="#1f9d57, #11968f, #2f74e0",
    border_soft="#e6eaf1",
    border_strong="#c2cad7",
    text_faint="#aeb6c4",
    hover="#e9edf3",
)


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
    terminal_bg="#0c0c0c",
    on_accent="#ffffff",
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
    terminal_bg="#0c0c0c",
    on_accent="#04222e",
)

THEMES = {
    "ComPort Zone Dark": COMPORT_DARK,
    "ComPort Zone Light": COMPORT_LIGHT,
    "VS Code Dark": VS_CODE_DARK,
    # Legacy name from the earlier prototype. Loading it now lands on the new default.
    "Workshop Dark": COMPORT_DARK,
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
        terminal_bg="#ffffff",
        on_accent="#ffffff",
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
        terminal_bg="#140d07",
        on_accent="#2a1a08",
    ),
}
