import heapq
import itertools
import math
import time
from dataclasses import dataclass

from .geometry_utils import haversine
from .road_graph import MINIMUM_DISTANCE_RATIO


class SearchLimitExceeded(Exception):
    pass


@dataclass(frozen=True)
class PathResult:
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    path_cost: float
    distance_meters: float
    nodes_explored: int
    computation_time_ms: float


def dijkstra(
    graph,
    start,
    goal,
    risk_by_edge=None,
    beta=0.0,
    edge_penalties=None,
    max_nodes_explored=None,
):
    return _search(
        graph,
        starts=(start,),
        goals=(goal,),
        risk_by_edge=risk_by_edge,
        beta=beta,
        edge_penalties=edge_penalties,
        max_nodes_explored=max_nodes_explored,
    )


def dijkstra_to_any(
    graph,
    starts,
    goals,
    max_nodes_explored=None,
):
    return _search(
        graph,
        starts=starts,
        goals=goals,
        max_nodes_explored=max_nodes_explored,
    )


def modified_a_star(
    graph,
    start,
    goal,
    risk_by_edge,
    beta,
    edge_penalties=None,
    max_nodes_explored=None,
):
    return _search(
        graph,
        starts=(start,),
        goals=(goal,),
        risk_by_edge=risk_by_edge,
        beta=beta,
        edge_penalties=edge_penalties,
        heuristic=lambda node: _distance_heuristic(node, graph.nodes[goal]),
        max_nodes_explored=max_nodes_explored,
    )


def _search(
    graph,
    starts,
    goals,
    risk_by_edge=None,
    beta=0.0,
    edge_penalties=None,
    heuristic=None,
    max_nodes_explored=None,
):
    starts = tuple(str(node_id) for node_id in starts)
    goals = tuple(str(node_id) for node_id in goals)
    if not starts or not goals:
        raise ValueError("Route searches require at least one start and one goal.")

    _validate_endpoints(graph, starts + goals)
    _validate_beta(beta)
    _validate_search_limit(max_nodes_explored)

    risks = risk_by_edge or {}
    penalties = edge_penalties or {}
    counter = itertools.count()
    queue: list[tuple[float, float, int, str]] = []
    best_cost = {}

    for node_id in starts:
        best_cost[node_id] = 0.0
        priority = heuristic(graph.nodes[node_id]) if heuristic else 0.0
        heapq.heappush(queue, (priority, 0.0, next(counter), node_id))

    parent = {}
    nodes_explored = 0
    reached_goal = None
    started_at = time.perf_counter()

    while queue:
        _, current_cost, _, node = heapq.heappop(queue)
        if current_cost != best_cost.get(node):
            continue

        nodes_explored += 1
        if max_nodes_explored is not None and nodes_explored > max_nodes_explored:
            raise SearchLimitExceeded(
                "Route search exceeded the node exploration limit."
            )
        if node in goals:
            reached_goal = node
            break

        for edge_id in graph.outgoing_edges(node):
            edge = graph.edges[edge_id]
            next_cost = current_cost + _edge_cost(
                edge,
                risks.get(edge_id, 0.0),
                beta,
                penalties.get(edge_id, 0.0),
            )
            if next_cost < best_cost.get(edge.target, float("inf")):
                best_cost[edge.target] = next_cost
                parent[edge.target] = (node, edge_id)
                priority = next_cost
                if heuristic:
                    priority += heuristic(graph.nodes[edge.target])
                heapq.heappush(queue, (priority, next_cost, next(counter), edge.target))

    if reached_goal is None:
        return None

    node_ids, edge_ids = _reconstruct_path(parent, reached_goal)
    return PathResult(
        node_ids=node_ids,
        edge_ids=edge_ids,
        path_cost=best_cost[reached_goal],
        distance_meters=sum(
            graph.edges[edge_id].distance_meters for edge_id in edge_ids
        ),
        nodes_explored=nodes_explored,
        computation_time_ms=(time.perf_counter() - started_at) * 1000,
    )


def _validate_beta(beta):
    beta = float(beta)
    if not math.isfinite(beta) or beta < 0:
        raise ValueError("Risk weight beta must be finite and non-negative.")


def _validate_search_limit(max_nodes_explored):
    if max_nodes_explored is None:
        return
    if int(max_nodes_explored) <= 0:
        raise ValueError("Node exploration limit must be positive.")


def _edge_cost(edge, risk, beta, penalty):
    risk = float(risk)
    penalty = float(penalty)
    if not math.isfinite(risk) or not 0 <= risk <= 1:
        raise ValueError("Edge risk must be finite and between 0 and 1.")
    if not math.isfinite(penalty) or penalty < 0:
        raise ValueError("Edge penalties must be finite and non-negative.")
    return edge.distance_meters + float(beta) * risk * edge.distance_meters + penalty


def _distance_heuristic(node, goal):
    direct_distance = haversine(
        node.latitude,
        node.longitude,
        goal.latitude,
        goal.longitude,
    )
    return direct_distance * MINIMUM_DISTANCE_RATIO


def _validate_endpoints(graph, node_ids):
    if any(node_id not in graph.nodes for node_id in node_ids):
        raise ValueError("Route endpoints must exist in the graph.")


def _reconstruct_path(parent, goal):
    node_ids = [goal]
    edge_ids = []
    current = goal

    while current in parent:
        previous, edge_id = parent[current]
        edge_ids.append(edge_id)
        current = previous
        node_ids.append(current)

    return tuple(reversed(node_ids)), tuple(reversed(edge_ids))
