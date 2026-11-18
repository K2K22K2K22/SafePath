import logging
import os
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.views.defaults import page_not_found, server_error

from Model.utils.osm_graph import RoadDataUnavailable
from Model.utils.route_service import RouteNotFound, RouteOption
from Model.utils.routing import SearchLimitExceeded
from Model.views import RoutesRateThrottle


def route_option():
    return RouteOption(
        route_id="route-1",
        labels=("shortest",),
        algorithm="dijkstra",
        beta=0.0,
        node_ids=("A", "B"),
        edge_ids=("A-B",),
        geometry=((28.475, 77.477), (28.476, 77.477)),
        distance_meters=111.2,
        duration_seconds=12.5,
        risk_score=None,
        safety_score=None,
        risk_level="unknown",
        risk_data_available=False,
        incident_coverage_ratio=0.0,
        nodes_explored=2,
        computation_time_ms=1.25,
        path_cost=111.2,
        shared_interior_edge_ratio=0.0,
        explanation="Minimum road-edge distance in the loaded graph.",
    )


class HealthEndpointTests(SimpleTestCase):
    def test_liveness_endpoints_do_not_check_dependencies(self):
        self.client.cookies["sessionid"] = "private-session"
        with (
            patch("Model.views.connections") as connections,
            patch("Model.views.requests.get") as provider_request,
            patch(
                "django.contrib.sessions.backends.db.SessionStore.load"
            ) as session_load,
        ):
            for path in ("/health/", "/health/live/"):
                with self.subTest(path=path):
                    response = self.client.get(path, HTTP_HOST="localhost")
                    self.assertEqual(response.status_code, 200)

        connections.assert_not_called()
        provider_request.assert_not_called()
        session_load.assert_not_called()

    def test_readiness_checks_only_the_database(self):
        self.client.cookies["sessionid"] = "private-session"
        with (
            patch("Model.views.connections") as connections,
            patch("Model.views.requests.get") as provider_request,
            patch(
                "django.contrib.sessions.backends.db.SessionStore.load"
            ) as session_load,
        ):
            response = self.client.get("/health/ready/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})
        connections.__getitem__.assert_called_once_with("default")
        provider_request.assert_not_called()
        session_load.assert_not_called()

    def test_readiness_fails_without_exposing_database_errors(self):
        with patch("Model.views.connections") as connections:
            connections.__getitem__.return_value.cursor.side_effect = OSError(
                "password=private-value"
            )
            response = self.client.get("/health/ready/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_ready")
        self.assertNotIn("private-value", response.content.decode())


class ApiErrorTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    route_params = {
        "start_lat": "28.475",
        "start_lon": "77.477",
        "end_lat": "28.476",
        "end_lon": "77.477",
    }

    def test_validation_errors_have_a_stable_code(self):
        response = self.client.get("/api/routes/", {}, HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_request")

    def test_route_failures_have_distinct_codes(self):
        failures = (
            (RouteNotFound("no route"), 404, "route_not_found"),
            (
                RoadDataUnavailable("provider failed"),
                503,
                "road_provider_unavailable",
            ),
            (
                SearchLimitExceeded("search limit"),
                503,
                "search_limit_exceeded",
            ),
        )

        for error, status, code in failures:
            with self.subTest(code=code):
                with patch(
                    "Model.views.calculate_route_options",
                    side_effect=error,
                ):
                    response = self.client.get(
                        "/api/routes/",
                        self.route_params,
                        HTTP_HOST="localhost",
                    )

                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["code"], code)

    def test_rate_limit_response_has_a_stable_code(self):
        with (
            patch(
                "Model.views.calculate_route_options",
                return_value=[route_option()],
            ),
            patch.object(
                RoutesRateThrottle,
                "THROTTLE_RATES",
                {"routes": "1/minute"},
            ),
        ):
            first = self.client.get(
                "/api/routes/",
                self.route_params,
                HTTP_HOST="localhost",
            )
            second = self.client.get(
                "/api/routes/",
                self.route_params,
                HTTP_HOST="localhost",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["code"], "rate_limit_exceeded")

    def test_unexpected_errors_return_a_generic_response_and_safe_log(self):
        secret = "database-password=private-value"
        with patch(
            "Model.views.calculate_route_options",
            side_effect=RuntimeError(secret),
        ):
            with self.assertLogs("safepath.errors", level="ERROR") as logs:
                response = self.client.get(
                    "/api/routes/",
                    self.route_params,
                    HTTP_HOST="localhost",
                )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], "internal_error")
        self.assertNotIn(secret, response.content.decode())
        self.assertNotIn(secret, "\n".join(logs.output))

    def test_query_values_are_not_written_to_error_logs(self):
        with patch(
            "Model.views.calculate_route_options",
            side_effect=RuntimeError("upstream failed"),
        ):
            with self.assertLogs("safepath.errors", level="ERROR") as logs:
                response = self.client.get(
                    "/api/routes/?q=private-place",
                    self.route_params,
                    HTTP_HOST="localhost",
                )

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private-place", "\n".join(logs.output))

    def test_expected_validation_errors_do_not_create_error_logs(self):
        with self.assertNoLogs("safepath.errors", level="WARNING"):
            response = self.client.get("/api/routes/", {}, HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 400)


class OperationsLoggingTests(SimpleTestCase):
    def test_third_party_logs_use_the_safe_root_handler(self):
        self.assertEqual(settings.LOGGING["root"]["handlers"], ["stdout"])
        self.assertEqual(
            settings.LOGGING["handlers"]["stdout"]["formatter"],
            "safe",
        )

    def test_gunicorn_access_log_excludes_the_query_string(self):
        config_path = Path(settings.BASE_DIR) / "gunicorn.conf.py"
        with patch.dict(os.environ, {}, clear=True):
            config = runpy.run_path(str(config_path))

        self.assertIn("%(U)s", config["access_log_format"])
        self.assertNotIn("%(r)s", config["access_log_format"])
        self.assertTrue(config["control_socket_disable"])

    def test_log_formatter_redacts_query_values_and_exception_text(self):
        from safepath_backend.logging import SafeLogFormatter

        formatter = SafeLogFormatter("%(message)s")
        record = logging.LogRecord(
            "safepath.errors",
            logging.ERROR,
            __file__,
            1,
            "request https://example.test/api/geocode/?q=private-place",
            (),
            None,
        )

        formatted = formatter.format(record)
        self.assertNotIn("private-place", formatted)
        self.assertIn("/api/geocode/", formatted)

    def test_log_formatter_redacts_credentials_and_standalone_query_values(self):
        from safepath_backend.logging import redact_query_values

        message = redact_query_values(
            "database=postgres://admin:hunter2@db.example/safepath "
            "password=private-value q=private-place"
        )

        self.assertNotIn("hunter2", message)
        self.assertNotIn("private-value", message)
        self.assertNotIn("private-place", message)
        self.assertIn("[redacted]", message)

    def test_log_formatter_redacts_authorization_credentials(self):
        from safepath_backend.logging import redact_query_values

        for credential in (
            "authorization=Bearer private-token",
            "authorization=Basic private-token",
            "authorization=private-token",
            '"authorization": "Bearer private-token"',
            'authorization="Bearer private token"',
            "Authorization: Bearer private-token,private-tail",
        ):
            with self.subTest(credential=credential):
                message = redact_query_values(credential)
                self.assertNotIn("private-token", message)
                self.assertIn("[redacted]", message)

    def test_log_formatter_redacts_prefixed_and_space_containing_values(self):
        from safepath_backend.logging import redact_query_values

        message = redact_query_values(
            "oauth_token=private-token GET /api/geocode/?q=New York NY HTTP/1.1"
        )

        self.assertNotIn("private-token", message)
        self.assertNotIn("New York NY", message)
        self.assertIn("[redacted]", message)

    def test_log_formatter_redacts_exception_text(self):
        from safepath_backend.logging import SafeLogFormatter

        formatter = SafeLogFormatter("%(message)s")
        try:
            raise RuntimeError("password=private-value")
        except RuntimeError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            "safepath.errors",
            logging.ERROR,
            __file__,
            1,
            "Unexpected failure",
            (),
            exc_info,
        )

        formatted = formatter.format(record)
        self.assertNotIn("private-value", formatted)
        self.assertIn("RuntimeError: [details redacted]", formatted)

    def test_log_formatter_redacts_exception_text_before_query_redaction(self):
        from safepath_backend.logging import SafeLogFormatter

        formatter = SafeLogFormatter("%(message)s")
        try:
            raise RuntimeError("upstream GET https://example.test/api?q=private failed")
        except RuntimeError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            "gunicorn.error",
            logging.ERROR,
            __file__,
            1,
            f"Failed: {exc_info[1]}",
            (),
            exc_info,
        )

        formatted = formatter.format(record)
        self.assertNotIn("upstream GET", formatted)
        self.assertNotIn("private", formatted)
        self.assertIn("[details redacted]", formatted)

    def test_log_formatter_redacts_exception_used_as_log_message(self):
        from safepath_backend.logging import SafeLogFormatter

        formatter = SafeLogFormatter("%(message)s")
        try:
            raise RuntimeError("private failure")
        except RuntimeError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            "gunicorn.error",
            logging.ERROR,
            __file__,
            1,
            f"Failed: {exc_info[1]}",
            (),
            exc_info,
        )

        formatted = formatter.format(record)
        self.assertNotIn("private failure", formatted)
        self.assertIn("[details redacted]", formatted)


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
class ErrorPageTests(SimpleTestCase):
    def test_missing_page_uses_the_404_template(self):
        request = RequestFactory().get("/missing-page/")
        response = page_not_found(request, Http404())

        self.assertEqual(response.status_code, 404)
        self.assertIn("Page not found", response.content.decode())

    def test_unhandled_view_error_uses_the_500_template(self):
        request = RequestFactory().get("/")
        response = server_error(request)

        self.assertEqual(response.status_code, 500)
        content = response.content.decode()
        self.assertIn("Something went wrong", content)
        self.assertNotIn("private failure", content)
