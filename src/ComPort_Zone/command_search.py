from __future__ import annotations

from dataclasses import dataclass, field

SearchMatch = tuple[int, int]


def find_search_matches(text: str, needle: str, *, case_sensitive: bool = False) -> list[SearchMatch]:
    if not needle:
        return []
    haystack = text if case_sensitive else text.casefold()
    search_needle = needle if case_sensitive else needle.casefold()
    matches: list[SearchMatch] = []
    start = 0
    step = max(1, len(search_needle))
    while start <= len(haystack):
        index = haystack.find(search_needle, start)
        if index < 0:
            break
        matches.append((index, index + len(needle)))
        start = index + step
    return matches


def replace_all_matches(text: str, matches: list[SearchMatch], replacement: str) -> str:
    pieces: list[str] = []
    cursor = 0
    for start, end in matches:
        pieces.append(text[cursor:start])
        pieces.append(replacement)
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


@dataclass(slots=True)
class CommandSearchState:
    matches: list[SearchMatch] = field(default_factory=list)
    current_index: int = -1

    @property
    def current_match(self) -> SearchMatch | None:
        if 0 <= self.current_index < len(self.matches):
            return self.matches[self.current_index]
        return None

    @property
    def count_label(self) -> str:
        if self.current_match is None:
            return "0/0"
        return f"{self.current_index + 1}/{len(self.matches)}"

    def clear(self) -> None:
        self.matches = []
        self.current_index = -1

    def refresh(
        self,
        text: str,
        needle: str,
        *,
        case_sensitive: bool,
        cursor_position: int,
        reset: bool,
    ) -> SearchMatch | None:
        old_start = self.current_match[0] if self.current_match else -1
        self.matches = find_search_matches(text, needle, case_sensitive=case_sensitive)
        if not self.matches:
            self.current_index = -1
            return None
        if reset:
            self.current_index = next(
                (index for index, (start, _end) in enumerate(self.matches) if start >= cursor_position),
                0,
            )
        else:
            self.current_index = next(
                (index for index, (start, _end) in enumerate(self.matches) if start >= old_start),
                min(max(self.current_index, 0), len(self.matches) - 1),
            )
        return self.current_match

    def move_next(self) -> SearchMatch | None:
        if not self.matches:
            return None
        self.current_index = (self.current_index + 1) % len(self.matches)
        return self.current_match

    def move_previous(self) -> SearchMatch | None:
        if not self.matches:
            return None
        self.current_index = (self.current_index - 1) % len(self.matches)
        return self.current_match
