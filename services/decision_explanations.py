"""Shared schema and helpers for AI/automation decision explanations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Mapping

from utils.path_utils import get_data_dir

SCHEMA_VERSION = 1
DEFAULT_LOG_FILE = "decision_explanations.jsonl"
ENV_ENABLE_FLAG = "NEXGEN_DECISION_LOG"


@dataclass
class DecisionReason:
    """A single reason tag included in a decision explanation."""

    tag: str
    message: str
    weight: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tag": str(self.tag or "").strip() or "unspecified",
            "message": str(self.message or "").strip(),
        }
        if self.weight is not None:
            payload["weight"] = float(self.weight)
        if self.details:
            payload["details"] = dict(self.details)
        return payload


@dataclass
class DecisionExplanation:
    """Normalized payload for lineup/bullpen/trade-style decisions."""

    decision_type: str
    outcome: str
    reasons: list[DecisionReason] = field(default_factory=list)
    actor: str = "system"
    team_id: str | None = None
    subject_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    timestamp_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": int(self.schema_version),
            "timestamp_utc": str(self.timestamp_utc),
            "decision_type": str(self.decision_type or "").strip() or "unknown",
            "outcome": str(self.outcome or "").strip() or "unknown",
            "actor": str(self.actor or "").strip() or "system",
            "reasons": [reason.to_dict() for reason in self.reasons],
            "context": dict(self.context or {}),
        }
        if self.team_id:
            payload["team_id"] = str(self.team_id)
        if self.subject_id:
            payload["subject_id"] = str(self.subject_id)
        return payload


def reason(
    tag: str,
    message: str,
    *,
    weight: float | None = None,
    details: Mapping[str, Any] | None = None,
) -> DecisionReason:
    """Return a ``DecisionReason`` with normalized fields."""

    return DecisionReason(
        tag=str(tag or "").strip() or "unspecified",
        message=str(message or "").strip(),
        weight=weight,
        details=dict(details or {}),
    )


def explanation(
    decision_type: str,
    outcome: str,
    *,
    reasons: list[DecisionReason] | None = None,
    actor: str = "system",
    team_id: str | None = None,
    subject_id: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> DecisionExplanation:
    """Build a decision explanation with consistent defaults."""

    return DecisionExplanation(
        decision_type=str(decision_type or "").strip() or "unknown",
        outcome=str(outcome or "").strip() or "unknown",
        reasons=list(reasons or []),
        actor=str(actor or "").strip() or "system",
        team_id=str(team_id).strip() if team_id is not None else None,
        subject_id=str(subject_id).strip() if subject_id is not None else None,
        context=dict(context or {}),
    )


def should_persist_decision_logs() -> bool:
    """Return ``True`` when decision logs should be persisted."""

    token = str(os.getenv(ENV_ENABLE_FLAG, "")).strip().lower()
    return token in {"1", "true", "yes", "on"}


def append_decision_log(
    payload: DecisionExplanation | Mapping[str, Any],
    *,
    path: Path | str | None = None,
) -> Path:
    """Append a decision explanation JSON line and return the target path."""

    if isinstance(payload, DecisionExplanation):
        record = payload.to_dict()
    else:
        record = dict(payload)

    if path is None:
        log_path = get_data_dir() / DEFAULT_LOG_FILE
    else:
        log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return log_path


def summarize_decision_explanation(
    payload: Mapping[str, Any] | None,
    *,
    fallback: str = "No decision details available.",
    max_reasons: int = 3,
) -> str:
    """Return a compact, user-facing summary for a decision payload."""

    if not isinstance(payload, Mapping):
        return fallback

    decision_type = str(payload.get("decision_type") or "").strip().replace("_", " ")
    outcome = str(payload.get("outcome") or "").strip().replace("_", " ")
    reasons = payload.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        return fallback

    header_parts = []
    if decision_type:
        header_parts.append(decision_type.title())
    if outcome:
        header_parts.append(f"Outcome: {outcome}.")

    lines: list[str] = []
    if header_parts:
        lines.append(" ".join(header_parts))

    shown = 0
    for raw_reason in reasons:
        if shown >= max_reasons:
            break
        if not isinstance(raw_reason, Mapping):
            continue
        message = str(raw_reason.get("message") or "").strip()
        if not message:
            continue
        tag = str(raw_reason.get("tag") or "").strip().replace("_", " ")
        if tag:
            lines.append(f"- {message} ({tag})")
        else:
            lines.append(f"- {message}")
        shown += 1

    if shown == 0:
        return fallback

    hidden = max(0, len(reasons) - shown)
    if hidden:
        lines.append(f"- +{hidden} more reason(s)")
    return "\n".join(lines)


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_LOG_FILE",
    "ENV_ENABLE_FLAG",
    "DecisionReason",
    "DecisionExplanation",
    "reason",
    "explanation",
    "should_persist_decision_logs",
    "append_decision_log",
    "summarize_decision_explanation",
]
