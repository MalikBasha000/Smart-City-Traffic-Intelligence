import hashlib
import sqlite3
import time
from datetime import datetime
from geopy.geocoders import Nominatim
import numpy as np
import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components
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
    /* Dark background across entire viewport */
    .stApp {
        background-color: #0b0f19 !important;
        color: #f3f4f6 !important;
    }

    /* Prevent header clipping on mobile screens */
    .block-container {
        padding-top: 1.8rem !important;
        padding-bottom: 3rem !important;
    }

    /* Remove white backgrounds from input boxes */
    div[data-baseweb="input"],
    div[data-baseweb="base-input"] {
        background-color: #161f30 !important;
        border: 1px solid #334155 !important;
        border-radius: 8px !important;
    }
    div[data-baseweb="input"] input,
    input.st-bc {
        background-color: transparent !important;
        color: #ffffff !important;
        font-size: 15px !important;
        font-weight: 500 !important;
    }
    div[data-baseweb="input"]:focus-within {
        border-color: #ef4444 !important;
        box-shadow: 0 0 0 1px #ef4444 !important;
    }

    /* High contrast text on all field labels and captions */
    label, p, span, h1, h2, h3, h4, small {
        color: #e2e8f0 !important;
    }

    /* Red command-center primary action buttons */
    .stButton > button {
        background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%) !important;
        color: #ffffff !important;
        font-weight: 600 !important;
        font-size: 15px !important;
        border: 1px solid #dc2626 !important;
        border-radius: 8px !important;
        padding: 0.6rem 1.2rem !important;
        box-shadow: 0 4px 12px rgba(239, 68, 68, 0.35) !important;
        transition: all 0.2s ease-in-out !important;
        width: 100% !important;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%) !important;
        box-shadow: 0 6px 16px rgba(239, 68, 68, 0.5) !important;
    }

    /* Tabs styling matching dark command theme */
    button[data-baseweb="tab"] {
        color: #94a3b8 !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #ef4444 !important;
        border-bottom-color: #ef4444 !important;
    }

    /* Metric cards & info banners */
    .metric-card {
        background-color: #111827 !important;
        border: 1px solid #374151 !important;
        border-radius: 8px !important;
        padding: 14px !important;
        text-align: center !important;
    }
    .stAlert {
        background-color: #111827 !important;
        color: #f3f4f6 !important;
        border: 1px solid #374151 !important;
        border-radius: 8px !important;
    }
    code {
        color: #fca5a5 !important;
        background-color: #1e293b !important;
        border: 1px solid #334155 !important;
        border-radius: 4px !important;
        padding: 2px 6px !important;
    }
    
    /* Header box */
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
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# 2. SQLite Authentication & Hardware Incident DB
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
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS field_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            officer_badge TEXT,
            location_name TEXT,
            lat REAL,
            lon REAL,
            incident_type TEXT,
            notes TEXT
        )
    """
    )
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


def log_field_incident(officer_badge, loc_name, lat, lon, inc_type, notes):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO field_incidents (timestamp, officer_badge, location_name, lat, lon, incident_type, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), officer_badge, loc_name, lat, lon, inc_type, notes),
    )
    conn.commit()
    conn.close()


init_db()

# Session State for User Auth, GPS & Dynamic Location
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "officer_name" not in st.session_state:
    st.session_state.officer_name = ""
if "target_area_name" not in st.session_state:
    st.session_state.target_area_name = "Paradise Circle, Secunderabad"
if "target_lat" not in st.session_state:
    st.session_state.target_lat = 17.4416
if "target_lon" not in st.session_state:
    st.session_state.target_lon = 78.4871


# ---------------------------------------------------------
# 3. Dynamic Free-Form Geocoding Engine
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def geocode_location(query: str):
    try:
        geolocator = Nominatim(user_agent="smart_city_traffic_portal_v2")
        location = geolocator.geocode(query, timeout=10)
        if location:
            return location.latitude, location.longitude, location.address
    except Exception:
        pass
    return None, None, None


@st.cache_data(show_spinner=False)
def reverse_geocode(lat: float, lon: float):
    try:
        geolocator = Nominatim(user_agent="smart_city_traffic_portal_v2")
        location = geolocator.reverse(f"{lat}, {lon}", timeout=10)
        if location:
            return location.address
    except Exception:
        pass
    return f"GPS Sector ({lat:.4f}, {lon:.4f})"


# ---------------------------------------------------------
# 4. Agency Authentication Screen (Gatekeeper)
# ---------------------------------------------------------
if not st.session_state.authenticated:
    st.markdown(
        """
    <div style="text-align: center; margin-top: 20px; margin-bottom: 25px;">
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

            if st.button("Authorize & Enter Command Center", key="btn_auth_login"):
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

            if st.button("Submit Official Registration", key="btn_auth_reg"):
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
# 5. Data Ingestion & Model Loading
# ---------------------------------------------------------
@st.cache_data
def load_and_prepare_data():
    try:
        raw_df = pd.read_csv("data/traffic_data.csv")
        return process_features(raw_df)
    except Exception:
        return pd.DataFrame()


@st.cache_resource
def load_trained_model():
    return train_forecasting_model()


df = load_and_prepare_data()
model = load_trained_model()

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
weather_map = {"Clear": 0, "Fog": 1, "Rain": 2}


def predict_next_volume(row):
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
        return [230, 57, 70, 220]
    elif score >= 40:
        return [244, 162, 97, 220]
    return [42, 157, 143, 220]


# ---------------------------------------------------------
# 6. Top Bar: Agency Identity & Custom Area Search Engine
# ---------------------------------------------------------
col_head, col_prof = st.columns([4, 1.2])
with col_head:
    st.title("🚦 Smart City Traffic Intelligence & Dispatch System")
    st.caption("Live bottleneck detection, incident triage, and automated resource deployment.")
with col_prof:
    st.write(f"👮 Officer: **{st.session_state.officer_name or st.session_state.username}**")
    if st.button("Log Out", key="logout_btn"):
        st.session_state.authenticated = False
        st.session_state.username = ""
        st.session_state.officer_name = ""
        st.rerun()

# REAL-TIME SEARCH + MOBILE GPS HARDWARE LOCATION ROW
s_col1, s_col2, s_col3 = st.columns([2.8, 1.1, 1.1])
with s_col1:
    user_search_input = st.text_input(
        "🔍 Type ANY Area / Junction to Track & Point Arrow on Map:",
        value=st.session_state.target_area_name,
        placeholder="Type any area: e.g. Paradise Circle, Hitec City, Jubilee Hills, Charminar...",
        key="search_area_box",
    )

with s_col2:
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
    locate_pressed = st.button("🎯 Locate Target", key="locate_target_btn")

with s_col3:
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
    use_gps_pressed = st.button("📍 Sync My GPS", key="sync_gps_btn")

# Hardware GPS Receiver logic
if "gps_lat" in st.query_params and "gps_lon" in st.query_params:
    try:
        gps_lat = float(st.query_params["gps_lat"])
        gps_lon = float(st.query_params["gps_lon"])
        if abs(gps_lat - st.session_state.target_lat) > 0.0001 or abs(gps_lon - st.session_state.target_lon) > 0.0001:
            st.session_state.target_lat = gps_lat
            st.session_state.target_lon = gps_lon
            resolved_address = reverse_geocode(gps_lat, gps_lon)
            st.session_state.target_area_name = resolved_address
            del st.query_params["gps_lat"]
            del st.query_params["gps_lon"]
            st.rerun()
    except Exception:
        pass

# Trigger browser geolocation when "Sync My GPS" is clicked
if use_gps_pressed:
    components.html(
        """
        <script>
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                function(position) {
                    const lat = position.coords.latitude;
                    const lon = position.coords.longitude;
                    try {
                        const targetUrl = new URL(window.parent.location.href);
                        targetUrl.searchParams.set("gps_lat", lat);
                        targetUrl.searchParams.set("gps_lon", lon);
                        window.parent.location.href = targetUrl.toString();
                    } catch (e) {
                        window.location.href = window.location.pathname + "?gps_lat=" + lat + "&gps_lon=" + lon;
                    }
                },
                function(error) {
                    alert("GPS Access Denied or Unavailable: " + error.message);
                },
                { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }
            );
        } else {
            alert("Geolocation hardware is not accessible.");
        }
        </script>
        """,
        height=0,
    )

# Geocode dynamically when the user types or clicks
if locate_pressed or (user_search_input and user_search_input != st.session_state.target_area_name):
    lat, lon, full_address = geocode_location(user_search_input)
    if lat and lon:
        st.session_state.target_lat = lat
        st.session_state.target_lon = lon
        st.session_state.target_area_name = user_search_input
    else:
        st.warning(f"Could not locate '{user_search_input}'. Retaining current coordinates.")

st.divider()

# ---------------------------------------------------------
# 7. Sidebar Simulation & Sensor Controls
# ---------------------------------------------------------
st.sidebar.header("🕹️ Area Sensor & Simulation Controls")
data_mode = st.sidebar.radio(
    "Sensor Input Mode:",
    ["Live Targeted Area Telemetry", "Manual Override Feed", "Automated Ambient Simulation"],
    key="sim_mode_radio",
)

sim_capacity = st.sidebar.slider("Roadway Capacity (veh/hr)", 100, 500, 260, key="slider_cap")
sim_count = st.sidebar.slider("Current Vehicle Count", 0, int(sim_capacity * 1.5), int(sim_capacity * 0.78), key="slider_count")
sim_weather = st.sidebar.selectbox("Local Weather Condition", ["Clear", "Fog", "Rain"], key="select_weather")
sim_incident = st.sidebar.checkbox("Report Incident / Collision Alert", value=False, key="check_incident")
sim_hour = st.sidebar.slider("Observation Hour (0-23)", 0, 23, 18, key="slider_hour")

if data_mode == "Automated Ambient Simulation":
    auto_refresh = st.sidebar.checkbox("Enable Live Polling", value=True, key="check_auto_refresh")
    refresh_rate = st.sidebar.slider("Refresh Rate (seconds)", 2, 10, 3, key="slider_refresh_rate")

# ---------------------------------------------------------
# 8. Dynamic Record Pipeline for the Target Location
# ---------------------------------------------------------
now_ts = pd.Timestamp.now().replace(hour=sim_hour, minute=0, second=0)

primary_record = {
    "timestamp": now_ts,
    "junction_id": "TARGETED_ZONE",
    "junction_name": st.session_state.target_area_name,
    "latitude": float(st.session_state.target_lat),
    "longitude": float(st.session_state.target_lon),
    "vehicle_count": sim_count,
    "road_capacity": sim_capacity,
    "weather_condition": sim_weather,
    "accident_reported": 1 if sim_incident else 0,
}

all_records = [primary_record]

np.random.seed(42)
offsets = [
    (0.012, 0.009, "North Sector Link"),
    (-0.011, -0.010, "South Arterial Gate"),
    (-0.008, 0.014, "East Feeder Crossroad"),
    (0.014, -0.012, "West Ring Access"),
]

for d_lat, d_lon, label in offsets:
    cap = int(sim_capacity * np.random.uniform(0.7, 1.1))
    v_cnt = int(cap * np.random.uniform(0.4, 0.95))
    all_records.append(
        {
            "timestamp": now_ts,
            "junction_id": label.replace(" ", "_"),
            "junction_name": f"{label} ({st.session_state.target_area_name[:12]})",
            "latitude": float(st.session_state.target_lat) + d_lat,
            "longitude": float(st.session_state.target_lon) + d_lon,
            "vehicle_count": v_cnt,
            "road_capacity": cap,
            "weather_condition": sim_weather,
            "accident_reported": 1 if np.random.rand() < 0.1 else 0,
        }
    )

current_slice = process_features(pd.DataFrame(all_records))
current_slice["forecast_next_15m"] = current_slice.apply(predict_next_volume, axis=1)

# ---------------------------------------------------------
# 9. Telemetry KPI Badges
# ---------------------------------------------------------
target_row = current_slice[current_slice["junction_id"] == "TARGETED_ZONE"].iloc[0]

col1, col2, col3, col4 = st.columns(4)
col1.metric(
    "Targeted Area",
    st.session_state.target_area_name[:24],
    f"{target_row['vehicle_count']} veh",
)
avg_vc = target_row["vc_ratio"]
col2.metric(
    "Area V/C Saturation",
    f"{avg_vc:.2f}",
    delta="Saturated" if avg_vc >= 0.85 else "Stable",
    delta_color="inverse" if avg_vc >= 0.85 else "normal",
)
accidents_count = int(current_slice["accident_reported"].sum())
col3.metric(
    "Active Incidents",
    f"{accidents_count} Alert(s)",
    delta="Collision Reported" if target_row["accident_reported"] == 1 else "Normal Flow",
    delta_color="inverse" if target_row["accident_reported"] == 1 else "normal",
)
target_rpi = target_row["rpi_score"]
col4.metric(
    "Area RPI Stress Index",
    f"{target_rpi:.1f} / 100",
    delta="High Load" if target_rpi > 60 else "Normal Load",
    delta_color="inverse" if target_rpi > 60 else "normal",
)

st.divider()

# ---------------------------------------------------------
# 10. Interactive 3D Map with Dynamic Pointed Arrow Marker
# ---------------------------------------------------------
map_col, action_col = st.columns([3, 2])

arrow_data = pd.DataFrame(
    [
        {
            "latitude": float(st.session_state.target_lat),
            "longitude": float(st.session_state.target_lon),
            "name": st.session_state.target_area_name,
            "elevation": 3200,
        }
    ]
)

with map_col:
    st.subheader("🌐 Real-Time 3D Network Map")
    st.caption(
        f"🎯 Pointer Arrow Locked: **{st.session_state.target_area_name}** "
        f"({st.session_state.target_lat:.4f}, {st.session_state.target_lon:.4f})"
    )

    current_slice["pillar_color"] = current_slice["rpi_score"].apply(assign_pillar_color)

    view_center = pdk.ViewState(
        latitude=float(st.session_state.target_lat),
        longitude=float(st.session_state.target_lon),
        zoom=13.6,
        pitch=48,
        bearing=15,
    )

    column_layer = pdk.Layer(
        "ColumnLayer",
        data=current_slice,
        get_position=["longitude", "latitude"],
        get_elevation="rpi_score",
        elevation_scale=38,
        radius=200,
        get_fill_color="pillar_color",
        pickable=True,
        auto_highlight=True,
    )

    arrow_pointer_layer = pdk.Layer(
        "ConeLayer",
        data=arrow_data,
        get_position=["longitude", "latitude"],
        get_elevation="elevation",
        elevation_scale=1,
        radius=180,
        get_color=[255, 0, 55, 240],
        pickable=False,
    )

    target_halo_layer = pdk.Layer(
        "ScatterplotLayer",
        data=arrow_data,
        get_position=["longitude", "latitude"],
        get_radius=380,
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
# 11. Operational Dispatch Directives & Mobile Field Utils
# ---------------------------------------------------------
with action_col:
    tab_directives, tab_field_cam = st.tabs(["📋 Dispatch Directives", "📷 On-Scene Camera & Incident Triage"])

    with tab_directives:
        status_tag = (
            "🔴 CRITICAL"
            if target_row["rpi_score"] >= 60
            else ("🟡 ELEVATED" if target_row["rpi_score"] >= 40 else "🟢 OPTIMAL")
        )

        st.markdown(
            f"""
            <div style="background: #1e293b; border-left: 4px solid #ef4444; padding: 12px 14px; border-radius: 6px; margin-bottom: 14px;">
                <b>🎯 TARGETED SECTOR:</b> {st.session_state.target_area_name}<br>
                <span style="font-size: 13px; color: #cbd5e1;">Status: <b>{status_tag}</b> | Flow: <b>{target_row['vehicle_count']}/{target_row['road_capacity']} veh</b> | RPI: <b>{target_row['rpi_score']}</b> | 15m Forecast: <b>{target_row['forecast_next_15m']} veh</b></span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        prioritized_corridors = current_slice.sort_values(by="rpi_score", ascending=False)

        for _, corridor in prioritized_corridors.iterrows():
            is_focused = corridor["junction_id"] == "TARGETED_ZONE"
            c_status = (
                "🔴 CRITICAL"
                if corridor["rpi_score"] >= 60
                else ("🟡 ELEVATED" if corridor["rpi_score"] >= 40 else "🟢 OPTIMAL")
            )

            expander_title = (
                f"{c_status} | {corridor['junction_name']} (RPI: {corridor['rpi_score']}) "
                f"{'📍 [TARGETED]' if is_focused else ''}"
            )

            with st.expander(expander_title, expanded=is_focused):
                c_flow, c_pred = st.columns(2)
                c_flow.metric(
                    "Current Flow",
                    f"{corridor['vehicle_count']} / {corridor['road_capacity']} veh",
                )
                c_pred.metric(
                    "15-Min Forecast",
                    f"{corridor['forecast_next_15m']} veh",
                    delta=int(corridor["forecast_next_15m"] - corridor["vehicle_count"]),
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

        st.markdown("---")
        st.markdown("#### ⚡ Signal Corridor Override")
        sig_action = st.radio(
            f"Deploy Phase to {st.session_state.target_area_name[:20]}:",
            ["Hold Green Corridor", "Dynamic Adaptive Cycle", "Emergency All-Red Flush", "Manual Officer Control"],
            key="radio_signal_action",
        )
        if st.button("Dispatch Phase Signal", key="btn_dispatch_sig"):
            st.success(f"Signal command '{sig_action}' deployed to {st.session_state.target_area_name}.")

    with tab_field_cam:
        st.subheader("📷 Mobile Incident Reporting")
        st.caption("Capture physical bottlenecks, stalled vehicles, or lane hazards directly via phone camera.")

        inc_type = st.selectbox(
            "Incident Classification",
            ["Vehicle Breakdown / Stalled", "Multi-Vehicle Collision", "Waterlogging / Debris", "Illegal Parking Obstruction"],
            key="select_inc_cat",
        )
        inc_notes = st.text_input("Officer Quick Observation Notes", placeholder="e.g. Lane 2 blocked, tow truck requested", key="text_inc_notes")

        cam_photo = st.camera_input("📸 Capture Scene Evidence", key="cam_evidence_input")

        if cam_photo is not None:
            st.image(cam_photo, caption="Uploaded Live Evidence")
            if st.button("💾 Submit Incident Log to Central HQ", key="btn_save_incident"):
                log_field_incident(
                    st.session_state.username,
                    st.session_state.target_area_name,
                    st.session_state.target_lat,
                    st.session_state.target_lon,
                    inc_type,
                    inc_notes,
                )
                st.success("Incident logged into Command Center database with GPS tag.")

        conn = get_db_connection()
        recent_logs = pd.read_sql_query(
            "SELECT timestamp, officer_badge, incident_type, notes FROM field_incidents ORDER BY id DESC LIMIT 3",
            conn,
        )
        conn.close()

        if not recent_logs.empty:
            st.markdown("##### 🕒 Recent Field Reports")
            st.dataframe(recent_logs)

# ---------------------------------------------------------
# 12. Polling Loop for Live Automated Simulation
# ---------------------------------------------------------
if data_mode == "Automated Ambient Simulation" and auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()