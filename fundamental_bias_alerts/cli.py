from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .alerts import (
    AlertDecision,
    AlertStateStore,
    TelegramAlertSink,
    WebhookAlertSink,
    format_alert_payload,
)
from .config import iter_series_specs, load_raw_config, load_strategy_config
from .engine import score_instrument
from .fred import FredClient, FredRequestError
from .journal import PaperTradeJournalStore
from .models import ReleaseCalendar, SeriesSpec, StrategyConfig
from .playbook import (
    format_day_trade_playbook_brief,
    format_day_trade_playbook_payload,
    generate_day_trade_playbook,
)
from .release_calendar import load_release_calendar
from .snapshots import SnapshotStore
from .telegram import TelegramBotClient, TelegramRequestError, extract_recent_chats
from .validation import parse_confidence_bucket_lowers, validate_snapshot_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fundamentals-only hourly bias alerts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify-series", help="Print top FRED matches for unresolved series")
    verify.add_argument("--config", required=True)

    lock_series = subparsers.add_parser("lock-series", help="Resolve search-based series into explicit IDs")
    lock_series.add_argument("--config", required=True)
    lock_series.add_argument("--output", required=True)

    run = subparsers.add_parser("run", help="Run one scoring cycle")
    run.add_argument("--config", required=True)
    run.add_argument("--calendar", default="")
    run.add_argument("--webhook-env", default="")
    run.add_argument("--telegram-token-env", default="")
    run.add_argument("--telegram-chat-id-env", default="")

    loop = subparsers.add_parser("loop", help="Run scoring on a fixed interval")
    loop.add_argument("--config", required=True)
    loop.add_argument("--calendar", default="")
    loop.add_argument("--interval-minutes", type=int, default=60)
    loop.add_argument("--webhook-env", default="")
    loop.add_argument("--telegram-token-env", default="")
    loop.add_argument("--telegram-chat-id-env", default="")
    loop.add_argument(
        "--align-to-clock",
        action="store_true",
        help="Sleep until the next UTC interval boundary instead of waiting a fixed offset from startup.",
    )

    day_trade = subparsers.add_parser(
        "day-trade-playbook",
        help="Generate a session-aware day-trading playbook from live macro bias and a release calendar",
    )
    day_trade.add_argument("--config", required=True)
    day_trade.add_argument("--calendar", required=True)
    day_trade.add_argument(
        "--trade-date",
        default="",
        help="UTC trade date in YYYY-MM-DD format. Defaults to today in UTC.",
    )
    day_trade.add_argument(
        "--brief",
        action="store_true",
        help="Print a trader-friendly plain-English brief instead of JSON.",
    )
    day_trade.add_argument(
        "--reference-price",
        action="append",
        default=[],
        help="Repeat with SYMBOL=PRICE to compute exact paper-trade entry, stop, and target levels.",
    )
    day_trade.add_argument(
        "--account-size",
        type=float,
        default=0.0,
        help="Optional account size in USD for risk amount and position size calculations.",
    )

    validate = subparsers.add_parser("validate-prices", help="Score snapshot edge against hourly close data")
    validate.add_argument("--prices", required=True)
    validate.add_argument("--snapshots", default="data/bias_snapshots.jsonl")
    validate.add_argument(
        "--horizon-hours",
        type=int,
        action="append",
        default=[],
        help="Repeat this flag to evaluate multiple forward horizons. Defaults to 1 if omitted.",
    )
    validate.add_argument("--min-confidence", type=float, default=0.0)
    validate.add_argument("--symbol", default="")
    validate.add_argument(
        "--confidence-buckets",
        default="0.00,0.60,0.75,0.90",
        help="Comma-separated confidence bucket lower bounds used for report breakdowns.",
    )
    validate.add_argument(
        "--min-cohort-samples",
        type=int,
        default=1,
        help="Minimum evaluated samples required for a cohort to appear in ranked_cohorts.",
    )
    validate.add_argument(
        "--max-ranked-cohorts",
        type=int,
        default=20,
        help="Maximum number of ranked cohorts to include per horizon.",
    )

    telegram_chat_id = subparsers.add_parser(
        "telegram-chat-id",
        help="List recent Telegram chats seen by your bot so you can pick a chat ID",
    )
    telegram_chat_id.add_argument("--token-env", default="TELEGRAM_BOT_TOKEN")
    telegram_chat_id.add_argument("--limit", type=int, default=20)

    telegram_test = subparsers.add_parser(
        "telegram-test",
        help="Send a Telegram test message using your configured bot token and chat ID",
    )
    telegram_test.add_argument("--token-env", default="TELEGRAM_BOT_TOKEN")
    telegram_test.add_argument("--chat-id-env", default="TELEGRAM_CHAT_ID")
    telegram_test.add_argument(
        "--message",
        default="Fundamental Bias Alerts Telegram test OK.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    _load_dotenv_if_present()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "verify-series":
            return cmd_verify_series(Path(args.config))
        if args.command == "lock-series":
            return cmd_lock_series(Path(args.config), Path(args.output))
        if args.command == "run":
            return cmd_run(
                Path(args.config),
                calendar_path_text=args.calendar,
                webhook_env=args.webhook_env,
                telegram_token_env=args.telegram_token_env,
                telegram_chat_id_env=args.telegram_chat_id_env,
            )
        if args.command == "loop":
            return cmd_loop(
                Path(args.config),
                calendar_path_text=args.calendar,
                interval_minutes=args.interval_minutes,
                webhook_env=args.webhook_env,
                telegram_token_env=args.telegram_token_env,
                telegram_chat_id_env=args.telegram_chat_id_env,
                align_to_clock=args.align_to_clock,
            )
        if args.command == "day-trade-playbook":
            return cmd_day_trade_playbook(
                config_path=Path(args.config),
                calendar_path=Path(args.calendar),
                trade_date_text=args.trade_date,
                brief=args.brief,
                reference_price_texts=args.reference_price,
                account_size=args.account_size,
            )
        if args.command == "validate-prices":
            return cmd_validate_prices(
                prices_path=Path(args.prices),
                snapshots_path=Path(args.snapshots),
                horizon_hours=args.horizon_hours,
                min_confidence=args.min_confidence,
                symbol=args.symbol,
                confidence_buckets=args.confidence_buckets,
                min_cohort_samples=args.min_cohort_samples,
                max_ranked_cohorts=args.max_ranked_cohorts,
            )
        if args.command == "telegram-chat-id":
            return cmd_telegram_chat_id(
                token_env=args.token_env,
                limit=args.limit,
            )
        if args.command == "telegram-test":
            return cmd_telegram_test(
                token_env=args.token_env,
                chat_id_env=args.chat_id_env,
                message=args.message,
            )
        parser.error(f"Unsupported command {args.command!r}")
        return 2
    except (FredRequestError, TelegramRequestError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def cmd_verify_series(config_path: Path) -> int:
    client = _build_client()
    config = load_strategy_config(config_path)
    seen: set[str] = set()

    for spec in iter_series_specs(config):
        if spec.series_id or not spec.search_text or spec.search_text in seen:
            continue
        seen.add(spec.search_text)
        print(spec.search_text)
        for match in client.search_series(spec.search_text, limit=3):
            print(f"  - {match.series_id}: {match.title}")
    return 0


def cmd_lock_series(config_path: Path, output_path: Path) -> int:
    client = _build_client()
    raw = load_raw_config(config_path)

    for entity in raw["entities"]:
        for driver in entity["drivers"]:
            series = driver["series"]
            if series.get("series_id") or not series.get("search_text"):
                continue
            match = client.resolve_series(
                SeriesSpec(
                    series_id=series.get("series_id"),
                    search_text=series.get("search_text"),
                )
            )
            series["series_id"] = match.series_id
            series["resolved_title"] = match.title

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    print(f"Wrote locked config to {output_path}")
    return 0


def cmd_run(
    config_path: Path,
    *,
    calendar_path_text: str,
    webhook_env: str,
    telegram_token_env: str,
    telegram_chat_id_env: str,
) -> int:
    config = load_strategy_config(config_path)
    client = _build_client()
    calendar = _load_optional_calendar(calendar_path_text)
    sinks = _build_sinks(
        webhook_env=webhook_env,
        telegram_token_env=telegram_token_env,
        telegram_chat_id_env=telegram_chat_id_env,
    )
    _run_cycle(config, client=client, sinks=sinks, calendar=calendar)
    return 0


def cmd_loop(
    config_path: Path,
    *,
    calendar_path_text: str,
    interval_minutes: int,
    webhook_env: str,
    telegram_token_env: str,
    telegram_chat_id_env: str,
    align_to_clock: bool,
) -> int:
    config = load_strategy_config(config_path)
    client = _build_client()
    sinks = _build_sinks(
        webhook_env=webhook_env,
        telegram_token_env=telegram_token_env,
        telegram_chat_id_env=telegram_chat_id_env,
    )

    while True:
        _run_cycle(
            config,
            client=client,
            sinks=sinks,
            calendar=_load_optional_calendar(calendar_path_text),
        )
        if align_to_clock:
            current_time = datetime.now(tz=UTC)
            next_run_at = _next_interval_boundary(
                now=current_time,
                interval_minutes=max(1, interval_minutes),
            )
            sleep_seconds = max(1.0, (next_run_at - current_time).total_seconds())
        else:
            sleep_seconds = max(1, interval_minutes) * 60
        time.sleep(sleep_seconds)


def cmd_validate_prices(
    *,
    prices_path: Path,
    snapshots_path: Path,
    horizon_hours: list[int],
    min_confidence: float,
    symbol: str,
    confidence_buckets: str,
    min_cohort_samples: int,
    max_ranked_cohorts: int,
) -> int:
    report = validate_snapshot_file(
        snapshots_path=snapshots_path,
        prices_path=prices_path,
        horizon_hours=horizon_hours or [1],
        min_confidence=min_confidence,
        symbol_filter=symbol,
        confidence_bucket_lowers=parse_confidence_bucket_lowers(confidence_buckets),
        min_cohort_samples=min_cohort_samples,
        max_ranked_cohorts=max_ranked_cohorts,
    )
    print(json.dumps(report, indent=2))
    return 0


def cmd_day_trade_playbook(
    *,
    config_path: Path,
    calendar_path: Path,
    trade_date_text: str,
    brief: bool,
    reference_price_texts: list[str],
    account_size: float,
) -> int:
    config = load_strategy_config(config_path)
    calendar = load_release_calendar(calendar_path)
    client = _build_client()
    as_of = datetime.now(tz=UTC)
    reference_prices = _parse_reference_prices(reference_price_texts)
    valid_symbols = {instrument.symbol for instrument in config.instruments}
    unknown_symbols = sorted(set(reference_prices) - valid_symbols)
    if unknown_symbols:
        raise ValueError(
            "Reference prices were supplied for unknown symbols: "
            + ", ".join(unknown_symbols)
            + "."
        )
    if account_size < 0:
        raise ValueError("--account-size must be zero or a positive USD value.")
    results = _score_results(config, client=client, as_of=as_of)
    playbook = generate_day_trade_playbook(
        config=config,
        calendar=calendar,
        results=results,
        trade_date=_parse_trade_date(trade_date_text, as_of=as_of),
        as_of=as_of,
        reference_prices=reference_prices,
        account_size=account_size or None,
    )
    if brief:
        print(format_day_trade_playbook_brief(playbook))
    else:
        print(json.dumps(format_day_trade_playbook_payload(playbook), indent=2))
    return 0


def cmd_telegram_chat_id(*, token_env: str, limit: int) -> int:
    client = _build_telegram_client(token_env=token_env)
    chats = extract_recent_chats(client.get_updates(limit=limit))
    print(json.dumps(chats, indent=2))
    return 0


def cmd_telegram_test(*, token_env: str, chat_id_env: str, message: str) -> int:
    client = _build_telegram_client(token_env=token_env)
    chat_id = _required_env(chat_id_env, description="Telegram chat ID")
    client.send_message(chat_id=chat_id, text=message)
    print(f"Sent Telegram test message to chat {chat_id}.")
    return 0


def _run_cycle(
    config: StrategyConfig,
    *,
    client: FredClient,
    sinks: list[object],
    calendar: ReleaseCalendar | None = None,
) -> None:
    as_of = datetime.now(tz=UTC)
    store = AlertStateStore(
        Path(config.alerting.state_path),
        emit_on_first_run=config.alerting.emit_on_first_run,
    )

    results = _score_results(config, client=client, as_of=as_of)
    snapshot_store = _build_snapshot_store(config)
    if snapshot_store:
        snapshot_store.append_run(as_of=as_of, results=results)
    playbook_items_by_symbol: dict[str, object] = {}
    if config.day_trading is not None:
        playbook = generate_day_trade_playbook(
            config=config,
            calendar=calendar or ReleaseCalendar(events=()),
            results=results,
            trade_date=as_of.astimezone(UTC).date(),
            as_of=as_of,
        )
        journal_store = _build_trade_journal_store(config)
        if journal_store:
            journal_store.append_run(
                strategy_metadata=config.metadata,
                playbook=playbook,
            )
        playbook_items_by_symbol = {
            item.symbol: item
            for item in playbook.items
        }

    for result in results:
        payload = format_alert_payload(
            result,
            playbook_item=playbook_items_by_symbol.get(result.symbol),
        )
        print(json.dumps(payload, indent=2))

        decision = AlertDecision(
            symbol=result.symbol,
            direction=result.direction,
            score=result.score,
            confidence=result.confidence,
        )
        if store.should_emit(decision, min_score_change=config.alerting.min_score_change):
            for sink in sinks:
                sink.emit(payload)


def _build_client() -> FredClient:
    api_key = os.environ.get("FRED_API_KEY", "")
    return FredClient(api_key)


def _build_telegram_client(*, token_env: str) -> TelegramBotClient:
    return TelegramBotClient(
        _required_env(token_env, description="Telegram bot token"),
    )


def _score_results(
    config: StrategyConfig,
    *,
    client: FredClient,
    as_of: datetime,
) -> list[object]:
    series_observations = {
        spec.cache_key: client.get_observations(spec, limit=2)
        for spec in iter_series_specs(config)
    }
    return [
        score_instrument(
            instrument=instrument,
            entities=config.entities,
            series_observations=series_observations,
            as_of=as_of,
        )
        for instrument in config.instruments
    ]


def _load_dotenv_if_present(path: str | Path = ".env") -> None:
    dotenv_path = Path(path)
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _build_sinks(
    webhook_env: str = "",
    telegram_token_env: str = "",
    telegram_chat_id_env: str = "",
) -> list[object]:
    sinks: list[object] = []
    if webhook_env:
        url = os.environ.get(webhook_env, "")
        if url:
            sinks.append(WebhookAlertSink(url))
    if telegram_token_env or telegram_chat_id_env:
        if not telegram_token_env or not telegram_chat_id_env:
            raise ValueError(
                "Telegram delivery requires both --telegram-token-env and --telegram-chat-id-env."
            )
        sinks.append(
            TelegramAlertSink(
                bot_token=_required_env(telegram_token_env, description="Telegram bot token"),
                chat_id=_required_env(telegram_chat_id_env, description="Telegram chat ID"),
            )
        )
    return sinks


def _build_snapshot_store(config: StrategyConfig) -> SnapshotStore | None:
    if not config.research.snapshot_path:
        return None
    return SnapshotStore(Path(config.research.snapshot_path))


def _build_trade_journal_store(config: StrategyConfig) -> PaperTradeJournalStore | None:
    if not config.research.journal_path:
        return None
    return PaperTradeJournalStore(Path(config.research.journal_path))


def _parse_trade_date(trade_date_text: str, *, as_of: datetime) -> date:
    if not trade_date_text:
        return as_of.astimezone(UTC).date()
    return date.fromisoformat(trade_date_text)


def _next_interval_boundary(*, now: datetime, interval_minutes: int) -> datetime:
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be positive.")

    current = now.astimezone(UTC).replace(second=0, microsecond=0)
    midnight = current.replace(hour=0, minute=0)
    minutes_since_midnight = current.hour * 60 + current.minute
    next_slot = ((minutes_since_midnight // interval_minutes) + 1) * interval_minutes
    day_increment, minute_of_day = divmod(next_slot, 24 * 60)
    return midnight + timedelta(days=day_increment, minutes=minute_of_day)


def _required_env(name: str, *, description: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    raise ValueError(f"{description} env var {name!r} is not set.")


def _load_optional_calendar(path_text: str) -> ReleaseCalendar | None:
    if not path_text:
        return None
    return load_release_calendar(path_text)


def _parse_reference_prices(values: list[str]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for raw_value in values:
        if "=" not in raw_value:
            raise ValueError(
                f"Reference price {raw_value!r} is invalid. Use SYMBOL=PRICE, for example EURUSD=1.0825."
            )
        symbol_text, price_text = raw_value.split("=", 1)
        symbol = symbol_text.strip().upper()
        if not symbol:
            raise ValueError("Reference price symbol cannot be empty.")
        try:
            price = float(price_text)
        except ValueError as exc:
            raise ValueError(
                f"Reference price {raw_value!r} is invalid. PRICE must be numeric."
            ) from exc
        if price <= 0:
            raise ValueError(f"Reference price for {symbol} must be positive.")
        prices[symbol] = price
    return prices


if __name__ == "__main__":
    sys.exit(main())
