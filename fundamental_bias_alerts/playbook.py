from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .models import (
    DayTradeInstrumentPlaybook,
    DayTradePlaybook,
    DayTradingConfig,
    EventPolicySpec,
    InstrumentResult,
    InstrumentSpec,
    NoTradeWindow,
    ReleaseCalendar,
    ReleaseEvent,
    SessionSpec,
    SessionWindow,
    StrategyConfig,
    TradeExecutionPlan,
)


def generate_day_trade_playbook(
    *,
    config: StrategyConfig,
    calendar: ReleaseCalendar,
    results: list[InstrumentResult],
    trade_date: date,
    as_of: datetime | None = None,
    reference_prices: dict[str, float] | None = None,
    account_size: float | None = None,
) -> DayTradePlaybook:
    if config.day_trading is None:
        raise ValueError("Strategy config does not include a day_trading section.")

    as_of_utc = (as_of or datetime.now(tz=UTC)).astimezone(UTC)
    instrument_specs = {item.symbol: item for item in config.instruments}
    session_specs = {item.key: item for item in config.day_trading.sessions}

    items = tuple(
        _build_playbook_item(
            config=config.day_trading,
            instrument=instrument_specs[result.symbol],
            result=result,
            calendar=calendar,
            session_specs=session_specs,
            trade_date=trade_date,
            as_of=as_of_utc,
        )
        for result in results
    )
    ranked_items = _apply_tradable_ranks(
        items,
        max_ranked_setups=config.day_trading.max_ranked_setups,
    )
    planned_items = tuple(
        _with_execution_plan(
            item=item,
            instrument=instrument_specs[item.symbol],
            config=config.day_trading,
            as_of=as_of_utc,
            reference_price=(reference_prices or {}).get(item.symbol),
            account_size=account_size,
        )
        for item in ranked_items
    )

    return DayTradePlaybook(
        generated_at_utc=as_of_utc,
        trade_date_utc=trade_date,
        items=planned_items,
    )


def format_day_trade_playbook_payload(playbook: DayTradePlaybook) -> dict[str, Any]:
    return {
        "generated_at_utc": playbook.generated_at_utc.astimezone(UTC).isoformat(),
        "trade_date_utc": playbook.trade_date_utc.isoformat(),
        "top_setups": [_top_setup_payload(item) for item in _top_setup_items(playbook)],
        "instruments": [_playbook_item_payload(item) for item in playbook.items],
    }


def format_day_trade_playbook_brief(playbook: DayTradePlaybook) -> str:
    lines = [
        (
            "Day Trade Brief | "
            f"generated {playbook.generated_at_utc.astimezone(UTC).isoformat()} | "
            f"trade date {playbook.trade_date_utc.isoformat()}"
        )
    ]
    top_setups = _top_setup_items(playbook)
    if top_setups:
        lines.append(
            "Top setups: "
            + "; ".join(
                f"#{item.tradable_rank} {item.symbol} {_action_label(item)}"
                for item in top_setups
            )
        )
    else:
        lines.append("Top setups: None")

    for item in playbook.items:
        lines.extend(
            [
                "",
                _brief_headline(item),
                f"Why: {_brief_reasons(item)}",
                f"Sessions: {_session_summary(item)}",
                f"Lockouts: {_lockout_summary(item)}",
            ]
        )
        if item.execution_plan is not None:
            lines.append(f"Plan: {_execution_plan_brief(item.execution_plan)}")
        if item.notes:
            lines.append(f"Notes: {' '.join(item.notes)}")

    return "\n".join(lines)


def _build_playbook_item(
    *,
    config: DayTradingConfig,
    instrument: InstrumentSpec,
    result: InstrumentResult,
    calendar: ReleaseCalendar,
    session_specs: dict[str, SessionSpec],
    trade_date: date,
    as_of: datetime,
) -> DayTradeInstrumentPlaybook:
    relevant_events = tuple(
        event
        for event in calendar.events
        if _event_applies_to_instrument(event, instrument)
        and event.timestamp.astimezone(UTC).date() == trade_date
    )
    valid_session_keys = _valid_session_keys(
        config=config,
        symbol=result.symbol,
        events=relevant_events,
    )
    valid_sessions = tuple(
        _session_window(session_specs[key], trade_date)
        for key in valid_session_keys
        if key in session_specs
    )
    no_trade_windows = tuple(
        sorted(
            (
                _no_trade_window(event, _event_policy(config, event))
                for event in relevant_events
            ),
            key=lambda item: item.start_utc,
        )
    )

    stale_driver_count = _stale_driver_count(result)
    notes: list[str] = []
    allowed_direction = "no_trade"
    trade_state = "no_trade"

    if result.direction == "neutral":
        notes.append("Bias is neutral, so no directional day-trade is allowed.")
    else:
        allowed_direction = "long_only" if result.direction == "bullish" else "short_only"

    if result.confidence < config.min_confidence:
        allowed_direction = "no_trade"
        notes.append(
            f"Confidence {result.confidence:.2f} is below the day-trading floor of {config.min_confidence:.2f}."
        )

    if stale_driver_count > config.max_stale_drivers:
        allowed_direction = "no_trade"
        notes.append(
            f"Stale driver count {stale_driver_count} exceeds the limit of {config.max_stale_drivers}."
        )

    if allowed_direction != "no_trade":
        if any(window.start_utc <= as_of <= window.end_utc for window in no_trade_windows):
            trade_state = "lockout"
            notes.append("Current time is inside a no-trade window for a scheduled release.")
        else:
            trade_state = "ready"

    return DayTradeInstrumentPlaybook(
        symbol=result.symbol,
        bias=result.direction,
        score=result.score,
        bias_strength=abs(result.score),
        allowed_direction=allowed_direction,
        trade_state=trade_state,
        confidence=result.confidence,
        stale_driver_count=stale_driver_count,
        valid_sessions=valid_sessions,
        no_trade_windows=no_trade_windows,
        bias_reasons=result.reasons,
        notes=tuple(notes),
    )


def _apply_tradable_ranks(
    items: tuple[DayTradeInstrumentPlaybook, ...],
    *,
    max_ranked_setups: int,
) -> tuple[DayTradeInstrumentPlaybook, ...]:
    ready_items = sorted(
        (
            item
            for item in items
            if item.trade_state == "ready" and item.allowed_direction != "no_trade"
        ),
        key=lambda item: (
            -item.confidence,
            -item.bias_strength,
            item.stale_driver_count,
            item.symbol,
        ),
    )
    ranks_by_symbol = {
        item.symbol: index
        for index, item in enumerate(ready_items, start=1)
    }
    ranked_limit = max(0, max_ranked_setups)
    return tuple(
        replace(
            item,
            tradable_rank=ranks_by_symbol.get(item.symbol),
            is_top_setup=(
                ranks_by_symbol.get(item.symbol) is not None
                and ranks_by_symbol[item.symbol] <= ranked_limit
            ),
        )
        for item in items
    )


def _with_execution_plan(
    *,
    item: DayTradeInstrumentPlaybook,
    instrument: InstrumentSpec,
    config: DayTradingConfig,
    as_of: datetime,
    reference_price: float | None,
    account_size: float | None,
) -> DayTradeInstrumentPlaybook:
    return replace(
        item,
        execution_plan=_build_execution_plan(
            item=item,
            instrument=instrument,
            config=config,
            as_of=as_of,
            reference_price=reference_price,
            account_size=account_size,
        ),
    )


def _build_execution_plan(
    *,
    item: DayTradeInstrumentPlaybook,
    instrument: InstrumentSpec,
    config: DayTradingConfig,
    as_of: datetime,
    reference_price: float | None,
    account_size: float | None,
) -> TradeExecutionPlan:
    stop_loss_pct = config.stop_loss_pct_by_symbol.get(
        item.symbol,
        config.default_stop_loss_pct,
    )
    current_session = _current_session(item.valid_sessions, as_of)
    next_session = _next_session(item.valid_sessions, as_of)
    notes: list[str] = []
    session_label = current_session.label if current_session else (next_session.label if next_session else "")
    activation_start_utc = current_session.start_utc if current_session else (
        next_session.start_utc if next_session else None
    )
    expiry_utc = current_session.end_utc if current_session else (next_session.end_utc if next_session else None)

    if item.allowed_direction == "no_trade" or item.trade_state != "ready":
        return TradeExecutionPlan(
            status="blocked",
            entry_style="market",
            stop_loss_pct=stop_loss_pct,
            target_r_multiple=config.target_r_multiple,
            risk_per_trade_pct=config.risk_per_trade_pct,
            reference_price=reference_price,
            account_size=account_size,
            activation_start_utc=activation_start_utc,
            expiry_utc=expiry_utc,
            session_label=session_label,
            notes=("Execution blocked until the bias is tradable and out of lockout.",),
        )

    if current_session is None and next_session is None:
        return TradeExecutionPlan(
            status="blocked",
            entry_style="market",
            stop_loss_pct=stop_loss_pct,
            target_r_multiple=config.target_r_multiple,
            risk_per_trade_pct=config.risk_per_trade_pct,
            reference_price=reference_price,
            account_size=account_size,
            notes=("No valid trading session remains for this trade date.",),
        )

    if reference_price is None:
        if current_session is not None:
            notes.append("Supply a reference price to compute exact entry, stop, and target levels now.")
        else:
            notes.append("Supply a fresh reference price before the next valid session opens.")
        return TradeExecutionPlan(
            status="needs_price",
            entry_style="market",
            stop_loss_pct=stop_loss_pct,
            target_r_multiple=config.target_r_multiple,
            risk_per_trade_pct=config.risk_per_trade_pct,
            account_size=account_size,
            activation_start_utc=activation_start_utc,
            expiry_utc=expiry_utc,
            session_label=session_label,
            notes=tuple(notes),
        )

    entry_price = reference_price
    stop_price, target_price = _price_levels(
        direction=item.allowed_direction,
        entry_price=entry_price,
        stop_loss_pct=stop_loss_pct,
        target_r_multiple=config.target_r_multiple,
    )
    stop_distance_price = abs(entry_price - stop_price)
    target_distance_price = abs(target_price - entry_price)
    risk_amount = None
    position_size_units = None
    notional_value_usd = None
    if account_size is not None:
        risk_amount = account_size * (config.risk_per_trade_pct / 100.0)
        position_size_units = _position_size_units(
            instrument=instrument,
            reference_price=entry_price,
            stop_distance_price=stop_distance_price,
            risk_amount=risk_amount,
        )
        notional_value_usd = _notional_value_usd(
            instrument=instrument,
            reference_price=entry_price,
            position_size_units=position_size_units,
        )
    if current_session is None and next_session is not None:
        notes.append("Refresh the reference price before the next valid session opens.")

    return TradeExecutionPlan(
        status="ready_now" if current_session is not None else "waiting_for_session",
        entry_style="market",
        stop_loss_pct=stop_loss_pct,
        target_r_multiple=config.target_r_multiple,
        risk_per_trade_pct=config.risk_per_trade_pct,
        reference_price=reference_price,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        stop_distance_price=stop_distance_price,
        target_distance_price=target_distance_price,
        account_size=account_size,
        risk_amount=risk_amount,
        position_size_units=position_size_units,
        notional_value_usd=notional_value_usd,
        activation_start_utc=activation_start_utc,
        expiry_utc=expiry_utc,
        session_label=session_label,
        notes=tuple(notes),
    )


def _event_applies_to_instrument(event: ReleaseEvent, instrument: InstrumentSpec) -> bool:
    return event.currency in {instrument.base_entity, instrument.quote_entity}


def _valid_session_keys(
    *,
    config: DayTradingConfig,
    symbol: str,
    events: tuple[ReleaseEvent, ...],
) -> tuple[str, ...]:
    if events:
        preferred_keys: list[str] = []
        for event in events:
            policy = _event_policy(config, event)
            preferred_keys.extend(policy.preferred_sessions)
        if preferred_keys:
            return tuple(dict.fromkeys(preferred_keys))

    configured = config.instrument_sessions.get(symbol)
    if configured:
        return configured
    return tuple(session.key for session in config.sessions)


def _event_policy(config: DayTradingConfig, event: ReleaseEvent) -> EventPolicySpec:
    for policy in config.event_policies:
        if policy.currency == event.currency and policy.impact == event.impact:
            return policy
    for policy in config.event_policies:
        if policy.currency == event.currency:
            return policy
    return EventPolicySpec(
        currency=event.currency,
        impact=event.impact,
        block_before_minutes=10,
        block_after_minutes=20,
        preferred_sessions=(),
    )


def _no_trade_window(event: ReleaseEvent, policy: EventPolicySpec) -> NoTradeWindow:
    event_time_utc = event.timestamp.astimezone(UTC)
    return NoTradeWindow(
        label=event.label,
        currency=event.currency,
        impact=event.impact,
        start_utc=event_time_utc - timedelta(minutes=policy.block_before_minutes),
        end_utc=event_time_utc + timedelta(minutes=policy.block_after_minutes),
        event_time_utc=event_time_utc,
        source_url=event.source_url,
    )


def _session_window(spec: SessionSpec, trade_date: date) -> SessionWindow:
    zone = ZoneInfo(spec.timezone)
    start_local = datetime.combine(trade_date, _parse_time(spec.start_time), tzinfo=zone)
    end_local = datetime.combine(trade_date, _parse_time(spec.end_time), tzinfo=zone)
    if end_local <= start_local:
        end_local += timedelta(days=1)

    return SessionWindow(
        key=spec.key,
        label=spec.label,
        timezone=spec.timezone,
        start_utc=start_local.astimezone(UTC),
        end_utc=end_local.astimezone(UTC),
    )


def _current_session(
    sessions: tuple[SessionWindow, ...],
    as_of: datetime,
) -> SessionWindow | None:
    for session in sessions:
        if session.start_utc <= as_of <= session.end_utc:
            return session
    return None


def _next_session(
    sessions: tuple[SessionWindow, ...],
    as_of: datetime,
) -> SessionWindow | None:
    future_sessions = [session for session in sessions if session.start_utc > as_of]
    if not future_sessions:
        return None
    return min(future_sessions, key=lambda item: item.start_utc)


def _parse_time(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))


def _stale_driver_count(result: InstrumentResult) -> int:
    return sum(
        1
        for driver in (*result.base_result.drivers, *result.quote_result.drivers)
        if driver.data_state in {"stale", "missing", "error"}
    )


def _playbook_item_payload(item: DayTradeInstrumentPlaybook) -> dict[str, Any]:
    return {
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
        "valid_sessions": [
            {
                "key": session.key,
                "label": session.label,
                "timezone": session.timezone,
                "start_utc": session.start_utc.astimezone(UTC).isoformat(),
                "end_utc": session.end_utc.astimezone(UTC).isoformat(),
            }
            for session in item.valid_sessions
        ],
        "no_trade_windows": [
            {
                "label": window.label,
                "currency": window.currency,
                "impact": window.impact,
                "start_utc": window.start_utc.astimezone(UTC).isoformat(),
                "end_utc": window.end_utc.astimezone(UTC).isoformat(),
                "event_time_utc": window.event_time_utc.astimezone(UTC).isoformat(),
                "source_url": window.source_url,
            }
            for window in item.no_trade_windows
        ],
        "bias_reasons": list(item.bias_reasons),
        "notes": list(item.notes),
        "execution_plan": _execution_plan_payload(item.execution_plan),
    }


def _top_setup_items(playbook: DayTradePlaybook) -> list[DayTradeInstrumentPlaybook]:
    return sorted(
        (item for item in playbook.items if item.is_top_setup and item.tradable_rank is not None),
        key=lambda item: item.tradable_rank or 0,
    )


def _top_setup_payload(item: DayTradeInstrumentPlaybook) -> dict[str, Any]:
    return {
        "symbol": item.symbol,
        "tradable_rank": item.tradable_rank,
        "action": _action_value(item),
        "confidence": round(item.confidence, 6),
        "score": round(item.score, 6),
        "bias_strength": round(item.bias_strength, 6),
        "execution_plan": _execution_plan_payload(item.execution_plan),
    }


def _execution_plan_payload(plan: TradeExecutionPlan | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    return {
        "status": plan.status,
        "entry_style": plan.entry_style,
        "stop_loss_pct": round(plan.stop_loss_pct, 6),
        "target_r_multiple": round(plan.target_r_multiple, 6),
        "risk_per_trade_pct": round(plan.risk_per_trade_pct, 6),
        "reference_price": _rounded_value(plan.reference_price),
        "entry_price": _rounded_value(plan.entry_price),
        "stop_price": _rounded_value(plan.stop_price),
        "target_price": _rounded_value(plan.target_price),
        "stop_distance_price": _rounded_value(plan.stop_distance_price),
        "target_distance_price": _rounded_value(plan.target_distance_price),
        "account_size": _rounded_value(plan.account_size),
        "risk_amount": _rounded_value(plan.risk_amount),
        "position_size_units": _rounded_value(plan.position_size_units),
        "notional_value_usd": _rounded_value(plan.notional_value_usd),
        "activation_start_utc": (
            plan.activation_start_utc.astimezone(UTC).isoformat()
            if plan.activation_start_utc is not None
            else None
        ),
        "expiry_utc": (
            plan.expiry_utc.astimezone(UTC).isoformat()
            if plan.expiry_utc is not None
            else None
        ),
        "session_label": plan.session_label,
        "notes": list(plan.notes),
    }


def _rounded_value(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)


def _action_value(item: DayTradeInstrumentPlaybook) -> str:
    if item.trade_state == "lockout":
        return "wait"
    if item.allowed_direction == "long_only":
        return "buy"
    if item.allowed_direction == "short_only":
        return "sell"
    return "no_trade"


def _action_label(item: DayTradeInstrumentPlaybook) -> str:
    action = _action_value(item)
    if action == "buy":
        return "BUY ONLY"
    if action == "sell":
        return "SELL ONLY"
    if action == "wait":
        return "WAIT"
    return "NO TRADE"


def _trade_state_label(item: DayTradeInstrumentPlaybook) -> str:
    if item.trade_state == "no_trade":
        return "NO TRADE"
    return item.trade_state.upper()


def _brief_headline(item: DayTradeInstrumentPlaybook) -> str:
    action_label = _action_label(item)
    state_label = _trade_state_label(item)
    if item.is_top_setup and item.tradable_rank is not None:
        action_label = f"TOP {item.tradable_rank} {action_label}"
    if action_label == state_label:
        return f"{item.symbol} | {action_label} | confidence {item.confidence:.2f}"
    return f"{item.symbol} | {action_label} | {state_label} | confidence {item.confidence:.2f}"


def _brief_reasons(item: DayTradeInstrumentPlaybook) -> str:
    if item.bias_reasons:
        return "; ".join(item.bias_reasons[:2])
    if item.notes:
        return " ".join(item.notes)
    return "No dominant macro drivers were recorded."


def _execution_plan_brief(plan: TradeExecutionPlan) -> str:
    if plan.status == "blocked":
        if plan.notes:
            return "blocked | " + " ".join(plan.notes)
        return "blocked"
    if plan.status == "needs_price":
        note_text = f" | {' '.join(plan.notes)}" if plan.notes else ""
        session_text = f" | session {plan.session_label}" if plan.session_label else ""
        return (
            f"needs price | risk {plan.risk_per_trade_pct:.2f}% | "
            f"stop {plan.stop_loss_pct:.2%} | target {plan.target_r_multiple:.2f}R"
            f"{session_text}{note_text}"
        )

    core = (
        f"{plan.status} | entry {plan.entry_price:.6f} | stop {plan.stop_price:.6f} | "
        f"target {plan.target_price:.6f} | stop {plan.stop_loss_pct:.2%} | "
        f"target {plan.target_r_multiple:.2f}R"
    )
    if plan.risk_amount is not None:
        core += f" | risk ${plan.risk_amount:.2f}"
    if plan.position_size_units is not None:
        core += f" | size {plan.position_size_units:.4f} units"
    if plan.session_label:
        core += f" | session {plan.session_label}"
    if plan.notes:
        core += f" | {' '.join(plan.notes)}"
    return core


def _session_summary(item: DayTradeInstrumentPlaybook) -> str:
    if not item.valid_sessions:
        return "No preferred sessions configured."
    return ", ".join(
        (
            f"{session.label} "
            f"({session.start_utc.astimezone(UTC):%H:%M}-{session.end_utc.astimezone(UTC):%H:%M} UTC)"
        )
        for session in item.valid_sessions
    )


def _lockout_summary(item: DayTradeInstrumentPlaybook) -> str:
    if not item.no_trade_windows:
        return "None"
    return ", ".join(
        (
            f"{window.label} "
            f"({window.start_utc.astimezone(UTC):%H:%M}-{window.end_utc.astimezone(UTC):%H:%M} UTC)"
        )
        for window in item.no_trade_windows
    )


def _price_levels(
    *,
    direction: str,
    entry_price: float,
    stop_loss_pct: float,
    target_r_multiple: float,
) -> tuple[float, float]:
    if direction == "long_only":
        stop_price = entry_price * (1.0 - stop_loss_pct)
        target_price = entry_price * (1.0 + (stop_loss_pct * target_r_multiple))
        return stop_price, target_price
    stop_price = entry_price * (1.0 + stop_loss_pct)
    target_price = entry_price * (1.0 - (stop_loss_pct * target_r_multiple))
    return stop_price, target_price


def _position_size_units(
    *,
    instrument: InstrumentSpec,
    reference_price: float,
    stop_distance_price: float,
    risk_amount: float,
) -> float | None:
    if stop_distance_price <= 0 or risk_amount <= 0:
        return None
    if instrument.quote_entity == "USD":
        return risk_amount / stop_distance_price
    if instrument.base_entity == "USD":
        return (risk_amount * reference_price) / stop_distance_price
    return None


def _notional_value_usd(
    *,
    instrument: InstrumentSpec,
    reference_price: float,
    position_size_units: float | None,
) -> float | None:
    if position_size_units is None:
        return None
    if instrument.quote_entity == "USD":
        return position_size_units * reference_price
    if instrument.base_entity == "USD":
        return position_size_units
    return None
