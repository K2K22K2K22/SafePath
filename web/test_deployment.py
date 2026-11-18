import os
import runpy
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase

from scripts.verify_static_assets import fetch


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


class ContainerEntrypointTests(SimpleTestCase):
    def run_entrypoint(self, **environment):
        entrypoint = Path(settings.BASE_DIR) / "docker" / "entrypoint.sh"
        with tempfile.TemporaryDirectory() as directory:
            fake_gunicorn = Path(directory) / "gunicorn"
            fake_gunicorn.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_gunicorn.chmod(0o755)
            process_environment = os.environ.copy()
            process_environment["PATH"] = (
                f"{directory}{os.pathsep}{process_environment.get('PATH', '')}"
            )
            process_environment.update(environment)
            return subprocess.run(
                ["/bin/sh", str(entrypoint)],
                env=process_environment,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_accepts_stop_grace_greater_than_gunicorn_grace(self):
        result = self.run_entrypoint(
            SAFEPATH_RUN_MIGRATIONS="false",
            GUNICORN_GRACEFUL_TIMEOUT="30",
            DOCKER_STOP_GRACE_PERIOD="40s",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rejects_invalid_shutdown_grace(self):
        for environment in (
            {
                "GUNICORN_GRACEFUL_TIMEOUT": "30",
                "DOCKER_STOP_GRACE_PERIOD": "30",
            },
            {
                "GUNICORN_GRACEFUL_TIMEOUT": "invalid",
                "DOCKER_STOP_GRACE_PERIOD": "40s",
            },
        ):
            with self.subTest(environment=environment):
                result = self.run_entrypoint(
                    SAFEPATH_RUN_MIGRATIONS="false",
                    **environment,
                )

                self.assertEqual(result.returncode, 64, result.stdout + result.stderr)


class StaticAssetVerifierTests(SimpleTestCase):
    def response(self, url, body=b"asset", content_type="text/css", encoding=None):
        response = MagicMock()
        response.status = 200
        response.geturl.return_value = url
        response.read.return_value = body
        response.headers.get_content_type.return_value = content_type
        response.headers.get.return_value = encoding
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    def test_rejects_redirected_static_response(self):
        url = "https://example.test/static/app.css"
        response = self.response("https://example.test/login")
        with patch("scripts.verify_static_assets.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "redirected"):
                fetch(url)

    def test_rejects_unexpected_static_content_type(self):
        url = "https://example.test/static/app.css"
        response = self.response(url, content_type="text/html")
        with patch("scripts.verify_static_assets.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "unexpected content type"):
                fetch(url)

    def test_rejects_invalid_gzip_payload(self):
        url = "https://example.test/static/app.css"
        response = self.response(url, body=b"not gzip", encoding="gzip")
        with patch("scripts.verify_static_assets.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "invalid gzip payload"):
                fetch(url, accept_gzip=True)
