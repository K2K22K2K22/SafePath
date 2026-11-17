from dataclasses import replace
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from Model.utils.osm_graph import RoadDataUnavailable
from Model.utils.route_service import RouteNotFound, RouteOption
from Model.views import RoutesRateThrottle


def route_option():
    return RouteOption(
        route_id="route-1",
        labels=("safest",),
        algorithm="modified_astar",
        beta=8.0,
        node_ids=("A", "B"),
        edge_ids=("A-B",),
        geometry=((28.475, 77.477), (28.476, 77.477)),
        distance_meters=111.2,
        duration_seconds=12.5,
        risk_score=0.1,
        safety_score=90,
        risk_level="low",
        risk_data_available=True,
        incident_coverage_ratio=1.0,
        nodes_explored=4,
        computation_time_ms=1.25,
        path_cost=1000.1,
        shared_interior_edge_ratio=0.0,
        explanation="Lowest safety-weighted cost among the generated routes.",
    )


class RoutesApiTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_returns_structured_route_contract(self):
        with patch(
            "Model.views.calculate_route_options", return_value=[route_option()]
        ):
            response = self.client.get(
                "/api/routes/",
                {
                    "start_lat": "28.475",
                    "start_lon": "77.477",
                    "end_lat": "28.476",
                    "end_lon": "77.477",
                },
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["route_count"], 1)
        self.assertEqual(data["routes"][0]["distance_meters"], 111.2)
        self.assertEqual(data["routes"][0]["distance_km"], 0.1112)
        self.assertEqual(data["routes"][0]["labels"], ["safest"])
        self.assertEqual(data["routes"][0]["geometry"][0], [28.475, 77.477])

    def test_rejects_missing_or_invalid_coordinates(self):
        for params in [
            {},
            {
                "start_lat": "not-a-number",
                "start_lon": "77.477",
                "end_lat": "28.476",
                "end_lon": "77.477",
            },
            {
                "start_lat": "91",
                "start_lon": "77.477",
                "end_lat": "28.476",
                "end_lon": "77.477",
            },
        ]:
            response = self.client.get("/api/routes/", params, HTTP_HOST="localhost")
            self.assertEqual(response.status_code, 400)

    def test_returns_service_unavailable_when_road_data_fails(self):
        with patch(
            "Model.views.calculate_route_options",
            side_effect=RoadDataUnavailable("upstream failed"),
        ):
            response = self.client.get(
                "/api/routes/",
                {
                    "start_lat": "28.475",
                    "start_lon": "77.477",
                    "end_lat": "28.476",
                    "end_lon": "77.477",
                },
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 503)

    def test_returns_not_found_when_graph_has_no_route(self):
        with patch(
            "Model.views.calculate_route_options",
            side_effect=RouteNotFound("no route"),
        ):
            response = self.client.get(
                "/api/routes/",
                {
                    "start_lat": "28.475",
                    "start_lon": "77.477",
                    "end_lat": "28.476",
                    "end_lon": "77.477",
                },
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 404)

    def test_returns_bad_request_for_excessive_route_span(self):
        with patch(
            "Model.views.calculate_route_options",
            side_effect=ValueError("Route span is too large."),
        ):
            response = self.client.get(
                "/api/routes/",
                {
                    "start_lat": "28.475",
                    "start_lon": "77.477",
                    "end_lat": "28.476",
                    "end_lon": "77.477",
                },
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 400)

    def test_serializes_unknown_safety_without_claiming_a_score(self):
        option = replace(
            route_option(),
            risk_score=None,
            safety_score=None,
            risk_level="unknown",
            risk_data_available=False,
            incident_coverage_ratio=0.0,
        )
        with patch("Model.views.calculate_route_options", return_value=[option]):
            response = self.client.get(
                "/api/routes/",
                {
                    "start_lat": "28.475",
                    "start_lon": "77.477",
                    "end_lat": "28.476",
                    "end_lon": "77.477",
                },
                HTTP_HOST="localhost",
            )

        route = response.json()["routes"][0]
        self.assertIsNone(route["risk_score"])
        self.assertIsNone(route["safety_score"])
        self.assertEqual(route["risk_level"], "unknown")
        self.assertEqual(route["incident_coverage_ratio"], 0.0)

    def test_route_endpoint_is_throttled(self):
        params = {
            "start_lat": "28.475",
            "start_lon": "77.477",
            "end_lat": "28.476",
            "end_lon": "77.477",
        }
        with (
            patch.object(
                RoutesRateThrottle,
                "THROTTLE_RATES",
                {"routes": "2/minute"},
            ),
            patch("Model.views.calculate_route_options", return_value=[route_option()]),
        ):
            statuses = [
                self.client.get(
                    "/api/routes/", params, HTTP_HOST="localhost"
                ).status_code
                for _ in range(3)
            ]

        self.assertEqual(statuses, [200, 200, 429])
