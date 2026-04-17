# Fundamental Bias Alerts

This project is a local-first Python system for generating automated hourly, fundamentals-only bias alerts for:

- `XAUUSD`
- `EURUSD`
- `GBPUSD`
- `USDJPY`
- `USDCAD`
- `BTCUSD`
- `AUDUSD`

The goal is to build a researchable, auditable alert engine. It is not safe or honest to label any strategy "proven profitable" before it survives out-of-sample testing and live paper tracking. This repo is built to help us do that work properly.

## What It Does

- Scores macro/fundamental drivers for currencies and macro-sensitive assets.
- Converts those entity scores into pair-level directional bias.
- Runs once or on an hourly loop.
- Emits alerts to the console and optionally to a webhook or Telegram.
- Persists state so it can alert on meaningful bias changes instead of spamming every hour.
- Writes one JSONL snapshot per instrument per run for later validation against hourly prices.
- Lets you verify or lock FRED series matches before using them live.
- Generates a day-trading playbook with allowed direction, valid sessions, and no-trade windows around scheduled macro events.
- Ranks the top tradable setups so you can focus on the best 1 to 2 ideas instead of forcing trades across all 7 instruments.
- Appends each hourly day-trade signal to a paper-trade journal for later review.
- Turns a playbook into an exact paper-trade ticket when you supply reference prices and account size, or when live prices are available.
- Fetches live market prices from Twelve Data for `XAUUSD`, major FX pairs, and `BTCUSD`.
- Auto-opens and auto-closes paper trades for top setups, then logs `entry`, `stop`, `target`, `exit`, `R-multiple`, and win/loss outcomes.
- Sends a concise morning trader brief with the top setup, why it matters, session windows, and the live-priced ticket.
- Includes a Render-ready background worker blueprint for 24/7 cloud deployment.

## Why FRED / ALFRED

The MVP is built around the St. Louis Fed's FRED / ALFRED APIs because they provide:

- official or primary-source macro series aggregation
- historical revisions support through real-time periods / vintages
- searchable metadata for series resolution

Official documentation used for this build:

- FRED `fred/series/observations`: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
- FRED `fred/series/search`: https://fred.stlouisfed.org/docs/api/fred/series_search.html
- FRED real-time periods / ALFRED concepts: https://fred.stlouisfed.org/docs/api/fred/realtime_period.html

## Important Limitation

Hourly execution is supported, but FRED / ALFRED real-time controls are date-based, not intraday timestamp-based. That means you can run this engine hourly in real time, but you cannot claim a clean intraday historical proof without a separate release-timestamp calendar joined to price data. The system is intentionally honest about that.

## Quick Start

1. Create and activate a virtual environment.
2. Copy `.env.example` values into your shell environment.
3. Verify or lock the series mappings.
4. Run the engine once.
5. Validate the stored snapshots against hourly close data.
6. Generate a session-aware day-trading playbook.

PowerShell example:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
$env:FRED_API_KEY="your_key_here"
$env:TWELVEDATA_API_KEY="your_key_here"
python -m fundamental_bias_alerts.cli run --config configs/locked.json
```

You can also create a local `.env` file and the CLI will load it automatically if the variables are not already present in your shell.

Each run appends research snapshots to `data/bias_snapshots.jsonl` by default.

If day-trading config is enabled, each run also appends signal-journal entries to `data/paper_trade_journal.jsonl` by default.

If live prices are available, each run also appends paper-trade lifecycle entries to `data/paper_trade_ledger.jsonl` by default.

Hourly loop:

```powershell
python -m fundamental_bias_alerts.cli loop --config configs/locked.json --calendar configs/release_calendar.usd_q2_2026.json --interval-minutes 60
```

Hourly run with Telegram delivery:

```powershell
python -m fundamental_bias_alerts.cli run --config configs/locked.json --calendar configs/release_calendar.usd_q2_2026.json --telegram-token-env TELEGRAM_BOT_TOKEN --telegram-chat-id-env TELEGRAM_CHAT_ID
```

Day-trading playbook:

```powershell
python -m fundamental_bias_alerts.cli day-trade-playbook --config configs/locked.json --calendar configs/release_calendar.usd_q2_2026.json
```

Trader-ready brief:

```powershell
python -m fundamental_bias_alerts.cli day-trade-playbook --config configs/locked.json --calendar configs/release_calendar.usd_q2_2026.json --trade-date 2026-04-17 --brief
```

Exact paper-trade ticket:

```powershell
python -m fundamental_bias_alerts.cli day-trade-playbook --config configs/locked.json --calendar configs/release_calendar.usd_q2_2026.json --trade-date 2026-04-17 --reference-price EURUSD=1.0825 --reference-price XAUUSD=3320.50 --account-size 10000 --brief
```

Exact paper-trade ticket from live prices:

```powershell
python -m fundamental_bias_alerts.cli day-trade-playbook --config configs/locked.json --calendar configs/release_calendar.usd_q2_2026.json --trade-date 2026-04-17 --live-prices --account-size 10000 --brief
```

Live prices snapshot:

```powershell
python -m fundamental_bias_alerts.cli live-prices --config configs/locked.json
```

Paper-trade performance review:

```powershell
python -m fundamental_bias_alerts.cli paper-trade-review --config configs/locked.json
```

Morning trader brief:

```powershell
python -m fundamental_bias_alerts.cli morning-brief --config configs/locked.json --calendar configs/release_calendar.usd_q2_2026.json --account-size 10000
```

This command combines:

- the latest live macro bias from FRED
- day-trading confidence and stale-data gates from the strategy config
- a release calendar with scheduled macro events

The output includes:

- `action`
- `bias`
- `score`
- `bias_strength`
- `bias_reasons`
- `allowed_direction`
- `trade_state`
- `tradable_rank`
- `is_top_setup`
- `top_setups`
- `execution_plan`
- `valid_sessions`
- `no_trade_windows`

`execution_plan.status` meanings:

- `ready_now`: the setup is tradable now and the ticket includes exact levels.
- `waiting_for_session`: the bias is tradable, but you should wait for the next valid session window.
- `needs_price`: the setup is tradable, but you did not provide a reference price for exact levels.
- `blocked`: the setup is not tradable because it is neutral, stale, low-confidence, locked out, or out of session for the trade date.

Live price feed note:

- Exact tickets and automated paper-trade outcome logging use Twelve Data live prices: https://twelvedata.com/docs
- The `/price` endpoint is the latest-price endpoint, and intraday time series support is documented in the same official docs.
- Twelve Data's pricing page currently lists real-time forex and crypto on the free Basic plan, while commodities market data such as `XAU/USD` are listed under Grow or above, so confirm your current plan before relying on full top-7 coverage: https://twelvedata.com/pricing

Webhook alerts:

```powershell
$env:ALERT_WEBHOOK_URL="https://your.endpoint/hook"
python -m fundamental_bias_alerts.cli run --config configs/locked.json --webhook-env ALERT_WEBHOOK_URL
```

Telegram setup:

1. Create a bot with `@BotFather` and copy the bot token into `TELEGRAM_BOT_TOKEN`.
2. Open a chat with your bot and send it a message such as `/start`.
3. Discover the recent chat IDs your bot can see:

```powershell
python -m fundamental_bias_alerts.cli telegram-chat-id
```

4. Put the desired chat ID into `TELEGRAM_CHAT_ID`.
5. Send a live test message:

```powershell
python -m fundamental_bias_alerts.cli telegram-test
```

Telegram note:

- Telegram bots cannot start a conversation with you first. You must message the bot before it can send alerts to your private chat.

Validation against hourly prices:

```powershell
python -m fundamental_bias_alerts.cli validate-prices --snapshots data/bias_snapshots.jsonl --prices path\\to\\hourly_prices.csv --horizon-hours 1 --horizon-hours 4 --horizon-hours 24 --min-cohort-samples 10 --max-ranked-cohorts 25
```

Expected price CSV columns:

- `timestamp`
- `symbol`
- `close`

`timestamp` should be an ISO 8601 UTC hour such as `2026-04-16T13:00:00+00:00`.

Sample files are included at `examples/hourly_prices.sample.csv` and `examples/bias_snapshots.sample.jsonl`.

Windows helper scripts:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\\run-paper-hourly.ps1
powershell -ExecutionPolicy Bypass -File scripts\\run-paper-hourly.ps1 -TelegramBotTokenEnv TELEGRAM_BOT_TOKEN -TelegramChatIdEnv TELEGRAM_CHAT_ID
powershell -ExecutionPolicy Bypass -File scripts\\register-hourly-task.ps1 -UseTelegram
powershell -ExecutionPolicy Bypass -File scripts\\day-trade-playbook.ps1
powershell -ExecutionPolicy Bypass -File scripts\\day-trade-playbook.ps1 -TradeDate 2026-04-17 -Brief
powershell -ExecutionPolicy Bypass -File scripts\\day-trade-playbook.ps1 -TradeDate 2026-04-17 -Brief -ReferencePrice EURUSD=1.0825,XAUUSD=3320.5 -AccountSize 10000
powershell -ExecutionPolicy Bypass -File scripts\\validate-paper-study.ps1 -Prices your_hourly_prices.csv
```

`run-paper-hourly.ps1` is designed for Windows Task Scheduler if you want a stable hourly paper-tracking job without keeping an interactive shell open.

`register-hourly-task.ps1` creates an hourly Windows Scheduled Task that runs `run-paper-hourly.ps1`. If you pass `-UseTelegram`, it adds Telegram delivery using `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from your local `.env`.

The hourly task still respects the alert state rules: it runs every hour, but Telegram messages are only sent when the bias changes enough to emit an alert.
It also writes a paper-trade signal journal and a paper-trade ledger so you can review what the system wanted to trade and how each automated paper trade finished.

Render deployment:

- `render.yaml` provisions a background worker that runs the loop continuously in the cloud.
- It uses `FBA_STATE_PATH` and `FBA_SNAPSHOT_PATH` to write alert state and snapshots to a persistent disk mount.
- The worker start command uses `--align-to-clock` so hourly runs stay aligned to UTC hour boundaries instead of drifting from deploy time.
- See [docs/deploy.render.md](docs/deploy.render.md) for the deployment checklist.

GitHub Actions deployment:

- `.github/workflows/hourly-bias-alerts.yml` provides a no-laptop fallback for hourly Telegram delivery.
- It runs a single `run` cycle every hour at minute `17` UTC to avoid the top-of-hour GitHub Actions traffic spike.
- It persists `storage/.state/alert_state.json`, `storage/.state/paper_trade_journal.jsonl`, and `storage/.state/paper_trade_ledger.jsonl` on a dedicated `runtime-state` branch.
- It keeps `FBA_SNAPSHOT_PATH` ephemeral inside the GitHub runner to avoid committing hourly research data into the repository.
- Store `FRED_API_KEY`, `TWELVEDATA_API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` as repository secrets before using it if you want live-price-driven tickets and automated paper-trade outcomes in the cloud.
- GitHub scheduled workflows run from the latest commit on the default branch and public-repo schedules are auto-disabled after 60 days without repository activity.
- `.github/workflows/morning-brief.yml` sends a single daily Telegram morning brief at `05:47 UTC`, which avoids colliding with the hourly workflow at minute `17`.
- If you want the brief to include risk dollars and size, add an optional `MORNING_BRIEF_ACCOUNT_SIZE` repository secret.

Validation report highlights:

- `confidence_sweep` compares results at progressively stricter minimum-confidence cutoffs derived from `--confidence-buckets`
- `ranked_cohorts` ranks the strongest `symbol + direction + confidence bucket` combinations for each horizon
- `by_symbol`, `by_direction`, and `by_confidence_bucket` stay in the report for broader context

## Command Reference

- `python -m fundamental_bias_alerts.cli verify-series --config configs/default.json`
  Prints the top FRED search matches for every unresolved series.
- `python -m fundamental_bias_alerts.cli lock-series --config configs/default.json --output configs/locked.json`
  Resolves unresolved series into a locked config file using the top search match.
- `python -m fundamental_bias_alerts.cli run --config configs/locked.json`
  Runs one scoring pass, prints the current payload for each instrument, and appends snapshots to `data/bias_snapshots.jsonl`. Add `--calendar configs/release_calendar.usd_q2_2026.json` to enrich the output with day-trade ranking, journal entries, and automated paper-trade lifecycle logging when `TWELVEDATA_API_KEY` is set.
- `python -m fundamental_bias_alerts.cli loop --config configs/locked.json --interval-minutes 60`
  Runs continuously on a timer. Add `--calendar configs/release_calendar.usd_q2_2026.json` if you want no-trade windows, top setups, paper-trade signal journaling, and automated paper-trade opens/closes from live prices.
- `python -m fundamental_bias_alerts.cli telegram-chat-id`
  Prints recent Telegram chats seen by your bot so you can choose a chat ID.
- `python -m fundamental_bias_alerts.cli telegram-test`
  Sends a Telegram test message using `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
- `python -m fundamental_bias_alerts.cli day-trade-playbook --config configs/locked.json --calendar configs/release_calendar.usd_q2_2026.json`
  Produces a session-aware day-trading playbook from live macro bias and a scheduled release calendar. Add `--brief` for a trader-readable summary with action, why, sessions, lockouts, and execution-plan notes. Add repeated `--reference-price SYMBOL=PRICE` plus `--account-size` for exact paper-trade levels, or use `--live-prices` to fetch the prices automatically from Twelve Data.
- `python -m fundamental_bias_alerts.cli morning-brief --config configs/locked.json --calendar configs/release_calendar.usd_q2_2026.json`
  Produces a concise daily operator brief with the top setups, why they matter, session windows, and a live-priced ticket when `TWELVEDATA_API_KEY` is available. Add `--telegram-token-env TELEGRAM_BOT_TOKEN --telegram-chat-id-env TELEGRAM_CHAT_ID` to send it directly to Telegram.
- `python -m fundamental_bias_alerts.cli live-prices --config configs/locked.json`
  Fetches the current live prices for the configured instruments from Twelve Data so you can sanity-check the feed before trading.
- `python -m fundamental_bias_alerts.cli paper-trade-review --config configs/locked.json`
  Summarizes closed paper trades with win/loss counts and R-multiple performance by symbol and by session, and shows any currently open paper trades.
- `python -m fundamental_bias_alerts.cli validate-prices --snapshots data/bias_snapshots.jsonl --prices your_hourly_prices.csv --horizon-hours 1 --horizon-hours 4 --horizon-hours 24 --min-cohort-samples 10 --max-ranked-cohorts 25`
  Measures directional edge using stored bias snapshots and hourly close data, including confidence sweeps and ranked cohorts.

## Included Locked Config

`configs/locked.json` is included and uses manually locked FRED series IDs for the current research setup.

`configs/release_calendar.usd_q2_2026.json` is included as a sample official release calendar for major USD events in Q2 2026. It should be maintained manually from official source calendars.

Important caveat:

- several non-U.S. macro series available through FRED are published with slower or patchier updates than a true institutional macro calendar
- some "policy" drivers are overnight/interbank proxies rather than the central bank target rate itself
- if a driver is too old for its configured freshness window, the engine will mark it stale and exclude it from the score

## Project Layout

- `fundamental_bias_alerts/` core engine, config loader, data access, and CLI
- `configs/` default strategy and instrument definitions
- `docs/` spec and architecture decisions
- `examples/` sample research inputs, including a price CSV template
- `scripts/` Windows helper scripts for hourly paper runs, task registration, day-trading playbooks, and validation
- `render.yaml` Render Blueprint for an always-on cloud worker with persistent storage
- `tests/` unit tests for scoring and alert behavior
- `data/` runtime snapshots and local research artifacts

## Proof Checklist

If you want to turn this into something you can trust, the next validation steps are:

1. Lock every FRED series ID after manual review.
2. Run the engine hourly in paper mode for several weeks.
3. Export broker or exchange hourly closes into the documented CSV format.
4. Use `day-trade-playbook` to constrain intraday direction and respect release lockout windows.
5. Use `validate-prices` to measure forward edge by symbol, horizon, direction, confidence bucket, and ranked cohorts.
6. Reject or refine any driver whose edge disappears out of sample.
7. Only then decide whether to automate execution.
