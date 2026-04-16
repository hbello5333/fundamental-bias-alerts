from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request

from .models import InstrumentResult
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


def format_alert_payload(result: InstrumentResult) -> dict[str, Any]:
    return {
        "symbol": result.symbol,
        "direction": result.direction,
        "score": round(result.score, 4),
        "confidence": round(result.confidence, 4),
        "reasons": list(result.reasons),
        "base_score": round(result.base_result.score, 4),
        "quote_score": round(result.quote_result.score, 4),
    }


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
    if payload.get("base_score") is not None:
        lines.append(f"Base score: {payload.get('base_score')}")
    if payload.get("quote_score") is not None:
        lines.append(f"Quote score: {payload.get('quote_score')}")
    if isinstance(reasons, list) and reasons:
        lines.append("Why:")
        lines.extend(f"- {reason}" for reason in reasons[:4])
    return "\n".join(lines)
