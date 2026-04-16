# Deploying 24/7 on Render

This project is now prepared for a Render background worker deployment that can keep running when your laptop is off.

## Why This Shape

- The existing app is a Python CLI with local file-backed alert state and snapshot storage.
- Render cron jobs are not a good fit for this exact code path because cron jobs cannot use a persistent disk.
- Render background workers can run continuously, and Render persistent disks can preserve the alert state and research snapshots across restarts and deploys.

## Files Added for Render

- `render.yaml`
  Defines a Render background worker service.
- `FBA_STATE_PATH`
  Overrides the alert state path at runtime.
- `FBA_SNAPSHOT_PATH`
  Overrides the snapshot path at runtime.

## Deploy Steps

1. Push this repository to GitHub.
2. Create a Render account and connect the repository.
3. Create a new Blueprint deployment from the repo.
4. Review `render.yaml`.
5. Set secrets in Render when prompted:
   - `FRED_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
6. Deploy.

## Runtime Behavior

- The worker runs `python -m fundamental_bias_alerts.cli loop`.
- `--align-to-clock` keeps hourly runs aligned to UTC clock boundaries instead of drifting from deploy time.
- State is written to `storage/.state/alert_state.json`.
- Snapshots are written to `storage/data/bias_snapshots.jsonl`.

## After Deploy

- Check the Render logs for the first completed cycle.
- Confirm Telegram receives alerts.
- Trigger a manual deploy after any config change to `configs/locked.json`.
