import threading
import weakref
from dataclasses import dataclass

from django.conf import settings

from .osm_graph import RoadDataUnavailable, load_road_graph
from .risk_scoring import EdgeRiskScores, RiskScorer
from .road_graph import RoadGraph
from .routing import (
    PathResult,
    SearchLimitExceeded,
    dijkstra,
    dijkstra_to_any,
    modified_a_star,
)

BALANCED_RISK_WEIGHT = 2.0
SAFEST_RISK_WEIGHT = 8.0
DIVERSITY_THRESHOLD = 0.75
EDGE_PENALTY_MULTIPLIER = 2.0
COVERAGE_LENGTH_TOLERANCE_METERS = 1e-6
_RISK_CACHE: weakref.WeakKeyDictionary[RoadGraph, EdgeRiskScores] = (
    weakref.WeakKeyDictionary()
)
_RISK_CACHE_LOCK = threading.RLock()


class RouteNotFound(Exception):
    pass


@dataclass(frozen=True)
class RouteOption:
    route_id: str
    labels: tuple[str, ...]
    algorithm: str
    beta: float
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    geometry: tuple[tuple[float, float], ...]
    distance_meters: float
    duration_seconds: float
    risk_score: float | None
    safety_score: int | None
    risk_level: str
    risk_data_available: bool
    incident_coverage_ratio: float
    nodes_explored: int
    computation_time_ms: float
    path_cost: float
    shared_interior_edge_ratio: float
    explanation: str


@dataclass(frozen=True)
class _Candidate:
    path: PathResult
    algorithm: str
    beta: float
    penalized: bool = False


def calculate_route_options(start_lat, start_lon, end_lat, end_lon):
    road_result = load_road_graph(start_lat, start_lon, end_lat, end_lon)
    risks = _risk_scores_for_graph(road_result.graph)
    try:
        reachable_path = dijkstra_to_any(
            road_result.graph,
            [node_id for node_id, _ in road_result.start_candidates],
            [node_id for node_id, _ in road_result.end_candidates],
            max_nodes_explored=settings.SAFEPATH_MAX_NODES_EXPLORED,
        )
    except SearchLimitExceeded as error:
        raise RoadDataUnavailable("Route search exceeded its work limit.") from error
    if reachable_path is None:
        raise RouteNotFound(
            "No connected road route was found for the requested points."
        )

    return generate_route_options(
        road_result.graph,
        reachable_path.node_ids[0],
        reachable_path.node_ids[-1],
        risks,
    )


def generate_route_options(graph, start, end, risk_by_edge):
    max_nodes = settings.SAFEPATH_MAX_NODES_EXPLORED
    shortest = dijkstra(graph, start, end, max_nodes_explored=max_nodes)
    if shortest is None:
        raise RouteNotFound("No route exists between the selected road nodes.")

    safety_weighted = modified_a_star(
        graph,
        start,
        end,
        risk_by_edge,
        SAFEST_RISK_WEIGHT,
        max_nodes_explored=max_nodes,
    )
    balanced = modified_a_star(
        graph,
        start,
        end,
        risk_by_edge,
        BALANCED_RISK_WEIGHT,
        max_nodes_explored=max_nodes,
    )

    candidates = _candidate_pool(
        graph,
        start,
        end,
        risk_by_edge,
        shortest,
        safety_weighted,
        balanced,
        max_nodes,
    )
    safest = _safest_candidate(graph, candidates, risk_by_edge)
    role_candidates = []
    if safest is not None:
        role_candidates.append(("safest", safest))
    role_candidates.extend(
        [
            ("shortest", _Candidate(shortest, "dijkstra", 0.0)),
            ("balanced", _Candidate(balanced, "modified_astar", BALANCED_RISK_WEIGHT)),
        ]
    )

    selected: dict[tuple[str, ...], _Candidate] = {}
    labels: dict[tuple[str, ...], list[str]] = {}
    for label, candidate in role_candidates:
        key = candidate.path.edge_ids
        selected.setdefault(key, candidate)
        labels.setdefault(key, []).append(label)

    selected_keys = set(selected)
    alternatives = [
        candidate
        for candidate in candidates
        if candidate.path.edge_ids not in selected_keys
        and _is_distinct(candidate.path.edge_ids, selected.keys())
    ]
    alternatives.sort(
        key=lambda candidate: (
            _objective_cost(candidate.path, graph, risk_by_edge, BALANCED_RISK_WEIGHT),
            candidate.path.distance_meters,
        )
    )

    for candidate in alternatives:
        if len(selected) >= 4:
            break
        if not _is_distinct(candidate.path.edge_ids, selected.keys()):
            continue
        key = candidate.path.edge_ids
        selected[key] = candidate
        labels[key] = ["alternative"]

    ordered = []
    for _, candidate in role_candidates:
        key = candidate.path.edge_ids
        if key not in ordered:
            ordered.append(key)
    for candidate in alternatives:
        key = candidate.path.edge_ids
        if key in selected and key not in ordered and len(ordered) < 4:
            ordered.append(key)

    options = []
    for index, key in enumerate(ordered[:4], start=1):
        candidate = selected[key]
        options.append(
            _build_route_option(
                graph,
                risk_by_edge,
                candidate,
                tuple(labels[key]),
                index,
                shortest.edge_ids,
            )
        )

    return tuple(options)


def _candidate_pool(
    graph,
    start,
    end,
    risks,
    shortest,
    safest,
    balanced,
    max_nodes,
):
    candidates = []
    for candidate in [
        _Candidate(shortest, "dijkstra", 0.0),
        _Candidate(safest, "modified_astar", SAFEST_RISK_WEIGHT),
        _Candidate(balanced, "modified_astar", BALANCED_RISK_WEIGHT),
    ]:
        if candidate.path is not None:
            candidates.append(candidate)

    base_paths = [
        candidate.path for candidate in candidates if candidate.path is not None
    ]
    for base_path in base_paths:
        penalties = {
            edge_id: graph.edges[edge_id].distance_meters * EDGE_PENALTY_MULTIPLIER
            for edge_id in base_path.edge_ids
        }
        candidates.extend(
            candidate
            for candidate in [
                _Candidate(
                    dijkstra(
                        graph,
                        start,
                        end,
                        risks,
                        0.0,
                        penalties,
                        max_nodes,
                    ),
                    "dijkstra",
                    0.0,
                    True,
                ),
                _Candidate(
                    modified_a_star(
                        graph,
                        start,
                        end,
                        risks,
                        BALANCED_RISK_WEIGHT,
                        penalties,
                        max_nodes,
                    ),
                    "modified_astar",
                    BALANCED_RISK_WEIGHT,
                    True,
                ),
                _Candidate(
                    modified_a_star(
                        graph,
                        start,
                        end,
                        risks,
                        SAFEST_RISK_WEIGHT,
                        penalties,
                        max_nodes,
                    ),
                    "modified_astar",
                    SAFEST_RISK_WEIGHT,
                    True,
                ),
            ]
            if candidate.path is not None
        )

    unique: dict[tuple[str, ...], _Candidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.path.edge_ids, candidate)
    return list(unique.values())


def _safest_candidate(graph, candidates, risks):
    covered_candidates = [
        candidate
        for candidate in candidates
        if _route_coverage(candidate.path, graph, risks)[1]
    ]
    if not covered_candidates:
        return None
    return min(
        covered_candidates,
        key=lambda candidate: (
            _route_risk(candidate.path, graph, risks),
            _objective_cost(candidate.path, graph, risks, SAFEST_RISK_WEIGHT),
            candidate.path.distance_meters,
        ),
    )


def _build_route_option(
    graph,
    risks,
    candidate,
    route_labels,
    route_index,
    shortest_edge_ids,
):
    path = candidate.path
    distance = path.distance_meters
    coverage_ratio, risk_data_available = _route_coverage(path, graph, risks)
    route_risk = _route_risk(path, graph, risks)
    risk_score = route_risk if risk_data_available else None
    safety_score = round((1 - route_risk) * 100) if risk_data_available else None
    risk_level = _risk_level(route_risk) if risk_data_available else "unknown"
    duration = sum(
        graph.edges[edge_id].travel_time_seconds or 0.0 for edge_id in path.edge_ids
    )

    return RouteOption(
        route_id=f"route-{route_index}",
        labels=route_labels,
        algorithm=candidate.algorithm,
        beta=candidate.beta,
        node_ids=path.node_ids,
        edge_ids=path.edge_ids,
        geometry=_route_geometry(graph, path),
        distance_meters=distance,
        duration_seconds=duration,
        risk_score=risk_score,
        safety_score=safety_score,
        risk_level=risk_level,
        risk_data_available=risk_data_available,
        incident_coverage_ratio=coverage_ratio,
        nodes_explored=path.nodes_explored,
        computation_time_ms=path.computation_time_ms,
        path_cost=path.path_cost,
        shared_interior_edge_ratio=shared_interior_edge_ratio(
            path.edge_ids,
            shortest_edge_ids,
        ),
        explanation=_route_explanation(route_labels),
    )


def _route_geometry(graph, path):
    coordinates: list[tuple[float, float]] = []
    for edge_id in path.edge_ids:
        geometry = graph.edges[edge_id].geometry
        if coordinates and coordinates[-1] == geometry[0]:
            coordinates.extend(geometry[1:])
        else:
            coordinates.extend(geometry)

    if not coordinates and path.node_ids:
        node = graph.nodes[path.node_ids[0]]
        coordinates.append((node.latitude, node.longitude))
    return tuple(coordinates)


def _route_coverage(path, graph, risks):
    if not path.edge_ids:
        return 0.0, False
    if not isinstance(risks, EdgeRiskScores):
        return 0.0, False

    total_distance = sum(
        graph.edges[edge_id].distance_meters for edge_id in path.edge_ids
    )
    covered_lengths = risks.proximity_covered_lengths_meters
    covered_distance = sum(
        covered_lengths.get(edge_id, 0.0) for edge_id in path.edge_ids
    )
    ratio = covered_distance / total_distance if total_distance > 0 else 0.0
    fully_covered = total_distance > 0 and all(
        covered_lengths.get(edge_id, 0.0)
        >= graph.edges[edge_id].distance_meters - COVERAGE_LENGTH_TOLERANCE_METERS
        for edge_id in path.edge_ids
    )
    return ratio, fully_covered


def _route_risk(path, graph, risks):
    if not path.edge_ids or path.distance_meters <= 0:
        return 0.0
    weighted_risk = sum(
        graph.edges[edge_id].distance_meters * risks.get(edge_id, 0.0)
        for edge_id in path.edge_ids
    )
    return weighted_risk / path.distance_meters


def _objective_cost(path, graph, risks, beta):
    return sum(
        graph.edges[edge_id].distance_meters * (1 + beta * risks.get(edge_id, 0.0))
        for edge_id in path.edge_ids
    )


def _is_distinct(edge_ids, selected_edge_ids):
    return all(
        shared_interior_edge_ratio(edge_ids, selected) <= DIVERSITY_THRESHOLD
        for selected in selected_edge_ids
    )


def shared_interior_edge_ratio(first, second):
    first = tuple(first)
    second = tuple(second)
    if first == second:
        return 1.0

    prefix = 0
    while prefix < min(len(first), len(second)) and first[prefix] == second[prefix]:
        prefix += 1

    suffix = 0
    while (
        suffix < min(len(first) - prefix, len(second) - prefix)
        and first[-1 - suffix] == second[-1 - suffix]
    ):
        suffix += 1

    first_interior = set(first[prefix : len(first) - suffix])
    second_interior = set(second[prefix : len(second) - suffix])
    if not first_interior or not second_interior:
        return 1.0

    union = first_interior | second_interior
    return len(first_interior & second_interior) / len(union)


def _risk_level(risk_score):
    if risk_score < 0.2:
        return "low"
    if risk_score < 0.5:
        return "moderate"
    return "high"


def _route_explanation(labels):
    explanations = {
        "safest": "Lowest modeled risk among the generated, eligible routes.",
        "shortest": "Minimum road-edge distance in the loaded graph.",
        "balanced": "Balanced distance and risk objective.",
        "alternative": "Distinct path generated with temporary edge penalties.",
    }
    return " ".join(explanations[label] for label in labels)


def _risk_scores_for_graph(graph):
    with _RISK_CACHE_LOCK:
        cached = _RISK_CACHE.get(graph)
    if cached is not None:
        return cached

    scores = RiskScorer().score_edges(graph.edges)
    with _RISK_CACHE_LOCK:
        return _RISK_CACHE.setdefault(graph, scores)
