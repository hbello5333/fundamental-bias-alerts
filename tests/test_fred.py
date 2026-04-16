from __future__ import annotations

import io
import unittest
from unittest import mock
from urllib.error import HTTPError

from fundamental_bias_alerts.fred import FredClient, FredRequestError
from fundamental_bias_alerts.models import SeriesSpec


class FredClientTests(unittest.TestCase):
    @mock.patch("fundamental_bias_alerts.fred.time.sleep")
    @mock.patch("fundamental_bias_alerts.fred.request.urlopen")
    def test_get_observations_retries_transient_http_error(
        self,
        mock_urlopen: mock.Mock,
        mock_sleep: mock.Mock,
    ) -> None:
        first_error = HTTPError(
            url="https://example.test",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=io.BytesIO(b"temporary outage"),
        )
        self.addCleanup(first_error.close)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"observations": []}'
        mock_urlopen.side_effect = [first_error, response]

        client = FredClient("test-key", max_retries=1, retry_delay_seconds=0.0)
        observations = client.get_observations(SeriesSpec(series_id="DFF"))

        self.assertEqual(observations, [])
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_not_called()

    @mock.patch("fundamental_bias_alerts.fred.request.urlopen")
    def test_get_observations_reports_series_id_on_final_http_error(
        self,
        mock_urlopen: mock.Mock,
    ) -> None:
        mock_urlopen.side_effect = HTTPError(
            url="https://example.test",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=io.BytesIO(b"temporary outage"),
        )
        self.addCleanup(mock_urlopen.side_effect.close)
        client = FredClient("test-key", max_retries=0, retry_delay_seconds=0.0)

        with self.assertRaises(FredRequestError) as context:
            client.get_observations(SeriesSpec(series_id="DFF"))

        self.assertIn("DFF", str(context.exception))
        self.assertIn("HTTP 500", str(context.exception))
