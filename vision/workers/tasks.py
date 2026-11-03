from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone

def create_trigger_identity(event_time: datetime | None = None) -> tuple[str, str, str]:
    """Return a database timestamp plus filesystem-safe trigger identifiers."""

    occurred_at = (event_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
    artifact_token = occurred_at.strftime("%Y%m%d_%H%M%S_%f")
    return occurred_at.isoformat(), artifact_token, f"circle-{artifact_token}"


@dataclass
class TriggerTask:
    timestamp: str
    artifact_token: str
    frame_id: str
    frame: object
    gray: object
    circles_payload: list[dict]
    target_payload: dict
    trigger_monotonic: float
    trigger_epoch_ms: int
    enqueued_monotonic: float


@dataclass
class ActionTask:
    action_id: int
    frame_id: str
    result_label: str
    trigger_monotonic: float
    enqueued_monotonic: float

