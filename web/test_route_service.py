from itertools import combinations
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from Model.utils.risk_scoring import EdgeRiskScores
from Model.utils.road_graph import RoadGraph
from Model.utils.route_service import generate_route_options, shared_interior_edge_ratio
from Model.utils.routing import PathResult


def build_three_route_graph():
    graph = RoadGraph()
    for node_id, latitude, longitude in [
        ("A", 0.0, 0.0),
        ("B", 0.0009, 0.0),
        ("C", 0.0009, 0.001558),
        ("D", 0.0018, 0.0),
        ("E", 0.0009, 0.001004),
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

    def test_alternatives_are_distinct_from_every_selected_route(self):
        def path(edge_ids, distance):
            return PathResult(
                node_ids=("A", "D"),
                edge_ids=tuple(edge_ids),
                path_cost=float(distance),
                distance_meters=float(distance),
                nodes_explored=1,
                computation_time_ms=0.0,
            )

        role_one = path(("A-R1", "R1-D"), 200)
        role_two = path(("A-R2", "R2-D"), 200)
        alternative_one = path(
            ("A-P", "P-1", "P-2", "P-3", "P-4", "Z-D"),
            600,
        )
        alternative_two = path(
            ("A-P", "P-1", "P-2", "P-3", "P-4", "P-5", "Z-D"),
            700,
        )
        edge_ids = {
            edge_id
            for candidate in [role_one, role_two, alternative_one, alternative_two]
            for edge_id in candidate.edge_ids
        }
        graph = SimpleNamespace(
            edges={
                edge_id: SimpleNamespace(
                    distance_meters=100.0,
                    travel_time_seconds=10.0,
                    geometry=((0.0, 0.0), (0.0, 0.001)),
                )
                for edge_id in edge_ids
            }
        )
        candidates = [
            SimpleNamespace(path=role_one, algorithm="dijkstra", beta=0.0),
            SimpleNamespace(path=role_two, algorithm="modified_astar", beta=8.0),
            SimpleNamespace(path=alternative_one, algorithm="modified_astar", beta=8.0),
            SimpleNamespace(path=alternative_two, algorithm="modified_astar", beta=8.0),
        ]
        risks = {
            "A-R1": 0.8,
            "R1-D": 0.8,
            "A-R2": 0.1,
            "R2-D": 0.1,
            "A-P": 0.9,
        }

        with (
            patch(
                "Model.utils.route_service.dijkstra",
                return_value=role_one,
            ),
            patch(
                "Model.utils.route_service.modified_a_star",
                side_effect=[role_two, role_two],
            ),
            patch(
                "Model.utils.route_service._candidate_pool",
                return_value=candidates,
            ),
        ):
            options = generate_route_options(graph, "A", "D", risks)

        alternatives = [option for option in options if "alternative" in option.labels]
        self.assertEqual(len(alternatives), 1)
        self.assertEqual(alternatives[0].edge_ids, alternative_one.edge_ids)
        for first, second in combinations(options, 2):
            self.assertLessEqual(
                shared_interior_edge_ratio(first.edge_ids, second.edge_ids),
                0.75,
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
        graph.add_edge("A-B", "A", "B", 112.0, ((0.0, 0.0), (0.0, 0.001)))

        options = generate_route_options(graph, "A", "B", {"A-B": 0.0})

        self.assertEqual(len(options), 1)
        self.assertEqual(options[0].distance_meters, 112.0)

    def test_shared_interior_ratio_ignores_common_start_and_end_edges(self):
        ratio = shared_interior_edge_ratio(
            ("A-B", "B-C", "C-D"),
            ("A-B", "B-X", "X-D"),
        )

        self.assertEqual(ratio, 0.0)

    def test_uncovered_route_has_unknown_safety_and_no_safest_label(self):
        risks = EdgeRiskScores(
            {edge_id: 0.0 for edge_id in self.graph.edges},
            frozenset(),
            None,
        )

        options = generate_route_options(self.graph, "A", "D", risks)

        self.assertTrue(options)
        self.assertFalse(any("safest" in option.labels for option in options))
        self.assertTrue(all(option.risk_score is None for option in options))
        self.assertTrue(all(option.safety_score is None for option in options))
        self.assertTrue(all(option.risk_level == "unknown" for option in options))
