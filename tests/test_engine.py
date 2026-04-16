from __future__ import annotations

import unittest
from datetime import UTC, datetime

from fundamental_bias_alerts.engine import score_driver, score_instrument
from fundamental_bias_alerts.models import (
    DriverSpec,
    EntitySpec,
    InstrumentSpec,
    Observation,
    SeriesSpec,
)


class EngineTests(unittest.TestCase):
    def test_level_driver_rewards_higher_values(self) -> None:
        spec = DriverSpec(
            key="policy_rate",
            label="Policy rate",
            weight=0.4,
            mode="level",
            bullish_when="higher",
            neutral_value=2.0,
            scale=2.0,
            stale_after_hours=24 * 180,
            series=SeriesSpec(series_id="DFF"),
        )

        result = score_driver(
            spec,
            [
                Observation(date="2026-04-15", value=4.0),
                Observation(date="2026-04-14", value=4.0),
            ],
            as_of=datetime(2026, 4, 16, 12, 0, tzinfo=UTC),
        )

        self.assertAlmostEqual(result.score, 0.4)
        self.assertEqual(result.direction, "bullish")
        self.assertEqual(result.data_state, "ok")

    def test_delta_driver_inverts_for_lower_is_bullish(self) -> None:
        spec = DriverSpec(
            key="stress",
            label="Stress",
            weight=0.2,
            mode="delta",
            bullish_when="lower",
            scale=1.0,
            stale_after_hours=24 * 30,
            series=SeriesSpec(series_id="STLFSI4"),
        )

        result = score_driver(
            spec,
            [
                Observation(date="2026-04-15", value=0.5),
                Observation(date="2026-04-08", value=1.2),
            ],
            as_of=datetime(2026, 4, 16, 12, 0, tzinfo=UTC),
        )

        self.assertGreater(result.score, 0.0)
        self.assertEqual(result.direction, "bullish")

    def test_stale_data_reduces_confidence_and_score(self) -> None:
        spec = DriverSpec(
            key="growth",
            label="Growth",
            weight=0.25,
            mode="pct_change",
            bullish_when="higher",
            scale=0.01,
            stale_after_hours=24,
            series=SeriesSpec(series_id="INDPRO"),
        )

        result = score_driver(
            spec,
            [
                Observation(date="2026-04-10", value=101.0),
                Observation(date="2026-03-10", value=100.0),
            ],
            as_of=datetime(2026, 4, 16, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.data_state, "stale")

    def test_pair_score_is_base_minus_quote(self) -> None:
        usd = EntitySpec(
            key="USD",
            label="US Dollar",
            drivers=(
                DriverSpec(
                    key="policy_rate",
                    label="Policy rate",
                    weight=0.4,
                    mode="level",
                    bullish_when="higher",
                    neutral_value=2.0,
                    scale=2.0,
                    stale_after_hours=24 * 180,
                    series=SeriesSpec(series_id="DFF"),
                ),
            ),
        )
        eur = EntitySpec(
            key="EUR",
            label="Euro",
            drivers=(
                DriverSpec(
                    key="policy_rate",
                    label="Policy rate",
                    weight=0.4,
                    mode="level",
                    bullish_when="higher",
                    neutral_value=2.0,
                    scale=2.0,
                    stale_after_hours=24 * 180,
                    series=SeriesSpec(series_id="ECBMRRFR"),
                ),
            ),
        )
        instrument = InstrumentSpec(
            symbol="EURUSD",
            base_entity="EUR",
            quote_entity="USD",
            threshold=0.3,
        )

        result = score_instrument(
            instrument=instrument,
            entities={"EUR": eur, "USD": usd},
            series_observations={
                "ECBMRRFR": [
                    Observation(date="2026-04-15", value=2.0),
                    Observation(date="2026-04-14", value=2.0),
                ],
                "DFF": [
                    Observation(date="2026-04-15", value=4.0),
                    Observation(date="2026-04-14", value=4.0),
                ],
            },
            as_of=datetime(2026, 4, 16, 12, 0, tzinfo=UTC),
        )

        self.assertLess(result.score, 0.0)
        self.assertEqual(result.direction, "bearish")
