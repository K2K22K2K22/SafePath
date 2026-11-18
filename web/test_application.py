import re
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

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
        self.assertNotIn("Throught ABC Block", content)
        self.assertNotIn("Walk: 24 min", content)

    def test_loopback_hosts_remain_available_for_health_checks(self):
        self.assertIn("localhost", settings.ALLOWED_HOSTS)
        self.assertIn("127.0.0.1", settings.ALLOWED_HOSTS)

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
