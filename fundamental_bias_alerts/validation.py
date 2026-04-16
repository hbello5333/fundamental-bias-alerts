from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_CONFIDENCE_BUCKET_LOWERS = (0.0, 0.6, 0.75, 0.9)


def validate_snapshot_file(
    *,
    snapshots_path: str | Path,
    prices_path: str | Path,
    horizon_hours: int | list[int] | tuple[int, ...],
    min_confidence: float,
    symbol_filter: str = "",
    confidence_bucket_lowers: tuple[float, ...] | list[float] | None = None,
    min_cohort_samples: int = 1,
    max_ranked_cohorts: int = 20,
) -> dict[str, Any]:
    snapshots = _load_snapshots(Path(snapshots_path))
    prices = _load_prices(Path(prices_path))
    return validate_snapshots(
        snapshots=snapshots,
        prices=prices,
        horizon_hours=horizon_hours,
        min_confidence=min_confidence,
        symbol_filter=symbol_filter,
        confidence_bucket_lowers=confidence_bucket_lowers,
        min_cohort_samples=min_cohort_samples,
        max_ranked_cohorts=max_ranked_cohorts,
    )


def validate_snapshots(
    *,
    snapshots: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    horizon_hours: int | list[int] | tuple[int, ...],
    min_confidence: float,
    symbol_filter: str = "",
    confidence_bucket_lowers: tuple[float, ...] | list[float] | None = None,
    min_cohort_samples: int = 1,
    max_ranked_cohorts: int = 20,
) -> dict[str, Any]:
    horizons = _normalize_horizons(horizon_hours)
    buckets = _normalize_confidence_buckets(confidence_bucket_lowers)
    if len(horizons) == 1:
        return _validate_single_horizon(
            snapshots=snapshots,
            prices=prices,
            horizon_hours=horizons[0],
            min_confidence=min_confidence,
            symbol_filter=symbol_filter,
            confidence_buckets=buckets,
            min_cohort_samples=min_cohort_samples,
            max_ranked_cohorts=max_ranked_cohorts,
        )

    return {
        "horizon_hours": list(horizons),
        "min_confidence": min_confidence,
        "symbol_filter": symbol_filter or None,
        "confidence_buckets": [_bucket_descriptor(bucket) for bucket in buckets],
        "horizons": {
            str(horizon): _validate_single_horizon(
                snapshots=snapshots,
                prices=prices,
                horizon_hours=horizon,
                min_confidence=min_confidence,
                symbol_filter=symbol_filter,
                confidence_buckets=buckets,
                min_cohort_samples=min_cohort_samples,
                max_ranked_cohorts=max_ranked_cohorts,
            )
            for horizon in horizons
        },
    }


def parse_confidence_bucket_lowers(value: str) -> tuple[float, ...]:
    raw_parts = [part.strip() for part in value.split(",")]
    lowers = [float(part) for part in raw_parts if part]
    return tuple(lowers)


def _validate_single_horizon(
    *,
    snapshots: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    horizon_hours: int,
    min_confidence: float,
    symbol_filter: str,
    confidence_buckets: tuple[tuple[float, float, str], ...],
    min_cohort_samples: int,
    max_ranked_cohorts: int,
) -> dict[str, Any]:
    if horizon_hours <= 0:
        raise ValueError("horizon_hours must be positive")
    if min_cohort_samples <= 0:
        raise ValueError("min_cohort_samples must be positive")
    if max_ranked_cohorts <= 0:
        raise ValueError("max_ranked_cohorts must be positive")

    price_map = {
        (row["symbol"], row["timestamp"]): row["close"]
        for row in prices
    }

    evaluated: list[dict[str, Any]] = []
    sweep_candidates: list[dict[str, Any]] = []
    skipped_neutral = 0
    skipped_confidence = 0
    skipped_missing_prices = 0

    for snapshot in snapshots:
        symbol = str(snapshot["symbol"])
        if symbol_filter and symbol != symbol_filter:
            continue

        direction = str(snapshot["direction"])
        if direction == "neutral":
            skipped_neutral += 1
            continue

        confidence = float(snapshot.get("confidence", 0.0))
        if confidence < min_confidence:
            skipped_confidence += 1
            continue

        start_time = _parse_timestamp(snapshot.get("hour_bucket_utc") or snapshot["timestamp_utc"])
        end_time = start_time + timedelta(hours=horizon_hours)
        start_key = (symbol, start_time)
        end_key = (symbol, end_time)

        if start_key not in price_map or end_key not in price_map:
            skipped_missing_prices += 1
            continue

        start_price = float(price_map[start_key])
        end_price = float(price_map[end_key])
        forward_return = (end_price - start_price) / start_price
        signed_edge = forward_return if direction == "bullish" else -forward_return

        confidence_bucket = _bucket_label(confidence, confidence_buckets)
        sample = {
            "symbol": symbol,
            "direction": direction,
            "confidence": confidence,
            "confidence_bucket": confidence_bucket,
            "timestamp_utc": start_time.isoformat(),
            "forward_return": forward_return,
            "signed_edge": signed_edge,
            "win": signed_edge > 0.0,
        }
        sweep_candidates.append(sample)
        evaluated.append(sample)

    report = {
        "horizon_hours": horizon_hours,
        "min_confidence": min_confidence,
        "symbol_filter": symbol_filter or None,
        "confidence_buckets": [_bucket_descriptor(bucket) for bucket in confidence_buckets],
        "signals_evaluated": len(evaluated),
        "signals_skipped_neutral": skipped_neutral,
        "signals_skipped_confidence": skipped_confidence,
        "signals_skipped_missing_prices": skipped_missing_prices,
        "summary": _aggregate_metrics(evaluated),
        "by_symbol": _aggregate_by_symbol(evaluated),
        "by_direction": _aggregate_by_direction(evaluated),
        "by_confidence_bucket": _aggregate_by_confidence_bucket(evaluated, confidence_buckets),
        "confidence_sweep": _build_confidence_sweep(
            sweep_candidates=sweep_candidates,
            min_confidence=min_confidence,
            confidence_buckets=confidence_buckets,
        ),
        "ranked_cohorts": _rank_cohorts(
            samples=evaluated,
            min_cohort_samples=min_cohort_samples,
            max_ranked_cohorts=max_ranked_cohorts,
        ),
    }
    return report


def _load_snapshots(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _load_prices(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, Any]] = []

        for row in reader:
            timestamp_raw = row.get("timestamp", "")
            symbol = row.get("symbol", "")
            close_raw = row.get("close", "")
            if not timestamp_raw or not symbol or not close_raw:
                continue
            rows.append(
                {
                    "timestamp": _parse_timestamp(timestamp_raw),
                    "symbol": symbol,
                    "close": float(close_raw),
                }
            )
        return rows


def _aggregate_metrics(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {
            "sample_count": 0,
            "win_rate": None,
            "avg_forward_return": None,
            "avg_signed_edge": None,
            "avg_confidence": None,
            "bullish_count": 0,
            "bearish_count": 0,
        }

    wins = sum(1 for sample in samples if sample["win"])
    bullish_count = sum(1 for sample in samples if sample["direction"] == "bullish")
    bearish_count = sum(1 for sample in samples if sample["direction"] == "bearish")
    avg_forward_return = sum(sample["forward_return"] for sample in samples) / len(samples)
    avg_signed_edge = sum(sample["signed_edge"] for sample in samples) / len(samples)
    avg_confidence = sum(sample["confidence"] for sample in samples) / len(samples)

    return {
        "sample_count": len(samples),
        "win_rate": round(wins / len(samples), 6),
        "avg_forward_return": round(avg_forward_return, 6),
        "avg_signed_edge": round(avg_signed_edge, 6),
        "avg_confidence": round(avg_confidence, 6),
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
    }


def _aggregate_by_symbol(samples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        grouped.setdefault(sample["symbol"], []).append(sample)

    return {
        symbol: _aggregate_metrics(items)
        for symbol, items in sorted(grouped.items())
    }


def _aggregate_by_direction(samples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    directions = ("bullish", "bearish")
    return {
        direction: _aggregate_metrics(
            [sample for sample in samples if sample["direction"] == direction]
        )
        for direction in directions
    }


def _aggregate_by_confidence_bucket(
    samples: list[dict[str, Any]],
    confidence_buckets: tuple[tuple[float, float, str], ...],
) -> dict[str, dict[str, Any]]:
    return {
        bucket[2]: _aggregate_metrics(
            [sample for sample in samples if sample["confidence_bucket"] == bucket[2]]
        )
        for bucket in confidence_buckets
    }


def _build_confidence_sweep(
    *,
    sweep_candidates: list[dict[str, Any]],
    min_confidence: float,
    confidence_buckets: tuple[tuple[float, float, str], ...],
) -> list[dict[str, Any]]:
    cutoffs = [
        bucket[0]
        for bucket in confidence_buckets
        if bucket[0] >= min_confidence
    ]

    sweep_rows: list[dict[str, Any]] = []
    for cutoff in cutoffs:
        filtered = [
            sample
            for sample in sweep_candidates
            if sample["confidence"] >= cutoff
        ]
        metrics = _aggregate_metrics(filtered)
        sweep_rows.append(
            {
                "min_confidence": round(cutoff, 6),
                **metrics,
            }
        )
    return sweep_rows


def _rank_cohorts(
    *,
    samples: list[dict[str, Any]],
    min_cohort_samples: int,
    max_ranked_cohorts: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for sample in samples:
        key = (
            sample["symbol"],
            sample["direction"],
            sample["confidence_bucket"],
        )
        grouped.setdefault(key, []).append(sample)

    ranked: list[dict[str, Any]] = []
    for (symbol, direction, confidence_bucket), cohort_samples in grouped.items():
        metrics = _aggregate_metrics(cohort_samples)
        if metrics["sample_count"] < min_cohort_samples:
            continue
        ranked.append(
            {
                "symbol": symbol,
                "direction": direction,
                "confidence_bucket": confidence_bucket,
                "cohort": f"{symbol} | {direction} | {confidence_bucket}",
                **metrics,
            }
        )

    ranked.sort(
        key=lambda row: (
            row["avg_signed_edge"] if row["avg_signed_edge"] is not None else float("-inf"),
            row["win_rate"] if row["win_rate"] is not None else float("-inf"),
            row["sample_count"],
            row["avg_confidence"] if row["avg_confidence"] is not None else float("-inf"),
        ),
        reverse=True,
    )

    limited = ranked[:max_ranked_cohorts]
    for index, row in enumerate(limited, start=1):
        row["rank"] = index
    return limited


def _normalize_horizons(horizon_hours: int | list[int] | tuple[int, ...]) -> tuple[int, ...]:
    if isinstance(horizon_hours, int):
        horizons = [horizon_hours]
    else:
        horizons = list(horizon_hours)
    if not horizons:
        horizons = [1]

    normalized = sorted(set(int(item) for item in horizons))
    if any(item <= 0 for item in normalized):
        raise ValueError("horizon_hours must be positive")
    return tuple(normalized)


def _normalize_confidence_buckets(
    confidence_bucket_lowers: tuple[float, ...] | list[float] | None,
) -> tuple[tuple[float, float, str], ...]:
    lowers = list(confidence_bucket_lowers or DEFAULT_CONFIDENCE_BUCKET_LOWERS)
    if not lowers:
        lowers = list(DEFAULT_CONFIDENCE_BUCKET_LOWERS)
    lowers = [float(item) for item in lowers]
    if lowers[0] > 0.0:
        lowers.insert(0, 0.0)

    for index, lower in enumerate(lowers):
        if lower < 0.0 or lower > 1.0:
            raise ValueError("confidence bucket lower bounds must be between 0.0 and 1.0")
        if index > 0 and lower <= lowers[index - 1]:
            raise ValueError("confidence bucket lower bounds must be strictly increasing")

    buckets: list[tuple[float, float, str]] = []
    for index, lower in enumerate(lowers):
        upper = lowers[index + 1] if index + 1 < len(lowers) else 1.000001
        if index + 1 < len(lowers):
            label = f"{lower:.2f}-<{upper:.2f}"
        else:
            label = f"{lower:.2f}-1.00"
        buckets.append((lower, upper, label))
    return tuple(buckets)


def _bucket_label(
    confidence: float,
    confidence_buckets: tuple[tuple[float, float, str], ...],
) -> str:
    for index, bucket in enumerate(confidence_buckets):
        lower, upper, label = bucket
        if index == len(confidence_buckets) - 1:
            if lower <= confidence <= upper:
                return label
        elif lower <= confidence < upper:
            return label
    return confidence_buckets[-1][2]


def _bucket_descriptor(bucket: tuple[float, float, str]) -> dict[str, Any]:
    lower, upper, label = bucket
    inclusive_upper = upper > 1.0
    upper_bound = 1.0 if inclusive_upper else upper
    return {
        "label": label,
        "lower_bound": round(lower, 6),
        "upper_bound": round(upper_bound, 6),
        "inclusive_upper": inclusive_upper,
    }


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
