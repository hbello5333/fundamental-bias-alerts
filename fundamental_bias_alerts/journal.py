from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import DayTradeInstrumentPlaybook, DayTradePlaybook


class PaperTradeJournalStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append_run(
        self,
        *,
        strategy_metadata: dict[str, object],
        playbook: DayTradePlaybook,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for item in playbook.items:
                handle.write(
                    json.dumps(
                        _journal_entry(
                            strategy_metadata=strategy_metadata,
                            playbook=playbook,
                            item=item,
                        )
                    )
                    + "\n"
                )


def _journal_entry(
    *,
    strategy_metadata: dict[str, object],
    playbook: DayTradePlaybook,
    item: DayTradeInstrumentPlaybook,
) -> dict[str, Any]:
    return {
        "entry_type": "signal",
        "generated_at_utc": playbook.generated_at_utc.isoformat(),
        "trade_date_utc": playbook.trade_date_utc.isoformat(),
        "strategy_name": str(strategy_metadata.get("name", "")),
        "strategy_version": str(strategy_metadata.get("version", "")),
        "symbol": item.symbol,
        "bias": item.bias,
        "score": round(item.score, 6),
        "bias_strength": round(item.bias_strength, 6),
        "action": _action_value(item),
        "allowed_direction": item.allowed_direction,
        "trade_state": item.trade_state,
        "confidence": round(item.confidence, 6),
        "stale_driver_count": item.stale_driver_count,
        "tradable_rank": item.tradable_rank,
        "is_top_setup": item.is_top_setup,
        "bias_reasons": list(item.bias_reasons),
        "notes": list(item.notes),
        "valid_sessions": [
            {
                "key": session.key,
                "label": session.label,
                "start_utc": session.start_utc.isoformat(),
                "end_utc": session.end_utc.isoformat(),
            }
            for session in item.valid_sessions
        ],
        "no_trade_windows": [
            {
                "label": window.label,
                "currency": window.currency,
                "impact": window.impact,
                "start_utc": window.start_utc.isoformat(),
                "end_utc": window.end_utc.isoformat(),
                "event_time_utc": window.event_time_utc.isoformat(),
            }
            for window in item.no_trade_windows
        ],
        "top_symbols_for_run": [
            ranked_item.symbol
            for ranked_item in playbook.items
            if ranked_item.is_top_setup
        ],
    }


def _action_value(item: DayTradeInstrumentPlaybook) -> str:
    if item.trade_state == "lockout":
        return "wait"
    if item.allowed_direction == "long_only":
        return "buy"
    if item.allowed_direction == "short_only":
        return "sell"
    return "no_trade"
