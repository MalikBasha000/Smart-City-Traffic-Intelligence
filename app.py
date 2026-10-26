import time
import numpy as np
import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st
from src.analytics import get_recommendations, process_features
from src.predictor import train_forecasting_model

# 1. Page Configuration
st.set_page_config(
    page_title="Smart City Traffic Intelligence",
    page_icon="🚦",
    layout="wide",
)


# 2. Data Ingestion & Model Loading
@st.cache_data
def load_and_prepare_data():
    raw_df = pd.read_csv("data/traffic_data.csv")
    return process_features(raw_df)


@st.cache_resource
def load_trained_model():
    return train_forecasting_model()


df = load_and_prepare_data()
model = load_trained_model()

# Exact feature schema matching src/predictor.py
FEATURE_NAMES = [
    "hour",
    "dayofweek",
    "is_weekend",
    "lag_count_1",
    "lag_count_2",
    "weather_code",
    "accident_reported",
    "road_capacity",
]

# Junction coordinates and capacities
JUNCTION_META = {
    "J_CBD_01": {
        "name": "Central Business Hub",
        "lat": 17.4435,
        "lon": 78.3772,
        "capacity": 300,
    },
    "J_TECH_02": {
        "name": "Tech Corridor Junction",
        "lat": 17.4504,
        "lon": 78.3808,
        "capacity": 250,
    },
    "J_IND_03": {
        "name": "Industrial Ring Road",
        "lat": 17.4200,
        "lon": 78.3489,
        "capacity": 200,
    },
    "J_RES_04": {
        "name": "Suburban Arterial Gate",
        "lat": 17.4720,
        "lon": 78.3550,
        "capacity": 180,
    },
    "J_EXP_05": {
        "name": "Expressway Interchange",
        "lat": 17.4110,
        "lon": 78.4000,
        "capacity": 350,
    },
}

weather_map = {"Clear": 0, "Fog": 1, "Rain": 2}


def predict_next_volume(row):
    """Predict next 15-minute volume using DataFrame to preserve feature names."""
    try:
        input_data = {
            "hour": [int(row["hour"])],
            "dayofweek": [int(row["timestamp"].day_of_week)],
            "is_weekend": [1 if row["timestamp"].day_of_week >= 5 else 0],
            "lag_count_1": [float(row["vehicle_count"])],
            "lag_count_2": [float(row["vehicle_count"] * 0.95)],
            "weather_code": [int(weather_map.get(row["weather_condition"], 0))],
            "accident_reported": [int(row["accident_reported"])],
            "road_capacity": [int(row["road_capacity"])],
        }
        input_df = pd.DataFrame(input_data, columns=FEATURE_NAMES)
        return int(model.predict(input_df)[0])
    except Exception:
        return int(row["vehicle_count"])


def assign_pillar_color(score):
    if score >= 60:
        return [230, 57, 70, 220]  # Red: Critical
    elif score >= 40:
        return [244, 162, 97, 220]  # Amber: Elevated
    return [42, 157, 143, 220]  # Green: Free Flow


# 3. UI Header
st.title("🚦 Smart City Traffic Intelligence & Dispatch System")
st.caption(
    "Live bottleneck detection, incident triage, and automated resource deployment."
)

# 4. Mode Selection
st.sidebar.header("🕹️ Mode Selection")
data_mode = st.sidebar.radio(
    "Choose Data Source:",
    ["Historical Dataset", "Manual Testing Feed", "Automated Live Feed"],
)

current_slice = pd.DataFrame()

# Mode A: Historical Dataset
if data_mode == "Historical Dataset":
    unique_dates = df["timestamp"].dt.date.unique()
    selected_date = st.sidebar.date_input("Simulation Date", unique_dates[-1])
    day_data = df[df["timestamp"].dt.date == selected_date]

    selected_hour = st.sidebar.slider("Hour of Day (24h)", 0, 23, 18)
    selected_minute = st.sidebar.select_slider(
        "15-Minute Interval", options=[0, 15, 30, 45], value=30
    )

    active_timestamp = pd.Timestamp(
        f"{selected_date} {selected_hour:02d}:{selected_minute:02d}:00"
    )
    current_slice = day_data[day_data["timestamp"] == active_timestamp].copy()

# Mode B: Manual Override
elif data_mode == "Manual Testing Feed":
    st.sidebar.subheader("✏️ Enter Sensor Inputs")
    selected_jid = st.sidebar.selectbox(
        "Select Junction to Test",
        list(JUNCTION_META.keys()),
        format_func=lambda x: JUNCTION_META[x]["name"],
    )

    meta = JUNCTION_META[selected_jid]
    manual_count = st.sidebar.slider(
        "Vehicle Count",
        0,
        int(meta["capacity"] * 1.5),
        int(meta["capacity"] * 0.8),
    )
    manual_weather = st.sidebar.selectbox(
        "Weather Condition", ["Clear", "Fog", "Rain"]
    )
    manual_accident = st.sidebar.checkbox(
        "Report Incident / Accident", value=False
    )
    manual_hour = st.sidebar.slider("Current Hour (0-23)", 0, 23, 9)

    now_ts = pd.Timestamp.now().replace(hour=manual_hour, minute=0, second=0)

    manual_record = pd.DataFrame(
        [
            {
                "timestamp": now_ts,
                "junction_id": selected_jid,
                "junction_name": meta["name"],
                "latitude": meta["lat"],
                "longitude": meta["lon"],
                "vehicle_count": manual_count,
                "road_capacity": meta["capacity"],
                "weather_condition": manual_weather,
                "accident_reported": 1 if manual_accident else 0,
            }
        ]
    )
    current_slice = process_features(manual_record)

# Mode C: Live Automated Simulation
elif data_mode == "Automated Live Feed":
    auto_refresh = st.sidebar.checkbox("Enable Live Polling", value=True)
    refresh_rate = st.sidebar.slider("Refresh Rate (seconds)", 2, 10, 3)

    now_ts = pd.Timestamp.now()
    live_records = []
    current_weather = np.random.choice(
        ["Clear", "Rain", "Fog"], p=[0.7, 0.2, 0.1]
    )

    for jid, meta in JUNCTION_META.items():
        base = int(meta["capacity"] * np.random.uniform(0.4, 1.15))
        has_acc = 1 if np.random.rand() < 0.15 else 0
        if has_acc:
            base = int(base * 1.3)

        live_records.append(
            {
                "timestamp": now_ts,
                "junction_id": jid,
                "junction_name": meta["name"],
                "latitude": meta["lat"],
                "longitude": meta["lon"],
                "vehicle_count": base,
                "road_capacity": meta["capacity"],
                "weather_condition": current_weather,
                "accident_reported": has_acc,
            }
        )

    current_slice = process_features(pd.DataFrame(live_records))

if current_slice.empty:
    st.warning("No data points available for current configuration.")
    st.stop()

# 5. ML Forecast Predictions
current_slice["forecast_next_15m"] = current_slice.apply(
    predict_next_volume, axis=1
)

# Top KPIs
col1, col2, col3, col4 = st.columns(4)
col1.metric(
    "Monitored Vehicle Volume",
    f"{current_slice['vehicle_count'].sum():,} veh",
)
avg_vc = current_slice["vc_ratio"].mean()
col2.metric(
    "Network Avg V/C Ratio",
    f"{avg_vc:.2f}",
    delta="Saturated" if avg_vc >= 0.85 else "Stable",
    delta_color="inverse" if avg_vc >= 0.85 else "normal",
)
accidents_count = int(current_slice["accident_reported"].sum())
col3.metric(
    "Active Incidents", f"{accidents_count} Alert(s)", delta_color="inverse"
)
max_rpi = current_slice["rpi_score"].max()
col4.metric(
    "Peak RPI Stress Index",
    f"{max_rpi:.1f} / 100",
    delta="High Load" if max_rpi > 60 else "Normal Load",
    delta_color="inverse" if max_rpi > 60 else "normal",
)

st.divider()

# Map and Directives
map_col, action_col = st.columns([3, 2])

with map_col:
    st.subheader("🌐 Real-Time 3D Network Map")
    current_slice["pillar_color"] = current_slice["rpi_score"].apply(
        assign_pillar_color
    )

    view_center = pdk.ViewState(
        latitude=float(current_slice["latitude"].mean()),
        longitude=float(current_slice["longitude"].mean()),
        zoom=11.6,
        pitch=48,
    )

    column_layer = pdk.Layer(
        "ColumnLayer",
        data=current_slice,
        get_position=["longitude", "latitude"],
        get_elevation="rpi_score",
        elevation_scale=35,
        radius=260,
        get_fill_color="pillar_color",
        pickable=True,
        auto_highlight=True,
    )

    deck_map = pdk.Deck(
        layers=[column_layer],
        initial_view_state=view_center,
        tooltip={
            "html": (
                "<b>{junction_name}</b><br/>"
                "RPI Stress: <b>{rpi_score}</b><br/>"
                "Volume: {vehicle_count}/{road_capacity} (V/C: {vc_ratio})<br/>"
                "15m Forecast: <b>{forecast_next_15m} veh</b>"
            ),
            "style": {"color": "white", "backgroundColor": "#1e1e1e"},
        },
    )
    st.pydeck_chart(deck_map)

with action_col:
    st.subheader("📋 Operational Dispatch Directives")
    prioritized_corridors = current_slice.sort_values(
        by="rpi_score", ascending=False
    )

    for _, corridor in prioritized_corridors.iterrows():
        status_tag = (
            "🔴 CRITICAL"
            if corridor["rpi_score"] >= 60
            else ("🟡 ELEVATED" if corridor["rpi_score"] >= 40 else "🟢 OPTIMAL")
        )

        with st.expander(
            f"{status_tag} | {corridor['junction_name']} (RPI: {corridor['rpi_score']})"
        ):
            c_flow, c_pred = st.columns(2)
            c_flow.metric(
                "Current Flow",
                f"{corridor['vehicle_count']} / {corridor['road_capacity']} veh",
            )
            c_pred.metric(
                "15-Min Forecast",
                f"{corridor['forecast_next_15m']} veh",
                delta=int(
                    corridor["forecast_next_15m"] - corridor["vehicle_count"]
                ),
                delta_color="inverse",
            )
            st.write(
                f"**Road State:** V/C: {corridor['vc_ratio']} | Weather: {corridor['weather_condition']}"
            )
            st.write(
                f"**Incident Status:** {'🚨 Collision Active' if corridor['accident_reported'] == 1 else 'Normal'}"
            )
            st.write("**Recommended Interventions:**")
            for act in get_recommendations(corridor):
                st.markdown(f"- {act}")

# Polling loop for live automated simulation
if data_mode == "Automated Live Feed" and auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()