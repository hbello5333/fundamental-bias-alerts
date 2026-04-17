from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from .models import DayTradeInstrumentPlaybook, DayTradePlaybook, TradeExecutionPlan

PaperTradeStatus = Literal["open", "closed"]
PaperTradeOutcome = Literal["win", "loss", "flat"]
PaperTradeExitReason = Literal["target_hit", "stop_hit", "session_expired", "manual_close"]


@dataclass(frozen=True)
class PaperTrade:
    trade_id: str
    symbol: str
    trade_date_utc: date
    session_label: str
    status: PaperTradeStatus
    allowed_direction: str
    bias: str
    opened_at_utc: datetime
    entry_price: float
    stop_price: float
    target_price: float
    activation_start_utc: datetime | None = None
    expiry_utc: datetime | None = None
    closed_at_utc: datetime | None = None
    exit_price: float | None = None
    exit_reason: PaperTradeExitReason | None = None
    r_multiple: float | None = None
    outcome: PaperTradeOutcome | None = None
    confidence: float = 0.0
    tradable_rank: int | None = None
    risk_amount: float | None = None
    position_size_units: float | None = None
    notional_value_usd: float | None = None
    bias_reasons: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)
    strategy_name: str = ""
    strategy_version: str = ""


class PaperTradeLedgerStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def sync_playbook(
        self,
        *,
        strategy_metadata: dict[str, object],
        playbook: DayTradePlaybook,
        reference_prices: dict[str, float],
        as_of: datetime | None = None,
    ) -> list[dict[str, Any]]:
        effective_as_of = (as_of or playbook.generated_at_utc).astimezone(UTC)
        trades_by_id = {
            trade.trade_id: trade
            for trade in self.load_trades()
        }
        events: list[dict[str, Any]] = []

        for trade in sorted(trades_by_id.values(), key=lambda item: item.opened_at_utc):
            if trade.status != "open":
                continue
            current_price = reference_prices.get(trade.symbol)
            if current_price is None:
                continue
            closed_trade = _maybe_close_trade(
                trade=trade,
                current_price=current_price,
                as_of=effective_as_of,
            )
            if closed_trade is None:
                continue
            trades_by_id[trade.trade_id] = closed_trade
            payload = _trade_payload(closed_trade, entry_type="paper_trade_close")
            self._append_payload(payload)
            events.append(payload)

        open_symbols = {
            trade.symbol
            for trade in trades_by_id.values()
            if trade.status == "open"
        }
        for item in sorted(
            playbook.items,
            key=lambda candidate: ((candidate.tradable_rank or 999), candidate.symbol),
        ):
            if item.symbol in open_symbols:
                continue
            trade = _build_open_trade(
                strategy_metadata=strategy_metadata,
                playbook=playbook,
                item=item,
            )
            if trade is None or trade.trade_id in trades_by_id:
                continue
            trades_by_id[trade.trade_id] = trade
            open_symbols.add(trade.symbol)
            payload = _trade_payload(trade, entry_type="paper_trade_open")
            self._append_payload(payload)
            events.append(payload)

        return events

    def load_trades(self) -> list[PaperTrade]:
        if not self.path.exists():
            return []

        trades_by_id: dict[str, PaperTrade] = {}
        for raw_line in self.path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            entry_type = str(payload.get("entry_type", ""))
            if entry_type not in {"paper_trade_open", "paper_trade_close"}:
                continue
            trade = _trade_from_payload(payload)
            trades_by_id[trade.trade_id] = trade

        return sorted(
            trades_by_id.values(),
            key=lambda trade: (trade.trade_date_utc, trade.symbol, trade.opened_at_utc),
        )

    def review(
        self,
        *,
        as_of: datetime | None = None,
        max_recent_closed: int = 20,
    ) -> dict[str, Any]:
        effective_as_of = (as_of or datetime.now(tz=UTC)).astimezone(UTC)
        trades = self.load_trades()
        open_trades = [trade for trade in trades if trade.status == "open"]
        closed_trades = [trade for trade in trades if trade.status == "closed"]

        recent_closed = sorted(
            closed_trades,
            key=lambda trade: trade.closed_at_utc or trade.opened_at_utc,
            reverse=True,
        )[: max(0, max_recent_closed)]

        return {
            "generated_at_utc": effective_as_of.isoformat(),
            "ledger_path": str(self.path),
            "open_trade_count": len(open_trades),
            "closed_trade_count": len(closed_trades),
            "summary": _review_bucket_payload("all", closed_trades),
            "by_symbol": _aggregate_review_payload(closed_trades, key_name="symbol"),
            "by_session": _aggregate_review_payload(closed_trades, key_name="session_label"),
            "open_trades": [_trade_payload(trade, entry_type="paper_trade_open") for trade in open_trades],
            "recent_closed_trades": [
                _trade_payload(trade, entry_type="paper_trade_close")
                for trade in recent_closed
            ],
        }

    def _append_payload(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")


def _build_open_trade(
    *,
    strategy_metadata: dict[str, object],
    playbook: DayTradePlaybook,
    item: DayTradeInstrumentPlaybook,
) -> PaperTrade | None:
    plan = item.execution_plan
    if not _is_open_candidate(item, plan):
        return None
    assert plan is not None
    assert plan.entry_price is not None
    assert plan.stop_price is not None
    assert plan.target_price is not None

    return PaperTrade(
        trade_id=_trade_id(playbook.trade_date_utc, item.symbol),
        symbol=item.symbol,
        trade_date_utc=playbook.trade_date_utc,
        session_label=plan.session_label or "Unspecified",
        status="open",
        allowed_direction=item.allowed_direction,
        bias=item.bias,
        opened_at_utc=playbook.generated_at_utc.astimezone(UTC),
        entry_price=plan.entry_price,
        stop_price=plan.stop_price,
        target_price=plan.target_price,
        activation_start_utc=plan.activation_start_utc.astimezone(UTC)
        if plan.activation_start_utc is not None
        else None,
        expiry_utc=plan.expiry_utc.astimezone(UTC) if plan.expiry_utc is not None else None,
        confidence=item.confidence,
        tradable_rank=item.tradable_rank,
        risk_amount=plan.risk_amount,
        position_size_units=plan.position_size_units,
        notional_value_usd=plan.notional_value_usd,
        bias_reasons=item.bias_reasons,
        notes=item.notes + tuple(plan.notes),
        strategy_name=str(strategy_metadata.get("name", "")),
        strategy_version=str(strategy_metadata.get("version", "")),
    )


def _is_open_candidate(
    item: DayTradeInstrumentPlaybook,
    plan: TradeExecutionPlan | None,
) -> bool:
    return bool(
        item.is_top_setup
        and item.allowed_direction != "no_trade"
        and plan is not None
        and plan.status == "ready_now"
        and plan.entry_price is not None
        and plan.stop_price is not None
        and plan.target_price is not None
    )


def _maybe_close_trade(
    *,
    trade: PaperTrade,
    current_price: float,
    as_of: datetime,
) -> PaperTrade | None:
    exit_reason: PaperTradeExitReason | None = None
    exit_price: float | None = None

    if _target_hit(trade, current_price):
        exit_reason = "target_hit"
        exit_price = trade.target_price
    elif _stop_hit(trade, current_price):
        exit_reason = "stop_hit"
        exit_price = trade.stop_price
    elif trade.expiry_utc is not None and as_of >= trade.expiry_utc:
        exit_reason = "session_expired"
        exit_price = current_price

    if exit_reason is None or exit_price is None:
        return None

    r_multiple = _r_multiple(
        allowed_direction=trade.allowed_direction,
        entry_price=trade.entry_price,
        stop_price=trade.stop_price,
        exit_price=exit_price,
    )
    return PaperTrade(
        trade_id=trade.trade_id,
        symbol=trade.symbol,
        trade_date_utc=trade.trade_date_utc,
        session_label=trade.session_label,
        status="closed",
        allowed_direction=trade.allowed_direction,
        bias=trade.bias,
        opened_at_utc=trade.opened_at_utc,
        entry_price=trade.entry_price,
        stop_price=trade.stop_price,
        target_price=trade.target_price,
        activation_start_utc=trade.activation_start_utc,
        expiry_utc=trade.expiry_utc,
        closed_at_utc=as_of.astimezone(UTC),
        exit_price=exit_price,
        exit_reason=exit_reason,
        r_multiple=r_multiple,
        outcome=_outcome_from_r_multiple(r_multiple),
        confidence=trade.confidence,
        tradable_rank=trade.tradable_rank,
        risk_amount=trade.risk_amount,
        position_size_units=trade.position_size_units,
        notional_value_usd=trade.notional_value_usd,
        bias_reasons=trade.bias_reasons,
        notes=trade.notes,
        strategy_name=trade.strategy_name,
        strategy_version=trade.strategy_version,
    )


def _trade_id(trade_date: date, symbol: str) -> str:
    return f"{trade_date.isoformat()}:{symbol}"


def _target_hit(trade: PaperTrade, current_price: float) -> bool:
    if trade.allowed_direction == "long_only":
        return current_price >= trade.target_price
    return current_price <= trade.target_price


def _stop_hit(trade: PaperTrade, current_price: float) -> bool:
    if trade.allowed_direction == "long_only":
        return current_price <= trade.stop_price
    return current_price >= trade.stop_price


def _r_multiple(
    *,
    allowed_direction: str,
    entry_price: float,
    stop_price: float,
    exit_price: float,
) -> float:
    risk_distance = abs(entry_price - stop_price)
    if risk_distance <= 0:
        return 0.0
    if allowed_direction == "long_only":
        return (exit_price - entry_price) / risk_distance
    return (entry_price - exit_price) / risk_distance


def _outcome_from_r_multiple(r_multiple: float) -> PaperTradeOutcome:
    if r_multiple > 0:
        return "win"
    if r_multiple < 0:
        return "loss"
    return "flat"


def _aggregate_review_payload(
    trades: list[PaperTrade],
    *,
    key_name: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[PaperTrade]] = {}
    for trade in trades:
        key = getattr(trade, key_name) or "Unspecified"
        grouped.setdefault(str(key), []).append(trade)

    payloads = [
        _review_bucket_payload(key, bucket)
        for key, bucket in grouped.items()
    ]
    return sorted(
        payloads,
        key=lambda item: (
            -float(item["total_r_multiple"]),
            -float(item["win_rate"]),
            str(item["group"]),
        ),
    )


def _review_bucket_payload(group: str, trades: list[PaperTrade]) -> dict[str, Any]:
    wins = sum(1 for trade in trades if trade.outcome == "win")
    losses = sum(1 for trade in trades if trade.outcome == "loss")
    flats = sum(1 for trade in trades if trade.outcome == "flat")
    total_r_multiple = sum(trade.r_multiple or 0.0 for trade in trades)
    count = len(trades)
    return {
        "group": group,
        "trade_count": count,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate": round((wins / count) if count else 0.0, 6),
        "avg_r_multiple": round((total_r_multiple / count) if count else 0.0, 6),
        "total_r_multiple": round(total_r_multiple, 6),
    }


def _trade_payload(trade: PaperTrade, *, entry_type: str) -> dict[str, Any]:
    return {
        "entry_type": entry_type,
        "trade_id": trade.trade_id,
        "symbol": trade.symbol,
        "trade_date_utc": trade.trade_date_utc.isoformat(),
        "session_label": trade.session_label,
        "status": trade.status,
        "action": _action_from_direction(trade.allowed_direction),
        "allowed_direction": trade.allowed_direction,
        "bias": trade.bias,
        "opened_at_utc": trade.opened_at_utc.astimezone(UTC).isoformat(),
        "closed_at_utc": (
            trade.closed_at_utc.astimezone(UTC).isoformat()
            if trade.closed_at_utc is not None
            else None
        ),
        "entry_price": round(trade.entry_price, 6),
        "stop_price": round(trade.stop_price, 6),
        "target_price": round(trade.target_price, 6),
        "exit_price": _rounded_value(trade.exit_price),
        "exit_reason": trade.exit_reason,
        "r_multiple": _rounded_value(trade.r_multiple),
        "outcome": trade.outcome,
        "confidence": round(trade.confidence, 6),
        "tradable_rank": trade.tradable_rank,
        "risk_amount": _rounded_value(trade.risk_amount),
        "position_size_units": _rounded_value(trade.position_size_units),
        "notional_value_usd": _rounded_value(trade.notional_value_usd),
        "activation_start_utc": (
            trade.activation_start_utc.astimezone(UTC).isoformat()
            if trade.activation_start_utc is not None
            else None
        ),
        "expiry_utc": (
            trade.expiry_utc.astimezone(UTC).isoformat()
            if trade.expiry_utc is not None
            else None
        ),
        "bias_reasons": list(trade.bias_reasons),
        "notes": list(trade.notes),
        "strategy_name": trade.strategy_name,
        "strategy_version": trade.strategy_version,
    }


def _trade_from_payload(payload: dict[str, Any]) -> PaperTrade:
    return PaperTrade(
        trade_id=str(payload["trade_id"]),
        symbol=str(payload["symbol"]),
        trade_date_utc=date.fromisoformat(str(payload["trade_date_utc"])),
        session_label=str(payload.get("session_label") or "Unspecified"),
        status=str(payload["status"]),
        allowed_direction=str(payload["allowed_direction"]),
        bias=str(payload.get("bias", "")),
        opened_at_utc=_parse_datetime(payload["opened_at_utc"]),
        entry_price=float(payload["entry_price"]),
        stop_price=float(payload["stop_price"]),
        target_price=float(payload["target_price"]),
        activation_start_utc=_parse_optional_datetime(payload.get("activation_start_utc")),
        expiry_utc=_parse_optional_datetime(payload.get("expiry_utc")),
        closed_at_utc=_parse_optional_datetime(payload.get("closed_at_utc")),
        exit_price=_optional_float(payload.get("exit_price")),
        exit_reason=payload.get("exit_reason"),
        r_multiple=_optional_float(payload.get("r_multiple")),
        outcome=payload.get("outcome"),
        confidence=float(payload.get("confidence") or 0.0),
        tradable_rank=payload.get("tradable_rank"),
        risk_amount=_optional_float(payload.get("risk_amount")),
        position_size_units=_optional_float(payload.get("position_size_units")),
        notional_value_usd=_optional_float(payload.get("notional_value_usd")),
        bias_reasons=tuple(str(item) for item in payload.get("bias_reasons", [])),
        notes=tuple(str(item) for item in payload.get("notes", [])),
        strategy_name=str(payload.get("strategy_name", "")),
        strategy_version=str(payload.get("strategy_version", "")),
    )


def _parse_datetime(value: object) -> datetime:
    text = str(value)
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _parse_optional_datetime(value: object) -> datetime | None:
    if not value:
        return None
    return _parse_datetime(value)


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _action_from_direction(allowed_direction: str) -> str:
    if allowed_direction == "long_only":
        return "buy"
    if allowed_direction == "short_only":
        return "sell"
    return "no_trade"


def _rounded_value(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)
