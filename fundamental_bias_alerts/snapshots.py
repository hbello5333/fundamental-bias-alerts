from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import DriverResult, EntityResult, InstrumentResult


class SnapshotStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append_run(self, *, as_of: datetime, results: list[InstrumentResult]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for result in results:
                payload = format_snapshot_record(as_of=as_of, result=result)
                handle.write(json.dumps(payload) + "\n")


def format_snapshot_record(*, as_of: datetime, result: InstrumentResult) -> dict[str, Any]:
    driver_states = Counter(_iter_driver_states(result))

    return {
        "timestamp_utc": as_of.astimezone(UTC).isoformat(),
        "hour_bucket_utc": _hour_bucket(as_of).isoformat(),
        "symbol": result.symbol,
        "direction": result.direction,
        "score": round(result.score, 6),
        "confidence": round(result.confidence, 6),
        "threshold": round(result.threshold, 6),
        "reasons": list(result.reasons),
        "data_quality": {
            "ok_drivers": driver_states.get("ok", 0),
            "stale_drivers": driver_states.get("stale", 0),
            "missing_drivers": driver_states.get("missing", 0),
            "error_drivers": driver_states.get("error", 0),
        },
        "base": _entity_payload(result.base_result),
        "quote": _entity_payload(result.quote_result),
    }


def _hour_bucket(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _entity_payload(result: EntityResult) -> dict[str, Any]:
    return {
        "key": result.key,
        "label": result.label,
        "score": round(result.score, 6),
        "confidence": round(result.confidence, 6),
        "drivers": [_driver_payload(driver) for driver in result.drivers],
    }


def _driver_payload(result: DriverResult) -> dict[str, Any]:
    return {
        "key": result.key,
        "label": result.label,
        "direction": result.direction,
        "data_state": result.data_state,
        "score": round(result.score, 6),
        "confidence": round(result.confidence, 6),
        "reason": result.reason,
        "latest_value": _round_or_none(result.latest_value),
        "previous_value": _round_or_none(result.previous_value),
        "observation_date": result.observation_date.isoformat() if result.observation_date else None,
        "age_hours": _round_or_none(result.age_hours),
    }


def _iter_driver_states(result: InstrumentResult) -> list[str]:
    return [
        driver.data_state
        for driver in (*result.base_result.drivers, *result.quote_result.drivers)
    ]


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)
