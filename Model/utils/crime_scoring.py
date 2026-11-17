import math

import pandas as pd

from .geometry_utils import haversine

INCIDENT_RADIUS_METERS = 200
MAX_SEVERITY = 5


def calculate_segment_risk(summary):
    total_crimes = int(summary.get("total_crimes", 0))
    average_severity = float(summary.get("average_severity", 0.0))

    if total_crimes <= 0:
        return 0.0, f"No recorded incidents within {INCIDENT_RADIUS_METERS} metres."

    average_severity = min(max(average_severity, 0.0), MAX_SEVERITY)
    exposure = total_crimes * average_severity / MAX_SEVERITY
    risk = 1 - math.exp(-exposure)
    label = "incident" if total_crimes == 1 else "incidents"
    explanation = (
        f"{total_crimes} recorded {label} within {INCIDENT_RADIUS_METERS} metres, "
        f"average severity {average_severity:.1f} out of {MAX_SEVERITY}."
    )

    return risk, explanation


def summarize_crime_for_segment(a, b, crime_df, radius=INCIDENT_RADIUS_METERS):
    mid_lat = (a[0] + b[0]) / 2
    mid_lon = (a[1] + b[1]) / 2

    nearby_rows = [
        row
        for row in crime_df.itertuples(index=False)
        if haversine(mid_lat, mid_lon, row.latitude, row.longitude) <= radius
    ]
    nearby = pd.DataFrame(nearby_rows)

    summary = {
        "total_crimes": len(nearby),
        "crime_types": nearby["crime_type"].value_counts().to_dict()
        if "crime_type" in nearby.columns
        else {},
        "average_severity": float(nearby["severity"].mean())
        if len(nearby) > 0
        else 0.0,
    }

    return calculate_segment_risk(summary)
