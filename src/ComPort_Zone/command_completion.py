"""Shared completion-popup key policy and helpers.

The terminal command line (:class:`ComPort_Zone.widgets.IntegratedTerminalEdit`) and
the command-file editor (:class:`ComPort_Zone.command_editor.CommandPlainTextEdit`)
both drive a ``QCompleter`` popup. They used to each re-implement the key handling
and popup navigation, which drifted apart (the editor accepted on Enter while the
terminal only accepted on Tab). This module is the single source of truth so the two
behave identically:

* arrows / Home / End / Page Up / Page Down — move the highlight
* Tab / Backtab — accept the highlighted suggestion
* Enter / Return — *dismiss* the popup without accepting; the host then runs Enter's
  native action (submit in the terminal, newline in the editor)
* Esc — cancel the popup

The host widgets keep their own ``token_under_cursor`` / ``insert_completion`` and the
Enter action, since those are genuinely widget-specific.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

# Keys that move the highlighted row within a visible completion popup.
COMPLETION_NAVIGATION_KEYS = frozenset(
    {
        Qt.Key.Key_Down,
        Qt.Key.Key_Up,
        Qt.Key.Key_PageDown,
        Qt.Key.Key_PageUp,
        Qt.Key.Key_Home,
        Qt.Key.Key_End,
    }
)

# Actions returned by classify_completion_key for a key pressed while the popup shows.
NAVIGATE = "navigate"  # move the highlighted row
ACCEPT = "accept"      # insert the highlighted suggestion, then close
DISMISS = "dismiss"    # close the popup and let the host run the key's native action
CANCEL = "cancel"      # close the popup and swallow the key
IGNORE = ""            # the popup does not own this key


def classify_completion_key(key) -> str:
    """Map a key pressed while the completion popup is visible to a shared action."""
    if key in COMPLETION_NAVIGATION_KEYS:
        return NAVIGATE
    if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
        return ACCEPT
    if key in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
        return DISMISS
    if key == Qt.Key.Key_Escape:
        return CANCEL
    return IGNORE


def resolve_completion_text(completer) -> str:
    """The highlighted suggestion (falling back to the first match), or '' if none."""
    if completer is None:
        return ""
    popup_index = completer.popup().currentIndex()
    completion = str(popup_index.data() or "") if popup_index.isValid() else ""
    if not completion:
        completion = completer.currentCompletion()
    if not completion:
        first = completer.completionModel().index(0, 0)
        completion = str(first.data() or "") if first.isValid() else ""
    return completion


def move_completion_selection(completer, key) -> None:
    """Move the popup's highlighted row in response to a navigation ``key``."""
    if completer is None:
        return
    model = completer.completionModel()
    row_count = model.rowCount()
    if row_count <= 0:
        return
    popup = completer.popup()
    current_row = popup.currentIndex().row()
    if current_row < 0:
        current_row = max(completer.currentRow(), 0)
    if key == Qt.Key.Key_Down:
        target_row = min(current_row + 1, row_count - 1)
    elif key == Qt.Key.Key_Up:
        target_row = max(current_row - 1, 0)
    elif key == Qt.Key.Key_PageDown:
        target_row = min(current_row + 8, row_count - 1)
    elif key == Qt.Key.Key_PageUp:
        target_row = max(current_row - 8, 0)
    elif key == Qt.Key.Key_End:
        target_row = row_count - 1
    else:  # Home (and any other navigation key) jumps to the top
        target_row = 0
    completer.setCurrentRow(target_row)
    index = model.index(target_row, 0)
    if index.isValid():
        popup.setCurrentIndex(index)
