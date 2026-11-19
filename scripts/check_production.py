#!/usr/bin/env python3
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ALLOWED_HSTS_WARNINGS = {"security.W004", "security.W005", "security.W021"}


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    load_dotenv()
    os.environ.setdefault("DJANGO_DEBUG", "False")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "safepath_backend.settings")

    import django
    from django.core.checks import run_checks
    from django.core.exceptions import ImproperlyConfigured

    try:
        django.setup()
    except ImproperlyConfigured as error:
        print(f"Production configuration error: {error}", file=sys.stderr)
        return 2
    from django.conf import settings

    from Model.utils.osm_graph import (
        OVERPASS_CH_HOST,
        RoadDataUnavailable,
        _prepared_hostname,
        _validated_osm_url,
    )

    if not settings.SAFEPATH_CARTO_API_KEY:
        print(
            "Production configuration error: SAFEPATH_CARTO_API_KEY must be set "
            "to a customer-owned CARTO basemap key.",
            file=sys.stderr,
        )
        return 2

    try:
        _validated_osm_url(require_private=True)
    except RoadDataUnavailable as error:
        print(f"Production configuration error: {error}", file=sys.stderr)
        return 2

    if (
        _prepared_hostname(settings.SAFEPATH_OSM_API_URL) == OVERPASS_CH_HOST
        and not settings.SAFEPATH_OSM_API_KEY
    ):
        print(
            "Production configuration error: SAFEPATH_OSM_API_KEY must be set "
            "for Overpass.ch.",
            file=sys.stderr,
        )
        return 2

    database = settings.DATABASES["default"]
    if database.get("ENGINE") != "django.db.backends.postgresql":
        print(
            "Production configuration error: DATABASE_URL must configure PostgreSQL.",
            file=sys.stderr,
        )
        return 2
    sslmode = database.get("OPTIONS", {}).get("sslmode")
    if sslmode not in {"require", "verify-ca", "verify-full"}:
        print(
            "Production configuration error: PostgreSQL must use sslmode=require, "
            "verify-ca, or verify-full.",
            file=sys.stderr,
        )
        return 2
    if settings.SECURE_PROXY_SSL_HEADER is None:
        print(
            "Production configuration error: DJANGO_TRUST_X_FORWARDED_PROTO=True "
            "is required behind a trusted TLS proxy.",
            file=sys.stderr,
        )
        return 2

    issues = run_checks(include_deployment_checks=True)
    unexpected = [issue for issue in issues if issue.id not in ALLOWED_HSTS_WARNINGS]
    if unexpected:
        for issue in unexpected:
            print(f"{issue.id}: {issue.msg}", file=sys.stderr)
        return 1

    print("Production checks passed. Only deferred HSTS warnings are allowed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
