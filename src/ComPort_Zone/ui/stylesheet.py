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

from ..icons import checked_checkbox_image_path
from ..themes import ThemePalette, mix_hex, rgba
from .tokens import (
    CONTROL_H,
    FONT_BTN_W,
    LABEL_FS,
    MENU_BAR_H,
    MICRO_FS,
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
    QLabel#titleText {{ color: {tx2}; font-size: {UI_FS}px; }}
    QLabel#titleText[strong="true"] {{ color: {tx}; font-weight: 600; }}
    QLabel#titleLiveDot {{
        background: {green};
        border-radius: 3px;
        min-width: 6px; max-width: 6px; min-height: 6px; max-height: 6px;
    }}
    QToolButton#windowButton {{
        background: transparent;
        border: none;
        color: {tx3};
        border-radius: 0px;
    }}
    QToolButton#windowButton:hover {{ background: {hover}; color: {tx}; }}
    QToolButton#windowButtonClose:hover {{ background: #e23a4e; color: #ffffff; }}

    QMenuBar {{
        background: {panel};
        color: {tx2};
        border: none;
        padding: 0px 5px;
        font-size: {UI_FS}px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 2px 9px;
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
    QTabBar::tab:selected {{ color: {tx}; border-bottom: 2px solid {accent}; }}
    QTabWidget[activePane="false"] QTabBar::tab:selected {{ border-bottom: 2px solid {bd_strong}; }}

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
    QTextEdit#terminal[activeWorkspaceTab="true"] {{ border-top: 2px solid {accent}; }}

    QFrame#commandBar, QFrame#searchBar {{
        background: {panel};
        border-top: 1px solid {bd_soft};
    }}
    QFrame#searchBar {{ border-bottom: 1px solid {bd_soft}; border-top: none; }}

    QLabel#commandFileStatusLabel, QLabel#editorStatusLabel, QLabel#editorPathLabel {{
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
    QPlainTextEdit#commandFileEditor {{
        background: {term_bg};
        color: {tx};
        border: none;
        border-top: 2px solid transparent;
        selection-background-color: {sel};
        selection-color: {tx};
    }}
    QPlainTextEdit#commandFileEditor[activeWorkspaceTab="true"] {{ border-top: 2px solid {accent}; }}
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

    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px 2px 2px 0; border: none; }}
    QScrollBar::handle:vertical {{ background: {elevated}; border-radius: 4px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {bd_strong}; }}
    QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0 2px 2px 2px; border: none; }}
    QScrollBar::handle:horizontal {{ background: {elevated}; border-radius: 4px; min-width: 28px; }}
    QScrollBar::handle:horizontal:hover {{ background: {bd_strong}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ background: none; border: none; width: 0; height: 0; }}
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

    return "\n".join(parts)
