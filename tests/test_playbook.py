from __future__ import annotations

import unittest
from datetime import UTC, date, datetime

from fundamental_bias_alerts.models import (
    AlertingConfig,
    DayTradingConfig,
    DriverResult,
    EntityResult,
    EntitySpec,
    EventPolicySpec,
    InstrumentResult,
    InstrumentSpec,
    ReleaseCalendar,
    ReleaseEvent,
    ResearchConfig,
    SessionSpec,
    StrategyConfig,
)
from fundamental_bias_alerts.playbook import (
    format_day_trade_playbook_brief,
    format_morning_brief,
    format_day_trade_playbook_payload,
    generate_day_trade_playbook,
)


class DayTradePlaybookTests(unittest.TestCase):
    def test_playbook_uses_release_sessions_and_lockouts(self) -> None:
        config = self._strategy_config()
        results = [
            InstrumentResult(
                symbol="EURUSD",
                score=0.55,
                confidence=0.82,
                direction="bullish",
                threshold=0.3,
                reasons=("Test reason",),
                base_result=EntityResult(
                    key="EUR",
                    label="Euro",
                    score=0.4,
                    confidence=0.9,
                    drivers=(
                        DriverResult(
                            key="policy_rate",
                            label="ECB policy rate",
                            score=0.4,
                            confidence=1.0,
                            direction="bullish",
                            data_state="ok",
                            reason="ECB policy rate strong",
                            observation_date=date(2026, 4, 29),
                        ),
                    ),
                ),
                quote_result=EntityResult(
                    key="USD",
                    label="US Dollar",
                    score=-0.15,
                    confidence=0.8,
                    drivers=(
                        DriverResult(
                            key="cpi",
                            label="US CPI",
                            score=-0.15,
                            confidence=1.0,
                            direction="bearish",
                            data_state="ok",
                            reason="US CPI soft",
                            observation_date=date(2026, 4, 29),
                        ),
                    ),
                ),
            )
        ]
        calendar = ReleaseCalendar(
            events=(
                ReleaseEvent(
                    event_id="usd-cpi-2026-04-30",
                    label="US CPI",
                    currency="USD",
                    impact="high",
                    timestamp="2026-04-30T08:30:00-04:00",
                    source_url="https://www.bls.gov/schedule/news_release/cpi.htm",
                ),
            )
        )

        playbook = generate_day_trade_playbook(
            config=config,
            calendar=calendar,
            results=results,
            trade_date=date(2026, 4, 30),
            as_of=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
        )

        item = playbook.items[0]
        self.assertEqual(item.symbol, "EURUSD")
        self.assertEqual(item.allowed_direction, "long_only")
        self.assertEqual(item.trade_state, "ready")
        self.assertEqual([session.key for session in item.valid_sessions], ["new_york"])
        self.assertEqual(len(item.no_trade_windows), 1)
        self.assertEqual(item.no_trade_windows[0].label, "US CPI")
        self.assertEqual(item.no_trade_windows[0].start_utc.isoformat(), "2026-04-30T12:20:00+00:00")
        self.assertEqual(item.no_trade_windows[0].end_utc.isoformat(), "2026-04-30T12:50:00+00:00")
        self.assertEqual(item.bias_reasons, ("Test reason",))

    def test_playbook_blocks_low_confidence_and_stale_bias(self) -> None:
        config = self._strategy_config()
        results = [
            InstrumentResult(
                symbol="AUDUSD",
                score=0.4,
                confidence=0.6,
                direction="bullish",
                threshold=0.3,
                reasons=("Test reason",),
                base_result=EntityResult(
                    key="AUD",
                    label="Australian Dollar",
                    score=0.5,
                    confidence=0.5,
                    drivers=(
                        DriverResult(
                            key="inflation",
                            label="Australia CPI",
                            score=0.0,
                            confidence=0.0,
                            direction="neutral",
                            data_state="stale",
                            reason="Australia CPI stale",
                            observation_date=date(2025, 1, 1),
                        ),
                        DriverResult(
                            key="growth",
                            label="Australia growth",
                            score=0.0,
                            confidence=0.0,
                            direction="neutral",
                            data_state="stale",
                            reason="Australia growth stale",
                            observation_date=date(2025, 1, 1),
                        ),
                    ),
                ),
                quote_result=EntityResult(
                    key="USD",
                    label="US Dollar",
                    score=0.1,
                    confidence=1.0,
                    drivers=(
                        DriverResult(
                            key="policy_rate",
                            label="Fed policy rate",
                            score=0.1,
                            confidence=1.0,
                            direction="bullish",
                            data_state="ok",
                            reason="Fed policy steady",
                            observation_date=date(2026, 4, 29),
                        ),
                    ),
                ),
            )
        ]

        playbook = generate_day_trade_playbook(
            config=config,
            calendar=ReleaseCalendar(events=()),
            results=results,
            trade_date=date(2026, 4, 30),
            as_of=datetime(2026, 4, 30, 1, 0, tzinfo=UTC),
        )

        item = playbook.items[0]
        self.assertEqual(item.symbol, "AUDUSD")
        self.assertEqual(item.allowed_direction, "no_trade")
        self.assertEqual(item.trade_state, "no_trade")
        self.assertEqual([session.key for session in item.valid_sessions], ["asia", "london", "new_york"])
        self.assertTrue(any("confidence" in note.lower() for note in item.notes))
        self.assertTrue(any("stale" in note.lower() for note in item.notes))

    def test_payload_and_brief_include_action_and_reasons(self) -> None:
        config = self._strategy_config()
        results = [
            InstrumentResult(
                symbol="EURUSD",
                score=0.55,
                confidence=0.82,
                direction="bullish",
                threshold=0.3,
                reasons=(
                    "ECB policy rate strong",
                    "US CPI soft",
                ),
                base_result=EntityResult(
                    key="EUR",
                    label="Euro",
                    score=0.4,
                    confidence=0.9,
                    drivers=(),
                ),
                quote_result=EntityResult(
                    key="USD",
                    label="US Dollar",
                    score=-0.15,
                    confidence=0.8,
                    drivers=(),
                ),
            )
        ]

        playbook = generate_day_trade_playbook(
            config=config,
            calendar=ReleaseCalendar(events=()),
            results=results,
            trade_date=date(2026, 4, 30),
            as_of=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
        )

        payload = format_day_trade_playbook_payload(playbook)
        self.assertEqual(payload["top_setups"][0]["symbol"], "EURUSD")
        item_payload = payload["instruments"][0]
        self.assertEqual(item_payload["action"], "buy")
        self.assertEqual(item_payload["bias_reasons"], ["ECB policy rate strong", "US CPI soft"])
        self.assertEqual(item_payload["tradable_rank"], 1)
        self.assertTrue(item_payload["is_top_setup"])
        self.assertEqual(item_payload["execution_plan"]["status"], "needs_price")

        brief = format_day_trade_playbook_brief(playbook)
        self.assertIn("Top setups: #1 EURUSD BUY ONLY", brief)
        self.assertIn("EURUSD | TOP 1 BUY ONLY | READY | confidence 0.82", brief)
        self.assertIn("Why: ECB policy rate strong; US CPI soft", brief)
        self.assertIn("Sessions: London", brief)
        self.assertIn("Lockouts: None", brief)
        self.assertIn("Plan: needs price", brief)

    def test_morning_brief_highlights_top_setup_ticket(self) -> None:
        config = self._strategy_config()
        results = [
            InstrumentResult(
                symbol="EURUSD",
                score=0.55,
                confidence=0.82,
                direction="bullish",
                threshold=0.3,
                reasons=("ECB policy rate strong", "US CPI soft"),
                base_result=EntityResult(key="EUR", label="Euro", score=0.4, confidence=0.9, drivers=()),
                quote_result=EntityResult(key="USD", label="US Dollar", score=-0.15, confidence=0.8, drivers=()),
            ),
            InstrumentResult(
                symbol="AUDUSD",
                score=0.2,
                confidence=0.6,
                direction="neutral",
                threshold=0.3,
                reasons=("AUD mixed",),
                base_result=EntityResult(key="AUD", label="Australian Dollar", score=0.2, confidence=0.7, drivers=()),
                quote_result=EntityResult(key="USD", label="US Dollar", score=0.0, confidence=0.8, drivers=()),
            ),
        ]

        playbook = generate_day_trade_playbook(
            config=config,
            calendar=ReleaseCalendar(events=()),
            results=results,
            trade_date=date(2026, 4, 30),
            as_of=datetime(2026, 4, 30, 8, 0, tzinfo=UTC),
            reference_prices={"EURUSD": 1.1},
            account_size=10000.0,
        )

        brief = format_morning_brief(playbook)
        self.assertIn("Morning Brief | generated", brief)
        self.assertIn("Market posture: 1 tradable setup, 1 stand aside.", brief)
        self.assertIn("Top setups:", brief)
        self.assertIn("#1 EURUSD BUY ONLY | confidence 0.82", brief)
        self.assertIn("Ticket: ready_now | entry 1.100000 | stop 1.096700 | target 1.106600", brief)
        self.assertIn("Stand aside: AUDUSD", brief)

    def test_morning_brief_handles_no_tradable_setups(self) -> None:
        config = self._strategy_config()
        results = [
            InstrumentResult(
                symbol="AUDUSD",
                score=0.2,
                confidence=0.6,
                direction="neutral",
                threshold=0.3,
                reasons=("AUD mixed",),
                base_result=EntityResult(key="AUD", label="Australian Dollar", score=0.2, confidence=0.7, drivers=()),
                quote_result=EntityResult(key="USD", label="US Dollar", score=0.0, confidence=0.8, drivers=()),
            ),
            InstrumentResult(
                symbol="EURUSD",
                score=0.15,
                confidence=0.65,
                direction="neutral",
                threshold=0.3,
                reasons=("EUR mixed",),
                base_result=EntityResult(key="EUR", label="Euro", score=0.15, confidence=0.7, drivers=()),
                quote_result=EntityResult(key="USD", label="US Dollar", score=0.0, confidence=0.8, drivers=()),
            ),
        ]

        playbook = generate_day_trade_playbook(
            config=config,
            calendar=ReleaseCalendar(events=()),
            results=results,
            trade_date=date(2026, 4, 30),
            as_of=datetime(2026, 4, 30, 5, 0, tzinfo=UTC),
        )

        brief = format_morning_brief(playbook)
        self.assertIn("Top setups: None", brief)
        self.assertIn("Highest-conviction stand aside:", brief)
        self.assertIn("Blocked by:", brief)
        self.assertIn("Stand aside:", brief)

    def test_playbook_ranks_ready_setups_and_keeps_only_top_two_flagged(self) -> None:
        config = self._strategy_config()
        results = [
            InstrumentResult(
                symbol="EURUSD",
                score=0.60,
                confidence=0.86,
                direction="bullish",
                threshold=0.3,
                reasons=("ECB strong",),
                base_result=EntityResult(key="EUR", label="Euro", score=0.4, confidence=0.9, drivers=()),
                quote_result=EntityResult(key="USD", label="US Dollar", score=-0.2, confidence=0.8, drivers=()),
            ),
            InstrumentResult(
                symbol="GBPUSD",
                score=0.45,
                confidence=0.92,
                direction="bullish",
                threshold=0.3,
                reasons=("BoE strong",),
                base_result=EntityResult(
                    key="GBP",
                    label="British Pound",
                    score=0.3,
                    confidence=0.9,
                    drivers=(),
                ),
                quote_result=EntityResult(key="USD", label="US Dollar", score=-0.15, confidence=0.8, drivers=()),
            ),
            InstrumentResult(
                symbol="AUDUSD",
                score=0.52,
                confidence=0.75,
                direction="bullish",
                threshold=0.3,
                reasons=("AUD strong",),
                base_result=EntityResult(
                    key="AUD",
                    label="Australian Dollar",
                    score=0.35,
                    confidence=0.9,
                    drivers=(),
                ),
                quote_result=EntityResult(key="USD", label="US Dollar", score=-0.17, confidence=0.8, drivers=()),
            ),
        ]

        playbook = generate_day_trade_playbook(
            config=config,
            calendar=ReleaseCalendar(events=()),
            results=results,
            trade_date=date(2026, 4, 30),
            as_of=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
        )

        ranked = {item.symbol: item for item in playbook.items}
        self.assertEqual(ranked["GBPUSD"].tradable_rank, 1)
        self.assertTrue(ranked["GBPUSD"].is_top_setup)
        self.assertEqual(ranked["EURUSD"].tradable_rank, 2)
        self.assertTrue(ranked["EURUSD"].is_top_setup)
        self.assertEqual(ranked["AUDUSD"].tradable_rank, 3)
        self.assertFalse(ranked["AUDUSD"].is_top_setup)

    def test_execution_plan_computes_exact_levels_and_position_size(self) -> None:
        config = self._strategy_config()
        results = [
            InstrumentResult(
                symbol="EURUSD",
                score=0.55,
                confidence=0.82,
                direction="bullish",
                threshold=0.3,
                reasons=("ECB policy rate strong", "US CPI soft"),
                base_result=EntityResult(key="EUR", label="Euro", score=0.4, confidence=0.9, drivers=()),
                quote_result=EntityResult(key="USD", label="US Dollar", score=-0.15, confidence=0.8, drivers=()),
            )
        ]

        playbook = generate_day_trade_playbook(
            config=config,
            calendar=ReleaseCalendar(events=()),
            results=results,
            trade_date=date(2026, 4, 30),
            as_of=datetime(2026, 4, 30, 8, 0, tzinfo=UTC),
            reference_prices={"EURUSD": 1.1},
            account_size=10000.0,
        )

        plan = playbook.items[0].execution_plan
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.status, "ready_now")
        self.assertAlmostEqual(plan.entry_price or 0.0, 1.1, places=6)
        self.assertAlmostEqual(plan.stop_price or 0.0, 1.0967, places=6)
        self.assertAlmostEqual(plan.target_price or 0.0, 1.1066, places=6)
        self.assertAlmostEqual(plan.risk_amount or 0.0, 25.0, places=6)
        self.assertAlmostEqual(plan.position_size_units or 0.0, 7575.757576, places=5)
        self.assertAlmostEqual(plan.notional_value_usd or 0.0, 8333.333333, places=5)

    def test_execution_plan_for_next_session_warns_to_refresh_reference_price(self) -> None:
        config = self._strategy_config()
        results = [
            InstrumentResult(
                symbol="EURUSD",
                score=0.55,
                confidence=0.82,
                direction="bullish",
                threshold=0.3,
                reasons=("ECB policy rate strong",),
                base_result=EntityResult(key="EUR", label="Euro", score=0.4, confidence=0.9, drivers=()),
                quote_result=EntityResult(key="USD", label="US Dollar", score=-0.15, confidence=0.8, drivers=()),
            )
        ]

        playbook = generate_day_trade_playbook(
            config=config,
            calendar=ReleaseCalendar(events=()),
            results=results,
            trade_date=date(2026, 4, 30),
            as_of=datetime(2026, 4, 30, 5, 0, tzinfo=UTC),
            reference_prices={"EURUSD": 1.1},
        )

        plan = playbook.items[0].execution_plan
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.status, "waiting_for_session")
        self.assertTrue(any("Refresh the reference price" in note for note in plan.notes))

    def _strategy_config(self) -> StrategyConfig:
        return StrategyConfig(
            metadata={"name": "test", "version": "0.5.0"},
            alerting=AlertingConfig(
                state_path=".state/test.json",
                emit_on_first_run=True,
                min_score_change=0.35,
            ),
            research=ResearchConfig(snapshot_path=None, journal_path=None),
            day_trading=DayTradingConfig(
                min_confidence=0.7,
                max_stale_drivers=1,
                max_ranked_setups=2,
                risk_per_trade_pct=0.25,
                target_r_multiple=2.0,
                default_stop_loss_pct=0.0035,
                stop_loss_pct_by_symbol={"EURUSD": 0.003, "GBPUSD": 0.0035, "AUDUSD": 0.0035},
                sessions=(
                    SessionSpec(
                        key="asia",
                        label="Asia",
                        timezone="Asia/Tokyo",
                        start_time="09:00",
                        end_time="12:00",
                    ),
                    SessionSpec(
                        key="london",
                        label="London",
                        timezone="Europe/London",
                        start_time="07:00",
                        end_time="11:00",
                    ),
                    SessionSpec(
                        key="new_york",
                        label="New York",
                        timezone="America/New_York",
                        start_time="08:00",
                        end_time="11:30",
                    ),
                ),
                instrument_sessions={
                    "EURUSD": ("london", "new_york"),
                    "GBPUSD": ("london", "new_york"),
                    "AUDUSD": ("asia", "london", "new_york"),
                },
                event_policies=(
                    EventPolicySpec(
                        currency="USD",
                        impact="high",
                        block_before_minutes=10,
                        block_after_minutes=20,
                        preferred_sessions=("new_york",),
                    ),
                    EventPolicySpec(
                        currency="AUD",
                        impact="high",
                        block_before_minutes=10,
                        block_after_minutes=20,
                        preferred_sessions=("asia",),
                    ),
                ),
            ),
            entities={
                "EUR": EntitySpec(key="EUR", label="Euro", drivers=()),
                "GBP": EntitySpec(key="GBP", label="British Pound", drivers=()),
                "USD": EntitySpec(key="USD", label="US Dollar", drivers=()),
                "AUD": EntitySpec(key="AUD", label="Australian Dollar", drivers=()),
            },
            instruments=(
                InstrumentSpec(symbol="EURUSD", base_entity="EUR", quote_entity="USD", threshold=0.3),
                InstrumentSpec(symbol="GBPUSD", base_entity="GBP", quote_entity="USD", threshold=0.3),
                InstrumentSpec(symbol="AUDUSD", base_entity="AUD", quote_entity="USD", threshold=0.3),
            ),
        )
