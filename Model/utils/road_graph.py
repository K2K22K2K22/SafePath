import math
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RoadNode:
    id: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class RoadEdge:
    id: str
    source: str
    target: str
    distance_meters: float
    geometry: tuple[tuple[float, float], ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    travel_time_seconds: float | None = None


class RoadGraph:
    def __init__(self):
        self.nodes: dict[str, RoadNode] = {}
        self.edges: dict[str, RoadEdge] = {}
        self.outgoing: dict[str, tuple[str, ...]] = {}
        self.incoming: dict[str, tuple[str, ...]] = {}

    def add_node(self, node_id, latitude, longitude):
        node_id = str(node_id)
        latitude = float(latitude)
        longitude = float(longitude)

        if node_id in self.nodes:
            raise ValueError(f"Node {node_id} already exists.")
        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise ValueError("Node latitude must be between -90 and 90.")
        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise ValueError("Node longitude must be between -180 and 180.")

        self.nodes[node_id] = RoadNode(node_id, latitude, longitude)
        self.outgoing[node_id] = ()
        self.incoming[node_id] = ()
        return self.nodes[node_id]

    def add_edge(
        self,
        edge_id,
        source,
        target,
        distance_meters,
        geometry,
        metadata=None,
        travel_time_seconds=None,
    ):
        edge_id = str(edge_id)
        source = str(source)
        target = str(target)
        distance_meters = float(distance_meters)
        geometry = tuple((float(lat), float(lon)) for lat, lon in geometry)

        if edge_id in self.edges:
            raise ValueError(f"Edge {edge_id} already exists.")
        if source not in self.nodes or target not in self.nodes:
            raise ValueError("Edge endpoints must exist in the graph.")
        if not math.isfinite(distance_meters) or distance_meters < 0:
            raise ValueError("Edge distance must be a finite non-negative number.")
        if not geometry:
            raise ValueError("Edge geometry must contain at least one point.")

        edge = RoadEdge(
            id=edge_id,
            source=source,
            target=target,
            distance_meters=distance_meters,
            geometry=geometry,
            metadata=dict(metadata or {}),
            travel_time_seconds=travel_time_seconds,
        )
        self.edges[edge_id] = edge
        self.outgoing[source] = self.outgoing[source] + (edge_id,)
        self.incoming[target] = self.incoming[target] + (edge_id,)
        return edge

    def outgoing_edges(self, node_id):
        return self.outgoing.get(str(node_id), ())
