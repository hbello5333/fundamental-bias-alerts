from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

from fundamental_bias_alerts.alerts import (
    AlertDecision,
    AlertStateStore,
    TelegramAlertSink,
    format_telegram_alert_text,
)


class AlertStateStoreTests(unittest.TestCase):
    def test_first_run_emits_when_enabled(self) -> None:
        path = self._state_path()
        store = AlertStateStore(path, emit_on_first_run=True)
        decision = store.should_emit(
            AlertDecision(
                symbol="EURUSD",
                direction="bullish",
                score=0.92,
                confidence=0.81,
            ),
            min_score_change=0.35,
        )

        self.assertTrue(decision)

    def test_same_direction_small_change_does_not_emit(self) -> None:
        path = self._state_path()
        store = AlertStateStore(path, emit_on_first_run=True)
        store.should_emit(
            AlertDecision(
                symbol="EURUSD",
                direction="bullish",
                score=0.92,
                confidence=0.81,
            ),
            min_score_change=0.35,
        )

        second_store = AlertStateStore(path, emit_on_first_run=True)
        decision = second_store.should_emit(
            AlertDecision(
                symbol="EURUSD",
                direction="bullish",
                score=1.10,
                confidence=0.85,
            ),
            min_score_change=0.35,
        )

        self.assertFalse(decision)

    def test_direction_change_emits(self) -> None:
        path = self._state_path()
        store = AlertStateStore(path, emit_on_first_run=True)
        store.should_emit(
            AlertDecision(
                symbol="EURUSD",
                direction="bullish",
                score=0.92,
                confidence=0.81,
            ),
            min_score_change=0.35,
        )

        second_store = AlertStateStore(path, emit_on_first_run=True)
        decision = second_store.should_emit(
            AlertDecision(
                symbol="EURUSD",
                direction="bearish",
                score=-0.40,
                confidence=0.74,
            ),
            min_score_change=0.35,
        )

        self.assertTrue(decision)

    def _state_path(self) -> Path:
        directory = Path(".state")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"test-{uuid4().hex}.json"
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path


class TelegramAlertSinkTests(unittest.TestCase):
    def test_format_telegram_alert_text_includes_reasons(self) -> None:
        rendered = format_telegram_alert_text(
            {
                "symbol": "EURUSD",
                "direction": "bullish",
                "score": 0.5523,
                "confidence": 0.82,
                "base_score": 0.4,
                "quote_score": -0.15,
                "reasons": ["ECB policy rate strong", "US CPI soft"],
            }
        )

        self.assertIn("Fundamental Bias Alert", rendered)
        self.assertIn("Symbol: EURUSD", rendered)
        self.assertIn("- ECB policy rate strong", rendered)

    def test_telegram_alert_sink_posts_message(self) -> None:
        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

            def read(self) -> bytes:
                return b'{"ok": true, "result": {"message_id": 1}}'

        with mock.patch(
            "fundamental_bias_alerts.telegram.request.urlopen",
            return_value=FakeResponse(),
        ) as mocked_urlopen:
            sink = TelegramAlertSink("token123", "456")
            sink.emit(
                {
                    "symbol": "EURUSD",
                    "direction": "bullish",
                    "score": 0.5523,
                    "confidence": 0.82,
                    "reasons": ["ECB policy rate strong"],
                    "base_score": 0.4,
                    "quote_score": -0.15,
                }
            )

        request_obj = mocked_urlopen.call_args.args[0]
        self.assertIn("/bottoken123/sendMessage", request_obj.full_url)
