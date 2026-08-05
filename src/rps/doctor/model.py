"""Result types for the diagnostic run."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = ["Status", "Finding", "Section", "Report"]


class Status(str, Enum):
    OK = "ok"
    """Present and working."""

    MISSING = "missing"
    """Looked for it, it is not there. A fact, not a failure."""

    FAILED = "failed"
    """It is there but did not work. Different problem, different fix."""

    UNKNOWN = "unknown"
    """Could not be determined from this machine at all."""

    INFO = "info"
    """Neutral measurement."""

    @property
    def mark(self) -> str:
        return {"ok": "✅", "missing": "➖", "failed": "❌", "unknown": "❔", "info": "•"}[
            self.value
        ]


@dataclass
class Finding:
    key: str
    label: str
    status: Status = Status.INFO
    detail: str = ""
    data: Any = None
    """Machine-readable payload for the JSON sidecar. Never rendered verbatim."""


@dataclass
class Section:
    title: str
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(
        self,
        key: str,
        label: str,
        status: Status = Status.INFO,
        detail: str = "",
        data: Any = None,
    ) -> Finding:
        finding = Finding(key=key, label=label, status=status, detail=detail, data=data)
        self.findings.append(finding)
        return finding

    def get(self, key: str) -> Finding | None:
        for finding in self.findings:
            if finding.key == key:
                return finding
        return None


@dataclass
class Report:
    generated_at: str
    app_version: str
    sections: list[Section] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    """Failures of the diagnostic itself. Kept apart from findings about the
    machine, so a bug in this tool is never read as a problem with Resolve."""

    def section(self, title: str) -> Section:
        for existing in self.sections:
            if existing.title == title:
                return existing
        created = Section(title=title)
        self.sections.append(created)
        return created

    def find(self, section_title: str, key: str) -> Finding | None:
        for existing in self.sections:
            if existing.title == section_title:
                return existing.get(key)
        return None
