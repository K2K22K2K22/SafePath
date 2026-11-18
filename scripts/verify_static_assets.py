#!/usr/bin/env python3
import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

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


def fetch(url, accept_gzip=False):
    headers = {"Accept-Encoding": "gzip"} if accept_gzip else {}
    request = Request(url, headers=headers)
    with urlopen(request, timeout=5) as response:
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        if not body:
            raise RuntimeError(f"{url} returned an empty response")
        return body, response.headers


def verify(base_url, manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = manifest.get("paths", {})
    missing = [asset for asset in REQUIRED_ASSETS if asset not in paths]
    if missing:
        raise RuntimeError(f"Static manifest is missing: {', '.join(missing)}")

    homepage, _ = fetch(base_url)
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
        fetch(url)
        print(f"OK {urlparse(url).path}")

    leaflet_css_url = urljoin(
        base_url, f"/static/{paths['web/vendor/leaflet/leaflet.css']}"
    )
    leaflet_css, _ = fetch(leaflet_css_url)
    for _, reference in re.findall(
        r"url\((['\"]?)([^)'\"]+)\1\)", leaflet_css.decode("utf-8")
    ):
        if reference.startswith(("data:", "#")):
            continue
        reference_url = urljoin(leaflet_css_url, reference)
        if not urlparse(reference_url).path.startswith("/static/"):
            raise RuntimeError(f"CSS reference is not a static asset: {reference}")
        fetch(reference_url)
        print(f"OK CSS {urlparse(reference_url).path}")

    for asset in ("web/css/app.css", "web/vendor/leaflet/leaflet.js"):
        url = urljoin(base_url, f"/static/{paths[asset]}")
        _, headers = fetch(url, accept_gzip=True)
        if headers.get("Content-Encoding") != "gzip":
            raise RuntimeError(f"{url} was not served with gzip compression")
        print(f"OK gzip {urlparse(url).path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    arguments = parser.parse_args()
    verify(arguments.base_url.rstrip("/") + "/", arguments.manifest)


if __name__ == "__main__":
    main()
