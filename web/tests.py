import math

import pandas as pd
from django.test import SimpleTestCase

from Model.utils.crime_scoring import calculate_segment_risk, summarize_crime_for_segment
from Model.utils.geometry_utils import haversine


class CrimeScoringTests(SimpleTestCase):
    def test_risk_is_zero_without_nearby_incidents(self):
        risk, explanation = calculate_segment_risk(
            {"total_crimes": 0, "average_severity": 0.0}
        )

        self.assertEqual(risk, 0.0)
        self.assertIn("No recorded incidents", explanation)

    def test_risk_increases_with_incident_count_and_severity(self):
        low_risk, _ = calculate_segment_risk(
            {"total_crimes": 1, "average_severity": 2.0}
        )
        high_risk, _ = calculate_segment_risk(
            {"total_crimes": 3, "average_severity": 4.0}
        )

        self.assertGreater(high_risk, low_risk)
        self.assertLessEqual(high_risk, 1.0)

    def test_incident_radius_is_measured_in_metres(self):
        segment = ((28.475, 77.477), (28.475, 77.477))
        incidents = pd.DataFrame(
            [
                {
                    "latitude": 28.478,
                    "longitude": 77.477,
                    "severity": 5,
                    "crime_type": "Test",
                }
            ]
        )

        risk, explanation = summarize_crime_for_segment(*segment, incidents)

        self.assertEqual(risk, 0.0)
        self.assertIn("No recorded incidents", explanation)

    def test_haversine_returns_metres(self):
        distance = haversine(28.475, 77.477, 28.476, 77.477)

        self.assertGreater(distance, 100)
        self.assertLess(distance, 120)
        self.assertTrue(math.isfinite(distance))
