from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request

from .models import DayTradeInstrumentPlaybook, InstrumentResult
from .telegram import TelegramBotClient


@dataclass(frozen=True)
class AlertDecision:
    symbol: str
    direction: str
    score: float
    confidence: float


class AlertStateStore:
    def __init__(self, path: Path, *, emit_on_first_run: bool) -> None:
        self.path = path
        self.emit_on_first_run = emit_on_first_run
        self._state = self._load()

    def should_emit(self, decision: AlertDecision, *, min_score_change: float) -> bool:
        previous = self._state.get(decision.symbol)
        emit = False

        if previous is None:
            emit = self.emit_on_first_run
        else:
            if previous.get("direction") != decision.direction:
                emit = True
            elif abs(float(previous.get("score", 0.0)) - decision.score) >= min_score_change:
                emit = True

        self._state[decision.symbol] = {
            "direction": decision.direction,
            "score": decision.score,
            "confidence": decision.confidence,
        }
        self._save()
        return emit

    def _load(self) -> dict[str, dict[str, float | str]]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")


def format_alert_payload(
    result: InstrumentResult,
    *,
    playbook_item: DayTradeInstrumentPlaybook | None = None,
) -> dict[str, Any]:
    payload = {
        "symbol": result.symbol,
        "direction": result.direction,
        "score": round(result.score, 4),
        "confidence": round(result.confidence, 4),
        "reasons": list(result.reasons),
        "base_score": round(result.base_result.score, 4),
        "quote_score": round(result.quote_result.score, 4),
    }
    if playbook_item is not None:
        payload.update(
            {
                "action": _action_value(playbook_item),
                "allowed_direction": playbook_item.allowed_direction,
                "trade_state": playbook_item.trade_state,
                "bias_strength": round(playbook_item.bias_strength, 4),
                "valid_sessions": [session.label for session in playbook_item.valid_sessions],
                "tradable_rank": playbook_item.tradable_rank,
                "is_top_setup": playbook_item.is_top_setup,
                "stale_driver_count": playbook_item.stale_driver_count,
                "no_trade_window_count": len(playbook_item.no_trade_windows),
            }
        )
    return payload


class ConsoleAlertSink:
    def emit(self, payload: dict[str, Any]) -> None:
        print(json.dumps(payload, indent=2))


class WebhookAlertSink:
    def __init__(self, url: str) -> None:
        self.url = url

    def emit(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=30):
            pass


class TelegramAlertSink:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.client = TelegramBotClient(bot_token)
        self.chat_id = chat_id.strip()
        if not self.chat_id:
            raise ValueError("Telegram chat ID is required.")

    def emit(self, payload: dict[str, Any]) -> None:
        self.client.send_message(
            chat_id=self.chat_id,
            text=format_telegram_alert_text(payload),
        )


def format_telegram_alert_text(payload: dict[str, Any]) -> str:
    reasons = payload.get("reasons", [])
    lines = [
        "Fundamental Bias Alert",
        f"Symbol: {payload.get('symbol', '')}",
        f"Direction: {payload.get('direction', '')}",
        f"Score: {payload.get('score', '')}",
        f"Confidence: {payload.get('confidence', '')}",
    ]
    if payload.get("action"):
        lines.append(f"Action: {payload.get('action')}")
    if payload.get("trade_state"):
        lines.append(f"Trade state: {payload.get('trade_state')}")
    if payload.get("is_top_setup") and payload.get("tradable_rank") is not None:
        lines.append(f"Setup rank: #{payload.get('tradable_rank')} top setup")
    elif payload.get("tradable_rank") is not None:
        lines.append(f"Tradable rank: #{payload.get('tradable_rank')}")
    valid_sessions = payload.get("valid_sessions", [])
    if isinstance(valid_sessions, list) and valid_sessions:
        lines.append(f"Sessions: {', '.join(valid_sessions)}")
    if payload.get("base_score") is not None:
        lines.append(f"Base score: {payload.get('base_score')}")
    if payload.get("quote_score") is not None:
        lines.append(f"Quote score: {payload.get('quote_score')}")
    if isinstance(reasons, list) and reasons:
        lines.append("Why:")
        lines.extend(f"- {reason}" for reason in reasons[:4])
    return "\n".join(lines)


def _action_value(item: DayTradeInstrumentPlaybook) -> str:
    if item.trade_state == "lockout":
        return "wait"
    if item.allowed_direction == "long_only":
        return "buy"
    if item.allowed_direction == "short_only":
        return "sell"
    return "no_trade"
