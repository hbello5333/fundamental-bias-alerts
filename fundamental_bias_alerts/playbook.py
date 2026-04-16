from __future__ import annotations

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
)


def generate_day_trade_playbook(
    *,
    config: StrategyConfig,
    calendar: ReleaseCalendar,
    results: list[InstrumentResult],
    trade_date: date,
    as_of: datetime | None = None,
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

    return DayTradePlaybook(
        generated_at_utc=as_of_utc,
        trade_date_utc=trade_date,
        items=items,
    )


def format_day_trade_playbook_payload(playbook: DayTradePlaybook) -> dict[str, Any]:
    return {
        "generated_at_utc": playbook.generated_at_utc.astimezone(UTC).isoformat(),
        "trade_date_utc": playbook.trade_date_utc.isoformat(),
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
        allowed_direction=allowed_direction,
        trade_state=trade_state,
        confidence=result.confidence,
        stale_driver_count=stale_driver_count,
        valid_sessions=valid_sessions,
        no_trade_windows=no_trade_windows,
        bias_reasons=result.reasons,
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
        "action": _action_value(item),
        "allowed_direction": item.allowed_direction,
        "trade_state": item.trade_state,
        "confidence": round(item.confidence, 6),
        "stale_driver_count": item.stale_driver_count,
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
    }


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
    if action_label == state_label:
        return f"{item.symbol} | {action_label} | confidence {item.confidence:.2f}"
    return f"{item.symbol} | {action_label} | {state_label} | confidence {item.confidence:.2f}"


def _brief_reasons(item: DayTradeInstrumentPlaybook) -> str:
    if item.bias_reasons:
        return "; ".join(item.bias_reasons[:2])
    if item.notes:
        return " ".join(item.notes)
    return "No dominant macro drivers were recorded."


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
