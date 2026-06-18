"""Central Qt style sheet for ComPort Zone — the Modern-IDE design system.

This is the faithful Qt translation of the design handoff (``styles/tokens.css`` +
``styles/app.css``). It is deliberately the *single* large QSS surface so the window
logic in :mod:`ui.main_window` stays readable.

Qt style sheets support only a subset of CSS, so a few design constructs are
translated rather than copied:

* ``color-mix(..., transparent)`` overlays  -> :func:`themes.rgba`
* ``color-mix()`` between two solid tones    -> :func:`themes.mix_hex` (precomputed)
* gradients                                  -> ``qlineargradient(...)``
* ``box-shadow`` / ``filter`` / ``letter-spacing`` -> dropped (Qt ignores them)

Everything else (radii, control heights, spacing, the green->blue brand gradient,
TX=green / RX=blue semantics) maps directly onto the same tokens the prototype uses.
"""

from __future__ import annotations

from ..icons import (
    checked_checkbox_image_path,
    gradient_line_image_path,
    scrollbar_arrow_image_path,
)
from ..themes import ThemePalette, mix_hex, rgba
from .tokens import (
    CONTROL_H,
    FONT_BTN_W,
    LABEL_FS,
    LED_LAMP,
    MENU_BAR_H,
    MICRO_FS,
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
    SESSION_TAB_H,
    TAB_MIN_W,
    UI_FS,
)

# Mono stack for terminal-flavoured chrome (chips, status bar, list rows). Qt honours
# the fallback list, so this lands on Cascadia/JetBrains where present and Consolas
# (always installed on Windows) otherwise.
MONO = '"Cascadia Mono", "JetBrains Mono", "Consolas", monospace'


def brand_gradient(theme: ThemePalette) -> str:
    """Return a horizontal ``qlineargradient`` for the green->teal->blue brand mark."""
    if not theme.brand_gradient:
        return theme.accent
    stops = [s.strip() for s in theme.brand_gradient.split(",") if s.strip()]
    if len(stops) >= 3:
        return (
            "qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {stops[0]}, stop:0.45 {stops[1]}, stop:1 {stops[-1]})"
        )
    if len(stops) == 2:
        return f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {stops[0]}, stop:1 {stops[1]})"
    return stops[0]


def build_stylesheet(theme: ThemePalette) -> str:
    # --- surfaces / ink (design token aliases) ------------------------------
    bg = theme.window            # --bg-base
    panel = theme.window_alt     # --bg-panel
    elevated = theme.surface_alt  # --bg-elevated
    field = theme.field          # --bg-input
    hover = theme.hover or theme.surface_alt
    sel = theme.search_highlight  # --bg-sel
    bd = theme.border
    bd_soft = theme.border_soft or theme.border
    bd_strong = theme.border_strong or theme.border
    tx = theme.text
    tx2 = theme.muted
    tx3 = theme.text_faint or theme.muted
    tx_faint = mix_hex(tx3, bg, 0.62)
    term_bg = theme.terminal_bg

    # --- semantics ----------------------------------------------------------
    green = theme.tx
    blue = theme.rx
    accent = theme.accent
    amber = theme.status
    red = theme.error
    on_accent = theme.on_accent
    grad = brand_gradient(theme)
    # The brand gradient stops, also rendered to a thin PNG so it can paint the
    # gradient accent *lines* (active tab underline + active split-pane edge) — QSS
    # `border` only accepts a solid color, so those use `border-image` instead.
    grad_stops = tuple(s.strip() for s in theme.brand_gradient.split(",") if s.strip()) or (accent,)
    grad_line = gradient_line_image_path(grad_stops)
    # A flat strip (same mechanism) for the *inactive* split pane's selected tab —
    # `border-image: none` does not reliably reset an inherited border-image in Qt
    # QSS, so the muted line must replace the image with another image.
    muted_line = gradient_line_image_path((bd_strong,))
    # A real tick for checked checkboxes (QSS-styled indicators drop the native one).
    check_img = checked_checkbox_image_path(accent, "#ffffff", 16, RADIUS_SM)

    # --- precomputed blends (Qt has no color-mix) ---------------------------
    line_hover = rgba(tx, 0.05)
    ghost_on_bg = rgba(accent, 0.13)
    press_bg = rgba(accent, 0.16)
    ok_bg = rgba(green, 0.12)
    ok_bd = mix_hex(green, bg, 0.42)
    warn_bg = rgba(amber, 0.12)
    err_bg = rgba(red, 0.12)
    danger_bd = mix_hex(red, bd, 0.45)
    sel_text = tx
    # Scrollbar handle: a muted grey that reads clearly against the panel (the old
    # elevated tone was nearly invisible), a touch brighter on hover.
    scroll_handle = mix_hex(tx2, panel, 0.42)
    scroll_handle_hover = mix_hex(tx2, panel, 0.15)
    # Editor "Run" button — vivid brand green, lighter on hover / darker on press.
    run_btn = green
    run_btn_hover = mix_hex(green, "#ffffff", 0.16)
    run_btn_press = mix_hex(green, bg, 0.20)
    # Themed arrow glyphs for the two scrollbar buttons (no native arrows once the
    # bar is QSS-styled). A clearly-readable grey, brightening to full ink on hover.
    arrow_ink = mix_hex(tx2, tx, 0.45)
    arrow_up = scrollbar_arrow_image_path("up", arrow_ink)
    arrow_down = scrollbar_arrow_image_path("down", arrow_ink)
    arrow_left = scrollbar_arrow_image_path("left", arrow_ink)
    arrow_right = scrollbar_arrow_image_path("right", arrow_ink)
    arrow_up_h = scrollbar_arrow_image_path("up", tx)
    arrow_down_h = scrollbar_arrow_image_path("down", tx)
    arrow_left_h = scrollbar_arrow_image_path("left", tx)
    arrow_right_h = scrollbar_arrow_image_path("right", tx)

    parts: list[str] = []

    # =====================================================================
    # Base
    # =====================================================================
    parts.append(f"""
    QMainWindow, QDialog {{ background: {bg}; }}
    QWidget {{
        background: {bg};
        color: {tx};
    }}
    /* Labels carry no surface of their own — they show their container's colour
       (so header icons/titles match the panel). Chips re-add a background by id. */
    QLabel {{ background: transparent; }}
    QToolTip {{
        background: {elevated};
        color: {tx};
        border: 1px solid {bd_strong};
        border-radius: {RADIUS_SM}px;
        padding: 4px 7px;
    }}
    """)

    # =====================================================================
    # Window chrome — custom title bar + menu bar
    # =====================================================================
    parts.append(f"""
    QWidget#titleBar {{
        background: {panel};
        border-bottom: 1px solid {bd_soft};
    }}
    QToolButton#windowButton {{
        background: transparent;
        border: none;
        color: {tx3};
        border-radius: 0px;
    }}
    QToolButton#windowButton:hover {{ background: {hover}; color: {tx}; }}
    QToolButton#windowButtonClose:hover {{ background: #e23a4e; color: #ffffff; }}

    /* Command palette box ("command center"), centred in the title row. */
    QToolButton#commandCenter {{
        background: {field};
        color: {tx2};
        border: 1px solid {bd_soft};
        border-radius: {RADIUS_SM}px;
        padding: 3px 12px;
        font-size: {UI_FS}px;
        min-width: 240px; max-width: 440px;
    }}
    QToolButton#commandCenter:hover {{ background: {hover}; border-color: {bd_strong}; color: {tx}; }}

    /* The application menu bar now lives inside the title row — transparent so the
       bar's panel colour shows through, with items vertically centred in the row. */
    QMenuBar {{
        background: transparent;
        color: {tx2};
        border: none;
        padding: 0;
        font-size: {UI_FS}px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 4px 9px;
        border-radius: {RADIUS_SM}px;
        color: {tx2};
    }}
    QMenuBar::item:selected {{ background: {hover}; color: {tx}; }}
    QMenuBar::item:pressed {{ background: {hover}; color: {tx}; }}

    QMenu {{
        background: {panel};
        color: {tx};
        border: 1px solid {bd};
        border-radius: {RADIUS_MD}px;
        padding: 5px;
    }}
    QMenu::item {{
        background: transparent;
        padding: 6px 26px 6px 22px;
        border-radius: {RADIUS_SM}px;
        color: {tx};
    }}
    QMenu::item:selected {{ background: {hover}; color: {tx}; }}
    QMenu::item:disabled {{ color: {tx_faint}; }}
    QMenu::separator {{ height: 1px; background: {bd_soft}; margin: 5px 8px; }}
    QMenu::icon {{ padding-left: 6px; }}
    """)

    # =====================================================================
    # Buttons
    # =====================================================================
    parts.append(f"""
    QPushButton {{
        background: {elevated};
        color: {tx};
        border: 1px solid {bd};
        border-radius: {RADIUS_SM}px;
        padding: 6px 11px;
        min-height: {CONTROL_H - 14}px;
        font-size: {UI_FS}px;
        font-weight: 500;
    }}
    QPushButton:hover {{ background: {hover}; border-color: {bd_strong}; }}
    QPushButton:pressed {{ background: {press_bg}; }}
    QPushButton:focus {{ border-color: {accent}; outline: none; }}
    QPushButton:disabled {{ color: {tx_faint}; border-color: {bd_soft}; background: {panel}; }}

    QPushButton[role="accent"], QPushButton[role="primary"] {{
        background: {grad};
        color: {on_accent};
        border: none;
        font-weight: 600;
        padding: 6px 13px;
    }}
    QPushButton[role="accent"]:hover, QPushButton[role="primary"]:hover {{ background: {grad}; }}
    QPushButton[role="accent"]:disabled, QPushButton[role="primary"]:disabled {{
        background: {elevated}; color: {tx_faint};
    }}

    QPushButton[role="danger"] {{ color: {red}; border-color: {danger_bd}; }}
    QPushButton[role="danger"]:hover {{ background: {err_bg}; border-color: {red}; }}

    QPushButton[role="ghost"] {{ background: transparent; border-color: transparent; color: {tx2}; }}
    QPushButton[role="ghost"]:hover {{ background: {hover}; color: {tx}; }}
    QPushButton[role="ghost"][on="true"] {{ color: {accent}; background: {ghost_on_bg}; }}
    """)

    # =====================================================================
    # Inputs / combos
    # =====================================================================
    parts.append(f"""
    QLineEdit, QComboBox, QAbstractSpinBox {{
        background: {field};
        color: {tx};
        border: 1px solid {bd};
        border-radius: {RADIUS_SM}px;
        padding: 5px 9px;
        selection-background-color: {sel};
        selection-color: {tx};
    }}
    QLineEdit:hover, QComboBox:hover {{ border-color: {bd_strong}; }}
    QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {{ border-color: {accent}; }}
    QComboBox {{ padding-right: 24px; }}
    /* Setting a border on a styled QAbstractSpinBox disables the native
       steppers, so the up/down buttons must be defined explicitly or they
       stop responding to clicks. */
    QAbstractSpinBox {{ padding-right: 20px; }}
    QAbstractSpinBox::up-button {{
        subcontrol-origin: border; subcontrol-position: top right;
        width: 18px; border: none; background: transparent;
    }}
    QAbstractSpinBox::down-button {{
        subcontrol-origin: border; subcontrol-position: bottom right;
        width: 18px; border: none; background: transparent;
    }}
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {hover}; }}
    QAbstractSpinBox::up-arrow {{ image: url({arrow_up}); width: 9px; height: 9px; }}
    QAbstractSpinBox::down-arrow {{ image: url({arrow_down}); width: 9px; height: 9px; }}
    QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled {{ image: none; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding; subcontrol-position: center right;
        width: 22px; border: none; background: transparent;
    }}
    QComboBox QAbstractItemView {{
        background: {panel};
        color: {tx};
        border: 1px solid {bd};
        border-radius: {RADIUS_MD}px;
        padding: 4px;
        outline: none;
        selection-background-color: {hover};
        selection-color: {tx};
    }}
    QComboBox QAbstractItemView::item {{ padding: 5px 8px; border-radius: {RADIUS_SM}px; min-height: 20px; }}
    /* A styled ::item (border-radius) suppresses the view's
       selection-background-color, so the highlighted/current row must be
       painted explicitly or the dropdown shows no marked line. */
    QComboBox QAbstractItemView::item:hover,
    QComboBox QAbstractItemView::item:selected {{ background: {hover}; color: {tx}; }}
    """)

    # =====================================================================
    # Session tab bar (.app-tabs / .app-tab)
    # =====================================================================
    parts.append(f"""
    QTabWidget::pane {{ border: none; background: {bg}; }}
    QTabWidget[activePane="true"]::pane, QTabWidget[activePane="false"]::pane {{
        border-top: 1px solid {bd_soft};
    }}
    QTabBar {{ background: {bg}; border-bottom: 1px solid {bd_soft}; qproperty-drawBase: 0; }}
    QTabBar::tab {{
        background: transparent;
        color: {tx3};
        padding: 8px 14px;
        min-width: {TAB_MIN_W}px;
        height: {SESSION_TAB_H - 14}px;
        border: none;
        border-bottom: 2px solid transparent;
        font-size: {UI_FS}px;
    }}
    QTabBar::tab:hover:!selected {{ color: {tx2}; }}
    QTabBar::tab:selected {{
        color: {tx};
        border-bottom: 2px solid transparent;
        border-image: url({grad_line}) 0 0 2 0 stretch;
    }}
    QTabWidget[activePane="false"] QTabBar::tab:selected {{
        border-bottom: 2px solid transparent;
        border-image: url({muted_line}) 0 0 2 0 stretch;
    }}

    QToolButton#newTabButton {{
        background: transparent;
        color: {tx3};
        border: none;
        border-radius: {RADIUS_SM}px;
        font-size: 16px;
        padding: 0 8px;
    }}
    QToolButton#newTabButton:hover {{ background: {hover}; color: {tx}; }}
    QToolButton#tabCloseButton {{
        background: transparent; color: {tx_faint};
        border: none; border-radius: 3px; padding: 0; margin-right: 2px;
    }}
    QToolButton#tabCloseButton:hover {{ background: {hover}; color: {tx}; }}
    /* Hide the native left/right scroll arrows on the session tab strip — overflow
       is surfaced through the ⋯ menu (QToolButton#tabOverflowButton) instead, while
       scroll mode is kept on so the tab bar's minimum width stays ≈ one tab. */
    QTabWidget#sessionTabs QTabBar::scroller {{ width: 0px; height: 0px; }}
    QToolButton#tabOverflowButton {{
        background: transparent; border: none; border-radius: {RADIUS_SM}px;
        color: {tx2}; font-size: 15px; font-weight: 700; padding: 0;
    }}
    QToolButton#tabOverflowButton:hover {{ background: {hover}; color: {tx}; }}
    QToolButton#tabOverflowButton::menu-indicator {{ image: none; width: 0; }}
    """)

    # =====================================================================
    # Activity rail + drawer / side panel (.app-rail / .app-side)
    # =====================================================================
    parts.append(f"""
    QFrame#drawer {{ background: {panel}; border-right: 1px solid {bd_soft}; }}
    QFrame#drawerRail {{ background: {bg}; border-right: 1px solid {bd_soft}; }}
    QFrame#drawerPanel, QFrame#editorSidePanel {{ background: {panel}; }}
    QFrame#editorSidePanel {{ border-right: 1px solid {bd_soft}; }}
    /* Let the side panel's {panel} colour show through its scroll/content layers
       instead of the generic QWidget base — otherwise the dock reads as base black. */
    QScrollArea#drawerScroll {{ background: transparent; border: none; }}
    QWidget#drawerViewport {{ background: transparent; }}
    QWidget#drawerContent {{ background: transparent; }}
    QWidget#drawerListViewport {{ background: transparent; }}
    QFrame#quickActionPage {{ background: transparent; }}

    QToolButton#railButton {{
        background: transparent;
        color: {tx3};
        border: none;
        border-left: 2px solid transparent;
        border-radius: 0px;
        padding: 7px 4px;
        margin: 2px 6px 2px 0;
    }}
    QToolButton#railButton:hover {{ background: {hover}; color: {tx2}; }}
    QToolButton#railButton:checked {{ color: {tx}; border-left: 2px solid {accent}; }}

    QLabel#drawerTitle {{
        color: {tx3};
        font-size: {LABEL_FS}px;
        font-weight: 700;
        padding: 8px 4px 6px 4px;
    }}
    QLabel#drawerSection {{
        color: {tx3};
        font-size: {LABEL_FS - 1}px;
        font-weight: 700;
        padding: 10px 4px 4px 4px;
    }}
    QLabel#drawerHelpText {{ color: {tx2}; padding: 2px 3px 6px 3px; }}

    /* panel header (.cpz-panel-h): icon + UPPERCASE title + count badge + +/⋯ */
    QFrame#quickPanelHeader {{
        background: transparent;
        border-bottom: 1px solid {bd_soft};
        min-height: 30px;
    }}
    QLabel#quickPanelTitle {{ color: {tx3}; font-size: {LABEL_FS}px; font-weight: 700; }}
    QLabel#quickPanelCount {{
        color: {tx3}; background: transparent;
        padding: 1px 5px; min-width: 12px;
        font-family: {MONO}; font-size: 10px;
    }}
    QToolButton#quickPanelHeaderButton {{
        background: transparent; border: none; border-radius: {RADIUS_SM}px;
        color: {tx3}; font-size: 15px; font-weight: 600; padding: 0;
        min-width: 20px; max-width: 22px; min-height: 22px;
    }}
    QToolButton#quickPanelHeaderButton:hover {{ background: {hover}; color: {tx}; }}
    QToolButton#quickPanelHeaderButton::menu-indicator {{ image: none; width: 0; }}
    QToolButton#quickPanelCollapse {{
        background: transparent; border: none; border-radius: {RADIUS_SM}px;
        padding: 0; min-width: 18px; max-width: 18px; min-height: 22px;
    }}
    QToolButton#quickPanelCollapse:hover {{ background: {hover}; }}
    QListWidget#quickHistoryList {{
        background: transparent; padding: 4px;
        qproperty-placeholderColor: {tx_faint};
    }}
    """)

    # =====================================================================
    # List rows (.cpz-item) — quick commands / files / generic lists
    # =====================================================================
    parts.append(f"""
    QListWidget {{ outline: none; background: transparent; border: none; }}
    QListWidget::item {{
        color: {tx};
        border-radius: {RADIUS_SM}px;
        padding: 6px 9px;
        margin: 1px 2px;
    }}
    QListWidget::item:hover {{ background: {hover}; }}
    QListWidget::item:selected {{ background: {sel}; color: {sel_text}; }}
    QListWidget#quickCommandList, QListWidget#quickFileList {{
        background: transparent; padding: 4px 4px;
        qproperty-placeholderColor: {tx_faint};
    }}
    QListWidget#quickCommandList::item, QListWidget#quickFileList::item {{
        font-family: {MONO};
        border-radius: {RADIUS_SM}px;
        padding: 5px 7px;
        margin: 1px 0;
    }}

    QPushButton#drawerActionButton {{
        text-align: left;
        border-radius: {RADIUS_MD}px;
        padding: 8px 10px;
    }}
    QPushButton#drawerActionButton[role="drawerPrimary"] {{
        background: {grad}; color: {on_accent}; border: none; font-weight: 600;
    }}
    QPushButton#drawerActionButton[role="drawerPrimary"]:hover {{ background: {grad}; }}
    QPushButton#drawerActionButton[role="drawerDanger"]:hover {{ background: {err_bg}; border-color: {red}; color: {red}; }}

    QToolButton#drawerMenuButton {{
        background: {field}; color: {tx};
        border: 1px solid {bd}; border-radius: {RADIUS_SM}px;
        padding: 6px 9px;
    }}
    QToolButton#drawerMenuButton:hover {{ border-color: {bd_strong}; }}
    QToolButton#drawerMenuButton::menu-indicator {{ image: none; width: 0; }}
    QComboBox#quickSortCombo, QComboBox#quickFileSortCombo {{ padding: 5px 9px; }}
    """)

    # =====================================================================
    # Terminal + command/input bar + search bar
    # =====================================================================
    parts.append(f"""
    QFrame#terminalColumn {{ background: {bg}; border: none; }}
    QTextEdit#terminal {{
        background: {term_bg};
        color: {tx};
        border: none;
        border-top: 2px solid transparent;
        selection-background-color: {sel};
        selection-color: {tx};
    }}
    QTextEdit#terminal[activeWorkspaceTab="true"] {{
        border-top: 2px solid transparent;
        border-image: url({grad_line}) 2 0 0 0 stretch;
    }}

    QFrame#commandBar, QFrame#searchBar {{
        background: {panel};
        border-top: 1px solid {bd_soft};
    }}
    QFrame#searchBar {{ border-bottom: 1px solid {bd_soft}; border-top: none; }}

    /* Floating find / find+replace overlay (terminal + editor). */
    QFrame#searchOverlay {{
        background: {elevated}; border: 1px solid {bd_strong}; border-radius: {RADIUS_MD}px;
    }}
    QLineEdit#searchOverlayField {{
        background: {field}; border: 1px solid {bd}; border-radius: {RADIUS_SM}px;
        padding: 3px 7px; color: {tx}; min-width: 150px; min-height: 22px;
    }}
    QLineEdit#searchOverlayField:focus {{ border: 1px solid {accent}; }}
    QToolButton#searchOverlayButton {{
        background: transparent; border: 1px solid transparent; border-radius: {RADIUS_SM}px;
        color: {tx2}; font-size: 12px; font-weight: 600; padding: 0 6px; min-width: 24px; min-height: 22px;
    }}
    QToolButton#searchOverlayButton:hover {{ background: {hover}; color: {tx}; }}
    QToolButton#searchOverlayButton:checked {{ background: {ghost_on_bg}; color: {accent}; border: 1px solid {accent}; }}
    QToolButton#searchOverlayIcon {{
        background: transparent; border: none; border-radius: {RADIUS_SM}px; min-width: 22px; min-height: 22px;
    }}
    QToolButton#searchOverlayIcon:hover {{ background: {hover}; }}
    QLabel#searchOverlayCount {{ color: {tx3}; font-family: {MONO}; font-size: 11px; }}

    /* Command-file editor chrome: icon toolbar + green Run button. */
    QToolButton#editorToolButton {{
        background: transparent; border: none; border-radius: {RADIUS_SM}px;
        padding: 2px; min-width: 26px; min-height: 24px;
    }}
    QToolButton#editorToolButton:hover {{ background: {hover}; }}
    QFrame#editorToolbarRule {{ background: {bd_soft}; border: none; max-height: 1px; min-height: 1px; }}
    QLabel#editorSendLabel {{ color: {tx3}; font-size: {MICRO_FS}px; padding: 0 2px; }}
    QPushButton#editorRunButton {{
        background: {run_btn}; color: {on_accent}; border: none; border-radius: {RADIUS_SM}px;
        padding: 4px 14px; font-weight: 700; min-height: 24px;
    }}
    QPushButton#editorRunButton:hover {{ background: {run_btn_hover}; }}
    QPushButton#editorRunButton:pressed {{ background: {run_btn_press}; }}
    /* Grayed-out while no terminal is connected to run into. The #id selector
       outweighs the generic QPushButton:disabled rule, so it needs its own. */
    QPushButton#editorRunButton:disabled {{ background: {elevated}; color: {tx_faint}; }}

    QLabel#editorStatusLabel, QLabel#editorPathLabel {{
        color: {tx3}; font-size: {MICRO_FS}px; padding: 0 2px;
    }}
    QToolButton#commandBarOverflow {{
        background: transparent; border: none; border-radius: {RADIUS_SM}px;
        color: {tx2}; font-size: 15px; font-weight: 700; padding: 0 6px; min-width: 22px;
    }}
    QToolButton#commandBarOverflow:hover {{ background: {hover}; color: {tx}; }}
    QToolButton#commandBarOverflow::menu-indicator {{ image: none; width: 0; }}

    /* status-area view/IO toggles (timestamps, hex, log): ghost until active */
    QToolButton#statusToggleButton {{
        background: transparent; border: none; border-radius: {RADIUS_SM}px;
        color: {tx2}; padding: 0; min-width: 26px; max-width: 30px; min-height: 24px;
    }}
    QToolButton#statusToggleButton:hover {{ background: {hover}; color: {tx}; }}
    QToolButton#statusToggleButton:checked {{ background: {ghost_on_bg}; color: {accent}; }}
    QToolButton#statusToggleButton:checked:hover {{ background: {press_bg}; }}
    """)

    # =====================================================================
    # Connection status chip (.cpz-chip) — pill with state colours
    # =====================================================================
    parts.append(f"""
    QLabel#connectionStatus, QLabel#terminalConnectionStatus {{
        background: {field};
        color: {tx2};
        border: 1px solid {bd};
        border-radius: 11px;
        padding: 3px 11px;
        font-family: {MONO};
        font-size: {MICRO_FS}px;
        font-weight: 600;
    }}
    QLabel#connectionStatus[state="connected"], QLabel#terminalConnectionStatus[state="connected"] {{
        color: {green}; border-color: {ok_bd}; background: {ok_bg};
    }}
    QLabel#connectionStatus[state="retrying"], QLabel#terminalConnectionStatus[state="retrying"] {{
        color: {amber}; border-color: {amber}; background: {warn_bg};
    }}
    QLabel#connectionStatus[state="missing"], QLabel#terminalConnectionStatus[state="missing"] {{
        color: {red}; border-color: {red}; background: {err_bg};
    }}
    QLabel#connectionStatus[state="no-port"], QLabel#terminalConnectionStatus[state="no-port"] {{
        color: {tx3}; border-color: {bd};
    }}

    QPushButton#statusActionButton, QPushButton#terminalConnectionActionButton {{
        min-width: 88px; padding: 5px 12px; border-radius: {RADIUS_SM}px;
    }}
    QPushButton#statusActionButton[role="connected"], QPushButton#terminalConnectionActionButton[role="connected"] {{ color: {green}; border-color: {ok_bd}; }}
    QPushButton#statusActionButton[role="retrying"], QPushButton#terminalConnectionActionButton[role="retrying"] {{ color: {amber}; border-color: {amber}; }}
    QPushButton#statusActionButton[role="missing"], QPushButton#terminalConnectionActionButton[role="missing"] {{ color: {red}; border-color: {red}; }}
    QPushButton#statusActionButton[role="no-port"], QPushButton#terminalConnectionActionButton[role="no-port"] {{ color: {tx2}; }}
    QPushButton#statusActionButton:hover, QPushButton#terminalConnectionActionButton:hover {{ border-color: {accent}; }}
    """)

    # =====================================================================
    # Command-file editor (.app-editor) + syntax gutter
    # =====================================================================
    parts.append(f"""
    QTextEdit#commandFileEditor {{
        background: {term_bg};
        color: {tx};
        border: none;
        border-top: 2px solid transparent;
        selection-background-color: {sel};
        selection-color: {tx};
    }}
    QTextEdit#commandFileEditor[activeWorkspaceTab="true"] {{
        border-top: 2px solid transparent;
        border-image: url({grad_line}) 2 0 0 0 stretch;
    }}
    QLabel#editorFontControlsLabel, QLabel#statusFontControlsLabel {{
        color: {tx3}; font-size: {MICRO_FS}px; padding: 0 2px 0 8px;
    }}
    QPushButton#editorFontSizeButton, QPushButton#statusFontSizeButton {{
        min-width: {FONT_BTN_W}px; max-width: {FONT_BTN_W}px;
        padding: 0; border-radius: {RADIUS_SM}px;
        background: transparent; border: 1px solid transparent; color: {tx2};
        font-weight: 600;
    }}
    QPushButton#editorFontSizeButton:hover, QPushButton#statusFontSizeButton:hover {{
        background: {hover}; border-color: {bd_soft}; color: {tx};
    }}
    """)

    # =====================================================================
    # Status bar (.cpz-status) — slim, segmented, mono
    # =====================================================================
    parts.append(f"""
    QStatusBar {{
        background: {bg};
        color: {tx3};
        border-top: 1px solid {bd_soft};
        min-height: {18}px;
        font-family: {MONO};
        font-size: {MICRO_FS}px;
    }}
    QStatusBar::item {{ border: none; }}
    QStatusBar QLabel {{ font-family: {MONO}; }}
    QLabel#footer {{ color: {tx3}; padding-left: 10px; }}
    QLabel#versionInfo {{ color: {tx_faint}; padding: 0 10px; font-size: {MICRO_FS}px; }}
    """)

    # =====================================================================
    # Splitters, scrollbars, dialogs, palette, misc
    # =====================================================================
    parts.append(f"""
    QSplitter::handle {{ background: {bd_soft}; }}
    QSplitter::handle:hover {{ background: {accent}; }}
    /* Favorites resize divider: a thin line that brightens on hover/drag. */
    QSplitter#favoritesSplitter {{ background: transparent; }}
    QSplitter#favoritesSplitter::handle:vertical {{
        background: transparent; height: 11px; margin: 0 2px;
        border-top: 1px solid {bd_soft};
    }}
    QSplitter#favoritesSplitter::handle:vertical:hover {{ border-top: 1px solid {accent}; }}

    /* Scrollbars: transparent track, rounded handle, two arrow buttons (no bg).
       The top/bottom (or left/right) margin reserves the space the arrow buttons
       sit in (subcontrol-origin: margin) — without it they collapse to nothing. */
    QScrollBar:vertical {{ background: transparent; width: 14px; margin: 14px 0 14px 0; border: none; }}
    QScrollBar::handle:vertical {{ background: {scroll_handle}; border-radius: 4px; min-height: 28px; margin: 0 3px; }}
    QScrollBar::handle:vertical:hover {{ background: {scroll_handle_hover}; }}
    QScrollBar::sub-line:vertical {{ background: transparent; border: none; height: 14px; subcontrol-position: top; subcontrol-origin: margin; }}
    QScrollBar::add-line:vertical {{ background: transparent; border: none; height: 14px; subcontrol-position: bottom; subcontrol-origin: margin; }}
    QScrollBar::up-arrow:vertical {{ image: url({arrow_up}); width: 9px; height: 9px; }}
    QScrollBar::down-arrow:vertical {{ image: url({arrow_down}); width: 9px; height: 9px; }}
    QScrollBar::up-arrow:vertical:hover {{ image: url({arrow_up_h}); }}
    QScrollBar::down-arrow:vertical:hover {{ image: url({arrow_down_h}); }}

    QScrollBar:horizontal {{ background: transparent; height: 14px; margin: 0 14px 0 14px; border: none; }}
    QScrollBar::handle:horizontal {{ background: {scroll_handle}; border-radius: 4px; min-width: 28px; margin: 3px 0; }}
    QScrollBar::handle:horizontal:hover {{ background: {scroll_handle_hover}; }}
    QScrollBar::sub-line:horizontal {{ background: transparent; border: none; width: 14px; subcontrol-position: left; subcontrol-origin: margin; }}
    QScrollBar::add-line:horizontal {{ background: transparent; border: none; width: 14px; subcontrol-position: right; subcontrol-origin: margin; }}
    QScrollBar::left-arrow:horizontal {{ image: url({arrow_left}); width: 9px; height: 9px; }}
    QScrollBar::right-arrow:horizontal {{ image: url({arrow_right}); width: 9px; height: 9px; }}
    QScrollBar::left-arrow:horizontal:hover {{ image: url({arrow_left_h}); }}
    QScrollBar::right-arrow:horizontal:hover {{ image: url({arrow_right_h}); }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QLabel#dialogTitle {{ font-size: 15px; font-weight: 700; color: {tx}; }}
    QLabel#dialogHint {{
        background: {elevated}; color: {tx2};
        border: 1px solid {bd}; border-radius: {RADIUS_MD}px; padding: 10px;
    }}
    QDialog#commandPalette {{ background: {panel}; }}
    QLineEdit#commandPaletteSearch {{ font-size: 14px; padding: 10px 12px; border-radius: {RADIUS_MD}px; }}
    QListWidget#commandPaletteList {{ padding: 6px; border-radius: {RADIUS_MD}px; }}
    QListWidget#commandPaletteList::item {{ border-radius: {RADIUS_SM}px; padding: 7px 10px; margin: 2px; }}
    QLabel#commandPaletteHint {{ color: {tx2}; padding: 0 4px; }}

    QLabel#splitDropPreview {{
        background: {ghost_on_bg}; color: {tx};
        border: 2px dashed {accent}; border-radius: {RADIUS_MD}px;
        font-weight: 700; padding: 12px;
    }}
    QCheckBox {{ color: {tx}; spacing: 7px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: {RADIUS_SM}px;
        border: 1px solid {bd_strong}; background: {field};
    }}
    QCheckBox::indicator:checked {{ border: none; image: url({check_img}); }}
    QCheckBox::indicator:checked:hover {{ image: url({check_img}); }}
    """)

    # =====================================================================
    # ControlPanel view — tiles, grid, binding chip
    # =====================================================================
    # State colors mirror ui/control_panel_tiles.tile_state_color: ok=tx green,
    # warn=status amber, fail/error=error red, stale/neutral=muted.
    stale_ink = mix_hex(tx2, bg, 0.75)
    parts.append(f"""
    QWidget#controlPanelGrid {{ background: {bg}; }}
    QWidget#controlPanelHeader {{
        background: {panel};
        border-bottom: 1px solid {bd_soft};
    }}
    QToolButton#controlPanelHeaderButton {{
        background: transparent; border: none; border-radius: {RADIUS_SM}px;
        color: {tx2}; padding: 2px 7px; min-height: 24px;
    }}
    QToolButton#controlPanelHeaderButton:hover {{ background: {hover}; color: {tx}; }}
    QToolButton#controlPanelHeaderButton:pressed {{ background: {press_bg}; }}
    QToolButton#controlPanelHeaderButton:checked {{ background: {ghost_on_bg}; color: {accent}; }}
    QToolButton#controlPanelHeaderButton:checked:hover {{ background: {press_bg}; }}
    /* Master arm (v3, FR-74): amber accent disarmed, red accent armed.
       The armed state is also `checked`, so the [panelArmed] selectors
       win on the cascade by raising specificity. */
    QToolButton#controlPanelHeaderButton[panelArmed="false"] {{ color: {amber}; }}
    QToolButton#controlPanelHeaderButton[panelArmed="true"] {{
        color: {red}; background: {err_bg};
    }}
    QToolButton#controlPanelHeaderButton[panelArmed="true"]:hover {{ background: {press_bg}; }}
    QLabel#controlPanelSaveState {{
        color: {tx_faint}; font-size: {MICRO_FS}px; font-family: {MONO}; padding: 0 4px;
    }}
    QFrame#controlPanelTile {{
        background: {elevated};
        border: 1px solid {bd_soft};
        border-radius: {RADIUS_LG}px;
    }}
    QFrame#controlPanelTile[tileState="ok"] {{ border: 1px solid {ok_bd}; }}
    QFrame#controlPanelTile[tileState="warn"] {{ border: 1px solid {mix_hex(amber, bg, 0.5)}; }}
    QFrame#controlPanelTile[tileState="fail"],
    QFrame#controlPanelTile[tileState="error"] {{ border: 1px solid {danger_bd}; }}
    QFrame#controlPanelTile[editMode="true"] {{ border: 1px dashed {accent}; }}
    QFrame#controlPanelTile[entryEnabled="false"] {{ border: 1px dashed {bd}; }}
    /* Brief flash when a writing tile's value just refreshed (3 s). */
    QFrame#controlPanelTile[recentlyUpdated="true"] {{
        border: 2px solid {accent};
        background: {mix_hex(accent, elevated, 0.22)};
    }}
    QFrame#controlPanelTile QLabel {{ background: transparent; }}
    QFrame#controlPanelTile[entryEnabled="false"] QLabel {{ color: {tx_faint}; }}

    QLabel#tileTitle {{
        color: {tx2};
        font-size: {LABEL_FS}px;
        font-weight: 600;
        letter-spacing: 0.4px;
    }}
    QLabel#tileTimestamp {{ color: {tx_faint}; font-size: {MICRO_FS}px; font-family: {MONO}; }}
    QLabel#tileValue {{
        color: {tx};
        font-family: {MONO};
        font-weight: 600;
    }}
    QLabel#tileValue[tileState="ok"] {{ color: {green}; }}
    QLabel#tileValue[tileState="warn"] {{ color: {amber}; }}
    QLabel#tileValue[tileState="fail"], QLabel#tileValue[tileState="error"] {{ color: {red}; }}
    QLabel#tileValue[tileState="stale"] {{ color: {stale_ink}; }}

    QLabel#tileLamp {{
        border-radius: {LED_LAMP // 2}px;
        background: {stale_ink};
        border: 1px solid {bd_strong};
    }}
    QLabel#tileLamp[tileState="ok"] {{ background: {green}; border-color: {ok_bd}; }}
    QLabel#tileLamp[tileState="warn"] {{ background: {amber}; border-color: {mix_hex(amber, bg, 0.5)}; }}
    QLabel#tileLamp[tileState="fail"], QLabel#tileLamp[tileState="error"]
        {{ background: {red}; border-color: {danger_bd}; }}
    QLabel#tileStateCaption {{ color: {tx}; font-weight: 700; }}
    QLabel#tileStateCaption[tileState="ok"] {{ color: {green}; }}
    QLabel#tileStateCaption[tileState="warn"] {{ color: {amber}; }}
    QLabel#tileStateCaption[tileState="fail"], QLabel#tileStateCaption[tileState="error"]
        {{ color: {red}; }}
    QLabel#tileStateCaption[tileState="stale"] {{ color: {stale_ink}; }}

    QLabel#tileBitsLamp {{
        border-radius: 6px;
        background: {stale_ink};
        border: 1px solid {bd_strong};
    }}
    QLabel#tileBitsLamp[tileState="ok"] {{ background: {green}; border-color: {ok_bd}; }}
    QLabel#tileBitsLamp[tileState="warn"] {{ background: {amber}; border-color: {mix_hex(amber, bg, 0.5)}; }}
    QLabel#tileBitsLamp[tileState="fail"] {{ background: {red}; border-color: {danger_bd}; }}
    QLabel#tileBitsLamp[tileState="neutral"] {{ background: {stale_ink}; border-color: {bd_strong}; }}
    QLabel#tileBitsLabel {{ color: {tx2}; font-weight: 500; }}
    QLabel#tileBitsLabel[bitActive="true"] {{ color: {tx}; font-weight: 700; }}
    QLabel#tileBitsEmpty {{ color: {tx_faint}; font-style: italic; }}

    QPushButton#tileControlButton {{
        background: {hover}; color: {tx};
        border: 1px solid {bd_strong}; border-radius: {RADIUS_MD}px;
        font-weight: 700; padding: 6px 18px; min-height: 26px;
    }}
    QPushButton#tileControlButton:hover {{ background: {press_bg}; border-color: {accent}; }}
    QPushButton#tileControlButton:pressed {{ background: {press_bg}; }}
    QPushButton#tileControlButton:disabled {{ color: {tx_faint}; background: transparent; }}
    QPushButton#tileControlButton[controlState="on"] {{
        background: {ok_bg}; color: {green}; border-color: {ok_bd};
    }}
    /* Mismatch: the device's reported state disagrees with the last
       commanded direction (FR-59). Amber border wins over the on/off
       surface so the warning reads regardless of ON/OFF. */
    QPushButton#tileControlButton[mismatch="true"] {{ border-color: {amber}; }}

    QDoubleSpinBox#tileSetpointSpin {{
        background: {field}; color: {tx};
        border: 1px solid {bd_soft}; border-radius: {RADIUS_SM}px;
        padding: 3px 24px 3px 6px; min-height: 24px;
        font-family: {MONO};
    }}
    QDoubleSpinBox#tileSetpointSpin:focus {{ border-color: {accent}; }}
    QDoubleSpinBox#tileSetpointSpin:disabled {{ color: {tx_faint}; }}
    /* Mismatch: the readback differs from the commanded value (the
       device clamped/rejected the setpoint) — FR-66. */
    QDoubleSpinBox#tileSetpointSpin[mismatch="true"] {{
        color: {amber}; border-color: {amber};
    }}
    /* Custom subcontrols so the step buttons stay clickable when the
       spinbox is themed (Qt drops native rendering once any spinbox QSS
       lands). */
    QDoubleSpinBox#tileSetpointSpin::up-button,
    QDoubleSpinBox#tileSetpointSpin::down-button {{
        subcontrol-origin: border;
        width: 18px;
        background: transparent;
        border-left: 1px solid {bd_soft};
    }}
    QDoubleSpinBox#tileSetpointSpin::up-button {{ subcontrol-position: top right; }}
    QDoubleSpinBox#tileSetpointSpin::down-button {{ subcontrol-position: bottom right; }}
    QDoubleSpinBox#tileSetpointSpin::up-button:hover,
    QDoubleSpinBox#tileSetpointSpin::down-button:hover {{ background: {hover}; }}
    QDoubleSpinBox#tileSetpointSpin::up-button:pressed,
    QDoubleSpinBox#tileSetpointSpin::down-button:pressed {{ background: {press_bg}; }}
    QDoubleSpinBox#tileSetpointSpin::up-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-bottom: 5px solid {tx2};
        width: 0; height: 0;
    }}
    QDoubleSpinBox#tileSetpointSpin::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {tx2};
        width: 0; height: 0;
    }}
    QDoubleSpinBox#tileSetpointSpin::up-arrow:disabled,
    QDoubleSpinBox#tileSetpointSpin::down-arrow:disabled {{ border-color: transparent; }}
    QPushButton#tileSetpointSend {{
        background: {hover}; color: {tx};
        border: 1px solid {bd_strong}; border-radius: {RADIUS_SM}px;
        font-weight: 700; min-height: 22px;
    }}
    QPushButton#tileSetpointSend:hover {{ background: {press_bg}; border-color: {accent}; }}
    QPushButton#tileSetpointSend:pressed {{ background: {press_bg}; }}
    QPushButton#tileSetpointSend:disabled {{ color: {tx_faint}; background: transparent; }}

    QComboBox#tileEnumCombo {{
        background: {field}; color: {tx};
        border: 1px solid {bd_soft}; border-radius: {RADIUS_SM}px;
        padding: 3px 8px; min-height: 22px;
    }}
    QComboBox#tileEnumCombo:focus {{ border-color: {accent}; }}
    QComboBox#tileEnumCombo:disabled {{ color: {tx_faint}; }}
    /* Mismatch: the readback option differs from the commanded one
       (FR-70). */
    QComboBox#tileEnumCombo[mismatch="true"] {{
        color: {amber}; border-color: {amber};
    }}
    QComboBox#tileEnumCombo::drop-down {{ width: 18px; border: none; }}
    QPushButton#tileEnumSend {{
        background: {hover}; color: {tx};
        border: 1px solid {bd_strong}; border-radius: {RADIUS_SM}px;
        font-weight: 700; min-height: 22px;
    }}
    QPushButton#tileEnumSend:hover {{ background: {press_bg}; border-color: {accent}; }}
    QPushButton#tileEnumSend:pressed {{ background: {press_bg}; }}
    QPushButton#tileEnumSend:disabled {{ color: {tx_faint}; background: transparent; }}

    QLabel#controlPanelBindChip {{
        background: {elevated}; color: {tx2};
        border: 1px solid {bd}; border-radius: {RADIUS_MD}px;
        padding: 2px 8px; font-size: {MICRO_FS}px;
    }}
    QLabel#controlPanelBindChip[state="polling"] {{
        background: {ok_bg}; color: {green}; border-color: {ok_bd};
    }}
    QLabel#controlPanelBindChip[state="paused"] {{
        background: {warn_bg}; color: {amber}; border-color: {mix_hex(amber, bg, 0.5)};
    }}
    QLabel#controlPanelBindChip[state="unbound"] {{
        background: {err_bg}; color: {red}; border-color: {danger_bd};
    }}
    QLabel#controlPanelEmptyTitle {{ color: {tx}; font-size: 15px; font-weight: 700; }}
    QLabel#controlPanelEmptyHint {{ color: {tx2}; }}
    QWidget#controlPanelPreviewStrip {{
        background: {bg};
        border: 1px solid {bd_soft};
        border-radius: {RADIUS_MD}px;
    }}
    QWidget#controlPanelChartPage {{ background: {bg}; }}
    QWidget#controlPanelChartView {{
        background: {elevated};
        border: 1px solid {bd_soft};
        border-radius: {RADIUS_LG}px;
    }}
    QPushButton#controlPanelChartBack {{
        background: transparent; color: {tx2};
        border: 1px solid {bd_soft}; border-radius: {RADIUS_SM}px;
        padding: 4px 10px; font-weight: 600;
    }}
    QPushButton#controlPanelChartBack:hover {{ background: {hover}; color: {tx}; border-color: {accent}; }}
    QLabel#controlPanelChartTitle {{ color: {tx}; font-size: 15px; font-weight: 700; }}
    QLabel#controlPanelChartReadout {{ color: {tx_faint}; font-family: {MONO}; font-size: {MICRO_FS}px; }}

    QLabel#controlPanelBellBadge {{
        background: {red}; color: {on_accent};
        border: 1px solid {danger_bd}; border-radius: 6px;
        min-width: 12px; max-height: 12px; padding: 0 2px;
        font-size: 9px; font-weight: 700;
    }}
    QFrame#controlPanelAlertPanel {{
        background: {panel}; color: {tx};
        border: 1px solid {bd}; border-radius: {RADIUS_LG}px;
    }}
    QLabel#controlPanelAlertPanelTitle {{ color: {tx}; font-size: 14px; font-weight: 700; }}
    QLabel#controlPanelAlertPanelSubtitle {{ color: {tx_faint}; font-size: {MICRO_FS}px; }}
    QToolButton#controlPanelAlertPanelButton {{
        background: transparent; color: {tx2};
        border: 1px solid {bd_soft}; border-radius: {RADIUS_SM}px;
        padding: 2px 8px; min-height: 22px;
    }}
    QToolButton#controlPanelAlertPanelButton:hover {{ background: {hover}; color: {tx}; border-color: {accent}; }}
    QListWidget#controlPanelAlertList {{
        background: {elevated}; color: {tx2};
        border: 1px solid {bd_soft}; border-radius: {RADIUS_MD}px;
        font-family: {MONO}; font-size: {MICRO_FS}px;
    }}
    QListWidget#controlPanelAlertList::item {{ padding: 3px 6px; }}
    """)

    return "\n".join(parts)
