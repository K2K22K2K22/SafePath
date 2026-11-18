import re
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, override_settings

LOCAL_MAP_ASSETS = [
    "web/vendor/leaflet/leaflet.css",
    "web/vendor/leaflet/leaflet.js",
    "web/vendor/leaflet/images/layers.png",
    "web/vendor/leaflet/images/layers-2x.png",
    "web/vendor/leaflet/images/marker-icon.png",
    "web/vendor/leaflet/images/marker-shadow.png",
    "web/vendor/leaflet-heat/leaflet-heat.js",
    "web/css/app.css",
    "web/js/script.js",
    "web/images/favicon.svg",
    "web/images/location_on.png",
]


class ApplicationSmokeTests(SimpleTestCase):
    def test_home_page_loads_route_components(self):
        response = self.client.get("/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("route-card-template", content)
        self.assertIn("comparison-row-template", content)
        self.assertIn("Incident heatmap", content)
        self.assertIn("not a personal-safety assessment", content)
        self.assertIn("Unverified demonstration incident records", content)
        self.assertIn("Not verified crime data", content)
        self.assertIn("every edge is covered", content)
        self.assertIn("not an emergency or verified safety service", content)
        self.assertNotIn("Throught ABC Block", content)
        self.assertNotIn("Walk: 24 min", content)

    def test_home_page_displays_geocoder_attribution(self):
        response = self.client.get("/", HTTP_HOST="localhost")

        content = response.content.decode()
        self.assertIn("Nominatim", content)
        self.assertIn("OpenStreetMap", content)

    @override_settings(SAFEPATH_CARTO_API_KEY="test-carto-key")
    def test_home_page_exposes_customer_carto_key_as_json(self):
        response = self.client.get("/", HTTP_HOST="localhost")

        content = response.content.decode()
        self.assertIn('id="carto-api-key"', content)
        self.assertIn('"test-carto-key"', content)
        self.assertIn('data-carto-key="configured"', content)

    @override_settings(SAFEPATH_CARTO_API_KEY="")
    def test_missing_carto_key_uses_filtered_osm_fallback(self):
        response = self.client.get("/", HTTP_HOST="localhost")

        self.assertIn('data-carto-key="missing"', response.content.decode())

    def test_cross_origin_tile_requests_keep_a_referrer(self):
        response = self.client.get("/", HTTP_HOST="localhost")

        self.assertEqual(
            response.headers["Referrer-Policy"],
            "strict-origin-when-cross-origin",
        )

    def test_health_endpoint_reports_ready(self):
        response = self.client.get("/health/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_django_admin_and_authentication_framework_remain_available(self):
        admin_response = self.client.get("/admin/login/", HTTP_HOST="localhost")

        self.assertEqual(admin_response.status_code, 200)
        self.assertIn(
            "django.contrib.auth.backends.ModelBackend",
            settings.AUTHENTICATION_BACKENDS,
        )

    def test_local_map_assets_are_available(self):
        for asset in LOCAL_MAP_ASSETS:
            with self.subTest(asset=asset):
                path = finders.find(asset)
                self.assertIsNotNone(path)
                self.assertTrue(Path(path).is_file())

    def test_leaflet_css_image_dependencies_are_available(self):
        css_path = finders.find("web/vendor/leaflet/leaflet.css")
        if css_path is None:
            self.fail("Vendored Leaflet CSS was not found.")

        css = Path(css_path).read_text(encoding="utf-8")
        dependencies = set(re.findall(r"url\(\s*['\"]?(images/[^)'\"\s]+)", css))
        self.assertTrue(dependencies)
        for dependency in dependencies:
            with self.subTest(dependency=dependency):
                self.assertTrue((Path(css_path).parent / dependency).is_file())
