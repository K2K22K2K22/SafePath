#!/usr/bin/env python3
import argparse
import gzip
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

REQUIRED_ASSETS = (
    "web/css/app.css",
    "web/js/script.js",
    "web/vendor/leaflet/leaflet.css",
    "web/vendor/leaflet/leaflet.js",
    "web/vendor/leaflet-heat/leaflet-heat.js",
    "web/vendor/leaflet/images/layers.png",
    "web/vendor/leaflet/images/layers-2x.png",
    "web/vendor/leaflet/images/marker-icon.png",
    "web/vendor/leaflet/images/marker-shadow.png",
    "web/images/favicon.svg",
    "web/images/location_on.png",
)
RENDERED_ASSETS = (
    "web/css/app.css",
    "web/js/script.js",
    "web/vendor/leaflet/leaflet.css",
    "web/vendor/leaflet/leaflet.js",
    "web/vendor/leaflet-heat/leaflet-heat.js",
    "web/images/favicon.svg",
)
EXPECTED_CONTENT_TYPES = {
    ".css": {"text/css"},
    ".html": {"text/html"},
    ".js": {"application/javascript", "text/javascript"},
    ".png": {"image/png"},
    ".svg": {"image/svg+xml"},
}


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


opener = build_opener(NoRedirectHandler)


def open_without_redirect(request, timeout):
    return opener.open(request, timeout=timeout)


class StaticAssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "link" and attributes.get("href"):
            self.urls.append(attributes["href"])
        if tag == "script" and attributes.get("src"):
            self.urls.append(attributes["src"])


def fetch(url, accept_gzip=False, host_header=None):
    headers = {"X-Forwarded-Proto": "https"}
    if host_header:
        headers["Host"] = host_header
    if accept_gzip:
        headers["Accept-Encoding"] = "gzip"
    request = Request(url, headers=headers)
    try:
        response_context = open_without_redirect(request, timeout=5)
    except HTTPError as error:
        if 300 <= error.code < 400:
            target = error.headers.get("Location", error.geturl())
            raise RuntimeError(f"{url} redirected to {target}") from error
        raise
    with response_context as response:
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        if response.geturl() != url:
            raise RuntimeError(f"{url} redirected to {response.geturl()}")
        if not body:
            raise RuntimeError(f"{url} returned an empty response")

        suffix = Path(urlparse(url).path).suffix.lower()
        expected_types = EXPECTED_CONTENT_TYPES.get(suffix)
        if expected_types and response.headers.get_content_type() not in expected_types:
            raise RuntimeError(
                f"{url} returned an unexpected content type: "
                f"{response.headers.get_content_type()}"
            )
        if accept_gzip:
            if response.headers.get("Content-Encoding") != "gzip":
                raise RuntimeError(f"{url} was not served with gzip compression")
            try:
                gzip.decompress(body)
            except (gzip.BadGzipFile, EOFError) as error:
                raise RuntimeError(f"{url} returned an invalid gzip payload") from error

        return body, response.headers


def verify(base_url, manifest_path, host_header=None):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = manifest.get("paths", {})
    missing = [asset for asset in REQUIRED_ASSETS if asset not in paths]
    if missing:
        raise RuntimeError(f"Static manifest is missing: {', '.join(missing)}")

    homepage, _ = fetch(base_url, host_header=host_header)
    parser = StaticAssetParser()
    parser.feed(homepage.decode("utf-8"))
    rendered_urls = {
        urljoin(base_url, url)
        for url in parser.urls
        if urlparse(url).path.startswith("/static/")
    }
    expected_rendered_urls = {
        urljoin(base_url, f"/static/{paths[asset]}") for asset in RENDERED_ASSETS
    }
    missing_rendered = expected_rendered_urls - rendered_urls
    if missing_rendered:
        raise RuntimeError(
            "Homepage does not render manifest URLs: "
            + ", ".join(sorted(missing_rendered))
        )

    asset_urls = {
        urljoin(base_url, f"/static/{paths[asset]}") for asset in REQUIRED_ASSETS
    }
    for url in sorted(rendered_urls | asset_urls):
        fetch(url, host_header=host_header)
        print(f"OK {urlparse(url).path}")

    leaflet_css_url = urljoin(
        base_url, f"/static/{paths['web/vendor/leaflet/leaflet.css']}"
    )
    leaflet_css, _ = fetch(leaflet_css_url, host_header=host_header)
    for _, reference in re.findall(
        r"url\((['\"]?)([^)'\"]+)\1\)", leaflet_css.decode("utf-8")
    ):
        if reference.startswith(("data:", "#")):
            continue
        reference_url = urljoin(leaflet_css_url, reference)
        if not urlparse(reference_url).path.startswith("/static/"):
            raise RuntimeError(f"CSS reference is not a static asset: {reference}")
        fetch(reference_url, host_header=host_header)
        print(f"OK CSS {urlparse(reference_url).path}")

    for asset in ("web/css/app.css", "web/vendor/leaflet/leaflet.js"):
        url = urljoin(base_url, f"/static/{paths[asset]}")
        fetch(url, accept_gzip=True, host_header=host_header)
        print(f"OK gzip {urlparse(url).path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--host-header")
    arguments = parser.parse_args()
    verify(
        arguments.base_url.rstrip("/") + "/",
        arguments.manifest,
        host_header=arguments.host_header,
    )


if __name__ == "__main__":
    main()
