import json
import multiprocessing
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from Model.views import (
    GEOCODER_REQUEST_INTERVAL_SECONDS,
    _reserve_geocoder_request,
    _validated_geocoder_url,
)


def make_upstream_response(payload, status_code=200, headers=None, chunks=None):
    body = (
        payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    )
    response = MagicMock(status_code=status_code, headers=headers or {})
    response.raise_for_status.return_value = None
    response.iter_content.return_value = chunks or [body]
    return response


class GeocodeApiTests(SimpleTestCase):
    def setUp(self):
        self.cache_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache_directory.cleanup)
        self.settings_override = override_settings(
            CACHES={
                "default": {
                    "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                    "LOCATION": "geocoder-tests",
                },
                "geocoder": {
                    "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
                    "LOCATION": self.cache_directory.name,
                    "MAX_ENTRIES": 100,
                },
            },
            SAFEPATH_CACHE_DIR=self.cache_directory.name,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        caches["geocoder"].clear()
        self.reservation_patcher = patch("Model.views._reserve_geocoder_request")
        self.reservation = self.reservation_patcher.start()
        self.addCleanup(self.reservation_patcher.stop)

    def test_requires_a_meaningful_query(self):
        response = self.client.get("/api/geocode/", {"q": "a"}, HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 400)

    def test_returns_validated_results(self):
        upstream = make_upstream_response(
            [
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
        )

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
        self.assertTrue(get.call_args.kwargs["stream"])
        self.assertEqual(get.call_args.kwargs["params"]["q"], "sample place")
        self.reservation.assert_called_once_with()

    def test_caches_normalized_queries(self):
        upstream = make_upstream_response(
            [
                {
                    "lat": "28.4748",
                    "lon": "77.4764",
                    "display_name": "Sample place, Delhi",
                }
            ]
        )

        with patch("Model.views.requests.get", return_value=upstream) as get:
            first = self.client.get(
                "/api/geocode/",
                {"q": "  Cafe\u0301   PLACE  "},
                HTTP_HOST="localhost",
            )
            second = self.client.get(
                "/api/geocode/",
                {"q": "café place"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["results"], first.json()["results"])
        self.assertEqual(get.call_args.kwargs["params"]["q"], "café place")
        get.assert_called_once()
        self.reservation.assert_called_once_with()

    def test_caches_successful_empty_results(self):
        upstream = make_upstream_response([])

        with patch("Model.views.requests.get", return_value=upstream) as get:
            first = self.client.get(
                "/api/geocode/",
                {"q": "missing place"},
                HTTP_HOST="localhost",
            )
            second = self.client.get(
                "/api/geocode/",
                {"q": "missing place"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["results"], [])
        self.assertEqual(second.json()["results"], [])
        get.assert_called_once()

    def test_rejects_malformed_payload_without_caching_it(self):
        upstream = make_upstream_response({"error": "unexpected response"})

        with patch("Model.views.requests.get", return_value=upstream) as get:
            first = self.client.get(
                "/api/geocode/",
                {"q": "malformed place"},
                HTTP_HOST="localhost",
            )
            second = self.client.get(
                "/api/geocode/",
                {"q": "malformed place"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(first.status_code, 503)
        self.assertEqual(first.json()["code"], "invalid_provider_response")
        self.assertEqual(second.status_code, 503)
        self.assertEqual(get.call_count, 2)

    def test_rejects_invalid_only_result_list_without_caching_it(self):
        upstream = make_upstream_response([{"lat": "not-a-number", "lon": "77.4764"}])

        with patch("Model.views.requests.get", return_value=upstream) as get:
            first = self.client.get(
                "/api/geocode/",
                {"q": "invalid place"},
                HTTP_HOST="localhost",
            )
            second = self.client.get(
                "/api/geocode/",
                {"q": "invalid place"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(first.status_code, 503)
        self.assertEqual(second.status_code, 503)
        self.assertEqual(get.call_count, 2)

    def test_rejects_boolean_coordinates_without_caching_them(self):
        upstream = make_upstream_response([{"lat": True, "lon": False}])

        with patch("Model.views.requests.get", return_value=upstream) as get:
            first = self.client.get(
                "/api/geocode/",
                {"q": "boolean place"},
                HTTP_HOST="localhost",
            )
            second = self.client.get(
                "/api/geocode/",
                {"q": "boolean place"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(first.status_code, 503)
        self.assertEqual(second.status_code, 503)
        self.assertEqual(get.call_count, 2)

    def test_rejects_deeply_nested_json_without_crashing(self):
        upstream = make_upstream_response(b"[" * 10000 + b"]" * 10000)

        with patch("Model.views.requests.get", return_value=upstream):
            response = self.client.get(
                "/api/geocode/",
                {"q": "nested place"},
                HTTP_HOST="localhost",
                raise_request_exception=False,
            )

        self.assertEqual(response.status_code, 503)

    def test_rejects_huge_coordinate_integers_without_crashing(self):
        upstream = make_upstream_response(
            [{"lat": 10**400, "lon": "77.4764", "display_name": "Invalid place"}]
        )

        with patch("Model.views.requests.get", return_value=upstream):
            response = self.client.get(
                "/api/geocode/",
                {"q": "huge coordinate"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 503)

    def test_rejects_oversized_geocoder_response(self):
        upstream = make_upstream_response(
            b"",
            chunks=[b"x" * (64 * 1024 + 1)],
        )

        with patch("Model.views.requests.get", return_value=upstream):
            response = self.client.get(
                "/api/geocode/",
                {"q": "oversized place"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 503)

    def test_rejects_oversized_declared_geocoder_response(self):
        upstream = make_upstream_response(
            [],
            headers={"Content-Length": str(64 * 1024 + 1)},
        )

        with patch("Model.views.requests.get", return_value=upstream):
            response = self.client.get(
                "/api/geocode/",
                {"q": "oversized place"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 503)

    def test_does_not_cache_provider_failures(self):
        upstream = make_upstream_response(
            [
                {
                    "lat": "28.4748",
                    "lon": "77.4764",
                    "display_name": "Sample place, Delhi",
                }
            ]
        )

        with patch(
            "Model.views.requests.get",
            side_effect=[requests.RequestException("temporary failure"), upstream],
        ) as get:
            failed = self.client.get(
                "/api/geocode/",
                {"q": "retry place"},
                HTTP_HOST="localhost",
            )
            recovered = self.client.get(
                "/api/geocode/",
                {"q": "retry place"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.json()["code"], "geocoder_unavailable")
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(get.call_count, 2)

    def test_cache_read_failure_does_not_block_provider_search(self):
        upstream = make_upstream_response([])

        with (
            patch.object(caches["geocoder"], "get", side_effect=OSError),
            patch("Model.views.requests.get", return_value=upstream),
        ):
            response = self.client.get(
                "/api/geocode/",
                {"q": "cache unavailable"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    def test_cache_write_failure_does_not_block_provider_result(self):
        upstream = make_upstream_response(
            [
                {
                    "lat": "28.4748",
                    "lon": "77.4764",
                    "display_name": "Sample place, Delhi",
                }
            ]
        )

        with (
            patch.object(caches["geocoder"], "set", side_effect=OSError),
            patch("Model.views.requests.get", return_value=upstream),
        ):
            response = self.client.get(
                "/api/geocode/",
                {"q": "cache write unavailable"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_corrupt_cached_value_is_ignored(self):
        upstream = make_upstream_response([])

        with (
            patch.object(caches["geocoder"], "get", return_value={"invalid": "value"}),
            patch("Model.views.requests.get", return_value=upstream) as get,
        ):
            response = self.client.get(
                "/api/geocode/",
                {"q": "corrupt cache"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 200)
        get.assert_called_once()

    def test_request_lock_failure_returns_generic_service_error(self):
        self.reservation.side_effect = OSError("lock unavailable")

        with patch("Model.views.requests.get") as get:
            response = self.client.get(
                "/api/geocode/",
                {"q": "lock unavailable"},
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "geocoder_unavailable")
        self.assertNotIn("invalid response", response.content.decode())
        get.assert_not_called()

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

    def test_invalid_lock_timestamp_fails_closed(self):
        lock_path = Path(self.cache_directory.name) / "geocoder-request.lock"

        for timestamp in ("garbage", "-1", "nan", "inf"):
            with self.subTest(timestamp=timestamp):
                lock_path.write_text(timestamp, encoding="ascii")
                with self.assertRaisesRegex(OSError, "request lock is invalid"):
                    _reserve_geocoder_request()

    @override_settings(SAFEPATH_GEOCODER_URL="http://127.0.0.1/search")
    def test_rejects_non_https_provider_url(self):
        with self.assertRaises(ValueError):
            _validated_geocoder_url()


class GeocoderPacingTests(SimpleTestCase):
    def test_production_interval_is_one_second(self):
        self.assertEqual(GEOCODER_REQUEST_INTERVAL_SECONDS, 1.0)

    def test_coordinates_worker_processes_through_shared_lock(self):
        if "fork" not in multiprocessing.get_all_start_methods():
            self.skipTest("The shared file lock requires a POSIX fork context.")

        with tempfile.TemporaryDirectory() as cache_directory:
            with (
                override_settings(SAFEPATH_CACHE_DIR=cache_directory),
                patch("Model.views.GEOCODER_REQUEST_INTERVAL_SECONDS", 0.05),
            ):
                context = multiprocessing.get_context("fork")
                queue = context.Queue()
                processes = [
                    context.Process(target=_reserve_slot_in_process, args=(queue,))
                    for _ in range(2)
                ]
                for process in processes:
                    process.start()
                for process in processes:
                    process.join(timeout=5)
                    self.assertEqual(process.exitcode, 0)
                starts = [queue.get(timeout=1) for _ in processes]

        self.assertGreaterEqual(abs(starts[0] - starts[1]), 0.04)


def _reserve_slot_in_process(queue):
    queue.put(_reserve_geocoder_request())
