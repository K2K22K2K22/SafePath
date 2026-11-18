#!/usr/bin/env python3
import os
import sys
from http.client import HTTPConnection
from urllib.parse import urlparse

TRUTHY_VALUES = {"1", "true", "yes", "on"}


def build_headers():
    allowed_hosts = [
        host.strip()
        for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost").split(",")
        if host.strip()
    ]
    host = allowed_hosts[0] if allowed_hosts else "localhost"
    return {"Host": host, "X-Forwarded-Proto": "https"}


def is_valid_health_response(status, location, host, trust_forwarded_proto=False):
    if status == 200:
        return True
    if status != 301 or trust_forwarded_proto:
        return False
    target = urlparse(location)
    return (
        target.scheme == "https" and target.netloc == host and target.path == "/health/"
    )


def main():
    headers = build_headers()
    trust_forwarded_proto = (
        os.environ.get("DJANGO_TRUST_X_FORWARDED_PROTO", "False").lower()
        in TRUTHY_VALUES
    )
    connection = HTTPConnection(
        "127.0.0.1",
        int(os.environ.get("PORT", "8000")),
        timeout=3,
    )
    try:
        connection.request("GET", "/health/", headers=headers)
        response = connection.getresponse()
        response.read()
        location = response.getheader("Location", "")
        if not is_valid_health_response(
            response.status,
            location,
            headers["Host"],
            trust_forwarded_proto,
        ):
            raise RuntimeError(
                f"Health check returned HTTP {response.status} at {location or '/'}"
            )
        if response.status == 301:
            print(
                "warning: health endpoint answered with HTTPS redirect",
                file=sys.stderr,
            )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
