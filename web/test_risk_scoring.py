import math

import pandas as pd
from django.test import SimpleTestCase

from Model.utils.risk_scoring import RiskScorer, risk_from_exposure
from Model.utils.road_graph import RoadGraph


class RiskScoringTests(SimpleTestCase):
    def setUp(self):
        self.graph = RoadGraph()
        self.graph.add_node("A", 0.0, 0.0)
        self.graph.add_node("B", 0.0, 0.01)
        self.graph.add_edge(
            "A-B",
            "A",
            "B",
            1112.0,
            ((0.0, 0.0), (0.0, 0.01)),
        )

    def test_incident_at_segment_endpoint_contributes_to_edge_risk(self):
        incidents = pd.DataFrame(
            [
                {
                    "latitude": 0.0,
                    "longitude": 0.0,
                    "severity": 5,
                }
            ]
        )

        scores = RiskScorer(incidents).score_edges(self.graph.edges)

        self.assertGreater(scores["A-B"], 0.6)

    def test_incident_outside_radius_does_not_contribute(self):
        incidents = pd.DataFrame(
            [
                {
                    "latitude": 0.003,
                    "longitude": 0.0,
                    "severity": 5,
                }
            ]
        )

        scores = RiskScorer(incidents).score_edges(self.graph.edges)

        self.assertEqual(scores["A-B"], 0.0)

    def test_invalid_severity_is_discarded(self):
        incidents = pd.DataFrame(
            [
                {
                    "latitude": 0.0,
                    "longitude": 0.0,
                    "severity": math.nan,
                }
            ]
        )

        scores = RiskScorer(incidents).score_edges(self.graph.edges)

        self.assertEqual(scores["A-B"], 0.0)

    def test_exposure_transform_is_deterministic_and_bounded(self):
        self.assertAlmostEqual(risk_from_exposure(1.0), 1 - math.exp(-1.0))
        self.assertEqual(risk_from_exposure(-1.0), 0.0)
        self.assertLessEqual(risk_from_exposure(1000.0), 1.0)
