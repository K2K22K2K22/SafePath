import math

from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .utils.osm_graph import RoadDataUnavailable
from .utils.route_service import RouteNotFound, calculate_route_options


class RoutesRateThrottle(ScopedRateThrottle):
    scope = "routes"


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
    except RoadDataUnavailable:
        return Response(
            {"detail": "Road data is temporarily unavailable. Please try again."},
            status=503,
        )

    serialized_routes = [_serialize_route(option) for option in options]
    shortest = _route_with_label(options, "shortest") or options[0]
    safest = _route_with_label(options, "safest") or shortest

    return Response(
        {
            "origin": {"lat": start_lat, "lon": start_lon},
            "destination": {"lat": end_lat, "lon": end_lon},
            "routes": serialized_routes,
            "route_count": len(serialized_routes),
            "incident_data": {"source": "bundled_csv"},
            "original_route": [list(point) for point in shortest.geometry],
            "safe_path": [list(point) for point in safest.geometry],
            "distance_meters": shortest.distance_meters,
            "avg_risk": shortest.risk_score,
            "nodes": len(shortest.node_ids),
            "segments": len(shortest.edge_ids),
        }
    )


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
        "incident_coverage_ratio": round(option.incident_coverage_ratio, 4),
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
