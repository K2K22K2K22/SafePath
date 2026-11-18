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

    def test_exact_duplicate_incidents_are_counted_once(self):
        incident = {
            "latitude": 0.0,
            "longitude": 0.0,
            "severity": 5,
            "description": "Same incident",
        }
        incidents = pd.DataFrame([incident, incident.copy()])

        scores = RiskScorer(incidents).score_edges(self.graph.edges)

        self.assertAlmostEqual(scores["A-B"], 1 - math.exp(-1.0))

    def test_malformed_incident_does_not_abort_scoring(self):
        incidents = pd.DataFrame(
            [
                {"latitude": "bad", "longitude": 0.0, "severity": 5},
                {"latitude": 0.0, "longitude": 0.0, "severity": 5},
            ]
        )

        scores = RiskScorer(incidents).score_edges(self.graph.edges)

        self.assertGreater(scores["A-B"], 0.6)

    def test_coverage_uses_record_proximity_not_a_bounding_rectangle(self):
        graph = RoadGraph()
        graph.add_node("A", 10.0, 10.0)
        graph.add_node("B", 10.0, 10.01)
        graph.add_edge(
            "A-B",
            "A",
            "B",
            1112.0,
            ((10.0, 10.0), (10.0, 10.01)),
        )
        incidents = pd.DataFrame(
            [
                {"latitude": 0.0, "longitude": 0.0, "severity": 5},
                {"latitude": 20.0, "longitude": 20.0, "severity": 5},
            ]
        )

        scores = RiskScorer(incidents).score_edges(graph.edges)

        self.assertEqual(scores["A-B"], 0.0)
        self.assertEqual(scores.proximity_covered_lengths_meters["A-B"], 0.0)

    def test_coverage_is_partial_when_only_part_of_an_edge_is_near_a_record(self):
        incidents = pd.DataFrame([{"latitude": 0.0, "longitude": 0.005, "severity": 5}])

        scores = RiskScorer(incidents).score_edges(self.graph.edges)

        coverage = scores.proximity_covered_lengths_meters["A-B"]
        self.assertGreater(coverage, 300.0)
        self.assertLess(coverage, 500.0)

    def test_endpoint_record_covers_only_the_proximity_zone_length(self):
        incidents = pd.DataFrame([{"latitude": 0.0, "longitude": 0.0, "severity": 5}])

        scores = RiskScorer(incidents).score_edges(self.graph.edges)

        self.assertAlmostEqual(
            scores.proximity_covered_lengths_meters["A-B"],
            200.0,
            delta=1.0,
        )

    def test_overlapping_record_zones_are_unioned_without_double_counting(self):
        graph = RoadGraph()
        graph.add_node("A", 0.0, 0.0)
        graph.add_node("B", 0.0, 0.0027)
        graph.add_edge(
            "A-B",
            "A",
            "B",
            300.0,
            ((0.0, 0.0), (0.0, 0.0027)),
        )
        incidents = pd.DataFrame(
            [
                {"latitude": 0.0, "longitude": 0.0, "severity": 5},
                {"latitude": 0.0, "longitude": 0.00135, "severity": 5},
            ]
        )

        scores = RiskScorer(incidents).score_edges(graph.edges)

        self.assertAlmostEqual(
            scores.proximity_covered_lengths_meters["A-B"],
            300.0,
            delta=1.0,
        )

    def test_combined_record_zones_can_cover_an_entire_edge(self):
        graph = RoadGraph()
        graph.add_node("A", 0.0, 0.0)
        graph.add_node("B", 0.0, 0.0035)
        graph.add_edge(
            "A-B",
            "A",
            "B",
            389.0,
            ((0.0, 0.0), (0.0, 0.0035)),
        )
        incidents = pd.DataFrame(
            [
                {"latitude": 0.0, "longitude": 0.0, "severity": 5},
                {"latitude": 0.0, "longitude": 0.0035, "severity": 5},
            ]
        )

        scores = RiskScorer(incidents).score_edges(graph.edges)

        self.assertAlmostEqual(
            scores.proximity_covered_lengths_meters["A-B"],
            389.0,
            delta=0.5,
        )

    def test_coverage_is_deterministic(self):
        incidents = pd.DataFrame([{"latitude": 0.0, "longitude": 0.005, "severity": 5}])
        scorer = RiskScorer(incidents)

        first = scorer.score_edges(self.graph.edges)
        second = scorer.score_edges(self.graph.edges)

        self.assertEqual(
            first.proximity_covered_lengths_meters,
            second.proximity_covered_lengths_meters,
        )
