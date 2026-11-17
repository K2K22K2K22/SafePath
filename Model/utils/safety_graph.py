from collections import defaultdict

from .geometry_utils import haversine


class RoadGraph:
    def __init__(self):
        self.edges = defaultdict(list)
        self.risk = {}

    def add_edge(self, a, b):
        distance = haversine(a[0], a[1], b[0], b[1])
        self.edges[a].append((b, distance))
        self.edges[b].append((a, distance))

    def set_risk(self, a, b, value):
        self.risk[(a, b)] = value
        self.risk[(b, a)] = value

    def get_neighbors(self, node):
        return self.edges[node]
