from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from fundamental_bias_alerts.models import DayTradeInstrumentPlaybook, DayTradePlaybook, TradeExecutionPlan
from fundamental_bias_alerts.paper_trades import PaperTradeLedgerStore


class PaperTradeLedgerStoreTests(unittest.TestCase):
    def test_sync_playbook_opens_top_setup_once(self) -> None:
        ledger_path = self._ledger_path()
        store = PaperTradeLedgerStore(ledger_path)
        playbook = self._playbook(
            generated_at=datetime(2026, 4, 17, 8, 0, tzinfo=UTC),
            entry_price=1.1000,
            stop_price=1.0967,
            target_price=1.1066,
            plan_status="ready_now",
        )

        first_events = store.sync_playbook(
            strategy_metadata={"name": "test", "version": "0.7.0"},
            playbook=playbook,
            reference_prices={"EURUSD": 1.1000},
        )
        second_events = store.sync_playbook(
            strategy_metadata={"name": "test", "version": "0.7.0"},
            playbook=playbook,
            reference_prices={"EURUSD": 1.1000},
        )

        trades = store.load_trades()
        self.assertEqual(len(first_events), 1)
        self.assertEqual(first_events[0]["entry_type"], "paper_trade_open")
        self.assertEqual(second_events, [])
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].status, "open")
        self.assertAlmostEqual(trades[0].entry_price, 1.1, places=6)
        self.assertEqual(len(ledger_path.read_text(encoding="utf-8").splitlines()), 1)

    def test_sync_playbook_closes_trade_on_target_and_review_groups_results(self) -> None:
        store = PaperTradeLedgerStore(self._ledger_path())
        open_playbook = self._playbook(
            generated_at=datetime(2026, 4, 17, 8, 0, tzinfo=UTC),
            entry_price=1.1000,
            stop_price=1.0967,
            target_price=1.1066,
            plan_status="ready_now",
        )
        close_playbook = self._playbook(
            generated_at=datetime(2026, 4, 17, 9, 0, tzinfo=UTC),
            entry_price=1.1050,
            stop_price=1.1017,
            target_price=1.1116,
            plan_status="ready_now",
        )

        store.sync_playbook(
            strategy_metadata={"name": "test", "version": "0.7.0"},
            playbook=open_playbook,
            reference_prices={"EURUSD": 1.1000},
        )
        close_events = store.sync_playbook(
            strategy_metadata={"name": "test", "version": "0.7.0"},
            playbook=close_playbook,
            reference_prices={"EURUSD": 1.1067},
            as_of=datetime(2026, 4, 17, 9, 0, tzinfo=UTC),
        )

        trades = store.load_trades()
        self.assertEqual(len(close_events), 1)
        self.assertEqual(close_events[0]["entry_type"], "paper_trade_close")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].status, "closed")
        self.assertEqual(trades[0].exit_reason, "target_hit")
        self.assertAlmostEqual(trades[0].r_multiple or 0.0, 2.0, places=6)
        self.assertEqual(trades[0].outcome, "win")

        review = store.review(as_of=datetime(2026, 4, 17, 9, 1, tzinfo=UTC))
        self.assertEqual(review["closed_trade_count"], 1)
        self.assertEqual(review["summary"]["wins"], 1)
        self.assertAlmostEqual(review["summary"]["total_r_multiple"], 2.0, places=6)
        self.assertEqual(review["by_symbol"][0]["group"], "EURUSD")
        self.assertEqual(review["by_session"][0]["group"], "London")

    def test_sync_playbook_closes_trade_on_session_expiry_with_fractional_r(self) -> None:
        store = PaperTradeLedgerStore(self._ledger_path())
        playbook = self._playbook(
            generated_at=datetime(2026, 4, 17, 8, 0, tzinfo=UTC),
            entry_price=1.1000,
            stop_price=1.0967,
            target_price=1.1066,
            plan_status="ready_now",
        )
        store.sync_playbook(
            strategy_metadata={"name": "test", "version": "0.7.0"},
            playbook=playbook,
            reference_prices={"EURUSD": 1.1000},
        )

        close_events = store.sync_playbook(
            strategy_metadata={"name": "test", "version": "0.7.0"},
            playbook=self._playbook(
                generated_at=datetime(2026, 4, 17, 11, 30, tzinfo=UTC),
                entry_price=1.1010,
                stop_price=1.0977,
                target_price=1.1076,
                plan_status="blocked",
            ),
            reference_prices={"EURUSD": 1.10165},
            as_of=datetime(2026, 4, 17, 11, 30, tzinfo=UTC),
        )

        self.assertEqual(close_events[0]["exit_reason"], "session_expired")
        self.assertAlmostEqual(close_events[0]["r_multiple"], 0.5, places=6)
        self.assertEqual(close_events[0]["outcome"], "win")

    def _ledger_path(self) -> Path:
        directory = Path(".state")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"paper-trades-{uuid4().hex}.jsonl"
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def _playbook(
        self,
        *,
        generated_at: datetime,
        entry_price: float,
        stop_price: float,
        target_price: float,
        plan_status: str,
    ) -> DayTradePlaybook:
        return DayTradePlaybook(
            generated_at_utc=generated_at,
            trade_date_utc=date(2026, 4, 17),
            items=(
                DayTradeInstrumentPlaybook(
                    symbol="EURUSD",
                    bias="bullish",
                    score=0.55,
                    bias_strength=0.55,
                    allowed_direction="long_only",
                    trade_state="ready",
                    confidence=0.82,
                    stale_driver_count=0,
                    valid_sessions=(),
                    no_trade_windows=(),
                    bias_reasons=("ECB policy rate strong", "US CPI soft"),
                    notes=(),
                    tradable_rank=1,
                    is_top_setup=True,
                    execution_plan=TradeExecutionPlan(
                        status=plan_status,
                        entry_style="market",
                        stop_loss_pct=0.003,
                        target_r_multiple=2.0,
                        risk_per_trade_pct=0.25,
                        reference_price=entry_price,
                        entry_price=entry_price,
                        stop_price=stop_price,
                        target_price=target_price,
                        stop_distance_price=abs(entry_price - stop_price),
                        target_distance_price=abs(target_price - entry_price),
                        activation_start_utc=datetime(2026, 4, 17, 7, 0, tzinfo=UTC),
                        expiry_utc=datetime(2026, 4, 17, 11, 0, tzinfo=UTC),
                        session_label="London",
                        notes=(),
                    ),
                ),
            ),
        )
