import hashlib
import json
import math
import pickle
import time
import unicodedata
import zlib
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.cache import caches
from django.core.files import locks
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .utils.crime_loader import PUBLIC_INCIDENT_DATA_METADATA
from .utils.osm_graph import RoadDataUnavailable
from .utils.risk_scoring import INCIDENT_RADIUS_METERS, RiskScorer
from .utils.route_service import RouteNotFound, calculate_route_options
from .utils.routing import SearchLimitExceeded

GEOCODER_REQUEST_INTERVAL_SECONDS = 1.0
MAX_GEOCODER_RESPONSE_BYTES = 64 * 1024
INCIDENT_COVERAGE_SEMANTICS = {
    "basis": "record_proximity",
    "radius_meters": INCIDENT_RADIUS_METERS,
    "measurement": "union_of_record_influence_zones",
    "route_eligibility": "every_edge_fully_covered",
    "unknown_when": "coverage_is_partial_or_missing",
}
_GEOCODER_CACHE_ERRORS = (
    OSError,
    EOFError,
    pickle.PickleError,
    zlib.error,
    ValueError,
    AttributeError,
    ImportError,
    IndexError,
)


class RoutesRateThrottle(ScopedRateThrottle):
    scope = "routes"


class GeocodeRateThrottle(ScopedRateThrottle):
    scope = "geocode"


class HeatmapRateThrottle(ScopedRateThrottle):
    scope = "heatmap"


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET"])
@throttle_classes([HeatmapRateThrottle])
def safety_heatmap(request):
    try:
        incidents = RiskScorer().incidents
    except (OSError, ValueError):
        return Response(
            {"detail": "Incident data is temporarily unavailable."},
            status=503,
        )

    points = [
        {
            "lat": latitude,
            "lon": longitude,
            "intensity": round(intensity, 4),
        }
        for longitude, latitude, intensity in incidents
    ]
    return Response(
        {
            "points": points,
            "radius_meters": INCIDENT_RADIUS_METERS,
            "record_count": len(points),
            "source": "bundled_csv",
            "metadata": {
                **PUBLIC_INCIDENT_DATA_METADATA,
                "source": "bundled_csv",
            },
            "coverage_semantics": INCIDENT_COVERAGE_SEMANTICS,
        }
    )


safety_heatmap.cls.throttle_scope = "heatmap"


@api_view(["GET"])
@throttle_classes([GeocodeRateThrottle])
def geocode(request):
    raw_query = request.GET.get("q", "").strip()
    if len(raw_query) < 2:
        return Response({"detail": "Enter at least two characters."}, status=400)
    if len(raw_query) > 200:
        return Response({"detail": "Location search is too long."}, status=400)
    query = _normalize_geocoder_query(raw_query)

    try:
        url = _validated_geocoder_url()
    except ValueError:
        return Response(
            {"detail": "Location search is temporarily unavailable. Please try again."},
            status=503,
        )

    cache_key = _geocoder_cache_key(url, query)
    geocoder_cache = None
    try:
        geocoder_cache = caches["geocoder"]
        cached_results = geocoder_cache.get(cache_key)
    except _GEOCODER_CACHE_ERRORS:
        cached_results = None
    if isinstance(cached_results, list):
        return Response({"results": cached_results, "source": "nominatim"})

    try:
        _reserve_geocoder_request()
        response = requests.get(
            url,
            params={
                "format": "jsonv2",
                "q": query,
                "limit": 5,
                "addressdetails": 0,
            },
            headers={
                "Accept": "application/json",
                "Accept-Language": "en",
                "User-Agent": settings.SAFEPATH_HTTP_USER_AGENT,
            },
            timeout=(3, settings.SAFEPATH_GEOCODER_TIMEOUT_SECONDS),
            allow_redirects=False,
            stream=True,
        )
        try:
            if 300 <= response.status_code < 400:
                return Response(
                    {"detail": "Location service redirects were rejected."},
                    status=503,
                )
            response.raise_for_status()
            payload = _read_geocoder_payload(response)
            results = _validated_geocoder_results(payload)
        finally:
            response.close()
    except (requests.RequestException, OSError):
        return Response(
            {"detail": "Location search is temporarily unavailable. Please try again."},
            status=503,
        )
    except (TypeError, ValueError):
        return Response(
            {"detail": "Location search returned an invalid response."},
            status=503,
        )

    if geocoder_cache is not None:
        try:
            geocoder_cache.set(
                cache_key,
                results,
                timeout=settings.SAFEPATH_GEOCODER_CACHE_TTL_SECONDS,
            )
        except _GEOCODER_CACHE_ERRORS:
            pass
    return Response({"results": results, "source": "nominatim"})


geocode.cls.throttle_scope = "geocode"


@api_view(["GET"])
@throttle_classes([RoutesRateThrottle])
def routes(request):
    try:
        start_lat = _coordinate(request.GET.get("start_lat"), "start_lat", -90, 90)
        start_lon = _coordinate(request.GET.get("start_lon"), "start_lon", -180, 180)
        end_lat = _coordinate(request.GET.get("end_lat"), "end_lat", -90, 90)
        end_lon = _coordinate(request.GET.get("end_lon"), "end_lon", -180, 180)
    except ValueError as error:
        return Response({"detail": str(error)}, status=400)

    try:
        options = calculate_route_options(start_lat, start_lon, end_lat, end_lon)
    except ValueError as error:
        return Response({"detail": str(error)}, status=400)
    except RouteNotFound:
        return Response(
            {"detail": "No route was found for these coordinates."}, status=404
        )
    except SearchLimitExceeded:
        return Response(
            {"detail": "Route search temporarily exceeded its work limit."},
            status=503,
        )
    except RoadDataUnavailable:
        return Response(
            {"detail": "Road data is temporarily unavailable. Please try again."},
            status=503,
        )

    serialized_routes = [_serialize_route(option) for option in options]
    shortest = _route_with_label(options, "shortest") or options[0]
    safest = _route_with_label(options, "safest")

    return Response(
        {
            "origin": {"lat": start_lat, "lon": start_lon},
            "destination": {"lat": end_lat, "lon": end_lon},
            "routes": serialized_routes,
            "route_count": len(serialized_routes),
            "incident_data": {
                **PUBLIC_INCIDENT_DATA_METADATA,
                "source": "bundled_csv",
                "coverage_semantics": INCIDENT_COVERAGE_SEMANTICS,
            },
            "original_route": [list(point) for point in shortest.geometry],
            "safe_path": (
                [list(point) for point in safest.geometry]
                if safest is not None
                else None
            ),
            "safest_route_available": safest is not None,
            "distance_meters": shortest.distance_meters,
            "avg_risk": shortest.risk_score,
            "nodes": len(shortest.node_ids),
            "segments": len(shortest.edge_ids),
        }
    )


routes.cls.throttle_scope = "routes"


def _normalize_geocoder_query(query):
    return " ".join(unicodedata.normalize("NFKC", query).split()).casefold()


def _geocoder_cache_key(url, query):
    digest = hashlib.sha256(f"{url}\0{query}".encode()).hexdigest()
    return f"geocoder:{digest}"


def _read_geocoder_payload(response):
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except (TypeError, ValueError) as error:
            raise ValueError("The geocoder response length is invalid.") from error
        if declared_length < 0 or declared_length > MAX_GEOCODER_RESPONSE_BYTES:
            raise ValueError("The geocoder response is too large.")

    content = bytearray()
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        if not isinstance(chunk, (bytes, bytearray)):
            raise ValueError("The geocoder response is invalid.")
        if len(content) + len(chunk) > MAX_GEOCODER_RESPONSE_BYTES:
            raise ValueError("The geocoder response is too large.")
        content.extend(chunk)

    try:
        text = bytes(content).decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("The geocoder response is not UTF-8.") from error
    try:
        return json.loads(text)
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("The geocoder response is invalid.") from error


def _validated_geocoder_results(payload):
    if not isinstance(payload, list):
        raise ValueError("The geocoder response must be a list.")

    results: list[dict[str, float | str]] = []

    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            raw_latitude = item["lat"]
            raw_longitude = item["lon"]
        except KeyError:
            continue
        if isinstance(raw_latitude, bool) or isinstance(raw_longitude, bool):
            continue
        try:
            latitude = float(raw_latitude)
            longitude = float(raw_longitude)
        except (TypeError, ValueError, OverflowError):
            continue
        if not (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
        ):
            continue
        label = " ".join(str(item.get("display_name", "")).split())
        results.append(
            {
                "lat": latitude,
                "lon": longitude,
                "label": label or f"{latitude}, {longitude}",
            }
        )
    if payload and not results:
        raise ValueError("The geocoder response contained no valid results.")
    return results


def _reserve_geocoder_request():
    path = Path(settings.SAFEPATH_CACHE_DIR) / "geocoder-request.lock"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("a+", encoding="ascii") as state:
        if not locks.lock(state, locks.LOCK_EX):
            raise OSError("The geocoder request lock is unavailable.")
        try:
            state.seek(0)
            stored_timestamp = state.read().strip()
            if stored_timestamp:
                try:
                    last_request = float(stored_timestamp)
                except ValueError as error:
                    raise OSError("The geocoder request lock is invalid.") from error
                if not math.isfinite(last_request) or last_request < 0:
                    raise OSError("The geocoder request lock is invalid.")
            else:
                last_request = 0.0

            now = time.time()
            elapsed = now - last_request
            delay = (
                max(0.0, GEOCODER_REQUEST_INTERVAL_SECONDS - elapsed)
                if elapsed >= 0
                else GEOCODER_REQUEST_INTERVAL_SECONDS
            )
            if delay > 0:
                time.sleep(delay)

            started_at = time.time()
            state.seek(0)
            state.truncate()
            state.write(f"{started_at:.6f}")
            state.flush()
        finally:
            locks.unlock(state)
    return started_at


def _validated_geocoder_url():
    url = settings.SAFEPATH_GEOCODER_URL
    parsed = urlparse(url)
    allowed_hosts = {
        host.strip().lower() for host in settings.SAFEPATH_GEOCODER_ALLOWED_HOSTS
    }
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        raise ValueError("Location service URL is not allowed.")
    return url


def _coordinate(value, name, minimum, maximum):
    if value is None or value == "":
        raise ValueError(f"Missing required coordinate: {name}.")
    try:
        coordinate = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a number.") from error
    if not math.isfinite(coordinate) or not minimum <= coordinate <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return coordinate


def _serialize_route(option):
    return {
        "id": option.route_id,
        "type": option.labels[0],
        "labels": list(option.labels),
        "algorithm": option.algorithm,
        "cost_function": {"alpha": 1.0, "beta": option.beta},
        "node_ids": list(option.node_ids),
        "edge_ids": list(option.edge_ids),
        "geometry": [list(point) for point in option.geometry],
        "distance_meters": option.distance_meters,
        "distance_km": round(option.distance_meters / 1000, 6),
        "duration_seconds": round(option.duration_seconds, 3),
        "duration_source": "estimated_from_road_data",
        "risk_score": (
            round(option.risk_score, 6) if option.risk_score is not None else None
        ),
        "safety_score": option.safety_score,
        "risk_level": option.risk_level,
        "risk_data_available": option.risk_data_available,
        "incident_coverage_ratio": math.floor(option.incident_coverage_ratio * 10000)
        / 10000,
        "nodes_explored": option.nodes_explored,
        "computation_time_ms": round(option.computation_time_ms, 3),
        "path_cost": round(option.path_cost, 3),
        "diversity": {
            "shared_interior_edge_ratio": round(
                option.shared_interior_edge_ratio,
                4,
            )
        },
        "explanation": option.explanation,
    }


def _route_with_label(options, label):
    return next((option for option in options if label in option.labels), None)
