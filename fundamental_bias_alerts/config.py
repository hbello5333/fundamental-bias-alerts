from __future__ import annotations

import json
import os
from pathlib import Path

from .models import (
    AlertingConfig,
    DayTradingConfig,
    DriverSpec,
    EntitySpec,
    EventPolicySpec,
    InstrumentSpec,
    ResearchConfig,
    SessionSpec,
    SeriesSpec,
    StrategyConfig,
)


def load_raw_config(path: str | Path) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_strategy_config(path: str | Path) -> StrategyConfig:
    raw = load_raw_config(path)

    entities: dict[str, EntitySpec] = {}
    for raw_entity in raw["entities"]:
        drivers = tuple(_parse_driver(driver) for driver in raw_entity["drivers"])
        entity = EntitySpec(
            key=raw_entity["key"],
            label=raw_entity["label"],
            drivers=drivers,
        )
        entities[entity.key] = entity

    instruments = tuple(
        InstrumentSpec(
            symbol=item["symbol"],
            base_entity=item["base_entity"],
            quote_entity=item["quote_entity"],
            threshold=float(item["threshold"]),
        )
        for item in raw["instruments"]
    )

    state_path_override = os.environ.get("FBA_STATE_PATH", "").strip()
    snapshot_path_override = os.environ.get("FBA_SNAPSHOT_PATH", "").strip()
    journal_path_override = os.environ.get("FBA_JOURNAL_PATH", "").strip()

    alerting = AlertingConfig(
        state_path=state_path_override or raw["alerting"]["state_path"],
        emit_on_first_run=bool(raw["alerting"]["emit_on_first_run"]),
        min_score_change=float(raw["alerting"]["min_score_change"]),
    )
    research_raw = raw.get("research", {})
    snapshot_path = snapshot_path_override or research_raw.get(
        "snapshot_path",
        "data/bias_snapshots.jsonl",
    )
    journal_path = journal_path_override or research_raw.get(
        "journal_path",
        "data/paper_trade_journal.jsonl",
    )
    research = ResearchConfig(
        snapshot_path=str(snapshot_path) if snapshot_path else None,
        journal_path=str(journal_path) if journal_path else None,
    )
    day_trading = _parse_day_trading(raw.get("day_trading"))

    return StrategyConfig(
        metadata=dict(raw["metadata"]),
        alerting=alerting,
        research=research,
        day_trading=day_trading,
        entities=entities,
        instruments=instruments,
    )


def iter_series_specs(config: StrategyConfig) -> list[SeriesSpec]:
    series_specs: list[SeriesSpec] = []
    for entity in config.entities.values():
        for driver in entity.drivers:
            series_specs.append(driver.series)
    return series_specs


def _parse_driver(raw_driver: dict[str, object]) -> DriverSpec:
    return DriverSpec(
        key=raw_driver["key"],
        label=raw_driver["label"],
        weight=float(raw_driver["weight"]),
        mode=raw_driver["mode"],
        bullish_when=raw_driver["bullish_when"],
        neutral_value=(
            float(raw_driver["neutral_value"])
            if raw_driver.get("neutral_value") is not None
            else None
        ),
        scale=float(raw_driver["scale"]),
        stale_after_hours=int(raw_driver["stale_after_hours"]),
        series=SeriesSpec(
            series_id=raw_driver["series"].get("series_id"),
            search_text=raw_driver["series"].get("search_text"),
        ),
    )


def _parse_day_trading(raw_day_trading: dict[str, object] | None) -> DayTradingConfig | None:
    if not raw_day_trading:
        return None

    sessions = tuple(
        SessionSpec(
            key=item["key"],
            label=item["label"],
            timezone=item["timezone"],
            start_time=item["start_time"],
            end_time=item["end_time"],
        )
        for item in raw_day_trading.get("sessions", [])
    )
    instrument_sessions = {
        str(symbol): tuple(str(session) for session in session_keys)
        for symbol, session_keys in raw_day_trading.get("instrument_sessions", {}).items()
    }
    event_policies = tuple(
        EventPolicySpec(
            currency=item["currency"],
            impact=item["impact"],
            block_before_minutes=int(item["block_before_minutes"]),
            block_after_minutes=int(item["block_after_minutes"]),
            preferred_sessions=tuple(item.get("preferred_sessions", [])),
        )
        for item in raw_day_trading.get("event_policies", [])
    )

    return DayTradingConfig(
        min_confidence=float(raw_day_trading.get("min_confidence", 0.7)),
        max_stale_drivers=int(raw_day_trading.get("max_stale_drivers", 1)),
        sessions=sessions,
        instrument_sessions=instrument_sessions,
        event_policies=event_policies,
        max_ranked_setups=int(raw_day_trading.get("max_ranked_setups", 2)),
        risk_per_trade_pct=float(raw_day_trading.get("risk_per_trade_pct", 0.25)),
        target_r_multiple=float(raw_day_trading.get("target_r_multiple", 2.0)),
        default_stop_loss_pct=float(raw_day_trading.get("default_stop_loss_pct", 0.0035)),
        stop_loss_pct_by_symbol={
            str(symbol): float(value)
            for symbol, value in raw_day_trading.get("stop_loss_pct_by_symbol", {}).items()
        },
    )
