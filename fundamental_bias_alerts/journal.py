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
        "execution_plan": item.execution_plan and {
            "status": item.execution_plan.status,
            "entry_style": item.execution_plan.entry_style,
            "stop_loss_pct": round(item.execution_plan.stop_loss_pct, 6),
            "target_r_multiple": round(item.execution_plan.target_r_multiple, 6),
            "risk_per_trade_pct": round(item.execution_plan.risk_per_trade_pct, 6),
            "reference_price": _rounded_value(item.execution_plan.reference_price),
            "entry_price": _rounded_value(item.execution_plan.entry_price),
            "stop_price": _rounded_value(item.execution_plan.stop_price),
            "target_price": _rounded_value(item.execution_plan.target_price),
            "stop_distance_price": _rounded_value(item.execution_plan.stop_distance_price),
            "target_distance_price": _rounded_value(item.execution_plan.target_distance_price),
            "account_size": _rounded_value(item.execution_plan.account_size),
            "risk_amount": _rounded_value(item.execution_plan.risk_amount),
            "position_size_units": _rounded_value(item.execution_plan.position_size_units),
            "notional_value_usd": _rounded_value(item.execution_plan.notional_value_usd),
            "activation_start_utc": (
                item.execution_plan.activation_start_utc.isoformat()
                if item.execution_plan.activation_start_utc is not None
                else None
            ),
            "expiry_utc": (
                item.execution_plan.expiry_utc.isoformat()
                if item.execution_plan.expiry_utc is not None
                else None
            ),
            "session_label": item.execution_plan.session_label,
            "notes": list(item.execution_plan.notes),
        },
    }


def _action_value(item: DayTradeInstrumentPlaybook) -> str:
    if item.trade_state == "lockout":
        return "wait"
    if item.allowed_direction == "long_only":
        return "buy"
    if item.allowed_direction == "short_only":
        return "sell"
    return "no_trade"


def _rounded_value(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)
