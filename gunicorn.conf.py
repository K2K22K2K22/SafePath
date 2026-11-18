import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = 5
accesslog = "-"
access_log_format = "%(m)s %(U)s %(s)s %(b)s %(L)s"
errorlog = "-"
capture_output = True
control_socket_disable = True
logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "safe": {
            "()": "safepath_backend.logging.SafeLogFormatter",
            "format": "%(levelname)s %(name)s %(message)s",
        }
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "formatter": "safe",
            "stream": "ext://sys.stdout",
        },
        "stderr": {
            "class": "logging.StreamHandler",
            "formatter": "safe",
            "stream": "ext://sys.stderr",
        },
    },
    "root": {"handlers": ["stderr"], "level": "WARNING"},
    "loggers": {
        "gunicorn.error": {
            "handlers": ["stderr"],
            "level": "INFO",
            "propagate": False,
        },
        "gunicorn.access": {
            "handlers": ["stdout"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
# Django alone decides whether forwarded protocol headers are trusted.
forwarded_allow_ips = ""
