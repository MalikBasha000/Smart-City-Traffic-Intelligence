import pandas as pd
import numpy as np

def process_features(df):
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["hour"] = df["timestamp"].dt.hour
    df["day_name"] = df["timestamp"].dt.day_name()
    
    df["is_peak_hour"] = df["hour"].apply(lambda h: 1 if (8 <= h <= 10 or 17 <= h <= 20) else 0)
    df["vc_ratio"] = (df["vehicle_count"] / df["road_capacity"]).round(2)
    
    weather_map = {"Clear": 0.0, "Fog": 0.5, "Rain": 1.0}
    df["weather_score"] = df["weather_condition"].map(weather_map).fillna(0.0)
    
    df["rpi_score"] = (
        (df["vc_ratio"].clip(0, 1.5) / 1.5) * 40 +
        df["accident_reported"] * 30 +
        df["weather_score"] * 15 +
        df["is_peak_hour"] * 15
    ).round(1)
    
    return df

def get_recommendations(row):
    actions = []
    if row["accident_reported"] == 1:
        actions.append("CRITICAL: Dispatch Rapid Incident Response & EMS clearance unit.")
    if row["vc_ratio"] >= 1.0:
        actions.append("SIGNAL ADJUSTMENT: Extend green signal phase along primary corridor by +25s.")
        actions.append("DIVERSION: Activate dynamic VMS detour signs at upstream intersections.")
    elif row["vc_ratio"] >= 0.8:
        actions.append("PATROL: Deploy mobile traffic marshal to prevent intersection box blocking.")
    if row["weather_condition"] == "Rain" and row["is_peak_hour"] == 1:
        actions.append("ADVISORY: Broadcast wet road safety advisory and reduce speed limits via digital signs.")
    if not actions:
        actions.append("NORMAL FLOW: Standard timing plan active; maintain passive camera monitoring.")
    return actions