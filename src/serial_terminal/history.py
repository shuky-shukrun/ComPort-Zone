from __future__ import annotations

from collections import Counter


class HistoryStore:
    def __init__(self, commands: list[str] | None = None, limit: int = 500) -> None:
        self.limit = limit
        self._commands: list[str] = []
        self._counts: Counter[str] = Counter()
        self._recency: dict[str, int] = {}
        self._tick = 0
        self._navigation_index: int | None = None
        self._draft = ""
        for command in commands or []:
            self.add(command)

    def add(self, command: str) -> None:
        command = command.strip()
        if not command:
            return
        if command in self._commands:
            self._commands.remove(command)
        self._commands.append(command)
        self._counts[command] += 1
        self._tick += 1
        self._recency[command] = self._tick
        if len(self._commands) > self.limit:
            removed = self._commands.pop(0)
            if removed not in self._commands:
                self._counts.pop(removed, None)
                self._recency.pop(removed, None)
        self.reset_navigation()

    def all_commands(self) -> list[str]:
        return list(self._commands)

    def reset_navigation(self) -> None:
        self._navigation_index = None
        self._draft = ""

    def navigate(self, direction: int, current_text: str) -> str:
        if direction not in (-1, 1):
            raise ValueError("direction must be -1 or 1")
        if not self._commands:
            return current_text
        if self._navigation_index is None:
            self._draft = current_text
            self._navigation_index = len(self._commands)
        next_index = max(0, min(len(self._commands), self._navigation_index + direction))
        if next_index == len(self._commands):
            draft = self._draft
            self.reset_navigation()
            return draft
        self._navigation_index = next_index
        return self._commands[self._navigation_index]

    def suggestions(self, prefix: str = "", limit: int = 20) -> list[str]:
        prefix = prefix.strip().casefold()
        matches = [
            command
            for command in self._commands
            if not prefix or command.casefold().startswith(prefix)
        ]
        matches.sort(
            key=lambda command: (
                -self._counts[command],
                -self._recency[command],
                command.casefold(),
            )
        )
        return matches[:limit]
