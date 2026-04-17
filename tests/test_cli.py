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
from fundamental_bias_alerts.cli import _build_sinks, _next_interval_boundary, _run_cycle
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
