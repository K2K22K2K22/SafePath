import math
from dataclasses import dataclass

from shapely import LineString, Point
from shapely.geometry import box
from shapely.strtree import STRtree

from .crime_loader import load_crime_data
from .geometry_utils import EARTH_RADIUS_METERS

INCIDENT_RADIUS_METERS = 200
MAX_SEVERITY = 5


@dataclass(frozen=True)
class EdgeRiskScores:
    scores: dict[str, float]
    covered_edge_ids: frozenset[str]
    coverage_bounds: tuple[float, float, float, float] | None

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
        self.incidents = self._valid_incidents(data)
        self.coverage_bounds = self._coverage_bounds()

    def score_edges(self, edges):
        if not edges:
            return EdgeRiskScores({}, frozenset(), self.coverage_bounds)
        if not self.incidents:
            return EdgeRiskScores(
                {edge_id: 0.0 for edge_id in edges},
                frozenset(),
                self.coverage_bounds,
            )

        reference_lat = sum(item[1] for item in self.incidents) / len(self.incidents)
        incident_points = [
            Point(self._project(lon, lat, reference_lat))
            for lon, lat, _ in self.incidents
        ]
        tree = STRtree(incident_points)
        scores = {}
        covered_edge_ids = set()
        coverage_area = self._coverage_area()

        for edge_id, edge in edges.items():
            line = LineString(
                [self._project(lon, lat, reference_lat) for lat, lon in edge.geometry]
            )
            geographic_line = LineString([(lon, lat) for lat, lon in edge.geometry])
            if coverage_area is not None and coverage_area.intersects(geographic_line):
                covered_edge_ids.add(edge_id)

            search_area = box(
                line.bounds[0] - self.radius_meters,
                line.bounds[1] - self.radius_meters,
                line.bounds[2] + self.radius_meters,
                line.bounds[3] + self.radius_meters,
            )
            exposure = 0.0

            for index in tree.query(search_area):
                distance = line.distance(incident_points[index])
                if distance <= self.radius_meters:
                    severity = self.incidents[index][2]
                    exposure += severity * (1 - distance / self.radius_meters)

            scores[edge_id] = risk_from_exposure(exposure)

        return EdgeRiskScores(
            scores,
            frozenset(covered_edge_ids),
            self.coverage_bounds,
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

    def _coverage_bounds(self):
        if not self.incidents:
            return None
        longitudes = [incident[0] for incident in self.incidents]
        latitudes = [incident[1] for incident in self.incidents]
        return (
            min(longitudes),
            min(latitudes),
            max(longitudes),
            max(latitudes),
        )

    def _coverage_area(self):
        if self.coverage_bounds is None:
            return None
        left, bottom, right, top = self.coverage_bounds
        return box(left, bottom, right, top)


def risk_from_exposure(exposure):
    return 1 - math.exp(-max(exposure, 0.0))
