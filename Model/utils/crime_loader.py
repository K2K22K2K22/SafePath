import json
from pathlib import Path
from typing import Any

import pandas as pd

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "delhi_crime_data.csv"
SOURCE_METADATA_FILE = (
    Path(__file__).resolve().parents[2] / "data" / "source_metadata.json"
)


def load_source_metadata() -> dict[str, Any]:
    with SOURCE_METADATA_FILE.open(encoding="utf-8") as metadata_file:
        return json.load(metadata_file)


INCIDENT_DATA_METADATA = load_source_metadata()


def load_crime_data():
    dataframe = pd.read_csv(DATA_FILE)
    dataframe.columns = dataframe.columns.str.lower()
    return dataframe
