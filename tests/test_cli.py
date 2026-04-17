from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fundamental_bias_alerts.alerts import TelegramAlertSink
from fundamental_bias_alerts.cli import (
    _build_sinks,
    _next_interval_boundary,
    _parse_reference_prices,
    _run_cycle,
)
from fundamental_bias_alerts.market_data import MarketPriceQuote
from fundamental_bias_alerts.models import (
    AlertingConfig,
    DayTradingConfig,
    DriverSpec,
    EntitySpec,
    InstrumentSpec,
    Observation,
    ReleaseCalendar,
    ResearchConfig,
    SessionSpec,
    SeriesSpec,
    StrategyConfig,
)


class FakeFredClient:
    def __init__(self, observations: dict[str, list[Observation]]) -> None:
        self.observations = observations

    def get_observations(self, spec: SeriesSpec, *, limit: int = 2) -> list[Observation]:
        return self.observations[spec.cache_key][:limit]


class FakeMarketDataClient:
    def __init__(self, prices: dict[str, float]) -> None:
        self.prices = prices

    def get_price(self, symbol: str) -> MarketPriceQuote:
        return MarketPriceQuote(
            symbol=symbol,
            provider_symbol=f"{symbol[:3]}/{symbol[3:]}",
            price=self.prices[symbol],
            as_of_utc=datetime(2026, 4, 17, 8, 0, tzinfo=UTC),
        )

    def get_prices_best_effort(
        self,
        symbols: list[str],
    ) -> tuple[dict[str, MarketPriceQuote], dict[str, str]]:
        quotes: dict[str, MarketPriceQuote] = {}
        errors_by_symbol: dict[str, str] = {}
        for symbol in symbols:
            if symbol in self.prices:
                quotes[symbol] = self.get_price(symbol)
            else:
                errors_by_symbol[symbol] = f"{symbol} unavailable"
        return quotes, errors_by_symbol


class CliRunCycleTests(unittest.TestCase):
    def test_run_cycle_prints_once_and_writes_snapshot(self) -> None:
        unique = uuid4().hex
        state_path = Path(".state") / f"test-alert-state-{unique}.json"
        snapshot_path = Path(".state") / f"test-snapshots-{unique}.jsonl"
        self.addCleanup(lambda: state_path.unlink(missing_ok=True))
        self.addCleanup(lambda: snapshot_path.unlink(missing_ok=True))

        usd_series = "DFF"
        eur_series = "ECBMRRFR"
        config = StrategyConfig(
            metadata={"name": "test"},
            alerting=AlertingConfig(
                state_path=str(state_path),
                emit_on_first_run=True,
                min_score_change=0.35,
            ),
            research=ResearchConfig(
                snapshot_path=str(snapshot_path),
                journal_path=None,
            ),
            day_trading=None,
            entities={
                "USD": EntitySpec(
                    key="USD",
                    label="US Dollar",
                    drivers=(
                        DriverSpec(
                            key="policy_rate",
                            label="Fed policy rate",
                            weight=0.4,
                            mode="level",
                            bullish_when="higher",
                            neutral_value=2.0,
                            scale=2.0,
                            stale_after_hours=24 * 365 * 100,
                            series=SeriesSpec(series_id=usd_series),
                        ),
                    ),
                ),
                "EUR": EntitySpec(
                    key="EUR",
                    label="Euro",
                    drivers=(
                        DriverSpec(
                            key="policy_rate",
                            label="ECB policy rate",
                            weight=0.4,
                            mode="level",
                            bullish_when="higher",
                            neutral_value=2.0,
                            scale=2.0,
                            stale_after_hours=24 * 365 * 100,
                            series=SeriesSpec(series_id=eur_series),
                        ),
                    ),
                ),
            },
            instruments=(
                InstrumentSpec(
                    symbol="EURUSD",
                    base_entity="EUR",
                    quote_entity="USD",
                    threshold=0.3,
                ),
            ),
        )

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            _run_cycle(
                config,
                client=FakeFredClient(
                    {
                        usd_series: [
                            Observation(date="2026-04-15", value=4.0),
                            Observation(date="2026-04-14", value=4.0),
                        ],
                        eur_series: [
                            Observation(date="2026-04-15", value=2.0),
                            Observation(date="2026-04-14", value=2.0),
                        ],
                    }
                ),
                market_data_client=None,
                sinks=_build_sinks(""),
            )

        rendered = stdout.getvalue()
        self.assertEqual(rendered.count('"symbol": "EURUSD"'), 1)

        lines = snapshot_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["symbol"], "EURUSD")

    def test_run_cycle_writes_journal_and_enriches_output_with_playbook_fields(self) -> None:
        unique = uuid4().hex
        state_path = Path(".state") / f"test-alert-state-{unique}.json"
        journal_path = Path(".state") / f"test-journal-{unique}.jsonl"
        self.addCleanup(lambda: state_path.unlink(missing_ok=True))
        self.addCleanup(lambda: journal_path.unlink(missing_ok=True))

        usd_series = "DFF"
        eur_series = "ECBMRRFR"
        config = StrategyConfig(
            metadata={"name": "test", "version": "0.5.0"},
            alerting=AlertingConfig(
                state_path=str(state_path),
                emit_on_first_run=True,
                min_score_change=0.35,
            ),
            research=ResearchConfig(
                snapshot_path=None,
                journal_path=str(journal_path),
            ),
            day_trading=DayTradingConfig(
                min_confidence=0.7,
                max_stale_drivers=1,
                max_ranked_setups=2,
                sessions=(
                    SessionSpec(
                        key="london",
                        label="London",
                        timezone="Europe/London",
                        start_time="07:00",
                        end_time="11:00",
                    ),
                ),
                instrument_sessions={"EURUSD": ("london",)},
                event_policies=(),
                risk_per_trade_pct=0.25,
                target_r_multiple=2.0,
                default_stop_loss_pct=0.003,
                stop_loss_pct_by_symbol={},
            ),
            entities={
                "USD": EntitySpec(
                    key="USD",
                    label="US Dollar",
                    drivers=(
                        DriverSpec(
                            key="policy_rate",
                            label="Fed policy rate",
                            weight=0.4,
                            mode="level",
                            bullish_when="higher",
                            neutral_value=2.0,
                            scale=2.0,
                            stale_after_hours=24 * 365 * 100,
                            series=SeriesSpec(series_id=usd_series),
                        ),
                    ),
                ),
                "EUR": EntitySpec(
                    key="EUR",
                    label="Euro",
                    drivers=(
                        DriverSpec(
                            key="policy_rate",
                            label="ECB policy rate",
                            weight=0.4,
                            mode="level",
                            bullish_when="higher",
                            neutral_value=2.0,
                            scale=2.0,
                            stale_after_hours=24 * 365 * 100,
                            series=SeriesSpec(series_id=eur_series),
                        ),
                    ),
                ),
            },
            instruments=(
                InstrumentSpec(
                    symbol="EURUSD",
                    base_entity="EUR",
                    quote_entity="USD",
                    threshold=0.3,
                ),
            ),
        )

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            _run_cycle(
                config,
                client=FakeFredClient(
                    {
                        usd_series: [
                            Observation(date="2026-04-15", value=4.0),
                            Observation(date="2026-04-14", value=4.0),
                        ],
                        eur_series: [
                            Observation(date="2026-04-15", value=2.0),
                            Observation(date="2026-04-14", value=2.0),
                        ],
                    }
                ),
                market_data_client=None,
                sinks=[],
                calendar=ReleaseCalendar(events=()),
            )

        rendered = stdout.getvalue()
        self.assertIn('"action": "sell"', rendered)
        self.assertIn('"trade_state": "ready"', rendered)
        self.assertIn('"is_top_setup": true', rendered)

        journal_lines = journal_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(journal_lines), 1)
        journal_entry = json.loads(journal_lines[0])
        self.assertEqual(journal_entry["symbol"], "EURUSD")
        self.assertEqual(journal_entry["action"], "sell")
        self.assertEqual(journal_entry["tradable_rank"], 1)
        self.assertTrue(journal_entry["is_top_setup"])
        self.assertEqual(journal_entry["execution_plan"]["status"], "needs_price")

    def test_run_cycle_writes_trade_ledger_and_prints_trade_events_with_live_prices(self) -> None:
        unique = uuid4().hex
        state_path = Path(".state") / f"test-alert-state-{unique}.json"
        trade_log_path = Path(".state") / f"test-trade-ledger-{unique}.jsonl"
        self.addCleanup(lambda: state_path.unlink(missing_ok=True))
        self.addCleanup(lambda: trade_log_path.unlink(missing_ok=True))

        usd_series = "DFF"
        eur_series = "ECBMRRFR"
        config = StrategyConfig(
            metadata={"name": "test", "version": "0.7.0"},
            alerting=AlertingConfig(
                state_path=str(state_path),
                emit_on_first_run=True,
                min_score_change=0.35,
            ),
            research=ResearchConfig(
                snapshot_path=None,
                journal_path=None,
                trade_log_path=str(trade_log_path),
            ),
            day_trading=DayTradingConfig(
                min_confidence=0.7,
                max_stale_drivers=1,
                max_ranked_setups=2,
                sessions=(
                    SessionSpec(
                        key="all_day",
                        label="All Day",
                        timezone="UTC",
                        start_time="00:00",
                        end_time="23:59",
                    ),
                ),
                instrument_sessions={"EURUSD": ("all_day",)},
                event_policies=(),
                risk_per_trade_pct=0.25,
                target_r_multiple=2.0,
                default_stop_loss_pct=0.003,
                stop_loss_pct_by_symbol={},
            ),
            entities={
                "USD": EntitySpec(
                    key="USD",
                    label="US Dollar",
                    drivers=(
                        DriverSpec(
                            key="policy_rate",
                            label="Fed policy rate",
                            weight=0.4,
                            mode="level",
                            bullish_when="higher",
                            neutral_value=2.0,
                            scale=2.0,
                            stale_after_hours=24 * 365 * 100,
                            series=SeriesSpec(series_id=usd_series),
                        ),
                    ),
                ),
                "EUR": EntitySpec(
                    key="EUR",
                    label="Euro",
                    drivers=(
                        DriverSpec(
                            key="policy_rate",
                            label="ECB policy rate",
                            weight=0.4,
                            mode="level",
                            bullish_when="higher",
                            neutral_value=2.0,
                            scale=2.0,
                            stale_after_hours=24 * 365 * 100,
                            series=SeriesSpec(series_id=eur_series),
                        ),
                    ),
                ),
            },
            instruments=(
                InstrumentSpec(
                    symbol="EURUSD",
                    base_entity="EUR",
                    quote_entity="USD",
                    threshold=0.3,
                ),
            ),
        )

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            _run_cycle(
                config,
                client=FakeFredClient(
                    {
                        usd_series: [
                            Observation(date="2026-04-15", value=4.0),
                            Observation(date="2026-04-14", value=4.0),
                        ],
                        eur_series: [
                            Observation(date="2026-04-15", value=2.0),
                            Observation(date="2026-04-14", value=2.0),
                        ],
                    }
                ),
                market_data_client=FakeMarketDataClient({"EURUSD": 1.1}),
                sinks=[],
                calendar=ReleaseCalendar(events=()),
            )
            _run_cycle(
                config,
                client=FakeFredClient(
                    {
                        usd_series: [
                            Observation(date="2026-04-15", value=4.0),
                            Observation(date="2026-04-14", value=4.0),
                        ],
                        eur_series: [
                            Observation(date="2026-04-15", value=2.0),
                            Observation(date="2026-04-14", value=2.0),
                        ],
                    }
                ),
                market_data_client=FakeMarketDataClient({"EURUSD": 1.0933}),
                sinks=[],
                calendar=ReleaseCalendar(events=()),
            )

        rendered = stdout.getvalue()
        self.assertIn('"entry_type": "paper_trade_open"', rendered)
        self.assertIn('"entry_type": "paper_trade_close"', rendered)

        trade_lines = trade_log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(trade_lines), 2)
        latest_trade = json.loads(trade_lines[-1])
        self.assertEqual(latest_trade["status"], "closed")
        self.assertEqual(latest_trade["exit_reason"], "target_hit")
        self.assertAlmostEqual(latest_trade["r_multiple"], 2.0, places=6)

    def test_parse_reference_prices_reads_symbol_price_pairs(self) -> None:
        prices = _parse_reference_prices(["eurusd=1.0825", "XAUUSD=3300.5"])

        self.assertEqual(prices["EURUSD"], 1.0825)
        self.assertEqual(prices["XAUUSD"], 3300.5)

    def test_parse_reference_prices_rejects_invalid_pairs(self) -> None:
        with self.assertRaisesRegex(ValueError, "Use SYMBOL=PRICE"):
            _parse_reference_prices(["EURUSD"])

    def test_parse_reference_prices_rejects_non_positive_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be positive"):
            _parse_reference_prices(["EURUSD=0"])

    def test_build_sinks_adds_telegram_sink_when_envs_are_present(self) -> None:
        previous_token = os.environ.get("TEST_TELEGRAM_BOT_TOKEN")
        previous_chat = os.environ.get("TEST_TELEGRAM_CHAT_ID")
        self.addCleanup(self._restore_env, "TEST_TELEGRAM_BOT_TOKEN", previous_token)
        self.addCleanup(self._restore_env, "TEST_TELEGRAM_CHAT_ID", previous_chat)
        os.environ["TEST_TELEGRAM_BOT_TOKEN"] = "token123"
        os.environ["TEST_TELEGRAM_CHAT_ID"] = "456"

        sinks = _build_sinks(
            telegram_token_env="TEST_TELEGRAM_BOT_TOKEN",
            telegram_chat_id_env="TEST_TELEGRAM_CHAT_ID",
        )

        self.assertEqual(len(sinks), 1)
        self.assertIsInstance(sinks[0], TelegramAlertSink)

    def test_build_sinks_requires_both_telegram_env_names(self) -> None:
        with self.assertRaisesRegex(ValueError, "Telegram delivery requires both"):
            _build_sinks(telegram_token_env="TEST_TELEGRAM_BOT_TOKEN")

    def test_next_interval_boundary_aligns_to_next_utc_hour(self) -> None:
        boundary = _next_interval_boundary(
            now=datetime(2026, 4, 16, 10, 37, 45, tzinfo=UTC),
            interval_minutes=60,
        )
        self.assertEqual(boundary.isoformat(), "2026-04-16T11:00:00+00:00")

    def test_next_interval_boundary_rolls_to_next_day(self) -> None:
        boundary = _next_interval_boundary(
            now=datetime(2026, 4, 16, 23, 50, 0, tzinfo=UTC),
            interval_minutes=15,
        )
        self.assertEqual(boundary.isoformat(), "2026-04-17T00:00:00+00:00")

    def _restore_env(self, key: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
