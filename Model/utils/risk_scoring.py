import math

from shapely import LineString, Point
from shapely.geometry import box
from shapely.strtree import STRtree

from .crime_loader import load_crime_data
from .geometry_utils import EARTH_RADIUS_METERS

INCIDENT_RADIUS_METERS = 200
MAX_SEVERITY = 5


class RiskScorer:
    def __init__(self, incidents=None, radius_meters=INCIDENT_RADIUS_METERS):
        if not math.isfinite(radius_meters) or radius_meters <= 0:
            raise ValueError("Incident radius must be a finite positive number.")

        data = load_crime_data() if incidents is None else incidents
        self.radius_meters = float(radius_meters)
        self.incidents = self._valid_incidents(data)

    def score_edges(self, edges):
        if not self.incidents or not edges:
            return {edge_id: 0.0 for edge_id in edges}

        reference_lat = sum(item[1] for item in self.incidents) / len(self.incidents)
        incident_points = [
            Point(self._project(lon, lat, reference_lat))
            for lon, lat, _ in self.incidents
        ]
        tree = STRtree(incident_points)
        scores = {}

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

            for index in tree.query(search_area):
                distance = line.distance(incident_points[index])
                if distance <= self.radius_meters:
                    severity = self.incidents[index][2]
                    exposure += severity * (1 - distance / self.radius_meters)

            scores[edge_id] = risk_from_exposure(exposure)

        return scores

    @staticmethod
    def _valid_incidents(data):
        incidents = []
        for row in data.itertuples(index=False):
            latitude = float(row.latitude)
            longitude = float(row.longitude)
            severity = float(row.severity)
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


def risk_from_exposure(exposure):
    return 1 - math.exp(-max(exposure, 0.0))
