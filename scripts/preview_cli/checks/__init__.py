"""Health check definitions for pr-preview doctor."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class CheckResult:
    id: str
    title: str
    status: str  # "PASS", "WARN", "FAIL", "SKIP"
    message: str
    fix: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)
