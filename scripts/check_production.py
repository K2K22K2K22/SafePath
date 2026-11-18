#!/usr/bin/env python3
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ALLOWED_HSTS_WARNINGS = {"security.W004", "security.W005", "security.W021"}


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    load_dotenv()
    os.environ.setdefault("DJANGO_DEBUG", "False")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "safepath_backend.settings")

    import django
    from django.core.checks import run_checks
    from django.core.exceptions import ImproperlyConfigured

    try:
        django.setup()
    except ImproperlyConfigured as error:
        print(f"Production configuration error: {error}", file=sys.stderr)
        return 2
    issues = run_checks(include_deployment_checks=True)
    unexpected = [issue for issue in issues if issue.id not in ALLOWED_HSTS_WARNINGS]
    if unexpected:
        for issue in unexpected:
            print(f"{issue.id}: {issue.msg}", file=sys.stderr)
        return 1

    print("Production checks passed. Only deferred HSTS warnings are allowed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
