import os
import runpy
import secrets
import subprocess
import sys
import tempfile
from email.message import Message
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings

from scripts.healthcheck import build_headers, is_valid_health_response, main
from scripts.verify_static_assets import fetch

VALID_SECRET = secrets.token_urlsafe(64)


class ProductionCheckTests(SimpleTestCase):
    def test_missing_configuration_returns_readable_error(self):
        environment = os.environ.copy()
        environment.pop("DJANGO_SECRET_KEY", None)
        environment.pop("DJANGO_ALLOWED_HOSTS", None)
        environment["DJANGO_DEBUG"] = "False"
        script = Path(settings.BASE_DIR) / "scripts" / "check_production.py"

        result = subprocess.run(
            [sys.executable, str(script)],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Production configuration error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


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
        self.assertEqual(config["forwarded_allow_ips"], "")

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
                "DJANGO_SECRET_KEY": VALID_SECRET,
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


class ProductionSecuritySettingsTests(SimpleTestCase):
    def load_settings(self, environment):
        settings_path = Path(settings.BASE_DIR) / "safepath_backend" / "settings.py"
        with patch.dict(os.environ, environment, clear=True):
            return runpy.run_path(str(settings_path))

    def test_production_enforces_https_and_secure_cookies(self):
        config = self.load_settings(
            {
                "DJANGO_DEBUG": "False",
                "DJANGO_SECRET_KEY": VALID_SECRET,
                "DJANGO_ALLOWED_HOSTS": "safepath.example.com",
                "DJANGO_CSRF_TRUSTED_ORIGINS": "https://safepath.example.com",
                "DJANGO_TRUST_X_FORWARDED_PROTO": "True",
            }
        )

        self.assertEqual(config["ALLOWED_HOSTS"], ["safepath.example.com"])
        self.assertEqual(
            config["CSRF_TRUSTED_ORIGINS"],
            ["https://safepath.example.com"],
        )
        self.assertTrue(config["SECURE_SSL_REDIRECT"])
        self.assertTrue(config["SESSION_COOKIE_SECURE"])
        self.assertTrue(config["CSRF_COOKIE_SECURE"])
        self.assertEqual(
            config["SECURE_PROXY_SSL_HEADER"],
            ("HTTP_X_FORWARDED_PROTO", "https"),
        )
        self.assertEqual(config["SECURE_HSTS_SECONDS"], 0)

    def test_proxy_trust_is_explicit(self):
        config = self.load_settings(
            {
                "DJANGO_DEBUG": "False",
                "DJANGO_SECRET_KEY": VALID_SECRET,
                "DJANGO_ALLOWED_HOSTS": "safepath.example.com",
            }
        )

        self.assertIsNone(config["SECURE_PROXY_SSL_HEADER"])

    def test_rejects_weak_production_secret(self):
        for secret in ("short-secret", "a" * 50, "replace-with-" + "a" * 50):
            with self.subTest(secret=secret):
                with self.assertRaisesRegex(ImproperlyConfigured, "at least 50"):
                    self.load_settings(
                        {
                            "DJANGO_DEBUG": "False",
                            "DJANGO_SECRET_KEY": secret,
                            "DJANGO_ALLOWED_HOSTS": "safepath.example.com",
                        }
                    )

    def test_rejects_missing_production_hosts(self):
        with self.assertRaisesRegex(ImproperlyConfigured, "at least one"):
            self.load_settings(
                {
                    "DJANGO_DEBUG": "False",
                    "DJANGO_SECRET_KEY": VALID_SECRET,
                }
            )

    def test_rejects_wildcard_production_hosts(self):
        for hosts in ("*", ".example.com"):
            with self.subTest(hosts=hosts):
                with self.assertRaisesRegex(ImproperlyConfigured, "without wildcards"):
                    self.load_settings(
                        {
                            "DJANGO_DEBUG": "False",
                            "DJANGO_SECRET_KEY": VALID_SECRET,
                            "DJANGO_ALLOWED_HOSTS": hosts,
                        }
                    )

    def test_rejects_production_host_with_port(self):
        with self.assertRaisesRegex(ImproperlyConfigured, "without ports"):
            self.load_settings(
                {
                    "DJANGO_DEBUG": "False",
                    "DJANGO_SECRET_KEY": VALID_SECRET,
                    "DJANGO_ALLOWED_HOSTS": "safepath.example.com:8443",
                }
            )

    def test_rejects_insecure_csrf_trusted_origin(self):
        for origin in (
            "http://safepath.example.com",
            "https://*.example.com",
        ):
            with self.subTest(origin=origin):
                with self.assertRaisesRegex(
                    ImproperlyConfigured,
                    "exact HTTPS origins",
                ):
                    self.load_settings(
                        {
                            "DJANGO_DEBUG": "False",
                            "DJANGO_SECRET_KEY": VALID_SECRET,
                            "DJANGO_ALLOWED_HOSTS": "safepath.example.com",
                            "DJANGO_CSRF_TRUSTED_ORIGINS": origin,
                        }
                    )

    def test_rejects_invalid_hsts_duration(self):
        for value in ("invalid", "-1"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ImproperlyConfigured,
                    "DJANGO_SECURE_HSTS_SECONDS",
                ):
                    self.load_settings(
                        {
                            "DJANGO_DEBUG": "False",
                            "DJANGO_SECRET_KEY": VALID_SECRET,
                            "DJANGO_ALLOWED_HOSTS": "safepath.example.com",
                            "DJANGO_SECURE_HSTS_SECONDS": value,
                        }
                    )

    def test_rejects_hsts_options_without_duration(self):
        for variable in (
            "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
            "DJANGO_SECURE_HSTS_PRELOAD",
        ):
            with self.subTest(variable=variable):
                with self.assertRaisesRegex(ImproperlyConfigured, "must be positive"):
                    self.load_settings(
                        {
                            "DJANGO_DEBUG": "False",
                            "DJANGO_SECRET_KEY": VALID_SECRET,
                            "DJANGO_ALLOWED_HOSTS": "safepath.example.com",
                            variable: "True",
                        }
                    )

    def test_debug_keeps_local_hosts_and_non_secure_cookies(self):
        config = self.load_settings({"DJANGO_DEBUG": "True"})

        self.assertEqual(config["ALLOWED_HOSTS"], ["localhost", "127.0.0.1"])
        self.assertFalse(config["SECURE_SSL_REDIRECT"])
        self.assertFalse(config["SESSION_COOKIE_SECURE"])
        self.assertFalse(config["CSRF_COOKIE_SECURE"])
        self.assertIsNone(config["SECURE_PROXY_SSL_HEADER"])


@override_settings(
    ALLOWED_HOSTS=["safepath.example.com"],
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    SECURE_SSL_REDIRECT=True,
)
class ProductionRequestSecurityTests(SimpleTestCase):
    def test_redirects_plain_http(self):
        response = self.client.get("/health/", HTTP_HOST="safepath.example.com")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response.headers["Location"],
            "https://safepath.example.com/health/",
        )

    def test_accepts_proxy_confirmed_https(self):
        response = self.client.get(
            "/health/",
            HTTP_HOST="safepath.example.com",
            HTTP_X_FORWARDED_PROTO="https",
        )

        self.assertEqual(response.status_code, 200)


class DatabaseSettingsTests(SimpleTestCase):
    def load_settings(self, environment):
        settings_path = Path(settings.BASE_DIR) / "safepath_backend" / "settings.py"
        with patch.dict(os.environ, environment, clear=True):
            return runpy.run_path(str(settings_path))

    def test_postgres_url_preserves_ssl_options_and_connection_policy(self):
        config = self.load_settings(
            {
                "DATABASE_URL": (
                    "postgresql://user:p%40ss@db.example.com:5432/safepath"
                    "?sslmode=verify-full&sslrootcert=/etc/ssl/ca.pem"
                ),
                "DJANGO_DEBUG": "False",
                "DJANGO_SECRET_KEY": VALID_SECRET,
                "DJANGO_ALLOWED_HOSTS": "safepath.example.com",
                "SAFEPATH_DATABASE_CONN_MAX_AGE": "90",
            }
        )

        uppercase_settings = {
            name: value for name, value in config.items() if name.isupper()
        }
        self.assertNotIn("DATABASE_URL", uppercase_settings)

        database = config["DATABASES"]["default"]
        self.assertEqual(database["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(database["NAME"], "safepath")
        self.assertEqual(database["USER"], "user")
        self.assertEqual(database["PASSWORD"], "p@ss")
        self.assertEqual(database["HOST"], "db.example.com")
        self.assertEqual(database["PORT"], 5432)
        self.assertEqual(
            database["OPTIONS"],
            {
                "sslmode": "verify-full",
                "sslrootcert": "/etc/ssl/ca.pem",
            },
        )
        self.assertEqual(database["CONN_MAX_AGE"], 90)
        self.assertTrue(database["CONN_HEALTH_CHECKS"])

    def test_sqlite_remains_the_local_fallback(self):
        config = self.load_settings(
            {
                "DJANGO_DEBUG": "False",
                "DJANGO_SECRET_KEY": VALID_SECRET,
                "DJANGO_ALLOWED_HOSTS": "safepath.example.com",
                "SAFEPATH_DATABASE_PATH": "/tmp/safepath-test.sqlite3",
            }
        )

        database = config["DATABASES"]["default"]
        self.assertEqual(database["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(database["NAME"], "/tmp/safepath-test.sqlite3")

    def test_rejects_invalid_connection_lifetime(self):
        for value in ("invalid", "-1"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ImproperlyConfigured,
                    "SAFEPATH_DATABASE_CONN_MAX_AGE",
                ):
                    self.load_settings(
                        {
                            "DATABASE_URL": (
                                "postgresql://user:pass@db.example.com:5432/safepath"
                            ),
                            "DJANGO_DEBUG": "False",
                            "DJANGO_SECRET_KEY": VALID_SECRET,
                            "DJANGO_ALLOWED_HOSTS": "safepath.example.com",
                            "SAFEPATH_DATABASE_CONN_MAX_AGE": value,
                        }
                    )

    def test_rejects_non_postgres_database_url(self):
        for database_url in (
            "sqlite:////tmp/safepath-test.sqlite3",
            "pgsql://user:pass@db.example.com:5432/safepath",
        ):
            with self.subTest(database_url=database_url):
                with self.assertRaisesRegex(
                    ImproperlyConfigured,
                    "must use the postgres",
                ):
                    self.load_settings(
                        {
                            "DATABASE_URL": database_url,
                            "DJANGO_DEBUG": "False",
                            "DJANGO_SECRET_KEY": VALID_SECRET,
                            "DJANGO_ALLOWED_HOSTS": "safepath.example.com",
                        }
                    )

    def test_requires_encrypted_production_database_connection(self):
        for database_url in (
            "postgresql://user:pass@db.example.com:5432/safepath",
            "postgresql://user:pass@db.example.com:5432/safepath?sslmode=prefer",
            (
                "postgresql://user:pass@db.example.com:5432/safepath"
                "?sslmode=require&sslmode=disable"
            ),
        ):
            with self.subTest(database_url=database_url):
                with self.assertRaisesRegex(ImproperlyConfigured, "sslmode"):
                    self.load_settings(
                        {
                            "DATABASE_URL": database_url,
                            "DJANGO_DEBUG": "False",
                            "DJANGO_SECRET_KEY": VALID_SECRET,
                            "DJANGO_ALLOWED_HOSTS": "safepath.example.com",
                        }
                    )

    def test_rejects_libpq_option_override(self):
        for query in (
            "options=-c%20sslmode=disable",
            "dbname=other",
            "service=other",
            "connect_timeout=1",
        ):
            with self.subTest(query=query):
                with self.assertRaisesRegex(ImproperlyConfigured, "connection options"):
                    self.load_settings(
                        {
                            "DATABASE_URL": (
                                "postgresql://user:pass@db.example.com:5432/safepath"
                                f"?sslmode=verify-full&{query}"
                            ),
                            "DJANGO_DEBUG": "False",
                            "DJANGO_SECRET_KEY": VALID_SECRET,
                            "DJANGO_ALLOWED_HOSTS": "safepath.example.com",
                        }
                    )


class DatabaseSessionTests(TestCase):
    def test_session_survives_database_round_trip(self):
        if os.environ.get("DATABASE_URL"):
            self.assertEqual(
                settings.DATABASES["default"]["ENGINE"],
                "django.db.backends.postgresql",
            )
        session = SessionStore()
        session["deployment"] = "verified"
        session.save()

        restored = SessionStore(session_key=session.session_key)
        self.assertEqual(restored.get("deployment"), "verified")


class HealthcheckTests(SimpleTestCase):
    def test_validates_health_redirect_target(self):
        self.assertTrue(
            is_valid_health_response(
                301,
                "https://safepath.example.com/health/",
                "safepath.example.com",
            )
        )
        self.assertFalse(
            is_valid_health_response(
                301,
                "https://other.example.com/health/",
                "safepath.example.com",
            )
        )
        self.assertFalse(
            is_valid_health_response(
                301,
                "https://safepath.example.com/health/",
                "safepath.example.com",
                trust_forwarded_proto=True,
            )
        )

    def test_warns_when_health_endpoint_redirects(self):
        response = MagicMock(status=301)
        response.getheader.return_value = "https://safepath.example.com/health/"
        connection = MagicMock()
        connection.getresponse.return_value = response
        stderr = StringIO()

        with (
            patch.dict(
                os.environ,
                {
                    "DJANGO_ALLOWED_HOSTS": "safepath.example.com",
                    "PORT": "9000",
                },
                clear=True,
            ),
            patch(
                "scripts.healthcheck.HTTPConnection",
                return_value=connection,
            ),
            patch("scripts.healthcheck.sys.stderr", stderr),
        ):
            main()

        self.assertIn(
            "warning: health endpoint answered with HTTPS redirect", stderr.getvalue()
        )

    def test_uses_configured_host_and_forwarded_protocol(self):
        with patch.dict(
            os.environ,
            {
                "DJANGO_ALLOWED_HOSTS": "safepath.example.com,localhost",
                "PORT": "9000",
            },
            clear=True,
        ):
            headers = build_headers()

        self.assertEqual(headers["Host"], "safepath.example.com")
        self.assertEqual(headers["X-Forwarded-Proto"], "https")


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
            {
                "GUNICORN_GRACEFUL_TIMEOUT": "30",
                "DOCKER_STOP_GRACE_PERIOD": "abc",
            },
            {
                "GUNICORN_GRACEFUL_TIMEOUT": "30",
                "DOCKER_STOP_GRACE_PERIOD": "40",
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

    def test_sends_configured_host_header(self):
        url = "https://example.test/static/app.css"
        response = self.response(url)
        with patch(
            "scripts.verify_static_assets.open_without_redirect",
            return_value=response,
        ) as mocked_open:
            fetch(url, host_header="safepath.example.com")

        request = mocked_open.call_args.args[0]
        headers = dict(request.header_items())
        self.assertEqual(headers["Host"], "safepath.example.com")
        self.assertEqual(headers["X-forwarded-proto"], "https")

    def test_rejects_redirected_static_response(self):
        url = "https://example.test/static/app.css"
        headers = Message()
        headers["Location"] = "https://example.test/login"
        error = HTTPError(
            url,
            302,
            "Found",
            headers,
            None,
        )
        with patch(
            "scripts.verify_static_assets.open_without_redirect",
            side_effect=error,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                r"redirected to https://example\.test/login",
            ):
                fetch(url)

    def test_rejects_unexpected_static_content_type(self):
        url = "https://example.test/static/app.css"
        response = self.response(url, content_type="text/html")
        with patch(
            "scripts.verify_static_assets.open_without_redirect",
            return_value=response,
        ):
            with self.assertRaisesRegex(RuntimeError, "unexpected content type"):
                fetch(url)

    def test_rejects_invalid_gzip_payload(self):
        url = "https://example.test/static/app.css"
        response = self.response(url, body=b"not gzip", encoding="gzip")
        with patch(
            "scripts.verify_static_assets.open_without_redirect",
            return_value=response,
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid gzip payload"):
                fetch(url, accept_gzip=True)
