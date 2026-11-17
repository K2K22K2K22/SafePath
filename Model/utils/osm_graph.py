import itertools
import math
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests
from django.conf import settings

from .geometry_utils import haversine
from .road_graph import RoadGraph

DRIVE_HIGHWAYS = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "living_street",
    "service",
    "road",
}
DEFAULT_SPEEDS_KPH = {
    "motorway": 100,
    "trunk": 80,
    "primary": 60,
    "secondary": 50,
    "tertiary": 40,
    "unclassified": 30,
    "residential": 30,
    "living_street": 10,
    "service": 15,
    "road": 30,
}
_GRAPH_CACHE = {}


class RoadDataUnavailable(Exception):
    pass


@dataclass(frozen=True)
class RoadGraphResult:
    graph: RoadGraph
    start_node_id: str
    end_node_id: str
    start_snap_distance_meters: float
    end_snap_distance_meters: float
    start_candidates: tuple[tuple[str, float], ...]
    end_candidates: tuple[tuple[str, float], ...]


def load_road_graph(start_lat, start_lon, end_lat, end_lon):
    _validate_coordinates(start_lat, start_lon, end_lat, end_lon)
    padding_meters = settings.SAFEPATH_GRAPH_PADDING_METERS

    for padding in (padding_meters, padding_meters * 2):
        bbox = _build_bbox(
            start_lat,
            start_lon,
            end_lat,
            end_lon,
            padding,
        )
        graph = _load_cached_graph(bbox)
        if graph is None:
            graph = _download_graph(bbox)

        start_candidates = _nearest_candidates(graph, start_lat, start_lon)
        end_candidates = _nearest_candidates(graph, end_lat, end_lon)
        if not start_candidates or not end_candidates:
            continue
        start_node_id, start_distance = start_candidates[0]
        end_node_id, end_distance = end_candidates[0]
        if (
            max(start_distance, end_distance)
            > settings.SAFEPATH_MAX_SNAP_DISTANCE_METERS
        ):
            continue

        return RoadGraphResult(
            graph=graph,
            start_node_id=start_node_id,
            end_node_id=end_node_id,
            start_snap_distance_meters=start_distance,
            end_snap_distance_meters=end_distance,
            start_candidates=start_candidates,
            end_candidates=end_candidates,
        )

    raise RoadDataUnavailable(
        "No usable road graph was available near the requested origin and destination."
    )


def _download_graph(bbox):
    try:
        osm_xml = _fetch_osm_xml(bbox)
        graph = _build_graph_from_xml(osm_xml)
    except (ET.ParseError, OSError, ValueError, requests.RequestException) as error:
        raise RoadDataUnavailable("Road data could not be loaded.") from error

    if not graph.nodes or not graph.edges:
        raise RoadDataUnavailable("Road data did not contain a usable driving graph.")

    _GRAPH_CACHE[bbox] = (time.monotonic(), graph)
    return graph


def _fetch_osm_xml(bbox):
    left, bottom, right, top = bbox
    area = (right - left) * (top - bottom)
    if area > settings.SAFEPATH_OSM_API_MAX_AREA:
        return _fetch_split_bbox(bbox)

    try:
        response = requests.get(
            settings.SAFEPATH_OSM_API_URL,
            params={"bbox": f"{left},{bottom},{right},{top}"},
            headers={"User-Agent": settings.SAFEPATH_HTTP_USER_AGENT},
            timeout=(10, settings.SAFEPATH_ROAD_DATA_TIMEOUT_SECONDS),
        )
        response.raise_for_status()
    except requests.HTTPError as error:
        if error.response is not None and error.response.status_code in {400, 509}:
            return _fetch_split_bbox(bbox)
        raise

    if len(response.content) > settings.SAFEPATH_OSM_API_MAX_BYTES:
        raise RoadDataUnavailable("Road data response exceeded the allowed size.")
    return response.content


def _fetch_split_bbox(bbox):
    left, bottom, right, top = bbox
    width = right - left
    height = top - bottom
    if width <= 0 or height <= 0:
        raise RoadDataUnavailable("Road data area was invalid.")

    if width >= height:
        middle = (left + right) / 2
        first = _fetch_osm_xml((left, bottom, middle, top))
        second = _fetch_osm_xml((middle, bottom, right, top))
    else:
        middle = (bottom + top) / 2
        first = _fetch_osm_xml((left, bottom, right, middle))
        second = _fetch_osm_xml((left, middle, right, top))

    return _merge_osm_documents(first, second)


def _merge_osm_documents(*documents):
    merged = ET.Element("osm", {"version": "0.6"})
    seen = set()

    for document in documents:
        root = ET.fromstring(document)
        for element in root:
            key = (element.tag, element.attrib.get("id"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(element)

    return ET.tostring(merged, encoding="utf-8")


def _build_graph_from_xml(osm_xml):
    root = ET.fromstring(osm_xml)
    coordinates = {
        element.attrib["id"]: (
            float(element.attrib["lat"]),
            float(element.attrib["lon"]),
        )
        for element in root.findall("node")
        if "id" in element.attrib
        and "lat" in element.attrib
        and "lon" in element.attrib
    }
    graph = RoadGraph()
    added_nodes = set()

    for way in root.findall("way"):
        tags = {
            tag.attrib["k"]: tag.attrib["v"]
            for tag in way.findall("tag")
            if "k" in tag.attrib and "v" in tag.attrib
        }
        highway = _drivable_highway(tags.get("highway"))
        if not highway or not _is_accessible(tags):
            continue

        references = [
            element.attrib["ref"]
            for element in way.findall("nd")
            if "ref" in element.attrib
        ]
        forward, reverse = _edge_directions(tags)
        speed_kph = _speed_kph(tags, highway)

        for index, (source, target) in enumerate(itertools.pairwise(references)):
            if source not in coordinates or target not in coordinates:
                continue
            source_coordinate = coordinates[source]
            target_coordinate = coordinates[target]
            distance = haversine(
                source_coordinate[0],
                source_coordinate[1],
                target_coordinate[0],
                target_coordinate[1],
            )
            if distance <= 0:
                continue

            for node_id in (source, target):
                if node_id not in added_nodes:
                    graph.add_node(node_id, *coordinates[node_id])
                    added_nodes.add(node_id)

            edge_id = f"way-{way.attrib['id']}-{index}"
            metadata = {
                "osm_way_id": way.attrib.get("id"),
                "highway": highway,
                "name": tags.get("name"),
                "oneway": tags.get("oneway", "no"),
                "maxspeed": tags.get("maxspeed"),
            }
            travel_time = distance / (speed_kph / 3.6)

            if forward:
                graph.add_edge(
                    edge_id,
                    source,
                    target,
                    distance,
                    (source_coordinate, target_coordinate),
                    metadata,
                    travel_time,
                )
            if reverse:
                graph.add_edge(
                    f"{edge_id}-reverse",
                    target,
                    source,
                    distance,
                    (target_coordinate, source_coordinate),
                    metadata,
                    travel_time,
                )

    return graph


def _drivable_highway(value):
    if not value:
        return None
    highway = value.split(";")[0].strip().lower()
    if highway in DRIVE_HIGHWAYS:
        return highway
    if highway.endswith("_link") and highway.removesuffix("_link") in DRIVE_HIGHWAYS:
        return highway
    return None


def _is_accessible(tags):
    if tags.get("impassable", "").lower() in {"yes", "true", "1"}:
        return False
    for key in ("access", "motor_vehicle", "motorcar", "vehicle"):
        if tags.get(key, "").lower() in {"no", "private"}:
            return False
    return True


def _edge_directions(tags):
    oneway = tags.get("oneway", "").strip().lower()
    if oneway in {"-1", "reverse"}:
        return False, True
    if oneway in {"yes", "true", "1"}:
        return True, False
    if tags.get("junction", "").lower() == "roundabout":
        return True, False
    return True, True


def _speed_kph(tags, highway):
    maxspeed = tags.get("maxspeed", "").split(";")[0].strip().lower()
    match = re.search(r"\d+(?:\.\d+)?", maxspeed)
    if match:
        speed = float(match.group())
        if "mph" in maxspeed:
            speed *= 1.609344
        if 5 <= speed <= 160:
            return speed

    base_highway = highway.removesuffix("_link")
    return DEFAULT_SPEEDS_KPH.get(base_highway, 30)


def _build_bbox(start_lat, start_lon, end_lat, end_lon, padding_meters):
    reference_lat = (start_lat + end_lat) / 2
    lat_padding = padding_meters / 111_320
    lon_scale = max(math.cos(math.radians(reference_lat)), 0.1)
    lon_padding = padding_meters / (111_320 * lon_scale)

    left = math.floor((min(start_lon, end_lon) - lon_padding) * 10_000) / 10_000
    bottom = math.floor((min(start_lat, end_lat) - lat_padding) * 10_000) / 10_000
    right = math.ceil((max(start_lon, end_lon) + lon_padding) * 10_000) / 10_000
    top = math.ceil((max(start_lat, end_lat) + lat_padding) * 10_000) / 10_000
    return left, bottom, right, top


def _load_cached_graph(bbox):
    cached = _GRAPH_CACHE.get(bbox)
    if not cached:
        return None

    created_at, graph = cached
    if time.monotonic() - created_at > settings.SAFEPATH_GRAPH_CACHE_TTL_SECONDS:
        _GRAPH_CACHE.pop(bbox, None)
        return None
    return graph


def _nearest_candidates(graph, latitude, longitude):
    candidates = sorted(
        (
            (node_id, haversine(latitude, longitude, node.latitude, node.longitude))
            for node_id, node in graph.nodes.items()
        ),
        key=lambda item: item[1],
    )
    return tuple(
        candidate
        for candidate in candidates
        if candidate[1] <= settings.SAFEPATH_MAX_SNAP_DISTANCE_METERS
    )[: settings.SAFEPATH_SNAP_CANDIDATE_LIMIT]


def _validate_coordinates(start_lat, start_lon, end_lat, end_lon):
    coordinates = (start_lat, start_lon, end_lat, end_lon)
    if not all(math.isfinite(value) for value in coordinates):
        raise ValueError("Coordinates must be finite numbers.")
    if not -90 <= start_lat <= 90 or not -90 <= end_lat <= 90:
        raise ValueError("Latitude must be between -90 and 90.")
    if not -180 <= start_lon <= 180 or not -180 <= end_lon <= 180:
        raise ValueError("Longitude must be between -180 and 180.")
