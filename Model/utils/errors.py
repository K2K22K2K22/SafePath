import logging

from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("safepath.errors")


class ApiError(Exception):
    code: str = "internal_error"
    status_code: int = 500
    public_message: str = "An unexpected error occurred."
    log_level: int | None = None

    def __init__(self, diagnostic_message=None, public_message=None):
        self.diagnostic_message = diagnostic_message or self.public_message
        self.public_message = public_message or self.public_message
        super().__init__(self.diagnostic_message)


class InvalidRequestError(ApiError, ValueError):
    code = "invalid_request"
    status_code = 400
    public_message = "The request is invalid."


class RouteNotFoundError(ApiError):
    code = "route_not_found"
    status_code = 404
    public_message = "No route was found for these coordinates."
    log_level = logging.WARNING


class RoadProviderUnavailableError(ApiError):
    code = "road_provider_unavailable"
    status_code = 503
    public_message = "Road data is temporarily unavailable. Please try again."
    log_level = logging.WARNING


class GeocoderUnavailableError(ApiError):
    code = "geocoder_unavailable"
    status_code = 503
    public_message = "Location search is temporarily unavailable. Please try again."
    log_level = logging.WARNING


class InvalidProviderResponseError(ApiError):
    code = "invalid_provider_response"
    status_code = 503
    public_message = "The data provider returned an invalid response."
    log_level = logging.WARNING


class SearchLimitExceededError(ApiError):
    code = "search_limit_exceeded"
    status_code = 503
    public_message = "Route search temporarily exceeded its work limit."
    log_level = logging.WARNING


class IncidentDataUnavailableError(ApiError):
    code = "incident_data_unavailable"
    status_code = 503
    public_message = "Incident data is temporarily unavailable."
    log_level = logging.WARNING


def safepath_exception_handler(exc, context):
    request = context.get("request")

    if isinstance(exc, ApiError):
        _log_api_error(request, exc)
        return _error_response(
            exc.public_message,
            exc.code,
            exc.status_code,
        )

    response = drf_exception_handler(exc, context)
    if response is not None:
        if isinstance(exc, Throttled):
            response.data = {
                "detail": "Too many requests. Please try again later.",
                "code": "rate_limit_exceeded",
            }
        else:
            code = getattr(exc, "default_code", exc.__class__.__name__)
            if isinstance(response.data, dict):
                response.data = {**response.data, "code": code}
            else:
                response.data = {
                    "detail": response.data,
                    "code": code,
                }
        response._has_been_logged = True
        return response

    _log_api_error(request, exc, code="internal_error", level=logging.ERROR)
    return _error_response(
        "An unexpected error occurred.",
        "internal_error",
        500,
    )


def _error_response(message, code, status_code):
    response = Response({"detail": message, "code": code}, status=status_code)
    response._has_been_logged = True
    return response


def _log_api_error(request, error, code=None, level=None):
    level = level or getattr(error, "log_level", None)
    if level is None:
        return

    resolver_match = getattr(request, "resolver_match", None)
    route = getattr(resolver_match, "route", None)
    path = route or getattr(request, "path", "")
    method = getattr(request, "method", "UNKNOWN")
    logger.log(
        level,
        "API request failed method=%s path=%s code=%s error_type=%s",
        method,
        path,
        code or getattr(error, "code", "internal_error"),
        type(error).__name__,
    )
