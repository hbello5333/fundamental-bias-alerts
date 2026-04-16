from __future__ import annotations

import unittest
from datetime import UTC, datetime

from fundamental_bias_alerts.validation import parse_confidence_bucket_lowers, validate_snapshots


class ValidationTests(unittest.TestCase):
    def test_validate_snapshots_scores_directional_edge(self) -> None:
        snapshots = [
            {
                "symbol": "EURUSD",
                "direction": "bullish",
                "confidence": 0.8,
                "hour_bucket_utc": "2026-04-16T00:00:00+00:00",
            },
            {
                "symbol": "EURUSD",
                "direction": "bearish",
                "confidence": 0.8,
                "hour_bucket_utc": "2026-04-16T01:00:00+00:00",
            },
            {
                "symbol": "EURUSD",
                "direction": "neutral",
                "confidence": 0.9,
                "hour_bucket_utc": "2026-04-16T02:00:00+00:00",
            },
        ]
        prices = [
            {
                "symbol": "EURUSD",
                "timestamp": datetime(2026, 4, 16, 0, 0, tzinfo=UTC),
                "close": 100.0,
            },
            {
                "symbol": "EURUSD",
                "timestamp": datetime(2026, 4, 16, 1, 0, tzinfo=UTC),
                "close": 101.0,
            },
            {
                "symbol": "EURUSD",
                "timestamp": datetime(2026, 4, 16, 2, 0, tzinfo=UTC),
                "close": 99.0,
            },
            {
                "symbol": "EURUSD",
                "timestamp": datetime(2026, 4, 16, 3, 0, tzinfo=UTC),
                "close": 100.0,
            },
        ]

        report = validate_snapshots(
            snapshots=snapshots,
            prices=prices,
            horizon_hours=1,
            min_confidence=0.0,
        )

        self.assertEqual(report["signals_evaluated"], 2)
        self.assertEqual(report["signals_skipped_neutral"], 1)
        self.assertEqual(report["summary"]["win_rate"], 1.0)
        self.assertGreater(report["summary"]["avg_signed_edge"], 0.0)
        self.assertEqual(report["summary"]["sample_count"], 2)
        self.assertEqual(report["by_symbol"]["EURUSD"]["bullish_count"], 1)
        self.assertEqual(report["by_symbol"]["EURUSD"]["bearish_count"], 1)
        self.assertEqual(report["by_direction"]["bullish"]["sample_count"], 1)
        self.assertEqual(report["by_direction"]["bearish"]["sample_count"], 1)
        self.assertEqual(report["by_confidence_bucket"]["0.75-<0.90"]["sample_count"], 2)
        self.assertEqual(report["confidence_sweep"][0]["min_confidence"], 0.0)
        self.assertEqual(report["confidence_sweep"][0]["sample_count"], 2)
        self.assertEqual(report["ranked_cohorts"][0]["symbol"], "EURUSD")
        self.assertEqual(report["ranked_cohorts"][0]["direction"], "bearish")
        self.assertEqual(report["ranked_cohorts"][0]["confidence_bucket"], "0.75-<0.90")

    def test_validate_snapshots_supports_multiple_horizons(self) -> None:
        snapshots = [
            {
                "symbol": "BTCUSD",
                "direction": "bullish",
                "confidence": 0.95,
                "hour_bucket_utc": "2026-04-16T00:00:00+00:00",
            },
            {
                "symbol": "BTCUSD",
                "direction": "bearish",
                "confidence": 0.65,
                "hour_bucket_utc": "2026-04-16T01:00:00+00:00",
            },
        ]
        prices = [
            {
                "symbol": "BTCUSD",
                "timestamp": datetime(2026, 4, 16, 0, 0, tzinfo=UTC),
                "close": 100.0,
            },
            {
                "symbol": "BTCUSD",
                "timestamp": datetime(2026, 4, 16, 1, 0, tzinfo=UTC),
                "close": 102.0,
            },
            {
                "symbol": "BTCUSD",
                "timestamp": datetime(2026, 4, 16, 2, 0, tzinfo=UTC),
                "close": 101.0,
            },
            {
                "symbol": "BTCUSD",
                "timestamp": datetime(2026, 4, 16, 3, 0, tzinfo=UTC),
                "close": 99.0,
            },
        ]

        report = validate_snapshots(
            snapshots=snapshots,
            prices=prices,
            horizon_hours=[1, 2],
            min_confidence=0.0,
            confidence_bucket_lowers=parse_confidence_bucket_lowers("0.0,0.7,0.9"),
        )

        self.assertEqual(report["horizon_hours"], [1, 2])
        self.assertIn("1", report["horizons"])
        self.assertIn("2", report["horizons"])
        self.assertEqual(report["horizons"]["1"]["signals_evaluated"], 2)
        self.assertEqual(report["horizons"]["2"]["signals_evaluated"], 2)
        self.assertEqual(report["horizons"]["1"]["by_confidence_bucket"]["0.90-1.00"]["sample_count"], 1)
        self.assertEqual(report["horizons"]["1"]["by_confidence_bucket"]["0.70-<0.90"]["sample_count"], 0)
        self.assertEqual(report["horizons"]["1"]["by_confidence_bucket"]["0.00-<0.70"]["sample_count"], 1)
        self.assertEqual(report["horizons"]["1"]["confidence_sweep"][0]["min_confidence"], 0.0)
        self.assertEqual(report["horizons"]["1"]["ranked_cohorts"][0]["symbol"], "BTCUSD")
        self.assertEqual(report["horizons"]["1"]["ranked_cohorts"][0]["direction"], "bullish")

    def test_ranked_cohorts_respects_min_sample_filter(self) -> None:
        snapshots = [
            {
                "symbol": "EURUSD",
                "direction": "bullish",
                "confidence": 0.82,
                "hour_bucket_utc": "2026-04-16T00:00:00+00:00",
            },
            {
                "symbol": "EURUSD",
                "direction": "bullish",
                "confidence": 0.84,
                "hour_bucket_utc": "2026-04-16T01:00:00+00:00",
            },
            {
                "symbol": "BTCUSD",
                "direction": "bearish",
                "confidence": 0.93,
                "hour_bucket_utc": "2026-04-16T00:00:00+00:00",
            },
        ]
        prices = [
            {
                "symbol": "EURUSD",
                "timestamp": datetime(2026, 4, 16, 0, 0, tzinfo=UTC),
                "close": 100.0,
            },
            {
                "symbol": "EURUSD",
                "timestamp": datetime(2026, 4, 16, 1, 0, tzinfo=UTC),
                "close": 101.0,
            },
            {
                "symbol": "EURUSD",
                "timestamp": datetime(2026, 4, 16, 2, 0, tzinfo=UTC),
                "close": 102.0,
            },
            {
                "symbol": "BTCUSD",
                "timestamp": datetime(2026, 4, 16, 0, 0, tzinfo=UTC),
                "close": 100.0,
            },
            {
                "symbol": "BTCUSD",
                "timestamp": datetime(2026, 4, 16, 1, 0, tzinfo=UTC),
                "close": 99.0,
            },
        ]

        report = validate_snapshots(
            snapshots=snapshots,
            prices=prices,
            horizon_hours=1,
            min_confidence=0.0,
            min_cohort_samples=2,
        )

        self.assertEqual(len(report["ranked_cohorts"]), 1)
        self.assertEqual(report["ranked_cohorts"][0]["symbol"], "EURUSD")
        self.assertEqual(report["ranked_cohorts"][0]["sample_count"], 2)

    def test_parse_confidence_bucket_lowers_parses_csv_text(self) -> None:
        parsed = parse_confidence_bucket_lowers("0.0, 0.6, 0.8,0.95")
        self.assertEqual(parsed, (0.0, 0.6, 0.8, 0.95))
