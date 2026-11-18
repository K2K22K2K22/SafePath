import json
from pathlib import Path
from typing import Any

import pandas as pd

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "delhi_crime_data.csv"
SOURCE_METADATA_FILE = (
    Path(__file__).resolve().parents[2] / "data" / "source_metadata.json"
)
_VERIFICATION_STATUS = "unverified_demonstration_data"
_RECORD_NATURE = "fictitious_demo_records_per_repository_history"
_UNKNOWN_PROVENANCE_FIELDS = (
    "original_source",
    "collection_methodology",
    "collection_date",
    "geographical_coverage",
    "license",
    "redistribution_permission",
)
_FALLBACK_METADATA: dict[str, Any] = {
    "dataset_file": DATA_FILE.name,
    "verification_status": _VERIFICATION_STATUS,
    "verified": False,
    "record_nature": None,
    **{field: None for field in _UNKNOWN_PROVENANCE_FIELDS},
    "repository_evidence": [],
}


def load_source_metadata() -> dict[str, Any]:
    try:
        metadata = json.loads(SOURCE_METADATA_FILE.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("Source metadata must be an object.")
        if (
            metadata.get("verification_status") != _VERIFICATION_STATUS
            or metadata.get("verified") is not False
            or metadata.get("dataset_file") != DATA_FILE.name
            or metadata.get("record_nature") != _RECORD_NATURE
            or not isinstance(metadata.get("repository_evidence"), list)
            or any(
                metadata.get(field) is not None for field in _UNKNOWN_PROVENANCE_FIELDS
            )
        ):
            raise ValueError("Source metadata failed validation.")
    except (OSError, ValueError, TypeError, RecursionError):
        return dict(_FALLBACK_METADATA)
    return metadata


INCIDENT_DATA_METADATA = load_source_metadata()
PUBLIC_INCIDENT_DATA_METADATA = {
    "dataset_file": DATA_FILE.name,
    "verification_status": _VERIFICATION_STATUS,
    "verified": False,
    "record_nature": _RECORD_NATURE,
    **{
        field: INCIDENT_DATA_METADATA.get(field) for field in _UNKNOWN_PROVENANCE_FIELDS
    },
}


def load_crime_data():
    dataframe = pd.read_csv(DATA_FILE)
    dataframe.columns = dataframe.columns.str.lower()
    return dataframe
