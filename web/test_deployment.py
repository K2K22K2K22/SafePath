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
