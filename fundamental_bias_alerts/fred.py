from __future__ import annotations

import json
import time
from datetime import datetime
from urllib import error, parse, request

from .models import Observation, ResolvedSeries, SeriesSpec


class FredRequestError(RuntimeError):
    pass


class FredClient:
    """Minimal FRED client.

    Sources:
    - https://fred.stlouisfed.org/docs/api/fred/series_observations.html
    - https://fred.stlouisfed.org/docs/api/fred/series_search.html
    - https://fred.stlouisfed.org/docs/api/fred/realtime_period.html
    """

    def __init__(
        self,
        api_key: str,
        *,
        max_retries: int = 2,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        if not api_key:
            raise ValueError("FRED_API_KEY is required.")
        self.api_key = api_key
        self.base_url = "https://api.stlouisfed.org/fred"
        self.max_retries = max(0, max_retries)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)

    def search_series(self, search_text: str, *, limit: int = 3) -> list[ResolvedSeries]:
        payload = self._get_json(
            "/series/search",
            {
                "search_text": search_text,
                "limit": str(limit),
                "order_by": "search_rank",
                "sort_order": "desc",
            },
            request_label=search_text,
        )
        results = []
        for item in payload.get("seriess", []):
            results.append(
                ResolvedSeries(
                    series_id=item["id"],
                    title=item["title"],
                    frequency=item.get("frequency"),
                    units=item.get("units"),
                )
            )
        return results

    def resolve_series(self, spec: SeriesSpec) -> ResolvedSeries:
        if spec.series_id:
            return ResolvedSeries(series_id=spec.series_id, title=spec.series_id)
        if not spec.search_text:
            raise ValueError("SeriesSpec requires series_id or search_text.")
        matches = self.search_series(spec.search_text, limit=1)
        if not matches:
            raise ValueError(f"No FRED series found for search_text={spec.search_text!r}")
        return matches[0]

    def get_observations(
        self,
        spec: SeriesSpec,
        *,
        limit: int = 2,
        observation_end: datetime | None = None,
        realtime_end: datetime | None = None,
    ) -> list[Observation]:
        resolved = self.resolve_series(spec)
        params = {
            "series_id": resolved.series_id,
            "limit": str(limit),
            "sort_order": "desc",
        }
        if observation_end is not None:
            params["observation_end"] = observation_end.date().isoformat()
        if realtime_end is not None:
            params["realtime_start"] = realtime_end.date().isoformat()
            params["realtime_end"] = realtime_end.date().isoformat()

        payload = self._get_json(
            "/series/observations",
            params,
            request_label=resolved.series_id,
        )
        observations: list[Observation] = []
        for item in payload.get("observations", []):
            value = item.get("value")
            if value in (None, "."):
                continue
            observations.append(
                Observation(
                    date=item["date"],
                    value=float(value),
                )
            )
        return observations

    def _get_json(
        self,
        endpoint: str,
        params: dict[str, str],
        *,
        request_label: str = "",
    ) -> dict[str, object]:
        query = {
            "api_key": self.api_key,
            "file_type": "json",
            **params,
        }
        url = f"{self.base_url}{endpoint}?{parse.urlencode(query)}"

        for attempt in range(self.max_retries + 1):
            try:
                with request.urlopen(url, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))
            except error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= self.max_retries:
                    detail = exc.read().decode("utf-8", errors="replace").strip()
                    suffix = f": {detail}" if detail else ""
                    raise FredRequestError(
                        f"FRED request failed for {request_label or endpoint} "
                        f"with HTTP {exc.code} {exc.reason}{suffix}"
                    ) from exc
            except error.URLError as exc:
                if attempt >= self.max_retries:
                    raise FredRequestError(
                        f"FRED request failed for {request_label or endpoint}: {exc.reason}"
                    ) from exc

            delay_seconds = self.retry_delay_seconds * (attempt + 1)
            if delay_seconds > 0.0:
                time.sleep(delay_seconds)

        raise FredRequestError(f"FRED request failed for {request_label or endpoint}")
