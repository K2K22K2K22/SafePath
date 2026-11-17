from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase


class ApplicationSmokeTests(SimpleTestCase):
    def test_home_page_loads_route_components(self):
        response = self.client.get("/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("route-card-template", content)
        self.assertIn("comparison-row-template", content)
        self.assertIn("Safety heatmap", content)
        self.assertNotIn("Throught ABC Block", content)
        self.assertNotIn("Walk: 24 min", content)

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
        assets = [
            "web/vendor/leaflet/leaflet.css",
            "web/vendor/leaflet/leaflet.js",
            "web/vendor/leaflet-heat/leaflet-heat.js",
            "web/css/app.css",
            "web/js/script.js",
        ]

        for asset in assets:
            with self.subTest(asset=asset):
                path = finders.find(asset)
                self.assertIsNotNone(path)
                self.assertTrue(Path(path).is_file())
