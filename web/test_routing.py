import math
from typing import Any

from django.test import SimpleTestCase

from Model.utils.road_graph import RoadGraph
from Model.utils.routing import (
    SearchLimitExceeded,
    _distance_heuristic,
    _edge_cost,
    dijkstra,
    dijkstra_to_any,
    modified_a_star,
)


def build_test_graph():
    graph = RoadGraph()
    graph.add_node("A", 0.0, 0.0)
    graph.add_node("B", 0.0009, 0.0)
    graph.add_node("C", 0.0009, 0.001558)
    graph.add_node("D", 0.0018, 0.0)

    graph.add_edge("A-B", "A", "B", 100.0, ((0.0, 0.0), (0.0009, 0.0)))
    graph.add_edge("B-D", "B", "D", 100.0, ((0.0009, 0.0), (0.0018, 0.0)))
    graph.add_edge("A-C", "A", "C", 200.0, ((0.0, 0.0), (0.0009, 0.001558)))
    graph.add_edge("C-D", "C", "D", 200.0, ((0.0009, 0.001558), (0.0018, 0.0)))

    return graph


class DijkstraTests(SimpleTestCase):
    def test_returns_minimum_distance_path(self):
        graph = build_test_graph()

        result = dijkstra(graph, "A", "D")

        self.assertIsNotNone(result)
        self.assertEqual(result.node_ids, ("A", "B", "D"))
        self.assertEqual(result.edge_ids, ("A-B", "B-D"))
        self.assertEqual(result.path_cost, 200.0)
        self.assertEqual(result.distance_meters, 200.0)
        self.assertGreater(result.nodes_explored, 0)
        self.assertGreaterEqual(result.computation_time_ms, 0)

    def test_returns_none_for_disconnected_graph(self):
        graph = build_test_graph()
        graph.add_node("X", 1.0, 1.0)

        result = dijkstra(graph, "A", "X")

        self.assertIsNone(result)

    def test_edge_penalties_can_force_a_different_path(self):
        graph = build_test_graph()

        result = dijkstra(
            graph,
            "A",
            "D",
            edge_penalties={"A-B": 1000.0, "B-D": 1000.0},
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.edge_ids, ("A-C", "C-D"))
        self.assertEqual(result.path_cost, 400.0)


class ModifiedAStarTests(SimpleTestCase):
    def setUp(self):
        self.graph = build_test_graph()
        self.risks = {
            "A-B": 0.4,
            "B-D": 0.4,
            "A-C": 0.0,
            "C-D": 0.0,
        }

    def test_returns_minimum_configured_cost(self):
        result = modified_a_star(
            self.graph,
            "A",
            "D",
            risk_by_edge=self.risks,
            beta=2.0,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.edge_ids, ("A-B", "B-D"))
        self.assertEqual(result.path_cost, 360.0)

    def test_safety_objective_prefers_lower_risk_path(self):
        result = modified_a_star(
            self.graph,
            "A",
            "D",
            risk_by_edge=self.risks,
            beta=8.0,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.edge_ids, ("A-C", "C-D"))
        self.assertEqual(result.path_cost, 400.0)

    def test_modified_a_star_matches_dijkstra_for_same_objective(self):
        graph = build_test_graph()
        risks = {
            "A-B": 0.4,
            "B-D": 0.4,
            "A-C": 0.0,
            "C-D": 0.0,
        }

        astar = modified_a_star(graph, "A", "D", risks, beta=2.0)
        dijkstra_result = dijkstra(graph, "A", "D", risks, beta=2.0)

        self.assertIsNotNone(astar)
        self.assertIsNotNone(dijkstra_result)
        self.assertAlmostEqual(astar.path_cost, dijkstra_result.path_cost)

    def test_distance_heuristic_does_not_overestimate_remaining_distance(self):
        graph = build_test_graph()
        goal = graph.nodes["D"]

        for node_id, node in graph.nodes.items():
            remaining = dijkstra(graph, node_id, "D")
            self.assertIsNotNone(remaining)
            self.assertLessEqual(
                _distance_heuristic(node, goal),
                remaining.distance_meters,
            )

    def test_edge_cost_is_non_negative_for_valid_inputs(self):
        edge = build_test_graph().edges["A-B"]

        for risk, beta in ((0.0, 0.0), (0.4, 2.0), (1.0, 8.0)):
            with self.subTest(risk=risk, beta=beta):
                self.assertGreaterEqual(_edge_cost(edge, risk, beta, 0.0), 0.0)

    def test_distance_is_sum_of_actual_edge_lengths(self):
        graph = RoadGraph()
        graph.add_node("A", 0.0, 0.0)
        graph.add_node("B", 0.0, 0.001)
        graph.add_node("C", 0.0, 0.002)
        graph.add_edge("A-B", "A", "B", 120.0, ((0.0, 0.0), (0.0, 0.001)))
        graph.add_edge("B-C", "B", "C", 150.0, ((0.0, 0.001), (0.0, 0.002)))

        result = dijkstra(graph, "A", "C")

        self.assertIsNotNone(result)
        self.assertEqual(result.distance_meters, 270.0)
        self.assertEqual(result.path_cost, 270.0)

    def test_returns_none_for_disconnected_graph(self):
        self.graph.add_node("X", 1.0, 1.0)

        result = modified_a_star(
            self.graph,
            "A",
            "X",
            risk_by_edge=self.risks,
            beta=8.0,
        )

        self.assertIsNone(result)


class RoutingValidationTests(SimpleTestCase):
    def test_rejects_edge_shorter_than_endpoint_geodesic(self):
        graph = RoadGraph()
        graph.add_node("A", 0.0, 0.0)
        graph.add_node("B", 0.0, 0.0009)

        with self.assertRaises(ValueError):
            graph.add_edge("A-B", "A", "B", 1.0, ((0.0, 0.0), (0.0, 0.0009)))

    def test_rejects_non_finite_cost_inputs(self):
        graph = build_test_graph()

        cases: list[dict[str, Any]] = [
            {"beta": math.nan},
            {"risk_by_edge": {"A-B": math.inf}},
            {"edge_penalties": {"A-B": math.nan}},
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                dijkstra(graph, "A", "D", **kwargs)

    def test_search_limit_stops_excessive_work(self):
        graph = build_test_graph()

        with self.assertRaises(SearchLimitExceeded):
            dijkstra(graph, "A", "D", max_nodes_explored=1)

    def test_multi_source_search_finds_first_reachable_goal(self):
        graph = build_test_graph()
        graph.add_node("X", 1.0, 1.0)

        result = dijkstra_to_any(graph, ["X", "B"], ["D"])

        self.assertIsNotNone(result)
        self.assertEqual(result.node_ids, ("B", "D"))
