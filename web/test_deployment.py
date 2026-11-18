import os
import runpy
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase


class GunicornConfigurationTests(SimpleTestCase):
    def load_config(self, environment):
        config_path = Path(settings.BASE_DIR) / "gunicorn.conf.py"
        with patch.dict(os.environ, environment, clear=True):
            return runpy.run_path(str(config_path))

    def test_uses_conservative_defaults(self):
        config = self.load_config({})

        self.assertEqual(config["bind"], "0.0.0.0:8000")
        self.assertEqual(config["workers"], 2)
        self.assertEqual(config["timeout"], 60)
        self.assertEqual(config["graceful_timeout"], 30)
        self.assertEqual(config["accesslog"], "-")
        self.assertEqual(config["errorlog"], "-")
        self.assertTrue(config["capture_output"])

    def test_reads_runtime_environment(self):
        config = self.load_config(
            {
                "PORT": "9000",
                "GUNICORN_WORKERS": "3",
                "GUNICORN_TIMEOUT": "45",
                "GUNICORN_GRACEFUL_TIMEOUT": "20",
            }
        )

        self.assertEqual(config["bind"], "0.0.0.0:9000")
        self.assertEqual(config["workers"], 3)
        self.assertEqual(config["timeout"], 45)
        self.assertEqual(config["graceful_timeout"], 20)


class ProductionStaticAssetSettingsTests(SimpleTestCase):
    def load_settings(self, environment):
        settings_path = Path(settings.BASE_DIR) / "safepath_backend" / "settings.py"
        with patch.dict(os.environ, environment, clear=True):
            return runpy.run_path(str(settings_path))

    def test_production_uses_manifest_storage_after_security_middleware(self):
        config = self.load_settings(
            {
                "DJANGO_DEBUG": "False",
                "DJANGO_SECRET_KEY": "static-settings-test-secret-key-with-enough-length-92841",
                "DJANGO_ALLOWED_HOSTS": "safepath.example.com",
            }
        )

        self.assertEqual(
            config["MIDDLEWARE"][0],
            "django.middleware.security.SecurityMiddleware",
        )
        self.assertEqual(
            config["MIDDLEWARE"][1],
            "whitenoise.middleware.WhiteNoiseMiddleware",
        )
        self.assertEqual(config["STATIC_URL"], "/static/")
        self.assertEqual(config["STATIC_ROOT"], Path(settings.BASE_DIR) / "staticfiles")
        self.assertEqual(
            config["STORAGES"]["staticfiles"]["BACKEND"],
            "whitenoise.storage.CompressedManifestStaticFilesStorage",
        )
