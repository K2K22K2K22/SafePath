from django.test import SimpleTestCase

from Model.utils.road_graph import RoadGraph
from Model.utils.route_service import generate_route_options, shared_interior_edge_ratio


def build_three_route_graph():
    graph = RoadGraph()
    for node_id, latitude, longitude in [
        ("A", 0.0, 0.0),
        ("B", 0.0, 0.0009),
        ("C", 0.0, 0.0018),
        ("D", 0.0, 0.0027),
        ("E", 0.0, 0.0018),
    ]:
        graph.add_node(node_id, latitude, longitude)

    for edge_id, source, target, distance in [
        ("A-B", "A", "B", 100.0),
        ("B-D", "B", "D", 100.0),
        ("A-C", "A", "C", 200.0),
        ("C-D", "C", "D", 200.0),
        ("A-E", "A", "E", 150.0),
        ("E-D", "E", "D", 150.0),
    ]:
        graph.add_edge(
            edge_id,
            source,
            target,
            distance,
            (
                (graph.nodes[source].latitude, graph.nodes[source].longitude),
                (graph.nodes[target].latitude, graph.nodes[target].longitude),
            ),
        )

    return graph


class RouteServiceTests(SimpleTestCase):
    def setUp(self):
        self.graph = build_three_route_graph()
        self.risks = {
            "A-B": 0.4,
            "B-D": 0.4,
            "A-C": 0.0,
            "C-D": 0.0,
            "A-E": 0.2,
            "E-D": 0.2,
        }

    def test_returns_distinct_routes_with_accurate_metrics(self):
        options = generate_route_options(self.graph, "A", "D", self.risks)

        edge_sequences = [option.edge_ids for option in options]
        self.assertEqual(len(edge_sequences), len(set(edge_sequences)))
        self.assertGreaterEqual(len(options), 3)
        self.assertLessEqual(len(options), 4)

        shortest = next(option for option in options if "shortest" in option.labels)
        safest = next(option for option in options if "safest" in option.labels)
        self.assertEqual(shortest.distance_meters, 200.0)
        self.assertLess(safest.risk_score, shortest.risk_score)
        self.assertEqual(
            shortest.distance_meters,
            sum(
                self.graph.edges[edge_id].distance_meters
                for edge_id in shortest.edge_ids
            ),
        )

    def test_combines_objective_labels_when_same_route_wins_both(self):
        options = generate_route_options(self.graph, "A", "D", self.risks)

        shortest = next(option for option in options if "shortest" in option.labels)
        balanced = next(option for option in options if "balanced" in option.labels)

        self.assertEqual(shortest.edge_ids, balanced.edge_ids)
        self.assertIn("balanced", shortest.labels)

    def test_returns_only_available_route_when_no_alternative_exists(self):
        graph = RoadGraph()
        graph.add_node("A", 0.0, 0.0)
        graph.add_node("B", 0.0, 0.001)
        graph.add_edge("A-B", "A", "B", 100.0, ((0.0, 0.0), (0.0, 0.001)))

        options = generate_route_options(graph, "A", "B", {"A-B": 0.0})

        self.assertEqual(len(options), 1)
        self.assertEqual(options[0].distance_meters, 100.0)

    def test_shared_interior_ratio_ignores_common_start_and_end_edges(self):
        ratio = shared_interior_edge_ratio(
            ("A-B", "B-C", "C-D"),
            ("A-B", "B-X", "X-D"),
        )

        self.assertEqual(ratio, 0.0)
