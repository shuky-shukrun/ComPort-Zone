"""Design tokens: theme-independent spacing, radius, and sizing metrics.

Colors live in :mod:`ComPort_Zone.themes` (per-theme ``ThemePalette``). Metrics do
not change between themes, so they stay here as plain module-level ints — matching
the existing house style (``TERMINAL_FONT_MIN``/``MAX``, ``DRAWER_COLLAPSED_WIDTH``).

These constants are the single source of truth for both the QSS f-string in
``ui/main_window.py`` and the widget-build code. Values mirror the Modern-IDE design
handoff (``styles/tokens.css`` + ``styles/app.css``): one 4px spatial rhythm, three
corner radii, a 28px control height, and the bespoke window-shell dimensions.
"""

from __future__ import annotations

# --- Spacing (4px rhythm) ---------------------------------------------------
SPACE_XS = 2
SPACE_SM = 4
SPACE_MD = 6
SPACE_LG = 8
SPACE_XL = 12
SPACE_2XL = 16

# --- Corner radius (handoff: --r-sm 4 / --r 6 / --r-lg 9) -------------------
RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_LG = 9

# --- Control + icon sizing --------------------------------------------------
# --ctrl-h is 28px in the design's compact (default) density.
CONTROL_H = 28
CONTROL_H_SM = 24

ICON_SM = 13
ICON_MD = 16
ICON_LG = 18

# Compact square buttons used for font +/- in the status bar and editor toolbar.
# Width stays >= 38 so both controls remain comfortably clickable (asserted by tests).
FONT_BTN_W = 38
FONT_BTN_H = 30

# --- Layout -----------------------------------------------------------------
SPLITTER_HANDLE = 6
TAB_MIN_W = 120
# Floor for a single split-workspace pane. Kept well below any pane's content size
# hint so the splitter between two panes always has room to move in both directions —
# without it the terminal/editor command bars' (large) minimum widths consume all the
# slack and the divider looks frozen. The content copes with the squeeze: the command
# bars collapse into their ⋯ overflow as a pane narrows.
WORKSPACE_PANE_MIN_W = 200
# Open-drawer floor: wide enough that a row's send/play affordance and the panel
# header's +/⋯ buttons stay visible (title elides). Dragging below this collapses
# the drawer to the rail (see TerminalSessionWidget._drawer_resized).
DRAWER_MIN_W = 180
DRAWER_MAX_W = 520
# Below this dragged width the drawer auto-collapses to the activity rail.
DRAWER_COLLAPSE_AT = 188
FONT_UI_PT = 10

# --- Modern-IDE window shell (from styles/app.css) --------------------------
# Single VS Code-style chrome row: logo + menu bar + command palette + window
# buttons all share this height (the old separate menu row is gone).
TITLE_BAR_H = 32          # .cpz-title
MENU_BAR_H = 26           # legacy; menu items now sit inside the title row
TOOLBAR_H = 44            # .app-toolbar  (ctrl-h + 16)
STATUS_BAR_H = 30         # .cpz-status (24 in design; +6 to seat font controls)
RAIL_W = 46               # .app-rail
RAIL_ICON = 34            # .app-railicon
SESSION_TAB_H = 36        # .app-tabs
WINDOW_BTN_W = 46         # .cpz-wbtn
APP_ICON = 19             # .cpz-appicon
LIVE_DOT = 7              # .app-tab .tdot / title live dot
LED_LAMP = 18             # control_panel LED tile lamp diameter

# --- Typography (px, matching the handoff) ----------------------------------
UI_FS = 12                # --ui-fs
TERM_FS = 13              # --term-fs
MICRO_FS = 11             # status / footnote scale
LABEL_FS = 11             # uppercase section + select labels
