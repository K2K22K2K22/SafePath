from pathlib import Path

import yaml
from django.conf import settings
from django.test import SimpleTestCase


class RenderBlueprintTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        blueprint_path = Path(settings.BASE_DIR) / "render.yaml"
        cls.blueprint = yaml.safe_load(blueprint_path.read_text(encoding="utf-8"))
        cls.service = cls.blueprint["services"][0]

    def test_uses_one_free_singapore_python_service(self):
        self.assertEqual(len(self.blueprint["services"]), 1)
        self.assertNotIn("databases", self.blueprint)
        self.assertEqual(self.service["type"], "web")
        self.assertEqual(self.service["runtime"], "python")
        self.assertEqual(self.service["plan"], "free")
        self.assertEqual(self.service["region"], "singapore")
        self.assertEqual(self.service["branch"], "main")
        self.assertEqual(self.service["numInstances"], 1)
        self.assertEqual(self.service["healthCheckPath"], "/health/")
        self.assertEqual(self.service["maxShutdownDelaySeconds"], 40)

    def test_build_and_start_commands_match_the_native_runtime(self):
        build_command = self.service["buildCommand"]
        start_command = self.service["startCommand"]

        self.assertIn("pip install --requirement requirements.txt", build_command)
        self.assertIn("python manage.py collectstatic", build_command)
        self.assertIn('--ignore "web/css/src/*"', build_command)
        self.assertIn("python manage.py migrate --noinput", start_command)
        self.assertIn("gunicorn safepath_backend.wsgi:application", start_command)
        self.assertIn('--bind "0.0.0.0:${PORT:-10000}"', start_command)
        self.assertIn("--workers 1", start_command)
        self.assertNotIn("preDeployCommand", self.service)

    def test_environment_values_keep_secrets_out_of_the_repository(self):
        environment = {
            variable["key"]: variable for variable in self.service["envVars"]
        }

        self.assertEqual(environment["DJANGO_DEBUG"]["value"], "False")
        self.assertTrue(environment["DJANGO_SECRET_KEY"]["generateValue"])
        self.assertNotIn("value", environment["DJANGO_SECRET_KEY"])
        for key in (
            "DJANGO_ALLOWED_HOSTS",
            "CSRF_TRUSTED_ORIGINS",
            "DATABASE_URL",
            "SAFEPATH_CARTO_API_KEY",
            "SAFEPATH_OSM_API_URL",
            "SAFEPATH_OSM_API_ALLOWED_HOSTS",
            "SAFEPATH_OSM_API_PRODUCTION_ALLOWED_HOSTS",
        ):
            with self.subTest(key=key):
                self.assertTrue(environment[key]["sync"] is False)
                self.assertNotIn("value", environment[key])

    def test_python_version_matches_the_tested_runtime(self):
        version = (Path(settings.BASE_DIR) / ".python-version").read_text(
            encoding="utf-8"
        )
        self.assertEqual(version, "3.13.18\n")
