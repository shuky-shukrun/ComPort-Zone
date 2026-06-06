from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

TERMINAL_FONT_MIN = 8
TERMINAL_FONT_MAX = 24

# Line spacing as a percentage of the font's natural line height (100 = the font's
# default leading). The default is a touch above 100 because mono fonts read tight.
TERMINAL_LINE_SPACING_MIN = 100
TERMINAL_LINE_SPACING_MAX = 200
TERMINAL_LINE_SPACING_DEFAULT = 115


def pick_ui_font() -> QFont:
    families = {family.casefold(): family for family in QFontDatabase.families()}
    for candidate in ("Segoe UI Variable Text", "Segoe UI", "Inter"):
        if family := families.get(candidate.casefold()):
            return QFont(family, 10)
    return QApplication.font()


def pick_mono_font(point_size: int, family_name: str = "") -> QFont:
    families = {family.casefold(): family for family in QFontDatabase.families()}
    candidates = [family_name, "Cascadia Mono", "Cascadia Code", "Consolas", "JetBrains Mono"]
    for candidate in candidates:
        if candidate and (family := families.get(candidate.casefold())):
            return QFont(family, point_size)
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(point_size)
    return font


def preferred_terminal_font_families() -> list[str]:
    families = sorted(QFontDatabase.families(), key=str.casefold)
    preferred = ["Cascadia Mono", "Cascadia Code", "Consolas", "JetBrains Mono"]
    preferred_lookup = {family.casefold(): family for family in families}
    ordered = [
        preferred_lookup[candidate.casefold()]
        for candidate in preferred
        if candidate.casefold() in preferred_lookup
    ]
    ordered.extend(family for family in families if family not in ordered)
    return ordered
