import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split

def train_forecasting_model(data_path="data/traffic_data.csv"):
    df = pd.read_csv(data_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values(by=["junction_id", "timestamp"]).reset_index(drop=True)
    
    df["lag_count_1"] = df.groupby("junction_id")["vehicle_count"].shift(1)
    df["lag_count_2"] = df.groupby("junction_id")["vehicle_count"].shift(2)
    
    df["hour"] = df["timestamp"].dt.hour
    df["dayofweek"] = df["timestamp"].dt.day_of_week
    df["is_weekend"] = (df["dayofweek"] >= 5).astype(int)
    
    weather_map = {"Clear": 0, "Fog": 1, "Rain": 2}
    df["weather_code"] = df["weather_condition"].map(weather_map).fillna(0).astype(int)
    
    df = df.dropna().reset_index(drop=True)
    
    features = ["hour", "dayofweek", "is_weekend", "lag_count_1", "lag_count_2", "weather_code", "accident_reported", "road_capacity"]
    target = "vehicle_count"
    
    X = df[features]
    y = df[target]
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    
    model = RandomForestRegressor(n_estimators=70, max_depth=12, random_state=42)
    model.fit(X_train, y_train)
    return model