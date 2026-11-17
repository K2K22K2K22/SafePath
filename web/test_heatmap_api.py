from unittest.mock import patch

from django.test import SimpleTestCase


class HeatmapApiTests(SimpleTestCase):
    def test_returns_bundled_incident_points(self):
        response = self.client.get("/api/safety-heatmap/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "bundled_csv")
        self.assertEqual(payload["record_count"], len(payload["points"]))
        self.assertGreater(payload["record_count"], 0)
        self.assertEqual(payload["radius_meters"], 200)
        for point in payload["points"]:
            self.assertTrue(-90 <= point["lat"] <= 90)
            self.assertTrue(-180 <= point["lon"] <= 180)
            self.assertTrue(0 < point["intensity"] <= 1)

    def test_serializes_only_valid_incident_records(self):
        scorer = type(
            "Scorer",
            (),
            {"incidents": ((77.4764, 28.4748, 0.8),)},
        )()

        with patch("Model.views.RiskScorer", return_value=scorer):
            response = self.client.get(
                "/api/safety-heatmap/",
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["points"],
            [{"lat": 28.4748, "lon": 77.4764, "intensity": 0.8}],
        )

    def test_returns_empty_point_list_when_no_records_exist(self):
        scorer = type("Scorer", (), {"incidents": ()})()

        with patch("Model.views.RiskScorer", return_value=scorer):
            response = self.client.get(
                "/api/safety-heatmap/",
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["points"], [])
        self.assertEqual(response.json()["record_count"], 0)

    def test_returns_service_error_when_incident_data_cannot_be_loaded(self):
        with patch("Model.views.RiskScorer", side_effect=OSError("missing file")):
            response = self.client.get(
                "/api/safety-heatmap/",
                HTTP_HOST="localhost",
            )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("missing file", response.content.decode())
