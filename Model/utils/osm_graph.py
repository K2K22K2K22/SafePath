import itertools
import math
import re
import threading
import time
import weakref
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import urlparse

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
BLOCKED_ACCESS_VALUES = {"no", "private"}
RESTRICTED_ACCESS_VALUES = {
    "customers",
    "delivery",
    "destination",
    "parking",
    "permit",
}
PUBLIC_OVERPASS_HOSTS = frozenset(
    {
        "ethiopia.overpass.openplaceguide.org",
        "gall.openstreetmap.de",
        "lambert.openstreetmap.de",
        "lz4.overpass-api.de",
        "maps.mail.ru",
        "overpass-api.de",
        "overpass.atownsend.org.uk",
        "overpass.kumi.systems",
        "overpass.maprva.org",
        "overpass.openstreetmap.fr",
        "overpass.osm.ch",
        "overpass.osm.jp",
        "overpass.private.coffee",
        "ovp.dresel.systems",
        "z.overpass-api.de",
    }
)
OVERPASS_HIGHWAY_PATTERN = (
    "^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|"
    "living_street|service|road)(_link)?$"
)
OVERPASS_OVERSIZED_ERROR_MARKERS = (
    "exceeded the maximum allowed size",
    "please use a smaller area",
    "too large",
    "too many elements",
)
MAX_PROVIDER_ERROR_BYTES = 64 * 1024
ALLOWED_ACCESS_VALUES = {
    "yes",
    "true",
    "1",
    "permissive",
    "designated",
    "unlimited",
    "public",
}
PHYSICAL_BARRIERS = {
    "bollard",
    "block",
    "bus_trap",
    "cycle_barrier",
    "stile",
    "turnstile",
}
GATE_BARRIERS = {"gate", "lift_gate"}
_GRAPH_CACHE: OrderedDict[
    tuple[float, float, float, float], tuple[float, RoadGraph]
] = OrderedDict()
_GRAPH_CACHE_LOCK = threading.RLock()
_GRAPH_LOAD_LOCKS: weakref.WeakValueDictionary[
    tuple[float, float, float, float], threading.Lock
] = weakref.WeakValueDictionary()
_GRAPH_LOAD_LOCKS_GUARD = threading.Lock()
_ROAD_PROVIDER_REQUEST_LOCK = threading.RLock()


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


@dataclass
class _FetchBudget:
    deadline: float
    requests: int = 0
    bytes_read: int = 0

    def check_deadline(self):
        if time.monotonic() >= self.deadline:
            raise RoadDataUnavailable("Road data loading exceeded its time limit.")

    def remaining_seconds(self):
        self.check_deadline()
        return self.deadline - time.monotonic()

    def register_request(self):
        self.check_deadline()
        if self.requests >= settings.SAFEPATH_OSM_API_MAX_REQUESTS:
            raise RoadDataUnavailable("Road data loading exceeded its request limit.")
        self.requests += 1

    def add_bytes(self, byte_count):
        if self.bytes_read + byte_count > settings.SAFEPATH_OSM_API_MAX_BYTES:
            raise RoadDataUnavailable("Road data response exceeded the allowed size.")
        self.bytes_read += byte_count


def load_road_graph(start_lat, start_lon, end_lat, end_lon):
    _validate_coordinates(start_lat, start_lon, end_lat, end_lon)
    direct_distance = haversine(start_lat, start_lon, end_lat, end_lon)
    if direct_distance > settings.SAFEPATH_MAX_ROUTE_SPAN_METERS:
        raise ValueError(
            f"Route span cannot exceed {settings.SAFEPATH_MAX_ROUTE_SPAN_METERS} metres."
        )

    padding_meters = settings.SAFEPATH_GRAPH_PADDING_METERS
    for padding in (padding_meters, padding_meters * 2):
        bbox = _build_bbox(
            start_lat,
            start_lon,
            end_lat,
            end_lon,
            padding,
        )
        if _bbox_area(bbox) > settings.SAFEPATH_MAX_ROUTE_AREA:
            raise ValueError("Requested route area is too large.")

        graph = _load_cached_graph(bbox)
        if graph is None:
            with _load_lock(bbox):
                graph = _load_cached_graph(bbox)
                if graph is None:
                    graph = _download_graph(bbox)
        if not graph.nodes or not graph.edges:
            continue

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
        documents = _fetch_osm_xml(bbox)
        graph = _build_graph_from_xml(documents)
    except RoadDataUnavailable:
        raise
    except (ET.ParseError, OSError, ValueError, TypeError, KeyError) as error:
        raise RoadDataUnavailable("Road data could not be loaded.") from error
    except requests.RequestException as error:
        raise RoadDataUnavailable("Road data is temporarily unavailable.") from error

    if graph.nodes and graph.edges:
        _store_cached_graph(bbox, graph)
    return graph


def _fetch_osm_xml(bbox, budget=None, depth=0):
    budget = budget or _FetchBudget(
        deadline=time.monotonic() + settings.SAFEPATH_ROAD_DATA_TIMEOUT_SECONDS
    )
    budget.check_deadline()
    if _bbox_area(bbox) > settings.SAFEPATH_OSM_API_MAX_AREA:
        return _fetch_split_bbox(bbox, budget, depth + 1)

    url = _validated_osm_url()
    query = _overpass_query(bbox)
    budget.register_request()
    chunks = []
    split_required = False

    try:
        with _ROAD_PROVIDER_REQUEST_LOCK:
            budget.check_deadline()
            remaining = budget.remaining_seconds()
            timeout = (
                max(min(10.0, remaining), 0.1),
                max(min(settings.SAFEPATH_ROAD_DATA_TIMEOUT_SECONDS, remaining), 0.1),
            )
            with requests.get(
                url,
                params={"data": query},
                headers={
                    "Accept": "application/xml",
                    "User-Agent": settings.SAFEPATH_HTTP_USER_AGENT,
                },
                timeout=timeout,
                stream=True,
                allow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise RoadDataUnavailable(
                        "Road data provider redirects were rejected."
                    )

                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > settings.SAFEPATH_OSM_API_MAX_BYTES:
                            raise RoadDataUnavailable(
                                "Road data response exceeded the allowed size."
                            )
                    except ValueError as error:
                        raise RoadDataUnavailable(
                            "Road data provider returned an invalid content length."
                        ) from error

                if response.status_code == 400:
                    error_text = _read_provider_error(response, budget)
                    split_required = _overpass_error_requires_split(error_text)
                    if not split_required:
                        raise RoadDataUnavailable(
                            "Road data provider rejected the query."
                        )
                else:
                    response.raise_for_status()
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        budget.check_deadline()
                        if not chunk:
                            continue
                        budget.add_bytes(len(chunk))
                        chunks.append(chunk)
    except RoadDataUnavailable:
        raise
    except requests.RequestException as error:
        raise RoadDataUnavailable("Road data is temporarily unavailable.") from error

    if split_required:
        return _fetch_split_bbox(bbox, budget, depth + 1)
    return (b"".join(chunks),)


def _read_provider_error(response, budget):
    chunks = []
    bytes_read = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        budget.check_deadline()
        if not chunk:
            continue
        bytes_read += len(chunk)
        if bytes_read > MAX_PROVIDER_ERROR_BYTES:
            raise RoadDataUnavailable(
                "Road data provider error response was too large."
            )
        budget.add_bytes(len(chunk))
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace").lower()


def _overpass_error_requires_split(error_text):
    return any(marker in error_text for marker in OVERPASS_OVERSIZED_ERROR_MARKERS)


def _overpass_query(bbox):
    left, bottom, right, top = bbox
    return (
        "[out:xml][timeout:25][maxsize:268435456];\n"
        f'(way["highway"~"{OVERPASS_HIGHWAY_PATTERN}"]'
        f"({bottom:.7f},{left:.7f},{top:.7f},{right:.7f});\n"
        ">;\n"
        ");\n"
        "out body;"
    )


def _fetch_split_bbox(bbox, budget, depth):
    if depth > settings.SAFEPATH_OSM_API_MAX_SPLIT_DEPTH:
        raise RoadDataUnavailable("Road data area could not be split within the limit.")

    left, bottom, right, top = bbox
    width = right - left
    height = top - bottom
    if width <= 0 or height <= 0:
        raise RoadDataUnavailable("Road data area was invalid.")

    if width >= height:
        middle = (left + right) / 2
        first = _fetch_osm_xml((left, bottom, middle, top), budget, depth)
        second = _fetch_osm_xml((middle, bottom, right, top), budget, depth)
    else:
        middle = (bottom + top) / 2
        first = _fetch_osm_xml((left, bottom, right, middle), budget, depth)
        second = _fetch_osm_xml((left, middle, right, top), budget, depth)

    return first + second


def _build_graph_from_xml(osm_xml):
    documents = osm_xml if isinstance(osm_xml, (list, tuple)) else (osm_xml,)
    coordinates = {}
    node_tags = {}
    ways: dict[str, tuple[str, dict[str, str], list[str]]] = {}

    for document in documents:
        document_coordinates, document_node_tags, document_ways = _parse_osm_document(
            document
        )
        coordinates.update(document_coordinates)
        node_tags.update(document_node_tags)
        for way_id, way in document_ways.items():
            ways.setdefault(way_id, way)

    graph = RoadGraph()
    added_nodes = set()

    for way_id, tags, references in ways.values():
        highway = _drivable_highway(tags.get("highway"))
        if not highway or not _is_accessible(tags):
            continue

        forward, reverse = _edge_directions(tags, highway)
        speed_kph = _speed_kph(tags, highway)

        for index, (source, target) in enumerate(itertools.pairwise(references)):
            if source not in coordinates or target not in coordinates:
                continue
            if _node_blocks_vehicle(node_tags.get(source, {})) or _node_blocks_vehicle(
                node_tags.get(target, {})
            ):
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

            edge_id = f"way-{way_id}-{index}"
            metadata = {
                "osm_way_id": way_id,
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

            if len(graph.edges) > settings.SAFEPATH_MAX_GRAPH_EDGES:
                raise RoadDataUnavailable("Road data exceeded the graph edge limit.")

    return graph


def _validate_utf8_document(document):
    try:
        text = document.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RoadDataUnavailable(
            "Road data document must be UTF-8 encoded."
        ) from error
    if "\x00" in text:
        raise RoadDataUnavailable("Road data document must be UTF-8 encoded.")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", text, flags=re.IGNORECASE):
        raise RoadDataUnavailable(
            "Road data document contains prohibited XML declarations."
        )


def _parse_osm_document(document):
    if not isinstance(document, bytes):
        raise RoadDataUnavailable("Road data document must be bytes.")
    _validate_utf8_document(document)

    coordinates = {}
    node_tags = {}
    ways = {}
    depth = 0
    element_count = 0
    root_seen = False

    try:
        events = ET.iterparse(BytesIO(document), events=("start", "end"))
        for event, element in events:
            if event == "start":
                depth += 1
                if depth > settings.SAFEPATH_OSM_API_MAX_XML_DEPTH:
                    raise RoadDataUnavailable("Road data XML exceeded the depth limit.")
                if not root_seen:
                    root_seen = True
                    if element.tag != "osm" or element.attrib.get("version") != "0.6":
                        raise RoadDataUnavailable(
                            "Road data document was not valid OSM XML."
                        )
                continue

            depth -= 1
            element_count += 1
            if element_count > settings.SAFEPATH_OSM_API_MAX_XML_ELEMENTS:
                raise RoadDataUnavailable("Road data XML exceeded the element limit.")
            if element.tag in {"error", "remark"}:
                raise RoadDataUnavailable(
                    "Road data provider returned a partial response."
                )
            if element.tag == "node":
                node_id, coordinate, tags = _parse_node(element)
                coordinates[node_id] = coordinate
                node_tags[node_id] = tags
                element.clear()
            elif element.tag == "way":
                way = _parse_way(element)
                if way is not None:
                    way_id, tags, references = way
                    ways[way_id] = (way_id, tags, references)
                element.clear()
    except ET.ParseError as error:
        raise RoadDataUnavailable("Road data document was not valid XML.") from error

    if not root_seen:
        raise RoadDataUnavailable("Road data document was empty.")
    return coordinates, node_tags, ways


def _parse_node(element):
    try:
        node_id = element.attrib["id"]
        latitude = float(element.attrib["lat"])
        longitude = float(element.attrib["lon"])
    except (KeyError, TypeError, ValueError) as error:
        raise RoadDataUnavailable("Road data contained a malformed node.") from error

    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise RoadDataUnavailable("Road data contained an invalid node coordinate.")
    return node_id, (latitude, longitude), _tags_from_element(element)


def _parse_way(element):
    tags = _tags_from_element(element)
    if not _drivable_highway(tags.get("highway")):
        return None

    try:
        way_id = element.attrib["id"]
    except KeyError as error:
        raise RoadDataUnavailable(
            "Road data contained a malformed road way."
        ) from error

    references = [
        child.attrib["ref"] for child in element.findall("nd") if "ref" in child.attrib
    ]
    if len(references) < 2:
        return None
    return way_id, tags, references


def _tags_from_element(element):
    return {
        tag.attrib["k"]: tag.attrib["v"]
        for tag in element.findall("tag")
        if "k" in tag.attrib and "v" in tag.attrib
    }


def _drivable_highway(value):
    if not value:
        return None
    highway = value.split(";")[0].strip().lower()
    if highway in DRIVE_HIGHWAYS:
        return highway
    if highway.endswith("_link") and highway.removesuffix("_link") in DRIVE_HIGHWAYS:
        return highway
    return None


def _access_value(tags):
    for key in ("motorcar", "motor_vehicle", "vehicle", "access"):
        if key in tags:
            return tags[key].strip().lower()
    return None


def _is_accessible(tags):
    if tags.get("impassable", "").strip().lower() in {"yes", "true", "1"}:
        return False
    access = _access_value(tags)
    if access is None:
        return True
    if access in BLOCKED_ACCESS_VALUES or access in RESTRICTED_ACCESS_VALUES:
        return False
    return access in ALLOWED_ACCESS_VALUES


def _node_blocks_vehicle(tags):
    if tags.get("impassable", "").strip().lower() in {"yes", "true", "1"}:
        return True
    access = _access_value(tags)
    if access in BLOCKED_ACCESS_VALUES or access in RESTRICTED_ACCESS_VALUES:
        return True
    if access in ALLOWED_ACCESS_VALUES:
        return False

    barrier = tags.get("barrier", "").strip().lower()
    return barrier in PHYSICAL_BARRIERS or barrier in GATE_BARRIERS


def _edge_directions(tags, highway):
    oneway = tags.get("oneway", "").strip().lower()
    if oneway in {"-1", "reverse"}:
        return False, True
    if oneway in {"yes", "true", "1"}:
        return True, False
    if oneway in {"no", "false", "0"}:
        return True, True
    if tags.get("junction", "").strip().lower() == "roundabout":
        return True, False
    if highway.removesuffix("_link") == "motorway":
        return True, False
    return True, True


def _speed_kph(tags, highway):
    maxspeed = tags.get("maxspeed", "").split(";")[0].strip().lower()
    match = re.search(r"\d+(?:\.\d+)?", maxspeed)
    if match:
        speed = float(match.group())
        if "knot" in maxspeed:
            speed *= 1.852
        elif "mph" in maxspeed:
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


def _bbox_area(bbox):
    left, bottom, right, top = bbox
    return (right - left) * (top - bottom)


def _load_cached_graph(bbox):
    with _GRAPH_CACHE_LOCK:
        cached = _GRAPH_CACHE.get(bbox)
        if not cached:
            return None
        created_at, graph = cached
        if time.monotonic() - created_at > settings.SAFEPATH_GRAPH_CACHE_TTL_SECONDS:
            _GRAPH_CACHE.pop(bbox, None)
            return None
        _GRAPH_CACHE.move_to_end(bbox)
        return graph


def _store_cached_graph(bbox, graph):
    with _GRAPH_CACHE_LOCK:
        now = time.monotonic()
        expired = [
            key
            for key, (created_at, _) in _GRAPH_CACHE.items()
            if now - created_at > settings.SAFEPATH_GRAPH_CACHE_TTL_SECONDS
        ]
        for key in expired:
            _GRAPH_CACHE.pop(key, None)
        _GRAPH_CACHE[bbox] = (now, graph)
        _GRAPH_CACHE.move_to_end(bbox)
        while len(_GRAPH_CACHE) > settings.SAFEPATH_GRAPH_CACHE_MAX_ENTRIES:
            _GRAPH_CACHE.popitem(last=False)


def _load_lock(bbox):
    with _GRAPH_LOAD_LOCKS_GUARD:
        lock = _GRAPH_LOAD_LOCKS.get(bbox)
        if lock is None:
            lock = threading.Lock()
            _GRAPH_LOAD_LOCKS[bbox] = lock
        return lock


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


def _normalized_hostname(hostname):
    if not hostname:
        return ""
    host = hostname.strip().rstrip(".").lower()
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return ""


def _validated_osm_url(require_private=None):
    url = settings.SAFEPATH_OSM_API_URL
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise RoadDataUnavailable("Road data provider URL is invalid.") from error
    normalized_hostname = _normalized_hostname(hostname)
    allowed_hosts = {
        _normalized_hostname(host) for host in settings.SAFEPATH_OSM_API_ALLOWED_HOSTS
    }
    if (
        parsed.scheme != "https"
        or not normalized_hostname
        or normalized_hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise RoadDataUnavailable("Road data provider URL is not allowed.")
    require_private = (
        settings.SAFEPATH_PRODUCTION_MODE
        if require_private is None
        else require_private
    )
    if require_private:
        if normalized_hostname in PUBLIC_OVERPASS_HOSTS:
            raise RoadDataUnavailable(
                "Production requires a paid or self-hosted road data provider."
            )
        production_allowed_hosts = {
            _normalized_hostname(host)
            for host in settings.SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS
        }
        if normalized_hostname not in production_allowed_hosts:
            raise RoadDataUnavailable(
                "Production road data provider must be explicitly approved."
            )
    return url


def _validate_coordinates(start_lat, start_lon, end_lat, end_lon):
    coordinates = (start_lat, start_lon, end_lat, end_lon)
    if not all(math.isfinite(value) for value in coordinates):
        raise ValueError("Coordinates must be finite numbers.")
    if not -90 <= start_lat <= 90 or not -90 <= end_lat <= 90:
        raise ValueError("Latitude must be between -90 and 90.")
    if not -180 <= start_lon <= 180 or not -180 <= end_lon <= 180:
        raise ValueError("Longitude must be between -180 and 180.")
