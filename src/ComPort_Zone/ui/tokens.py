"""Design tokens: theme-independent spacing, radius, and sizing metrics.

Colors live in :mod:`ComPort_Zone.themes` (per-theme ``ThemePalette``). Metrics do
not change between themes, so they stay here as plain module-level ints — matching
the existing house style (``TERMINAL_FONT_MIN``/``MAX``, ``DRAWER_COLLAPSED_WIDTH``).

These constants are the single source of truth for both the QSS f-string in
``ui/main_window.py`` and the widget-build code. The goal is one consistent 4px
spatial rhythm and a small, predictable set of corner radii and control sizes,
replacing the hand-typed magic numbers that drifted across the UI.
"""

from __future__ import annotations

# --- Spacing (4px rhythm) ---------------------------------------------------
SPACE_XS = 2
SPACE_SM = 4
SPACE_MD = 6
SPACE_LG = 8
SPACE_XL = 12
SPACE_2XL = 16

# --- Corner radius (only three) ---------------------------------------------
RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 10

# --- Control + icon sizing --------------------------------------------------
CONTROL_H = 28
CONTROL_H_SM = 24

ICON_SM = 14
ICON_MD = 16
ICON_LG = 18

# Compact square buttons used for font +/- in the status bar and editor toolbar.
# Width >= 38 keeps both the editor and status-bar controls comfortably clickable.
FONT_BTN_W = 38
FONT_BTN_H = 30

# --- Layout -----------------------------------------------------------------
SPLITTER_HANDLE = 6
TAB_MIN_W = 150
DRAWER_MIN_W = 220
DRAWER_MAX_W = 520
FONT_UI_PT = 10
