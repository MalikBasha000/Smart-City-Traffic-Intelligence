import hashlib
import sqlite3
import time
import numpy as np
import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st
from src.analytics import get_recommendations, process_features
from src.predictor import train_forecasting_model

# ---------------------------------------------------------
# 1. Page Configuration & Professional Dark Palette
# ---------------------------------------------------------
st.set_page_config(
    page_title="Smart City Traffic Intelligence",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    .stApp {
        background-color: #0b0f19;
        color: #f3f4f6;
    }
    .header-box {
        background: linear-gradient(90deg, #111827 0%, #1e293b 100%);
        padding: 16px 24px;
        border-radius: 10px;
        border: 1px solid #334155;
        margin-bottom: 16px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .search-card {
        background-color: #111827;
        padding: 14px 20px;
        border-radius: 8px;
        border: 1px solid #374151;
        margin-bottom: 20px;
    }
    .target-badge {
        background-color: #ef4444;
        color: white;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 12px;
    }
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# 2. SQLite Authentication System (Persistent DB)
# ---------------------------------------------------------
def get_db_connection():
    return sqlite3.connect("traffic_users.db", check_same_thread=False)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            badge_id TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            name TEXT,
            dept TEXT,
            email TEXT
        )
    """
    )
    # Pre-seed default admin credentials if not existing
    c.execute("SELECT badge_id FROM users WHERE badge_id = 'officer_admin'")
    if not c.fetchone():
        c.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
            (
                "officer_admin",
                hash_password("traffic123"),
                "Command Center Admin",
                "Central Operations HQ",
                "admin@smartcity.gov",
            ),
        )
    conn.commit()
    conn.close()


def authenticate_user(badge_id: str, password: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "SELECT name, dept FROM users WHERE badge_id = ? AND password = ?",
        (badge_id.strip(), hash_password(password.strip())),
    )
    user = c.fetchone()
    conn.close()
    return user


def register_user(badge_id: str, password: str, name: str, dept: str, email: str):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
            (
                badge_id.strip(),
                hash_password(password.strip()),
                name.strip(),
                dept.strip(),
                email.strip(),
            ),
        )
        conn.commit()
        conn.close()
        return True, "Registration completed successfully! Please sign in."
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Badge ID / Username already registered. Please choose another."


init_db()

# Session State for User Auth
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "officer_name" not in st.session_state:
    st.session_state.officer_name = ""
if "searched_junction" not in st.session_state:
    st.session_state.searched_junction = "J_CBD_01"


# ---------------------------------------------------------
# 3. Agency Authentication Screen (Gatekeeper)
# ---------------------------------------------------------
if not st.session_state.authenticated:
    st.markdown(
        """
    <div style="text-align: center; margin-top: 40px; margin-bottom: 25px;">
        <h2>🚦 Smart City Traffic Intelligence Portal</h2>
        <p style="color: #94a3b8;">Restricted Access: Traffic Police, Municipal Planners & Authorized Command Centers</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    _, auth_center, _ = st.columns([1, 1.8, 1])

    with auth_center:
        tab_login, tab_register = st.tabs(["🔒 Agency Sign In", "📝 Register New Officer"])

        with tab_login:
            st.subheader("Officer Authentication")
            u_badge = st.text_input("Badge ID / Username", value="officer_admin", key="login_badge")
            u_pwd = st.text_input("Security Key / Password", type="password", value="traffic123", key="login_pwd")

            if st.button("Authorize & Enter Command Center", use_container_width=True):
                if u_badge and u_pwd:
                    user_match = authenticate_user(u_badge, u_pwd)
                    if user_match:
                        st.session_state.authenticated = True
                        st.session_state.username = u_badge
                        st.session_state.officer_name = user_match[0]
                        st.success("Authorization confirmed.")
                        st.rerun()
                    else:
                        st.error("Invalid Badge ID or Security Key.")
                else:
                    st.warning("Please provide all credentials.")

            st.caption("💡 Default Testing Credentials: `officer_admin` | Password: `traffic123`")

        with tab_register:
            st.subheader("Agency Credentials Enrollment")
            new_name = st.text_input("Full Official Name", key="reg_name")
            new_badge = st.text_input("Designated Badge ID / Username", key="reg_badge")
            new_dept = st.text_input("Control Zone / Sector Division", value="North Traffic Division", key="reg_dept")
            new_email = st.text_input("Official Govt Email", key="reg_email")
            new_pwd = st.text_input("Set Security Password", type="password", key="reg_pwd")

            if st.button("Submit Official Registration", use_container_width=True):
                if new_badge and new_pwd and new_name:
                    success, msg = register_user(new_badge, new_pwd, new_name, new_dept, new_email)
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
                else:
                    st.warning("Full Name, Badge ID, and Password are mandatory.")

    st.stop()


# ---------------------------------------------------------
# 4. Data Ingestion & Model Loading
# ---------------------------------------------------------
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


# ---------------------------------------------------------
# 5. Top Bar: Agency Identity, Search Engine & Target Locator
# ---------------------------------------------------------
col_head, col_prof = st.columns([4, 1.2])
with col_head:
    st.title("🚦 Smart City Traffic Intelligence & Dispatch System")
    st.caption("Live bottleneck detection, incident triage, and automated resource deployment.")
with col_prof:
    st.write(f"👮 Officer: **{st.session_state.officer_name or st.session_state.username}**")
    if st.button("Log Out", key="logout_btn", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.username = ""
        st.session_state.officer_name = ""
        st.rerun()

# SEARCH ENGINE COMPONENT
s_col1, s_col2 = st.columns([3.5, 1.2])
with s_col1:
    search_selection = st.selectbox(
        "🔍 Search Area / Monitored Junction to Target and Track:",
        options=list(JUNCTION_META.keys()),
        index=list(JUNCTION_META.keys()).index(st.session_state.searched_junction),
        format_func=lambda x: f"{JUNCTION_META[x]['name']} ({x})",
        help="Type or select any junction to point the locator arrow and focus telemetry.",
    )
    if search_selection != st.session_state.searched_junction:
        st.session_state.searched_junction = search_selection
        st.rerun()

with s_col2:
    st.write(" ")
    st.write(" ")
    if st.button("🎯 Focus & Point Arrow", use_container_width=True):
        st.rerun()

st.divider()

# ---------------------------------------------------------
# 6. Mode Selection (Sidebar)
# ---------------------------------------------------------
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
        index=list(JUNCTION_META.keys()).index(st.session_state.searched_junction),
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

# ---------------------------------------------------------
# 7. ML Forecast Predictions & Top KPIs
# ---------------------------------------------------------
current_slice["forecast_next_15m"] = current_slice.apply(
    predict_next_volume, axis=1
)

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

# ---------------------------------------------------------
# 8. Interactive 3D Map with Dynamic Downward Arrow Pointer
# ---------------------------------------------------------
map_col, action_col = st.columns([3, 2])

# Selected Junction Metadata for Arrow Pointer
target_meta = JUNCTION_META[st.session_state.searched_junction]
target_df = current_slice[current_slice["junction_id"] == st.session_state.searched_junction]

# Build pointer dataset pointing straight at the searched location
arrow_data = pd.DataFrame(
    [
        {
            "latitude": target_meta["lat"],
            "longitude": target_meta["lon"],
            "name": target_meta["name"],
            # High elevation for inverted cone arrow
            "elevation": 3200,
        }
    ]
)

with map_col:
    st.subheader("🌐 Real-Time 3D Network Map")
    st.caption(f"Currently tracking pointer beacon at: **{target_meta['name']}**")

    current_slice["pillar_color"] = current_slice["rpi_score"].apply(
        assign_pillar_color
    )

    # Focus map camera centered at the searched junction
    view_center = pdk.ViewState(
        latitude=float(target_meta["lat"]),
        longitude=float(target_meta["lon"]),
        zoom=13.0,
        pitch=48,
        bearing=15,
    )

    # Standard Traffic Volume Pillars
    column_layer = pdk.Layer(
        "ColumnLayer",
        data=current_slice,
        get_position=["longitude", "latitude"],
        get_elevation="rpi_score",
        elevation_scale=35,
        radius=240,
        get_fill_color="pillar_color",
        pickable=True,
        auto_highlight=True,
    )

    # DYNAMIC TARGET ARROW (Inverted Cone pointing straight down onto the junction)
    arrow_pointer_layer = pdk.Layer(
        "ConeLayer",
        data=arrow_data,
        get_position=["longitude", "latitude"],
        get_elevation="elevation",
        elevation_scale=1,
        radius=200,
        get_color=[255, 0, 55, 240],  # Neon Red Pointer
        pickable=False,
    )

    # Ground Pulsing Halo for Target Junction
    target_halo_layer = pdk.Layer(
        "ScatterplotLayer",
        data=arrow_data,
        get_position=["longitude", "latitude"],
        get_radius=420,
        get_fill_color=[255, 0, 55, 100],
        get_line_color=[255, 255, 255, 220],
        line_width_min_pixels=3,
        pickable=False,
    )

    deck_map = pdk.Deck(
        layers=[column_layer, arrow_pointer_layer, target_halo_layer],
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

# ---------------------------------------------------------
# 9. Operational Dispatch Directives & Signal Controls
# ---------------------------------------------------------
with action_col:
    st.subheader("📋 Operational Dispatch Directives")

    # Quick highlighted panel for the searched junction
    if not target_df.empty:
        t_row = target_df.iloc[0]
        st.markdown(
            f"""
        <div style="background: #1e293b; border-left: 4px solid #ef4444; padding: 10px 14px; border-radius: 6px; margin-bottom: 12px;">
            <b>🎯 TARGETED SECTOR:</b> {t_row['junction_name']}<br>
            <span style="font-size: 13px; color: #cbd5e1;">Flow: <b>{t_row['vehicle_count']}/{t_row['road_capacity']} veh</b> | RPI: <b>{t_row['rpi_score']}</b> | Forecast: <b>{t_row['forecast_next_15m']} veh</b></span>
        </div>
        """,
            unsafe_allow_html=True,
        )

    prioritized_corridors = current_slice.sort_values(
        by="rpi_score", ascending=False
    )

    for _, corridor in prioritized_corridors.iterrows():
        status_tag = (
            "🔴 CRITICAL"
            if corridor["rpi_score"] >= 60
            else ("🟡 ELEVATED" if corridor["rpi_score"] >= 40 else "🟢 OPTIMAL")
        )

        is_focused = corridor["junction_id"] == st.session_state.searched_junction
        expander_title = f"{status_tag} | {corridor['junction_name']} (RPI: {corridor['rpi_score']}) {'📍 [FOCUSED]' if is_focused else ''}"

        with st.expander(expander_title, expanded=is_focused):
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

# ---------------------------------------------------------
# 10. Polling Loop for Live Automated Simulation
# ---------------------------------------------------------
if data_mode == "Automated Live Feed" and auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()