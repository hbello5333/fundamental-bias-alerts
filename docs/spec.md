# Spec: Fundamentals-Only Hourly Bias Alert System

## Assumptions I'm Making

1. This is a local Python CLI service first, not a browser dashboard.
2. The first version should generate alerts, not place trades.
3. "Fundamentals-only" means macro and policy data only; no candlestick or chart-pattern logic.
4. "Profitable" and "proven" must mean demonstrated through paper/live validation, not marketing language.
5. The MVP should avoid paid dependencies and work from official or primary-source macro data where possible.

## Objective

Build an automated system that evaluates fundamental bias every hour for `XAUUSD`, `EURUSD`, `GBPUSD`, `USDJPY`, `USDCAD`, `BTCUSD`, and `AUDUSD`, then emits a directional alert with confidence and rationale.

Success looks like:

- the engine can run once or on an hourly loop
- all 7 instruments produce a bias result
- each alert explains the key supporting drivers
- the system stores enough state to avoid duplicate low-value alerts
- every hourly pass leaves an auditable snapshot trail for later validation
- the day-trading layer can express allowed direction, valid sessions, and no-trade windows
- the repo makes its evidence limits explicit instead of claiming false certainty

## Tech Stack

- Python 3.12+
- Standard library only for runtime
- `unittest` for tests
- FRED / ALFRED HTTP APIs for macro data retrieval and series search

## Commands

- Dev / run once:
  `python -m fundamental_bias_alerts.cli run --config configs/default.json`
- Verify series resolution:
  `python -m fundamental_bias_alerts.cli verify-series --config configs/default.json`
- Lock series mappings:
  `python -m fundamental_bias_alerts.cli lock-series --config configs/default.json --output configs/locked.json`
- Hourly loop:
  `python -m fundamental_bias_alerts.cli loop --config configs/locked.json --interval-minutes 60`
- Generate a day-trading playbook:
  `python -m fundamental_bias_alerts.cli day-trade-playbook --config configs/locked.json --calendar configs/release_calendar.usd_q2_2026.json`
- Validate snapshots against hourly closes:
  `python -m fundamental_bias_alerts.cli validate-prices --snapshots data/bias_snapshots.jsonl --prices hourly_prices.csv --horizon-hours 1 --horizon-hours 4 --horizon-hours 24 --min-cohort-samples 10 --max-ranked-cohorts 25`
- Tests:
  `python -m unittest discover -s tests -p "test_*.py" -v`

## Project Structure

- `fundamental_bias_alerts/`
  Core package: models, config parsing, FRED client, scoring engine, alerts, CLI.
- `configs/`
  Default and locked strategy files.
- `docs/`
  Spec and ADRs.
- `examples/`
  Sample price CSV inputs and other research artifacts.
- `scripts/`
  Windows helper scripts for hourly paper runs and validation.
- `tests/`
  Unit tests for deterministic scoring logic and alert deduplication.

## Code Style

Use small, explicit dataclasses and plain functions before adding abstractions.

```python
score = clamp(signal, -1.0, 1.0) * driver.weight * freshness
direction = "bullish" if score >= threshold else "bearish" if score <= -threshold else "neutral"
```

Conventions:

- keep runtime dependencies at zero in the MVP
- prefer typed dataclasses over unstructured dict mutation
- keep config external in JSON so the strategy can be audited without code changes
- explain non-obvious financial assumptions in docs, not hidden in logic

## Testing Strategy

- Framework: `unittest`
- Unit tests first for scoring math, confidence, and alert deduplication
- No network in tests; use fake providers and fixed observations
- Verification target: deterministic tests for all critical signal transformations

## Boundaries

- Always:
  - keep the system broker-agnostic
  - expose confidence and rationale with every bias
  - document data-source and backtest limitations
  - keep alerts non-executing in the MVP
- Ask first:
  - adding paid data feeds
  - adding broker execution
  - changing the meaning of "fundamentals-only"
  - replacing official data with third-party signal vendors
- Never:
  - claim the system is proven profitable without validation data
  - hardcode secrets
  - hide unresolved series mappings behind silent fallbacks

## Success Criteria

- A config file defines the 7 target instruments and their entity drivers.
- The CLI can resolve FRED search terms into locked series IDs.
- The engine outputs directional bias, score, confidence, and rationale for each instrument.
- Alerts are emitted only when a bias meaningfully changes or a first run occurs.
- Each run appends JSONL snapshots that can be joined to hourly close data.
- The day-trading playbook outputs allowed direction, preferred sessions, and release lockout windows.
- Validation reports break results down by horizon, symbol, direction, and confidence bucket.
- Validation reports include confidence sweeps and ranked cohorts to surface where edge is strongest.
- Tests pass locally.
- The README explains how to validate the system honestly.

## Open Questions

- Which alert channel matters most for you: webhook, Telegram, Discord, email, or terminal-only?
- Do you want the next slice to include a release-calendar join for cleaner historical studies?
- Do you want a lightweight dashboard after the CLI is stable?
