from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ClearanceLevel(str, Enum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


@dataclass
class AuditMetadata:
    audit_name: str
    mode: str


@dataclass
class AuditFinding:
    severity: str
    title: str
    detail: str = ""


@dataclass
class AuditResult:
    metadata: AuditMetadata
    findings: list[AuditFinding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DbCheckResult:
    name: str
    status: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class DbAuditSummary:
    overall_clearance: ClearanceLevel
    connection_status: str
    safe_actions: list[str]
    blocked_actions: list[str]
    warnings: list[str]
    evidence: dict[str, Any]
    check_results: list[DbCheckResult] = field(default_factory=list)
    recommended_next_step: str = ""
