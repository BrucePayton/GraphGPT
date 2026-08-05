from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class SourceLocation:
    file: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: Severity
    path: str
    message: str
    hint: str | None = None
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        where = self.path
        if self.location:
            where = f"{Path(self.location.file)}:{self.location.line}:{self.location.column}"
        hint = f"\n  hint: {self.hint}" if self.hint else ""
        return f"{self.severity.value.upper()} {self.code} {where}: {self.message}{hint}"


class GraphGPTError(Exception):
    """Base error containing stable, machine-readable diagnostics."""

    def __init__(self, diagnostics: list[Diagnostic]):
        self.diagnostics = diagnostics
        super().__init__("\n".join(item.render() for item in diagnostics))

