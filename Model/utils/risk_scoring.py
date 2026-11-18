import math
from dataclasses import dataclass

from shapely import LineString, Point
from shapely.geometry import box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .crime_loader import load_crime_data
from .geometry_utils import EARTH_RADIUS_METERS

INCIDENT_RADIUS_METERS = 200
MAX_SEVERITY = 5


@dataclass(frozen=True)
class EdgeRiskScores:
    scores: dict[str, float]
    proximity_covered_lengths_meters: dict[str, float]
    coverage_radius_meters: int

    def __getitem__(self, edge_id):
        return self.scores[edge_id]

    def get(self, edge_id, default=0.0):
        return self.scores.get(edge_id, default)

    def items(self):
        return self.scores.items()


class RiskScorer:
    def __init__(self, incidents=None, radius_meters=INCIDENT_RADIUS_METERS):
        if not math.isfinite(radius_meters) or radius_meters <= 0:
            raise ValueError("Incident radius must be a finite positive number.")

        data = load_crime_data() if incidents is None else incidents
        self.radius_meters = float(radius_meters)
        self.coverage_radius_meters = int(self.radius_meters)
        self.incidents = self._valid_incidents(data)

    def score_edges(self, edges):
        if not edges:
            return EdgeRiskScores({}, {}, self.coverage_radius_meters)
        if not self.incidents:
            return EdgeRiskScores(
                {edge_id: 0.0 for edge_id in edges},
                {edge_id: 0.0 for edge_id in edges},
                self.coverage_radius_meters,
            )

        reference_lat = sum(item[1] for item in self.incidents) / len(self.incidents)
        incident_points = [
            Point(self._project(lon, lat, reference_lat))
            for lon, lat, _ in self.incidents
        ]
        tree = STRtree(incident_points)
        scores = {}
        proximity_covered_lengths_meters = {}

        for edge_id, edge in edges.items():
            line = LineString(
                [self._project(lon, lat, reference_lat) for lat, lon in edge.geometry]
            )
            search_area = box(
                line.bounds[0] - self.radius_meters,
                line.bounds[1] - self.radius_meters,
                line.bounds[2] + self.radius_meters,
                line.bounds[3] + self.radius_meters,
            )
            exposure = 0.0
            covered_parts = []

            for index in tree.query(search_area):
                distance = line.distance(incident_points[index])
                if distance <= self.radius_meters:
                    severity = self.incidents[index][2]
                    exposure += severity * (1 - distance / self.radius_meters)
                    covered_parts.append(
                        line.intersection(
                            incident_points[index].buffer(self.radius_meters)
                        )
                    )

            scores[edge_id] = risk_from_exposure(exposure)
            proximity_covered_lengths_meters[edge_id] = self._covered_length_meters(
                line,
                covered_parts,
                edge.distance_meters,
            )

        return EdgeRiskScores(
            scores,
            proximity_covered_lengths_meters,
            self.coverage_radius_meters,
        )

    @staticmethod
    def _valid_incidents(data):
        incidents = []
        seen_rows = set()

        for raw_row in data.to_dict("records"):
            row_identity = tuple(
                sorted((key, str(value)) for key, value in raw_row.items())
            )
            if row_identity in seen_rows:
                continue
            seen_rows.add(row_identity)

            try:
                latitude = float(raw_row["latitude"])
                longitude = float(raw_row["longitude"])
                severity = float(raw_row["severity"])
            except (KeyError, TypeError, ValueError):
                continue

            if not all(
                math.isfinite(value) for value in (latitude, longitude, severity)
            ):
                continue
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                continue
            if not 1 <= severity <= MAX_SEVERITY:
                continue
            incidents.append((longitude, latitude, severity / MAX_SEVERITY))

        return incidents

    @staticmethod
    def _project(lon, lat, reference_lat):
        x = (
            math.radians(lon)
            * EARTH_RADIUS_METERS
            * math.cos(math.radians(reference_lat))
        )
        y = math.radians(lat) * EARTH_RADIUS_METERS
        return x, y

    @staticmethod
    def _covered_length_meters(line, covered_parts, edge_distance_meters):
        if not covered_parts or line.length <= 0:
            return 0.0
        covered = (
            covered_parts[0] if len(covered_parts) == 1 else unary_union(covered_parts)
        )
        fraction = min(1.0, max(0.0, covered.length / line.length))
        return edge_distance_meters * fraction


def risk_from_exposure(exposure):
    return 1 - math.exp(-max(exposure, 0.0))
