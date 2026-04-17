from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from uuid import uuid4

from fundamental_bias_alerts.config import load_strategy_config


class ConfigOverridesTests(unittest.TestCase):
    def test_load_strategy_config_allows_env_overrides_for_storage_paths(self) -> None:
        config_path = self._write_config()
        previous_state = os.environ.get("FBA_STATE_PATH")
        previous_snapshot = os.environ.get("FBA_SNAPSHOT_PATH")
        previous_journal = os.environ.get("FBA_JOURNAL_PATH")
        self.addCleanup(self._restore_env, "FBA_STATE_PATH", previous_state)
        self.addCleanup(self._restore_env, "FBA_SNAPSHOT_PATH", previous_snapshot)
        self.addCleanup(self._restore_env, "FBA_JOURNAL_PATH", previous_journal)
        os.environ["FBA_STATE_PATH"] = "storage/.state/cloud_alert_state.json"
        os.environ["FBA_SNAPSHOT_PATH"] = "storage/data/cloud_bias_snapshots.jsonl"
        os.environ["FBA_JOURNAL_PATH"] = "storage/data/cloud_paper_trade_journal.jsonl"

        config = load_strategy_config(config_path)

        self.assertEqual(config.alerting.state_path, "storage/.state/cloud_alert_state.json")
        self.assertEqual(config.research.snapshot_path, "storage/data/cloud_bias_snapshots.jsonl")
        self.assertEqual(
            config.research.journal_path,
            "storage/data/cloud_paper_trade_journal.jsonl",
        )

    def _write_config(self) -> Path:
        directory = Path(".state")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"test-config-{uuid4().hex}.json"
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        path.write_text(
            json.dumps(
                {
                    "metadata": {"name": "test", "version": "0.5.0"},
                    "alerting": {
                        "state_path": ".state/alert_state.json",
                        "emit_on_first_run": True,
                        "min_score_change": 0.35,
                    },
                    "research": {
                        "snapshot_path": "data/bias_snapshots.jsonl",
                        "journal_path": "data/paper_trade_journal.jsonl",
                    },
                    "entities": [],
                    "instruments": [],
                }
            ),
            encoding="utf-8",
        )
        return path

    def _restore_env(self, key: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
