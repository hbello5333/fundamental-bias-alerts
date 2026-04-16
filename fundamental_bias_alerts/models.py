from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

Direction = Literal["bullish", "bearish", "neutral"]
DriverMode = Literal["level", "delta", "pct_change"]
BullishWhen = Literal["higher", "lower"]
DataState = Literal["ok", "missing", "stale", "error"]
EventImpact = Literal["high", "medium", "low"]
AllowedDirection = Literal["long_only", "short_only", "no_trade"]
TradeState = Literal["ready", "lockout", "no_trade"]


@dataclass(frozen=True)
class SeriesSpec:
    series_id: str | None = None
    search_text: str | None = None

    @property
    def cache_key(self) -> str:
        if self.series_id:
            return self.series_id
        if self.search_text:
            return self.search_text
        raise ValueError("SeriesSpec requires either series_id or search_text.")


@dataclass(frozen=True)
class DriverSpec:
    key: str
    label: str
    weight: float
    mode: DriverMode
    bullish_when: BullishWhen
    scale: float
    stale_after_hours: int
    series: SeriesSpec
    neutral_value: float | None = None


@dataclass(frozen=True)
class EntitySpec:
    key: str
    label: str
    drivers: tuple[DriverSpec, ...]


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    base_entity: str
    quote_entity: str
    threshold: float


@dataclass(frozen=True)
class Observation:
    date: date | str
    value: float

    def __post_init__(self) -> None:
        if isinstance(self.date, str):
            object.__setattr__(self, "date", date.fromisoformat(self.date))


@dataclass(frozen=True)
class DriverResult:
    key: str
    label: str
    score: float
    confidence: float
    direction: Direction
    data_state: DataState
    reason: str
    latest_value: float | None = None
    previous_value: float | None = None
    observation_date: date | None = None
    age_hours: float | None = None


@dataclass(frozen=True)
class EntityResult:
    key: str
    label: str
    score: float
    confidence: float
    drivers: tuple[DriverResult, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class InstrumentResult:
    symbol: str
    score: float
    confidence: float
    direction: Direction
    threshold: float
    reasons: tuple[str, ...]
    base_result: EntityResult
    quote_result: EntityResult


@dataclass(frozen=True)
class AlertingConfig:
    state_path: str
    emit_on_first_run: bool
    min_score_change: float


@dataclass(frozen=True)
class ResearchConfig:
    snapshot_path: str | None


@dataclass(frozen=True)
class SessionSpec:
    key: str
    label: str
    timezone: str
    start_time: str
    end_time: str


@dataclass(frozen=True)
class EventPolicySpec:
    currency: str
    impact: EventImpact
    block_before_minutes: int
    block_after_minutes: int
    preferred_sessions: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DayTradingConfig:
    min_confidence: float
    max_stale_drivers: int
    sessions: tuple[SessionSpec, ...]
    instrument_sessions: dict[str, tuple[str, ...]]
    event_policies: tuple[EventPolicySpec, ...]


@dataclass(frozen=True)
class StrategyConfig:
    metadata: dict[str, object]
    alerting: AlertingConfig
    research: ResearchConfig
    day_trading: DayTradingConfig | None
    entities: dict[str, EntitySpec]
    instruments: tuple[InstrumentSpec, ...]


@dataclass(frozen=True)
class ResolvedSeries:
    series_id: str
    title: str
    frequency: str | None = None
    units: str | None = None


@dataclass(frozen=True)
class ReleaseEvent:
    event_id: str
    label: str
    currency: str
    impact: EventImpact
    timestamp: datetime | str
    source_url: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.timestamp, str):
            object.__setattr__(
                self,
                "timestamp",
                datetime.fromisoformat(self.timestamp.replace("Z", "+00:00")),
            )


@dataclass(frozen=True)
class ReleaseCalendar:
    events: tuple[ReleaseEvent, ...]


@dataclass(frozen=True)
class SessionWindow:
    key: str
    label: str
    timezone: str
    start_utc: datetime
    end_utc: datetime


@dataclass(frozen=True)
class NoTradeWindow:
    label: str
    currency: str
    impact: EventImpact
    start_utc: datetime
    end_utc: datetime
    event_time_utc: datetime
    source_url: str = ""


@dataclass(frozen=True)
class DayTradeInstrumentPlaybook:
    symbol: str
    bias: Direction
    allowed_direction: AllowedDirection
    trade_state: TradeState
    confidence: float
    stale_driver_count: int
    valid_sessions: tuple[SessionWindow, ...]
    no_trade_windows: tuple[NoTradeWindow, ...]
    bias_reasons: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DayTradePlaybook:
    generated_at_utc: datetime
    trade_date_utc: date
    items: tuple[DayTradeInstrumentPlaybook, ...]
