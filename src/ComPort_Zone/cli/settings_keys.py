"""Dotted-key access to the schema-v2 settings payload.

The CLI's ``settings get`` / ``settings set`` walk the AppSettings dict
produced by ``AppSettings.to_dict()``. Keys are dotted paths into the
nested structure (e.g. ``transport.profile.baudrate``).

Some keys are intentionally read-only or off-limits from the CLI:

* ``schema_version`` / ``minimum_compatible_schema_version`` are managed
  by the storage layer.
* GUI-only keys (theme, fonts, drawer state, window dimensions, the
  whole ``workspace`` tree) are surfaced in ``show`` but refused for
  ``set`` — they're not actionable without the GUI.
* ``libraries.*`` lives behind the ``quick`` / ``files`` subcommands;
  setting the raw list via ``settings set`` would skip duplicate
  detection and id management.
"""

from __future__ import annotations

from typing import Any


class SettingsKeyError(KeyError):
    """Base class — every subclass adds a usable ``identifier``."""

    def __init__(self, identifier: str, message: str) -> None:
        super().__init__(message)
        self.identifier = identifier
        self._message = message

    def __str__(self) -> str:  # KeyError str adds quotes; we don't want them.
        return self._message


class UnknownKeyError(SettingsKeyError):
    pass


class GuiOnlyKeyError(SettingsKeyError):
    pass


class ReadOnlyKeyError(SettingsKeyError):
    pass


class LibraryManagedKeyError(SettingsKeyError):
    pass


class SettingsValueError(ValueError):
    """Raised when a value can't be coerced to the target type."""


# ----------------------------------------------------------------- key catalogs

# Sections the user can pass to ``settings show --section``.
SECTION_NAMES: frozenset[str] = frozenset({"transport", "app", "history", "libraries", "workspace"})

# Always read-only.
_READ_ONLY: frozenset[str] = frozenset({
    "schema_version",
    "minimum_compatible_schema_version",
})

# Exact GUI-only key paths refused by ``set`` with a clear message.
_GUI_ONLY_KEYS: frozenset[str] = frozenset({
    "app.theme",
    "app.terminal_font.family",
    "app.terminal_font.size",
    "app.line_wrap_enabled",
    "app.scrollback_size",
    "app.drawer.collapsed",
    "app.drawer.width",
    "app.drawer.page_index",
    "app.window.width",
    "app.window.height",
})

# Anything starting with these prefixes is GUI-only too (sub-trees).
_GUI_ONLY_PREFIXES: tuple[str, ...] = (
    "workspace.",
    "app.terminal_font.",
    "app.drawer.",
    "app.window.",
)

# Library state is managed via ``quick`` / ``files`` subcommands.
_LIBRARY_PREFIXES: tuple[str, ...] = ("libraries.",)


# ----------------------------------------------------------------- predicates

def is_gui_only(key: str) -> bool:
    return key in _GUI_ONLY_KEYS or any(key.startswith(p) for p in _GUI_ONLY_PREFIXES)


def is_library_key(key: str) -> bool:
    return any(key.startswith(p) for p in _LIBRARY_PREFIXES)


def is_read_only(key: str) -> bool:
    return key in _READ_ONLY


# ----------------------------------------------------------------- get / set

def get_value(payload: dict[str, Any], key: str) -> Any:
    """Return the value at ``key`` in ``payload``.

    Returns the nested dict / list directly when the key terminates at a
    non-leaf — callers can format it however they like.
    """
    parts = key.split(".") if key else []
    if not parts:
        return payload
    cur: Any = payload
    for index, part in enumerate(parts):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
            continue
        traversed = ".".join(parts[: index + 1])
        raise UnknownKeyError(key, f"No such settings key: {traversed!r}.")
    return cur


def set_value(payload: dict[str, Any], key: str, raw_value: str) -> Any:
    """Coerce ``raw_value`` to the existing leaf's type and write it.

    Returns the coerced value so the caller can echo what was stored.
    """
    if not key:
        raise UnknownKeyError(key, "Empty settings key.")
    if is_read_only(key):
        raise ReadOnlyKeyError(key, f"{key} is read-only.")
    if is_gui_only(key):
        raise GuiOnlyKeyError(
            key,
            f"{key} is a GUI-only setting (theme, fonts, drawer/tab layout). "
            "Use the desktop app to change it.",
        )
    if is_library_key(key):
        raise LibraryManagedKeyError(
            key,
            f"{key} is managed via the `quick` and `files` subcommands.",
        )

    parts = key.split(".")
    cur: Any = payload
    for index, part in enumerate(parts[:-1]):
        if not isinstance(cur, dict) or part not in cur:
            traversed = ".".join(parts[: index + 1])
            raise UnknownKeyError(key, f"No such settings key: {traversed!r}.")
        cur = cur[part]
    last = parts[-1]
    if not isinstance(cur, dict) or last not in cur:
        raise UnknownKeyError(key, f"No such settings key: {key!r}.")

    existing = cur[last]
    coerced = _coerce(raw_value, existing, key)
    cur[last] = coerced
    return coerced


# ------------------------------------------------------------------ coercion

def _coerce(raw: str, existing: Any, key: str) -> Any:
    """Map a string from the CLI to the existing leaf's type.

    Refuses list/dict keys — those are structural and should be edited via
    dedicated subcommands. Floats coerce ints (so ``--stop-bits 1`` for a
    float field still works).
    """
    if isinstance(existing, bool):
        # bool MUST come before int — bool is a subclass of int.
        lowered = raw.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
        raise SettingsValueError(
            f"{key} expects true/false (got {raw!r})."
        )
    if isinstance(existing, int):
        try:
            return int(raw)
        except ValueError as exc:
            raise SettingsValueError(
                f"{key} expects an integer (got {raw!r})."
            ) from exc
    if isinstance(existing, float):
        try:
            return float(raw)
        except ValueError as exc:
            raise SettingsValueError(
                f"{key} expects a number (got {raw!r})."
            ) from exc
    if isinstance(existing, str):
        return raw
    if isinstance(existing, (list, dict)):
        raise SettingsValueError(
            f"{key} is a structured value; edit it through the matching subcommand."
        )
    raise SettingsValueError(
        f"{key} has an unsupported type ({type(existing).__name__})."
    )
