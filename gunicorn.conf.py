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
# Django alone decides whether forwarded protocol headers are trusted.
forwarded_allow_ips = ""
