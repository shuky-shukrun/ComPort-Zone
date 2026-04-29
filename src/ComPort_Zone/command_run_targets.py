from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

NO_RUN_TARGET_LABEL = "No connected COM ports"


@dataclass(frozen=True, slots=True)
class CommandRunTarget:
    id: int
    label: str


@dataclass(frozen=True, slots=True)
class CommandRunRequest:
    text: str
    path: Path | None = None
    display_name: str = "Untitled"

    @property
    def source_label(self) -> str:
        return str(self.path) if self.path is not None else self.display_name


RunTargetLike = CommandRunTarget | tuple[int, str]


def coerce_run_target(target: RunTargetLike) -> CommandRunTarget:
    if isinstance(target, CommandRunTarget):
        return target
    target_id, label = target
    return CommandRunTarget(int(target_id), str(label))


class CommandRunTargetService:
    def __init__(
        self,
        *,
        targets_supplier: Callable[[], Iterable[RunTargetLike]] | None = None,
        run_callback: Callable[[CommandRunRequest, int], bool | None] | None = None,
    ) -> None:
        self.targets_supplier = targets_supplier
        self.run_callback = run_callback

    def is_configured(self) -> bool:
        return self.targets_supplier is not None and self.run_callback is not None

    def targets(self) -> list[CommandRunTarget]:
        if self.targets_supplier is None:
            return []
        return [coerce_run_target(target) for target in self.targets_supplier()]

    def run(self, request: CommandRunRequest, target_id: int) -> bool:
        if self.run_callback is None:
            return False
        result = self.run_callback(request, target_id)
        return True if result is None else bool(result)
