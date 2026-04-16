from __future__ import annotations

from datetime import UTC, datetime, time
from math import isclose

from .models import (
    Direction,
    DriverResult,
    DriverSpec,
    EntityResult,
    EntitySpec,
    InstrumentResult,
    InstrumentSpec,
    Observation,
)


def score_driver(
    spec: DriverSpec,
    observations: list[Observation],
    *,
    as_of: datetime,
) -> DriverResult:
    sorted_observations = sorted(observations, key=lambda item: item.date, reverse=True)
    if not sorted_observations:
        return DriverResult(
            key=spec.key,
            label=spec.label,
            score=0.0,
            confidence=0.0,
            direction="neutral",
            data_state="missing",
            reason=f"{spec.label}: no data",
        )

    latest = sorted_observations[0]
    previous = sorted_observations[1] if len(sorted_observations) > 1 else None
    age_hours = _age_hours(latest, as_of=as_of)
    freshness = _freshness(age_hours=age_hours, stale_after_hours=spec.stale_after_hours)
    if freshness <= 0.0:
        return DriverResult(
            key=spec.key,
            label=spec.label,
            score=0.0,
            confidence=0.0,
            direction="neutral",
            data_state="stale",
            reason=f"{spec.label}: stale data",
            latest_value=latest.value,
            previous_value=previous.value if previous else None,
            observation_date=latest.date,
            age_hours=age_hours,
        )

    try:
        signal = _signal(spec, latest=latest, previous=previous)
    except ValueError as exc:
        return DriverResult(
            key=spec.key,
            label=spec.label,
            score=0.0,
            confidence=0.0,
            direction="neutral",
            data_state="error",
            reason=f"{spec.label}: {exc}",
            latest_value=latest.value,
            previous_value=previous.value if previous else None,
            observation_date=latest.date,
            age_hours=age_hours,
        )

    clamped_signal = _clamp(signal, -1.0, 1.0)
    score = clamped_signal * spec.weight * freshness
    confidence = freshness
    direction = _direction_from_score(score)
    comparison = _comparison_text(spec, latest=latest, previous=previous)
    reason = f"{spec.label}: {comparison}"

    return DriverResult(
        key=spec.key,
        label=spec.label,
        score=score,
        confidence=confidence,
        direction=direction,
        data_state="ok",
        reason=reason,
        latest_value=latest.value,
        previous_value=previous.value if previous else None,
        observation_date=latest.date,
        age_hours=age_hours,
    )


def score_entity(
    entity: EntitySpec,
    *,
    series_observations: dict[str, list[Observation]],
    as_of: datetime,
) -> EntityResult:
    results: list[DriverResult] = []
    total_weight = 0.0
    confidence_weight = 0.0
    score = 0.0

    for driver in entity.drivers:
        total_weight += driver.weight
        result = score_driver(
            driver,
            series_observations.get(driver.series.cache_key, []),
            as_of=as_of,
        )
        results.append(result)
        score += result.score
        confidence_weight += driver.weight * result.confidence

    confidence = confidence_weight / total_weight if total_weight else 0.0
    return EntityResult(
        key=entity.key,
        label=entity.label,
        score=score,
        confidence=confidence,
        drivers=tuple(results),
    )


def score_instrument(
    *,
    instrument: InstrumentSpec,
    entities: dict[str, EntitySpec],
    series_observations: dict[str, list[Observation]],
    as_of: datetime,
) -> InstrumentResult:
    base_result = score_entity(
        entities[instrument.base_entity],
        series_observations=series_observations,
        as_of=as_of,
    )
    quote_result = score_entity(
        entities[instrument.quote_entity],
        series_observations=series_observations,
        as_of=as_of,
    )
    score = base_result.score - quote_result.score
    confidence = (base_result.confidence + quote_result.confidence) / 2.0

    if score >= instrument.threshold:
        direction: Direction = "bullish"
    elif score <= -instrument.threshold:
        direction = "bearish"
    else:
        direction = "neutral"

    ranked_drivers = sorted(
        list(base_result.drivers) + list(quote_result.drivers),
        key=lambda result: abs(result.score),
        reverse=True,
    )
    reasons = tuple(result.reason for result in ranked_drivers[:4])

    return InstrumentResult(
        symbol=instrument.symbol,
        score=score,
        confidence=confidence,
        direction=direction,
        threshold=instrument.threshold,
        reasons=reasons,
        base_result=base_result,
        quote_result=quote_result,
    )


def _signal(spec: DriverSpec, *, latest: Observation, previous: Observation | None) -> float:
    if isclose(spec.scale, 0.0):
        raise ValueError("scale must be non-zero")

    if spec.mode == "level":
        if spec.neutral_value is None:
            raise ValueError("neutral_value is required for level mode")
        signal = (latest.value - spec.neutral_value) / spec.scale
    elif spec.mode == "delta":
        if previous is None:
            raise ValueError("at least two observations are required for delta mode")
        signal = (latest.value - previous.value) / spec.scale
    elif spec.mode == "pct_change":
        if previous is None:
            raise ValueError("at least two observations are required for pct_change mode")
        if isclose(previous.value, 0.0):
            raise ValueError("previous value cannot be zero in pct_change mode")
        signal = ((latest.value - previous.value) / abs(previous.value)) / spec.scale
    else:
        raise ValueError(f"unsupported mode {spec.mode!r}")

    if spec.bullish_when == "lower":
        signal *= -1.0
    return signal


def _age_hours(latest: Observation, *, as_of: datetime) -> float:
    observed_at = datetime.combine(latest.date, time.min, tzinfo=UTC)
    return max(0.0, (as_of - observed_at).total_seconds() / 3600.0)


def _freshness(*, age_hours: float, stale_after_hours: int) -> float:
    if stale_after_hours <= 0:
        return 1.0
    return 0.0 if age_hours >= stale_after_hours else 1.0


def _direction_from_score(score: float) -> Direction:
    if score > 0:
        return "bullish"
    if score < 0:
        return "bearish"
    return "neutral"


def _comparison_text(
    spec: DriverSpec,
    *,
    latest: Observation,
    previous: Observation | None,
) -> str:
    if spec.mode == "level":
        return f"latest={latest.value:.4f}, neutral={spec.neutral_value:.4f}"
    if previous is None:
        return f"latest={latest.value:.4f}"
    if spec.mode == "delta":
        return f"latest={latest.value:.4f}, previous={previous.value:.4f}"
    pct_change = ((latest.value - previous.value) / abs(previous.value)) * 100.0
    return (
        f"latest={latest.value:.4f}, previous={previous.value:.4f}, "
        f"change={pct_change:.2f}%"
    )


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
