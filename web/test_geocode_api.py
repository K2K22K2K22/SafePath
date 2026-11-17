from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase, override_settings

from Model.views import _validated_geocoder_url


class GeocodeApiTests(SimpleTestCase):
    def test_requires_a_meaningful_query(self):
        response = self.client.get("/api/geocode/", {"q": "a"}, HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 400)

    def test_returns_validated_results(self):
        upstream = MagicMock(status_code=200)
        upstream.json.return_value = [
            {
                "lat": "28.4748",
                "lon": "77.4764",
                "display_name": "Sample place, Delhi",
            },
            {
                "lat": "not-a-number",
                "lon": "77.4764",
                "display_name": "Invalid place",
            },
        ]
        upstream.raise_for_status.return_value = None

        with patch("Model.views.requests.get", return_value=upstream) as get:
            response = self.client.get(
                "/api/geocode/",
                {"q": "sample place"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["lat"], 28.4748)
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertEqual(get.call_args.kwargs["params"]["q"], "sample place")

    def test_returns_service_error_without_exposing_upstream_details(self):
        with patch(
            "Model.views.requests.get",
            side_effect=requests.RequestException("private upstream detail"),
        ):
            response = self.client.get(
                "/api/geocode/",
                {"q": "sample place"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private upstream detail", response.content.decode())

    def test_rejects_redirects(self):
        upstream = MagicMock(status_code=302)

        with patch("Model.views.requests.get", return_value=upstream):
            response = self.client.get(
                "/api/geocode/",
                {"q": "sample place"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 503)

    @override_settings(SAFEPATH_GEOCODER_URL="http://127.0.0.1/search")
    def test_rejects_non_https_provider_url(self):
        with self.assertRaises(ValueError):
            _validated_geocoder_url()
