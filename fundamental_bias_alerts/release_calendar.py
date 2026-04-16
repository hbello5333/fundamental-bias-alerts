from __future__ import annotations

import json
from pathlib import Path

from .models import ReleaseCalendar, ReleaseEvent


def load_release_calendar(path: str | Path) -> ReleaseCalendar:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    events = tuple(
        ReleaseEvent(
            event_id=item["event_id"],
            label=item["label"],
            currency=item["currency"],
            impact=item["impact"],
            timestamp=item["timestamp"],
            source_url=item.get("source_url", ""),
        )
        for item in raw.get("events", [])
    )
    return ReleaseCalendar(events=events)
