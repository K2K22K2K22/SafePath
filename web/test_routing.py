from django.test import SimpleTestCase

from Model.utils.road_graph import RoadGraph
from Model.utils.routing import dijkstra, modified_a_star


def build_test_graph():
    graph = RoadGraph()
    graph.add_node("A", 0.0, 0.0)
    graph.add_node("B", 0.0, 0.0009)
    graph.add_node("C", 0.0, 0.0018)
    graph.add_node("D", 0.0, 0.0027)

    graph.add_edge("A-B", "A", "B", 100.0, ((0.0, 0.0), (0.0, 0.0009)))
    graph.add_edge("B-D", "B", "D", 100.0, ((0.0, 0.0009), (0.0, 0.0027)))
    graph.add_edge("A-C", "A", "C", 200.0, ((0.0, 0.0), (0.0, 0.0018)))
    graph.add_edge("C-D", "C", "D", 200.0, ((0.0, 0.0018), (0.0, 0.0027)))

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
