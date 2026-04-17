from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib import error, parse, request


class MarketDataRequestError(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketPriceQuote:
    symbol: str
    provider_symbol: str
    price: float
    as_of_utc: datetime


class TwelveDataClient:
    """Minimal Twelve Data client for live spot prices.

    Sources:
    - https://twelvedata.com/docs
    - https://twelvedata.com/commodities
    - https://twelvedata.com/pricing
    """

    def __init__(
        self,
        api_key: str,
        *,
        max_retries: int = 2,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        if not api_key:
            raise ValueError("TWELVEDATA_API_KEY is required.")
        self.api_key = api_key
        self.base_url = "https://api.twelvedata.com"
        self.max_retries = max(0, max_retries)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)

    def get_price(self, symbol: str) -> MarketPriceQuote:
        normalized_symbol = symbol.strip().upper()
        provider_symbol = to_twelve_data_symbol(normalized_symbol)
        payload = self._get_json(
            "/price",
            {
                "symbol": provider_symbol,
                "dp": "11",
            },
            request_label=provider_symbol,
        )
        price_text = str(payload.get("price", "")).strip()
        if not price_text:
            raise MarketDataRequestError(
                f"Twelve Data price response for {provider_symbol} did not include a price."
            )
        return MarketPriceQuote(
            symbol=normalized_symbol,
            provider_symbol=provider_symbol,
            price=float(price_text),
            as_of_utc=datetime.now(tz=UTC),
        )

    def get_prices(self, symbols: list[str] | tuple[str, ...]) -> dict[str, MarketPriceQuote]:
        return {
            symbol.strip().upper(): self.get_price(symbol.strip().upper())
            for symbol in symbols
        }

    def get_prices_best_effort(
        self,
        symbols: list[str] | tuple[str, ...],
    ) -> tuple[dict[str, MarketPriceQuote], dict[str, str]]:
        quotes: dict[str, MarketPriceQuote] = {}
        errors_by_symbol: dict[str, str] = {}
        for symbol in symbols:
            normalized_symbol = symbol.strip().upper()
            try:
                quotes[normalized_symbol] = self.get_price(normalized_symbol)
            except MarketDataRequestError as exc:
                errors_by_symbol[normalized_symbol] = str(exc)
        return quotes, errors_by_symbol

    def _get_json(
        self,
        endpoint: str,
        params: dict[str, str],
        *,
        request_label: str = "",
    ) -> dict[str, object]:
        query = {**params}
        url = f"{self.base_url}{endpoint}?{parse.urlencode(query)}"
        request_obj = request.Request(
            url,
            headers={
                "Authorization": f"apikey {self.api_key}",
                "User-Agent": "fundamental-bias-alerts/0.7.0 (+https://github.com/hbello5333/fundamental-bias-alerts)",
                "Accept": "application/json",
            },
            method="GET",
        )

        for attempt in range(self.max_retries + 1):
            try:
                with request.urlopen(request_obj, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if str(payload.get("status", "")).lower() == "error":
                    raise MarketDataRequestError(
                        f"Twelve Data request failed for {request_label or endpoint}: "
                        f"{payload.get('message', 'unknown error')}"
                    )
                return payload
            except error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= self.max_retries:
                    detail = exc.read().decode("utf-8", errors="replace").strip()
                    suffix = f": {detail}" if detail else ""
                    raise MarketDataRequestError(
                        f"Twelve Data request failed for {request_label or endpoint} "
                        f"with HTTP {exc.code} {exc.reason}{suffix}"
                    ) from exc
            except error.URLError as exc:
                if attempt >= self.max_retries:
                    raise MarketDataRequestError(
                        f"Twelve Data request failed for {request_label or endpoint}: {exc.reason}"
                    ) from exc

            delay_seconds = self.retry_delay_seconds * (attempt + 1)
            if delay_seconds > 0.0:
                time.sleep(delay_seconds)

        raise MarketDataRequestError(
            f"Twelve Data request failed for {request_label or endpoint}"
        )


def to_twelve_data_symbol(symbol: str) -> str:
    normalized_symbol = symbol.strip().upper().replace("/", "")
    if len(normalized_symbol) != 6:
        raise ValueError(
            "Twelve Data symbol conversion expects a six-character pair like EURUSD or XAUUSD."
        )
    return f"{normalized_symbol[:3]}/{normalized_symbol[3:]}"
