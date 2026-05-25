"""Resolve a user-supplied identifier (id or label) to a single
``QuickCommand`` / ``QuickFile`` entry.

Used by the CLI's ``quick``/``files`` subcommands so a user can type either
the stable id, an exact label, or a label with arbitrary casing — and get a
clear error when the input is ambiguous or missing. Kept GUI-free so the CLI
can import it without dragging in PySide.

Resolution order (first match wins):
1. Exact ``id`` match (uuid4 hex, 32 chars but we don't enforce length here).
2. Exact label match — must be unique.
3. Case-insensitive label match — must be unique.

Any duplicate-label hit raises ``AmbiguousIdentifierError`` rather than
silently returning the first entry, because labels are user-editable and
duplicates do occur.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol, TypeVar


class _HasIdAndLabel(Protocol):
    id: str
    label: str


T = TypeVar("T", bound=_HasIdAndLabel)


class LibraryLookupError(LookupError):
    """Base class for all library-lookup failures.

    Subclasses carry the offending identifier and (where relevant) the set of
    candidate matches so callers can format actionable error messages.
    """

    def __init__(self, identifier: str, message: str) -> None:
        super().__init__(message)
        self.identifier = identifier


class EntryNotFoundError(LibraryLookupError):
    pass


class AmbiguousIdentifierError(LibraryLookupError):
    def __init__(self, identifier: str, matches: Sequence[_HasIdAndLabel]) -> None:
        ids = ", ".join(match.id for match in matches)
        super().__init__(
            identifier,
            f"{identifier!r} matches {len(matches)} entries; "
            f"disambiguate with an id ({ids}).",
        )
        self.matches: tuple[_HasIdAndLabel, ...] = tuple(matches)


def resolve_entry(entries: Iterable[T], identifier: str) -> T:
    """Return the single entry matching ``identifier`` by id or label.

    Raises :class:`EntryNotFoundError` when nothing matches, or
    :class:`AmbiguousIdentifierError` when multiple entries share the same
    label (exact or case-insensitive).
    """
    if not identifier:
        raise EntryNotFoundError(identifier, "Empty identifier.")

    entries_list = list(entries)

    for entry in entries_list:
        if entry.id == identifier:
            return entry

    exact_matches = [entry for entry in entries_list if entry.label == identifier]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise AmbiguousIdentifierError(identifier, exact_matches)

    lower = identifier.lower()
    ci_matches = [entry for entry in entries_list if entry.label.lower() == lower]
    if len(ci_matches) == 1:
        return ci_matches[0]
    if len(ci_matches) > 1:
        raise AmbiguousIdentifierError(identifier, ci_matches)

    raise EntryNotFoundError(
        identifier,
        f"No entry with id or label {identifier!r}.",
    )
