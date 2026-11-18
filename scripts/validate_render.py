#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

import yaml
from jsonschema import Draft202012Validator

DEFAULT_SCHEMA_URL = "https://render.com/schema/render.yaml.json"


def load_blueprint(path):
    with path.open(encoding="utf-8") as blueprint_file:
        return yaml.safe_load(blueprint_file)


def load_schema(source):
    if source.startswith(("https://", "http://")):
        request = Request(
            source, headers={"User-Agent": "SAFE PATH Blueprint validator"}
        )
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def validate(blueprint, schema):
    errors = sorted(
        Draft202012Validator(schema).iter_errors(blueprint),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if not errors:
        return 0
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path) or "root"
        print(f"{location}: {error.message}", file=sys.stderr)
    return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "blueprint",
        nargs="?",
        type=Path,
        default=Path("render.yaml"),
    )
    parser.add_argument("--schema", default=DEFAULT_SCHEMA_URL)
    args = parser.parse_args()

    try:
        blueprint = load_blueprint(args.blueprint)
        schema = load_schema(args.schema)
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"Render Blueprint validation could not run: {error}", file=sys.stderr)
        return 2

    result = validate(blueprint, schema)
    if result == 0:
        print(f"{args.blueprint} matches the Render Blueprint schema.")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
