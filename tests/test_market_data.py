from __future__ import annotations

import io
import unittest
from unittest import mock
from urllib.error import HTTPError

from fundamental_bias_alerts.market_data import (
    MarketDataRequestError,
    TwelveDataClient,
    to_twelve_data_symbol,
)


class MarketDataClientTests(unittest.TestCase):
    @mock.patch("fundamental_bias_alerts.market_data.request.urlopen")
    def test_get_price_uses_twelve_data_pair_format(
        self,
        mock_urlopen: mock.Mock,
    ) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"price": "1.08250"}'
        mock_urlopen.return_value = response

        client = TwelveDataClient("test-key", max_retries=0, retry_delay_seconds=0.0)
        quote = client.get_price("EURUSD")

        request_target = mock_urlopen.call_args.args[0]
        self.assertIn("symbol=EUR%2FUSD", request_target.full_url)
        self.assertEqual(request_target.get_header("Authorization"), "apikey test-key")
        self.assertEqual(quote.symbol, "EURUSD")
        self.assertEqual(quote.provider_symbol, "EUR/USD")
        self.assertAlmostEqual(quote.price, 1.0825, places=6)

    @mock.patch("fundamental_bias_alerts.market_data.request.urlopen")
    def test_get_price_reports_provider_symbol_on_final_http_error(
        self,
        mock_urlopen: mock.Mock,
    ) -> None:
        mock_urlopen.side_effect = HTTPError(
            url="https://example.test",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(b'{"status":"error","message":"forbidden"}'),
        )
        self.addCleanup(mock_urlopen.side_effect.close)
        client = TwelveDataClient("test-key", max_retries=0, retry_delay_seconds=0.0)

        with self.assertRaises(MarketDataRequestError) as context:
            client.get_price("XAUUSD")

        self.assertIn("XAU/USD", str(context.exception))
        self.assertIn("HTTP 403", str(context.exception))

    def test_symbol_conversion_supports_supported_pairs(self) -> None:
        self.assertEqual(to_twelve_data_symbol("eurusd"), "EUR/USD")
        self.assertEqual(to_twelve_data_symbol("BTCUSD"), "BTC/USD")
        self.assertEqual(to_twelve_data_symbol("XAUUSD"), "XAU/USD")

    def test_symbol_conversion_rejects_invalid_shapes(self) -> None:
        with self.assertRaisesRegex(ValueError, "six-character pair"):
            to_twelve_data_symbol("SPX")

    @mock.patch("fundamental_bias_alerts.market_data.request.urlopen")
    def test_get_prices_best_effort_returns_quotes_and_errors(
        self,
        mock_urlopen: mock.Mock,
    ) -> None:
        success_response = mock.MagicMock()
        success_response.__enter__.return_value.read.return_value = b'{"price": "1.08250"}'
        failed_response = HTTPError(
            url="https://example.test",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(b'{"status":"error","message":"forbidden"}'),
        )
        self.addCleanup(failed_response.close)
        mock_urlopen.side_effect = [success_response, failed_response]

        client = TwelveDataClient("test-key", max_retries=0, retry_delay_seconds=0.0)
        quotes, errors_by_symbol = client.get_prices_best_effort(["EURUSD", "XAUUSD"])

        self.assertEqual(sorted(quotes.keys()), ["EURUSD"])
        self.assertIn("XAUUSD", errors_by_symbol)
