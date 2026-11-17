from pathlib import Path

import pandas as pd

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "delhi_crime_data.csv"


def load_crime_data():
    dataframe = pd.read_csv(DATA_FILE)
    dataframe.columns = dataframe.columns.str.lower()
    return dataframe
