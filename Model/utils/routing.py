import heapq
import itertools
import time
from dataclasses import dataclass

from .geometry_utils import haversine


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
):
    start = str(start)
    goal = str(goal)
    _validate_endpoints(graph, start, goal)

    risks = risk_by_edge or {}
    penalties = edge_penalties or {}
    _validate_beta(beta)
    counter = itertools.count()
    queue = [(0.0, next(counter), start)]
    best_cost = {start: 0.0}
    parent = {}
    nodes_explored = 0
    started_at = time.perf_counter()

    while queue:
        current_cost, _, node = heapq.heappop(queue)
        if current_cost != best_cost.get(node):
            continue

        nodes_explored += 1
        if node == goal:
            break

        for edge_id in graph.outgoing_edges(node):
            edge = graph.edges[edge_id]
            next_cost = current_cost + _edge_cost(
                edge, risks.get(edge_id, 0.0), beta, penalties.get(edge_id, 0.0)
            )
            if next_cost < best_cost.get(edge.target, float("inf")):
                best_cost[edge.target] = next_cost
                parent[edge.target] = (node, edge_id)
                heapq.heappush(queue, (next_cost, next(counter), edge.target))

    if goal not in best_cost:
        return None

    node_ids, edge_ids = _reconstruct_path(graph, parent, start, goal)
    return PathResult(
        node_ids=node_ids,
        edge_ids=edge_ids,
        path_cost=best_cost[goal],
        distance_meters=sum(
            graph.edges[edge_id].distance_meters for edge_id in edge_ids
        ),
        nodes_explored=nodes_explored,
        computation_time_ms=(time.perf_counter() - started_at) * 1000,
    )


def modified_a_star(
    graph,
    start,
    goal,
    risk_by_edge,
    beta,
    edge_penalties=None,
):
    start = str(start)
    goal = str(goal)
    _validate_endpoints(graph, start, goal)

    risks = risk_by_edge or {}
    penalties = edge_penalties or {}
    _validate_beta(beta)
    counter = itertools.count()
    goal_node = graph.nodes[goal]
    queue = [
        (
            _distance_heuristic(graph.nodes[start], goal_node),
            0.0,
            next(counter),
            start,
        )
    ]
    best_cost = {start: 0.0}
    parent = {}
    nodes_explored = 0
    started_at = time.perf_counter()

    while queue:
        _, current_cost, _, node = heapq.heappop(queue)
        if current_cost != best_cost.get(node):
            continue

        nodes_explored += 1
        if node == goal:
            break

        for edge_id in graph.outgoing_edges(node):
            edge = graph.edges[edge_id]
            next_cost = current_cost + _edge_cost(
                edge, risks.get(edge_id, 0.0), beta, penalties.get(edge_id, 0.0)
            )
            if next_cost < best_cost.get(edge.target, float("inf")):
                best_cost[edge.target] = next_cost
                parent[edge.target] = (node, edge_id)
                estimate = next_cost + _distance_heuristic(
                    graph.nodes[edge.target], goal_node
                )
                heapq.heappush(
                    queue,
                    (
                        estimate,
                        next_cost,
                        next(counter),
                        edge.target,
                    ),
                )

    if goal not in best_cost:
        return None

    node_ids, edge_ids = _reconstruct_path(graph, parent, start, goal)
    return PathResult(
        node_ids=node_ids,
        edge_ids=edge_ids,
        path_cost=best_cost[goal],
        distance_meters=sum(
            graph.edges[edge_id].distance_meters for edge_id in edge_ids
        ),
        nodes_explored=nodes_explored,
        computation_time_ms=(time.perf_counter() - started_at) * 1000,
    )


def _validate_beta(beta):
    if float(beta) < 0:
        raise ValueError("Risk weight beta must be non-negative.")


def _edge_cost(edge, risk, beta, penalty):
    risk = min(max(float(risk), 0.0), 1.0)
    penalty = max(float(penalty), 0.0)
    return edge.distance_meters + float(beta) * risk * edge.distance_meters + penalty


def _distance_heuristic(node, goal):
    return haversine(node.latitude, node.longitude, goal.latitude, goal.longitude)


def _validate_endpoints(graph, start, goal):
    if start not in graph.nodes or goal not in graph.nodes:
        raise ValueError("Route endpoints must exist in the graph.")


def _reconstruct_path(graph, parent, start, goal):
    node_ids = [goal]
    edge_ids = []
    current = goal

    while current != start:
        previous, edge_id = parent[current]
        edge_ids.append(edge_id)
        current = previous
        node_ids.append(current)

    return tuple(reversed(node_ids)), tuple(reversed(edge_ids))
