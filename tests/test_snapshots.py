from __future__ import annotations

import unittest
from datetime import UTC, date, datetime

from fundamental_bias_alerts.models import DriverResult, EntityResult, InstrumentResult
from fundamental_bias_alerts.snapshots import format_snapshot_record


class SnapshotFormattingTests(unittest.TestCase):
    def test_snapshot_includes_driver_state_counts(self) -> None:
        result = InstrumentResult(
            symbol="EURUSD",
            score=0.42,
            confidence=0.75,
            direction="bullish",
            threshold=0.3,
            reasons=("ECB policy rate: latest=3.0000, neutral=2.0000",),
            base_result=EntityResult(
                key="EUR",
                label="Euro",
                score=0.42,
                confidence=1.0,
                drivers=(
                    DriverResult(
                        key="policy_rate",
                        label="ECB policy rate",
                        score=0.4,
                        confidence=1.0,
                        direction="bullish",
                        data_state="ok",
                        reason="ECB policy rate: latest=3.0000, neutral=2.0000",
                        latest_value=3.0,
                        previous_value=3.0,
                        observation_date=date(2026, 4, 15),
                        age_hours=12.0,
                    ),
                ),
            ),
            quote_result=EntityResult(
                key="USD",
                label="US Dollar",
                score=0.0,
                confidence=0.5,
                drivers=(
                    DriverResult(
                        key="growth",
                        label="US industrial production momentum",
                        score=0.0,
                        confidence=0.0,
                        direction="neutral",
                        data_state="stale",
                        reason="US industrial production momentum: stale data",
                        latest_value=100.0,
                        previous_value=99.0,
                        observation_date=date(2026, 3, 1),
                        age_hours=1000.0,
                    ),
                ),
            ),
        )

        payload = format_snapshot_record(
            as_of=datetime(2026, 4, 16, 12, 34, tzinfo=UTC),
            result=result,
        )

        self.assertEqual(payload["symbol"], "EURUSD")
        self.assertEqual(payload["data_quality"]["ok_drivers"], 1)
        self.assertEqual(payload["data_quality"]["stale_drivers"], 1)
        self.assertEqual(payload["hour_bucket_utc"], "2026-04-16T12:00:00+00:00")
        self.assertEqual(
            payload["quote"]["drivers"][0]["observation_date"],
            "2026-03-01",
        )
