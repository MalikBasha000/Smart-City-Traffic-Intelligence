import streamlit as st
import streamlit.components.v1 as components
import hashlib
import json
import base64
import os
import sys
import time
import math
import random
import requests
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sklearn.ensemble import RandomForestRegressor

try:
    import plotly.express as px
    import plotly.graph_objects as go
except ImportError:
    pass

try:
    import pydeck as pdk
except ImportError:
    pass

try:
    from geopy.geocoders import Nominatim
except ImportError:
    pass

st.set_page_config(
    page_title="Smart City Traffic Intelligence",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------
# GLOBAL ENVIRONMENT & API CONFIGURATION
# ---------------------------------------------------------------------
try:
    GOOGLE_MAPS_API_KEY = st.secrets.get("GOOGLE_MAPS_API_KEY", os.environ.get("GOOGLE_MAPS_API_KEY", ""))
except Exception:
    GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

# =====================================================================
# MASTER DIVISIONS & DATABASE LAYER
# =====================================================================

division_options_master = [
    "Secunderabad Traffic Division", "Alwal Patrol Sector", "Bolarum Field Unit",
    "Trimulgherry Cross Roads PS", "Bowenpally Junction Sector", "Karkhana Traffic Outpost",
    "Marredpally Corridor Sector", "Begumpet Flyover Division", "Malkajgiri Traffic Division",
    "Sainikpuri - Yapral Sector", "ECIL Cross Roads Unit", "Kompally NH-44 Corridor",
    "Panjagutta Junction Sector", "Ameerpet Metro Hub Division", "Somajiguda - Raj Bhavan Road",
    "Khairatabad Circle Unit", "Saifabad Secretariat Sector", "Tank Bund - Hussain Sagar Patrol",
    "Abids - Koti Commercial Division", "Hitec City Cyber Towers Division",
    "Madhapur Inorbit Corridor", "Gachibowli Junction Unit", "Kondapur - Botanical Garden Sector",
    "Raidurgam Metro Station Post", "Financial District / Nanakramguda", "Jubilee Hills Checkpost Division",
    "Banjara Hills Road No 1 & 12", "Kukatpally Y Junction Division", "Miyapur Cross Roads Post",
    "Nizampet - Bachupally Feeder", "JNTU - Forum Mall Corridor", "Charminar Heritage Sector",
    "Mehdipatnam Mor Division", "Bahadurpura - Zoo Park Corridor", "Falaknuma Traffic Post",
    "Chandrayangutta Flyover Unit", "Goshamahal Division", "Uppal Ring Road Division",
    "LB Nagar Cross Roads Hub", "Dilsukhnagar Metro Corridor", "Tarnaka - Osmania University Sector",
    "Malakpet Flyover Unit", "Amberpet - Ramanthapur Post", "Shamshabad Airport Expressway",
    "RGIA Airport Police Station", "Aramghar - Rajendranagar Junction", "Outer Ring Road (ORR) Patrol"
]

def get_db_connection():
    return sqlite3.connect("traffic_users.db", check_same_thread=False)

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def update_incident_status(incident_id: int, new_status: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE field_incidents SET status = ? WHERE id = ?", (new_status, incident_id))
    conn.commit()
    conn.close()

def delete_incident(incident_id: int):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM field_incidents WHERE id = ?", (incident_id,))
    conn.commit()
    conn.close()

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            badge_id TEXT PRIMARY KEY,
            password TEXT,
            name TEXT,
            dept TEXT,
            email TEXT,
            role TEXT,
            plain_password TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS field_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            officer_badge TEXT,
            location_name TEXT,
            lat REAL,
            lon REAL,
            incident_type TEXT,
            notes TEXT,
            image_path TEXT,
            status TEXT DEFAULT 'PENDING'
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS officer_sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            badge_id TEXT,
            officer_name TEXT,
            role TEXT,
            login_time TEXT,
            logout_time TEXT,
            last_ping TEXT,
            is_online INTEGER DEFAULT 1
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS emergency_dispatches (
            dispatch_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            emergency_type TEXT,
            origin_junction TEXT,
            destination_junction TEXT,
            corridor_path TEXT,
            total_junctions INTEGER,
            status TEXT DEFAULT 'ACTIVE',
            dispatched_by TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS junction_signals (
            junction_key TEXT PRIMARY KEY,
            junction_name TEXT,
            cycle_length_sec INTEGER DEFAULT 120,
            green_split_sec INTEGER DEFAULT 60,
            yellow_sec INTEGER DEFAULT 5,
            red_sec INTEGER DEFAULT 55,
            pedestrian_sec INTEGER DEFAULT 15,
            control_mode TEXT DEFAULT 'AUTO',
            last_updated TEXT
        )
    ''')

    # Column integrity check
    c.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in c.fetchall()]
    if "plain_password" not in cols:
        try:
            c.execute("ALTER TABLE users ADD COLUMN plain_password TEXT")
        except Exception:
            pass

    # Ensure baseline users exist
    c.execute("SELECT COUNT(*) FROM users")
    count_val = c.fetchone()[0]
    if count_val == 0:
        default_users = [
            ("TGH-1", hash_password("tony@1"), "Tony Stark", "Secunderabad Traffic Division", "tony@hydpolice.gov.in", "FIELD_OFFICER", "tony@1"),
            ("officer_admin", hash_password("admin@123"), "Commander Admin", "Secunderabad Traffic Division", "admin@hydpolice.gov.in", "ADMIN", "admin@123")
        ]
        c.executemany("""
            INSERT OR IGNORE INTO users (badge_id, password, name, dept, email, role, plain_password)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, default_users)
        conn.commit()

    conn.commit()
    conn.close()

def get_or_create_signal_state(junction_key: str, junction_name: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT cycle_length_sec, green_split_sec, yellow_sec, red_sec, pedestrian_sec, control_mode, last_updated FROM junction_signals WHERE junction_key = ?", (junction_key,))
    row = c.fetchone()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not row:
        c.execute('''
            INSERT INTO junction_signals (junction_key, junction_name, cycle_length_sec, green_split_sec, yellow_sec, red_sec, pedestrian_sec, control_mode, last_updated)
            VALUES (?, ?, 120, 60, 5, 55, 15, 'AUTO', ?)
        ''', (junction_key, junction_name, now_str))
        conn.commit()
        conn.close()
        return {"cycle": 120, "green": 60, "yellow": 5, "red": 55, "ped": 15, "mode": "AUTO", "updated": now_str}
    conn.close()
    return {"cycle": row[0], "green": row[1], "yellow": row[2], "red": row[3], "ped": row[4], "mode": row[5], "updated": row[6]}

def update_signal_timing(junction_key: str, cycle: int, green: int, yellow: int, ped: int, mode: str):
    red = max(5, cycle - green - yellow)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE junction_signals
        SET cycle_length_sec = ?, green_split_sec = ?, yellow_sec = ?, red_sec = ?, pedestrian_sec = ?, control_mode = ?, last_updated = ?
        WHERE junction_key = ?
    ''', (cycle, green, yellow, red, ped, mode, now_str, junction_key))
    conn.commit()
    conn.close()

def log_officer_login(badge_id: str, name: str, role: str):
    conn = get_db_connection()
    c = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        INSERT INTO officer_sessions (badge_id, officer_name, role, login_time, last_ping, is_online)
        VALUES (?, ?, ?, ?, ?, 1)
    """, (badge_id, name, role, now_str, now_str))
    session_id = c.lastrowid
    conn.commit()
    conn.close()
    return session_id

def log_officer_logout(session_id: int):
    if not session_id:
        return
    conn = get_db_connection()
    c = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        UPDATE officer_sessions
        SET logout_time = ?, is_online = 0
        WHERE session_id = ?
    """, (now_str, session_id))
    conn.commit()
    conn.close()

def authenticate_user(badge_id: str, password: str, expected_role: str = None):
    init_db()
    conn = get_db_connection()
    c = conn.cursor()
    
    # Defensive auto-check against empty cloud volumes
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        default_users = [
            ("TGH-1", hash_password("tony@1"), "Tony Stark", "Secunderabad Traffic Division", "tony@hydpolice.gov.in", "FIELD_OFFICER", "tony@1"),
            ("officer_admin", hash_password("admin@123"), "Commander Admin", "Secunderabad Traffic Division", "admin@hydpolice.gov.in", "ADMIN", "admin@123")
        ]
        c.executemany("INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?, ?, ?, ?)", default_users)
        conn.commit()

    if expected_role:
        c.execute(
            "SELECT name, dept, role FROM users WHERE badge_id = ? AND password = ? AND role = ?",
            (badge_id.strip(), hash_password(password.strip()), expected_role)
        )
    else:
        c.execute(
            "SELECT name, dept, role FROM users WHERE badge_id = ? AND password = ?",
            (badge_id.strip(), hash_password(password.strip()))
        )
    user = c.fetchone()
    conn.close()
    if user:
        return True, {"name": user[0], "dept": user[1], "role": user[2] if len(user) > 2 else "FIELD_OFFICER"}
    return False, None

def enroll_field_officer(badge_id: str, password: str, name: str, dept: str, email: str, creator_badge: str):
    init_db()
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("PRAGMA table_info(users)")
        cols = [row[1] for row in c.fetchall()]
        if "plain_password" in cols:
            c.execute(
                "INSERT INTO users (badge_id, password, name, dept, email, role, plain_password) VALUES (?, ?, ?, ?, ?, 'FIELD_OFFICER', ?)",
                (badge_id.strip(), hash_password(password.strip()), name.strip(), dept.strip(), email.strip(), password.strip())
            )
        else:
            c.execute(
                "INSERT INTO users (badge_id, password, name, dept, email, role) VALUES (?, ?, ?, ?, ?, 'FIELD_OFFICER')",
                (badge_id.strip(), hash_password(password.strip()), name.strip(), dept.strip(), email.strip())
            )
        conn.commit()
        conn.close()
        return True, f"Field Officer [{badge_id}] successfully enrolled!"
    except sqlite3.IntegrityError:
        conn.close()
        return False, f"Badge ID [{badge_id}] is already registered."

def update_field_officer(badge_id: str, name: str, dept: str, email: str, new_password: str):
    init_db()
    conn = get_db_connection()
    c = conn.cursor()
    if new_password and new_password.strip() and new_password != "••••••••":
        c.execute("""
            UPDATE users
            SET name = ?, dept = ?, email = ?, password = ?, plain_password = ?
            WHERE badge_id = ?
        """, (name.strip(), dept.strip(), email.strip(), hash_password(new_password.strip()), new_password.strip(), badge_id.strip()))
    else:
        c.execute("""
            UPDATE users
            SET name = ?, dept = ?, email = ?
            WHERE badge_id = ?
        """, (name.strip(), dept.strip(), email.strip(), badge_id.strip()))
    conn.commit()
    conn.close()

def delete_field_officer(badge_id: str):
    init_db()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE badge_id = ?", (badge_id.strip(),))
    c.execute("DELETE FROM officer_sessions WHERE badge_id = ?", (badge_id.strip(),))
    conn.commit()
    conn.close()

def log_field_incident(officer_badge, loc_name, lat, lon, inc_type, notes, img_path=None):
    init_db()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO field_incidents (timestamp, officer_badge, location_name, lat, lon, incident_type, notes, image_path, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), officer_badge, loc_name, lat, lon, inc_type, notes, img_path))
    conn.commit()
    conn.close()

# Module level database bootstrap
init_db()

# =====================================================================
# GEOLOCATION & ROAD NETWORK GRAPH TOPOLOGY
# =====================================================================

HYD_LANDMARK_COORDS = {
    "alwal": (17.5206, 78.5008, "Alwal, Secunderabad"),
    "bolarum": (17.5284, 78.5205, "Bolarum, Secunderabad"),
    "bowenpally": (17.4764, 78.4870, "Bowenpally Junction, Secunderabad"),
    "paradise": (17.4411, 78.4870, "Paradise Circle, Secunderabad"),
    "trimulgherry": (17.4842, 78.5085, "Trimulgherry Cross Roads, Secunderabad"),
    "karkhana": (17.4619, 78.5003, "Karkhana, Secunderabad"),
    "tarnaka": (17.4284, 78.5303, "Tarnaka Junction, Secunderabad"),
    "secunderabad": (17.4338, 78.5016, "Secunderabad Railway Station"),
    "marredpally": (17.4485, 78.5108, "Marredpally, Secunderabad"),
    "sainikpuri": (17.4912, 78.5444, "Sainikpuri, Secunderabad"),
    "ecil": (17.4716, 78.5583, "ECIL Cross Roads, Hyderabad"),
    "malkajgiri": (17.4523, 78.5323, "Malkajgiri, Hyderabad"),
    "kompally": (17.5404, 78.4891, "Kompally Junction, Hyderabad"),
    "shamshabad": (17.2403, 78.4294, "Shamshabad, Hyderabad"),
    "rgia": (17.2403, 78.4294, "Rajiv Gandhi Intl Airport, Shamshabad"),
    "charminar": (17.3616, 78.4747, "Charminar, Old City, Hyderabad"),
    "hitec city": (17.4474, 78.3762, "Hitec City Cyber Towers, Hyderabad"),
    "gachibowli": (17.4401, 78.3489, "Gachibowli Junction, Hyderabad"),
    "madhapur": (17.4483, 78.3915, "Madhapur, Hyderabad"),
    "jubilee hills": (17.4319, 78.4073, "Jubilee Hills Checkpost, Hyderabad"),
    "banjara hills": (17.4156, 78.4357, "Banjara Hills Road No 1, Hyderabad"),
    "begumpet": (17.4448, 78.4665, "Begumpet Flyover, Hyderabad"),
    "ameerpet": (17.4375, 78.4482, "Ameerpet Junction, Hyderabad"),
    "kukatpally": (17.4932, 78.3999, "Kukatpally Y Junction, Hyderabad"),
    "mehdipatnam": (17.3916, 78.4398, "Mehdipatnam Mor, Hyderabad"),
    "uppal": (17.4022, 78.5604, "Uppal Ring Road, Hyderabad"),
    "dilsukhnagar": (17.3688, 78.5247, "Dilsukhnagar, Hyderabad"),
}

HYD_JUNCTION_NETWORK = {
    "paradise": ["begumpet", "marredpally", "karkhana", "bowenpally"],
    "begumpet": ["paradise", "ameerpet", "panjagutta"],
    "ameerpet": ["begumpet", "panjagutta", "kukatpally"],
    "panjagutta": ["begumpet", "ameerpet", "banjara hills", "jubilee hills"],
    "banjara hills": ["panjagutta", "jubilee hills", "mehdipatnam"],
    "jubilee hills": ["panjagutta", "banjara hills", "madhapur", "hitec city"],
    "madhapur": ["jubilee hills", "hitec city", "gachibowli"],
    "hitec city": ["jubilee hills", "madhapur", "gachibowli", "kukatpally"],
    "gachibowli": ["madhapur", "hitec city", "shamshabad"],
    "bowenpally": ["paradise", "trimulgherry", "alwal"],
    "trimulgherry": ["bowenpally", "karkhana", "alwal", "sainikpuri"],
    "karkhana": ["paradise", "trimulgherry", "marredpally"],
    "marredpally": ["paradise", "karkhana", "secunderabad", "tarnaka"],
    "secunderabad": ["marredpally", "paradise"],
    "alwal": ["bowenpally", "trimulgherry", "bolarum", "kompally"],
    "bolarum": ["alwal", "kompally"],
    "kompally": ["alwal", "bolarum", "bowenpally"],
    "sainikpuri": ["trimulgherry", "ecil"],
    "ecil": ["sainikpuri", "malkajgiri", "tarnaka"],
    "malkajgiri": ["ecil", "secunderabad"],
    "tarnaka": ["marredpally", "ecil", "uppal"],
    "uppal": ["tarnaka", "dilsukhnagar"],
    "dilsukhnagar": ["uppal", "charminar"],
    "charminar": ["dilsukhnagar", "mehdipatnam", "shamshabad"],
    "mehdipatnam": ["banjara hills", "charminar", "shamshabad"],
    "kukatpally": ["ameerpet", "hitec city", "bowenpally"],
    "shamshabad": ["mehdipatnam", "charminar", "gachibowli"]
}

def calculate_dijkstra_route(start_key: str, end_key: str):
    import heapq
    if start_key not in HYD_JUNCTION_NETWORK or end_key not in HYD_JUNCTION_NETWORK:
        return [start_key, end_key]

    distances = {node: float('inf') for node in HYD_JUNCTION_NETWORK}
    previous_nodes = {node: None for node in HYD_JUNCTION_NETWORK}
    distances[start_key] = 0
    pq = [(0, start_key)]

    while pq:
        current_distance, current_node = heapq.heappop(pq)
        if current_node == end_key:
            break
        if current_distance > distances[current_node]:
            continue

        for neighbor in HYD_JUNCTION_NETWORK.get(current_node, []):
            weight = 1.0
            dist = current_distance + weight
            if dist < distances[neighbor]:
                distances[neighbor] = dist
                previous_nodes[neighbor] = current_node
                heapq.heappush(pq, (dist, neighbor))

    path = []
    curr = end_key
    while curr is not None:
        path.append(curr)
        curr = previous_nodes[curr]
    path.reverse()
    return path if path and path[0] == start_key else [start_key, end_key]

def set_officer_assigned_location(sector_name: str):
    if not sector_name:
        return
    clean = sector_name.strip().lower()
    for k, (lat, lon, label) in HYD_LANDMARK_COORDS.items():
        if k in clean:
            st.session_state.target_lat = lat
            st.session_state.target_lon = lon
            st.session_state.target_area_name = label
            st.session_state.search_area_box = label
            return

    st.session_state.target_area_name = sector_name
    st.session_state.search_area_box = sector_name

# =====================================================================
# COMMAND OPERATIONS SUBTABS & DIALOG
# =====================================================================

def render_incident_review_subtab():
    st.subheader("📋 Incident Review & Verification Portal")
    st.caption("Review field reports filed by patrol units. Verify, hold pending, or purge invalid alerts.")

    conn = get_db_connection()
    inc_df = pd.read_sql_query("SELECT * FROM field_incidents ORDER BY id DESC LIMIT 50", conn)
    conn.close()

    if inc_df.empty:
        st.info("No field incident reports logged yet.")
        return

    f_col1, f_col2 = st.columns(2)
    with f_col1:
        status_filter = st.selectbox("Filter by Action Status:", ["ALL", "PENDING", "VERIFIED", "DISMISSED"], key="dlg_stat_filter")
    with f_col2:
        type_filter = st.selectbox("Filter by Incident Type:", ["ALL"] + sorted(list(inc_df["incident_type"].dropna().unique())), key="dlg_type_filter")

    filtered = inc_df.copy()
    if status_filter != "ALL":
        filtered = filtered[filtered["status"] == status_filter]
    if type_filter != "ALL":
        filtered = filtered[filtered["incident_type"] == type_filter]

    if filtered.empty:
        st.info("No incident records found matching current filter.")
        return

    for _, row in filtered.iterrows():
        inc_id = row["id"]
        status_color = "#f59e0b" if row.get("status") == "PENDING" else ("#10b981" if row.get("status") == "VERIFIED" else "#ef4444")
        with st.expander(f"⚠️ [ID #{inc_id}] {row['incident_type']} | {row['location_name']} ({row['timestamp']})"):
            c_det1, c_det2 = st.columns([1.5, 1])
            with c_det1:
                st.write(f"**Reporting Officer:** `{row['officer_badge']}`")
                st.write(f"**GPS Coordinates:** `{row['lat']:.4f}, {row['lon']:.4f}`")
                st.write(f"**Officer Notes:** {row['notes'] if row['notes'] else 'No additional remarks'}")
                st.markdown(f"**Current Status:** <span style='color: {status_color}; font-weight: bold;'>{row.get('status', 'PENDING')}</span>", unsafe_allow_html=True)

            with c_det2:
                img_p = row.get("image_path")
                if img_p and os.path.exists(img_p):
                    st.image(img_p, caption="Captured Scene Evidence", use_container_width=True)
                else:
                    st.caption("No scene photograph attached.")

            if st.session_state.get("officer_role") == "ADMIN":
                a_col1, a_col2, a_col3 = st.columns([1, 1, 1])
                with a_col1:
                    if st.button("✅ Verify Alert", key=f"btn_verify_{inc_id}", use_container_width=True):
                        update_incident_status(inc_id, "VERIFIED")
                        st.toast(f"Incident #{inc_id} marked as VERIFIED")
                        st.rerun()
                with a_col2:
                    if st.button("❌ Dismiss Alert", key=f"btn_dismiss_{inc_id}", use_container_width=True):
                        update_incident_status(inc_id, "DISMISSED")
                        st.toast(f"Incident #{inc_id} marked as DISMISSED")
                        st.rerun()
                with a_col3:
                    if st.button("🗑️ Purge Log", key=f"btn_purge_{inc_id}", use_container_width=True):
                        delete_incident(inc_id)
                        st.toast(f"Incident #{inc_id} deleted permanently")
                        st.rerun()
            else:
                st.caption("🔒 Status verification & log management are restricted to Sector Admin Officers.")

def render_officer_duty_tracker_subtab():
    st.subheader("⏱️ Real-Time Officer Shift & Online Audit Roster")
    st.caption("Track individual officer shifts, filter by calendar date, and audit cumulative online duty duration.")

    conn = get_db_connection()
    sessions_df = pd.read_sql_query("""
        SELECT session_id, badge_id, officer_name, role, login_time, logout_time, is_online
        FROM officer_sessions
        ORDER BY session_id DESC
    """, conn)
    conn.close()

    if sessions_df.empty:
        st.info("No recorded officer shift sessions yet.")
        return

    now = datetime.now()
    records = []
    for _, row in sessions_df.iterrows():
        try:
            l_time = datetime.strptime(row["login_time"], "%Y-%m-%d %H:%M:%S")
            shift_date = l_time.date()
        except Exception:
            l_time = now
            shift_date = now.date()

        is_on = row["is_online"] == 1

        if is_on:
            duration = now - l_time
            dur_secs = max(0, int(duration.total_seconds()))
            hours, remainder = divmod(dur_secs, 3600)
            mins, _ = divmod(remainder, 60)
            status_text = f"🟢 ONLINE ({hours}h {mins}m on duty)"
            end_time = "ACTIVE DUTY"
        else:
            if row["logout_time"]:
                try:
                    out_time = datetime.strptime(row["logout_time"], "%Y-%m-%d %H:%M:%S")
                    duration = out_time - l_time
                    dur_secs = max(0, int(duration.total_seconds()))
                    hours, remainder = divmod(dur_secs, 3600)
                    mins, _ = divmod(remainder, 60)
                    status_text = f"⚪ Logged Out ({hours}h {mins}m)"
                    end_time = row["logout_time"]
                except Exception:
                    dur_secs = 0
                    status_text = "⚪ Logged Out"
                    end_time = row["logout_time"]
            else:
                dur_secs = 0
                status_text = "⚪ Logged Out"
                end_time = "Disconnected"

        records.append({
            "session_id": row["session_id"],
            "Badge ID": row["badge_id"],
            "Officer Name": row["officer_name"],
            "Role": row["role"],
            "Login Time": row["login_time"],
            "Logout Time": end_time,
            "Duty Status / Online Since": status_text,
            "duration_secs": dur_secs,
            "shift_date": shift_date,
            "is_online": is_on
        })

    all_data_df = pd.DataFrame(records)

    f_col1, f_col2, f_col3 = st.columns([1.6, 1.4, 1.2])
    unique_officers = all_data_df.groupby(["Badge ID", "Officer Name"]).size().reset_index()
    officer_options = ["ALL OFFICERS"] + [f"{r['Badge ID']} - {r['Officer Name']}" for _, r in unique_officers.iterrows()]

    min_date = all_data_df["shift_date"].min()
    max_date = all_data_df["shift_date"].max()

    with f_col1:
        selected_officer = st.selectbox("👤 Filter by Specific Officer:", officer_options, key="tracker_officer_filter")
    with f_col2:
        date_selection = st.date_input(
            "📅 Filter by Calendar Date / Range:",
            value=(min_date, max_date) if min_date != max_date else min_date,
            key="tracker_date_range"
        )
    with f_col3:
        status_filter = st.selectbox("📶 Filter by Status:", ["ALL", "🟢 ONLINE ONLY", "⚪ LOGGED OUT ONLY"], key="tracker_status_filter")

    filtered_df = all_data_df.copy()

    if selected_officer != "ALL OFFICERS":
        target_badge = selected_officer.split(" - ")[0].strip()
        filtered_df = filtered_df[filtered_df["Badge ID"] == target_badge]

    if isinstance(date_selection, (tuple, list)) and len(date_selection) == 2:
        start_d, end_d = date_selection
        filtered_df = filtered_df[(filtered_df["shift_date"] >= start_d) & (filtered_df["shift_date"] <= end_d)]
    elif isinstance(date_selection, (datetime, pd.Timestamp)):
        filtered_df = filtered_df[filtered_df["shift_date"] == date_selection.date()]
    elif date_selection:
        filtered_df = filtered_df[filtered_df["shift_date"] == date_selection]

    if status_filter == "🟢 ONLINE ONLY":
        filtered_df = filtered_df[filtered_df["is_online"] == True]
    elif status_filter == "⚪ LOGGED OUT ONLY":
        filtered_df = filtered_df[filtered_df["is_online"] == False]

    if filtered_df.empty:
        st.warning("No shift sessions found matching current date and officer criteria.")
        return

    total_seconds = filtered_df["duration_secs"].sum()
    tot_hours, remainder = divmod(total_seconds, 3600)
    tot_mins, _ = divmod(remainder, 60)

    active_shifts = filtered_df[filtered_df["is_online"] == True]
    curr_online_text = "🟢 Currently Active" if not active_shifts.empty else "⚪ Offline"

    m_col1, m_col2, m_col3 = st.columns(3)
    m_col1.metric("Selected Period Time on Duty", f"{tot_hours}h {tot_mins}m")
    m_col2.metric("Current Duty State", curr_online_text)
    m_col3.metric("Total Shift Sessions", len(filtered_df))

    st.markdown("##### 📆 Day-Wise Duty Breakdown")
    day_records = []
    for day_val, group in filtered_df.groupby("shift_date"):
        day_secs = group["duration_secs"].sum()
        d_hours, d_rem = divmod(day_secs, 3600)
        d_mins, _ = divmod(d_rem, 60)
        day_records.append({
            "Date": str(day_val),
            "Day of Week": day_val.strftime("%A"),
            "Total Online Duration": f"{d_hours}h {d_mins}m",
            "Shifts Logged": len(group),
            "Currently Online": "🟢 YES" if (group["is_online"] == True).any() else "⚪ No"
        })
    day_df = pd.DataFrame(day_records).sort_values(by="Date", ascending=False)
    st.dataframe(day_df, use_container_width=True)

    st.markdown("##### 📋 Detailed Log Sessions")
    display_cols = ["Badge ID", "Officer Name", "Role", "Login Time", "Logout Time", "Duty Status / Online Since"]
    st.dataframe(filtered_df[display_cols], use_container_width=True)

def render_green_wave_corridor_subtab():
    st.subheader("⚡ Automated 'Green Wave' Emergency Corridor Dispatch")
    st.caption("Pre-empt traffic signals along arterial routes to lock continuous green phases for ambulances and fire rescue.")

    col_em1, col_em2, col_em3 = st.columns([1.5, 2, 2])
    with col_em1:
        em_type = st.selectbox(
            "Emergency Vehicle Type:",
            ["🚑 Ambulance (Life Support)", "🚒 Fire & Rescue Unit", "🚓 High-Speed Police Escort", "🚨 Disaster Response Convoy"],
            key="gw_em_type"
        )
    with col_em2:
        available_nodes = sorted(list(HYD_JUNCTION_NETWORK.keys()))
        start_node = st.selectbox(
            "Origin Junction (Start):",
            available_nodes,
            index=available_nodes.index("paradise") if "paradise" in available_nodes else 0,
            key="gw_start_node",
            format_func=lambda x: HYD_LANDMARK_COORDS.get(x, (0, 0, x.title()))[2]
        )
    with col_em3:
        end_node = st.selectbox(
            "Target Destination (End):",
            available_nodes,
            index=available_nodes.index("begumpet") if "begumpet" in available_nodes else 1,
            key="gw_end_node",
            format_func=lambda x: HYD_LANDMARK_COORDS.get(x, (0, 0, x.title()))[2]
        )

    corridor_path = calculate_dijkstra_route(start_node, end_node)
    path_labels = [HYD_LANDMARK_COORDS.get(n, (0, 0, n.title()))[2] for n in corridor_path]

    st.markdown(f"**Calculated Emergency Corridor ({len(corridor_path)} Intersections):**")
    st.info(" ➔ ".join(path_labels))

    btn_gw1, btn_gw2 = st.columns([2, 1])
    with btn_gw1:
        if st.button("🟢 Activate Green Wave Pre-emption Corridor", use_container_width=True, key="btn_act_gw"):
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("""
                INSERT INTO emergency_dispatches (timestamp, emergency_type, origin_junction, destination_junction, corridor_path, total_junctions, status, dispatched_by)
                VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
            """, (now_str, em_type, start_node, end_node, " -> ".join(corridor_path), len(corridor_path), st.session_state.get("username", "HQ_DISPATCH")))
            conn.commit()
            conn.close()
            st.session_state.active_green_wave = corridor_path
            st.success(f"GREEN WAVE ACTIVE: All {len(corridor_path)} intersections locked to GREEN. Cross-streets holding ALL-RED.")
            st.rerun()

    with btn_gw2:
        if st.button("🛑 Deactivate / Restore Normal Cycles", use_container_width=True, key="btn_deact_gw"):
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("UPDATE emergency_dispatches SET status = 'COMPLETED' WHERE status = 'ACTIVE'")
            conn.commit()
            conn.close()
            if "active_green_wave" in st.session_state:
                del st.session_state["active_green_wave"]
            st.toast("Corridor pre-emption released. Standard automated signal cycles resumed.")
            st.rerun()

    st.markdown("---")
    st.markdown("##### 🚨 Emergency Corridor Dispatch Log")
    conn = get_db_connection()
    dispatches_df = pd.read_sql_query("SELECT dispatch_id, timestamp, emergency_type, origin_junction, destination_junction, corridor_path, total_junctions, status, dispatched_by FROM emergency_dispatches ORDER BY dispatch_id DESC LIMIT 8", conn)
    conn.close()
    if not dispatches_df.empty:
        st.dataframe(dispatches_df, use_container_width=True)
    else:
        st.caption("No emergency corridors dispatched yet.")

def render_officer_enrollment_subtab():
    st.subheader("➕ Enroll New Field Patrol Officer")
    st.caption("Admin Officers create official credentials and assign divisions. Give these credentials to the officer.")

    with st.form("admin_enroll_officer_form", clear_on_submit=True):
        col_e1, col_e2 = st.columns(2)
        with col_e1:
            en_name = st.text_input("Officer Full Name", placeholder="e.g. Constable Suresh Reddy")
            en_badge = st.text_input("Designated Badge ID", placeholder="e.g. TPD-204")
            en_dept = st.selectbox("Patrol Sector / Division", division_options_master)
        with col_e2:
            en_email = st.text_input("Official Govt Email", placeholder="officer@hydpolice.gov.in")
            en_pwd = st.text_input("Set Initial Password", type="default", placeholder="Assign password")

        st.write("")
        submit_enroll = st.form_submit_button("🛡️ Issue Credentials & Enroll Officer", use_container_width=True)

        if submit_enroll:
            if en_badge and en_pwd and en_name:
                ok, msg = enroll_field_officer(
                    en_badge, en_pwd, en_name, en_dept, en_email, st.session_state.get("username", "officer_admin")
                )
                if ok:
                    st.success(msg)
                    st.info(f"📋 Credential Sheet: Badge ID: {en_badge} | Password: {en_pwd} | Sector: {en_dept}")
                    st.rerun()
                else:
                    st.error(msg)
            else:
                st.warning("Please complete all required fields (Name, Badge ID, Password).")

    st.markdown("---")
    st.markdown("##### 👥 Enrolled Patrol Officer Registry (Edit & Manage)")
    st.caption("Review stored passwords, update officer names/divisions, or delete accounts.")

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in c.fetchall()]
    if "plain_password" in cols:
        officers_list = pd.read_sql_query("SELECT badge_id, name, dept, email, plain_password FROM users WHERE role = 'FIELD_OFFICER' ORDER BY badge_id ASC", conn)
    else:
        officers_list = pd.read_sql_query("SELECT badge_id, name, dept, email FROM users WHERE role = 'FIELD_OFFICER' ORDER BY badge_id ASC", conn)
        officers_list["plain_password"] = "••••••••"
    conn.close()

    if officers_list.empty:
        st.info("No field officers enrolled yet. Enroll an officer using the form above.")
    else:
        for idx, row in officers_list.iterrows():
            b_id = str(row["badge_id"])
            curr_name = row["name"] or ""
            curr_dept = row["dept"] or ""
            curr_email = row["email"] or ""
            curr_pwd = str(row.get("plain_password", "")) if row.get("plain_password") else ""

            with st.expander(f"👮 [{b_id}] - {curr_name} ({curr_dept})", expanded=False):
                with st.form(f"edit_officer_form_{b_id}_{idx}", clear_on_submit=False):
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        edit_name = st.text_input("Officer Name", value=curr_name, key=f"ed_name_{b_id}")
                        current_d_opts = list(division_options_master)
                        if curr_dept and curr_dept not in current_d_opts:
                            current_d_opts.insert(0, curr_dept)
                        d_idx = current_d_opts.index(curr_dept) if curr_dept in current_d_opts else 0
                        edit_dept = st.selectbox("Assigned Sector / Division", current_d_opts, index=d_idx, key=f"ed_dept_{b_id}")

                    with ec2:
                        edit_email = st.text_input("Official Govt Email", value=curr_email, key=f"ed_email_{b_id}")
                        edit_pwd = st.text_input("Officer Password", value=curr_pwd, key=f"ed_pwd_{b_id}")

                    save_edits = st.form_submit_button("💾 Save Changes", use_container_width=True)

                    if save_edits:
                        update_field_officer(b_id, edit_name, edit_dept, edit_email, edit_pwd)
                        st.success(f"Officer [{b_id}] updated successfully.")
                        st.rerun()

                del_col1, del_col2 = st.columns([4, 1.3])
                with del_col2:
                    if st.button("🗑️ Delete Officer", key=f"del_btn_{b_id}", use_container_width=True):
                        delete_field_officer(b_id)
                        st.toast(f"Officer [{b_id}] deleted.")
                        st.rerun()

@st.dialog("🛡️ Command Operations, Incident & Officer Center", width="large")
def show_incident_triage_dialog():
    is_admin = st.session_state.get("officer_role") == "ADMIN"
    if is_admin:
        tab_inc, tab_roster, tab_gw, tab_enroll = st.tabs([
            "📋 Incident Review & Verification",
            "⏱️ Officer Duty Tracker (Online Since)",
            "⚡ Green Wave Corridor Dispatch",
            "➕ Enroll Field Officer"
        ])
        with tab_inc:
            render_incident_review_subtab()
        with tab_roster:
            render_officer_duty_tracker_subtab()
        with tab_gw:
            render_green_wave_corridor_subtab()
        with tab_enroll:
            render_officer_enrollment_subtab()
    else:
        render_incident_review_subtab()

    st.markdown("---")
    if st.button("Close Portal", use_container_width=True):
        st.rerun()

# =====================================================================
# SESSION STATE & AUTHENTICATION SCREEN
# =====================================================================

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "officer_name" not in st.session_state:
    st.session_state.officer_name = ""
if "officer_dept" not in st.session_state:
    st.session_state.officer_dept = ""
if "officer_role" not in st.session_state:
    st.session_state.officer_role = ""
if "db_session_id" not in st.session_state:
    st.session_state.db_session_id = None
if "target_area_name" not in st.session_state:
    st.session_state.target_area_name = "Paradise Circle, Secunderabad"
if "target_lat" not in st.session_state:
    st.session_state.target_lat = 17.4411
if "target_lon" not in st.session_state:
    st.session_state.target_lon = 78.4870

if not st.session_state.authenticated:
    st.markdown("""<style>
      [data-testid="stAppViewContainer"] {
          background: radial-gradient(circle at 50% 30%, #1e293b 0%, #0f172a 100%) !important;
      }
      header[data-testid="stHeader"] {
          background-color: transparent !important;
      }
      .block-container {
          max-width: 980px !important;
          padding-top: 3rem !important;
          padding-bottom: 3rem !important;
      }
      .showcase-panel {
          background: linear-gradient(135deg, #091e3a 0%, #2b5876 50%, #4e4376 100%);
          height: 100%;
          min-height: 520px;
          border-radius: 22px;
          padding: 40px 30px;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          color: #ffffff;
          box-shadow: inset 0 0 40px rgba(0,0,0,0.3);
      }
      .showcase-pill {
          display: inline-block;
          background: rgba(255,255,255,0.18);
          backdrop-filter: blur(8px);
          padding: 6px 14px;
          border-radius: 30px;
          font-size: 0.8rem;
          font-weight: 600;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          color: #38bdf8;
          border: 1px solid rgba(255,255,255,0.2);
          width: fit-content;
      }
      .showcase-title {
          font-size: 2.1rem;
          font-weight: 700;
          line-height: 1.25;
          margin-top: 25px;
          color: #f8fafc;
      }
      .showcase-desc {
          color: #cbd5e1;
          font-size: 0.95rem;
          margin-top: 12px;
          line-height: 1.5;
      }
      .showcase-footer {
          display: flex;
          align-items: center;
          gap: 12px;
          font-size: 0.85rem;
          color: #94a3b8;
          border-top: 1px solid rgba(255,255,255,0.1);
          padding-top: 18px;
      }
      div[data-testid="stForm"] {
          border: none !important;
          padding: 10px 5px !important;
          background: transparent !important;
      }
      div[data-testid="stForm"] button, .stButton button {
          border-radius: 12px !important;
          height: 46px !important;
          font-weight: 600 !important;
          font-size: 1rem !important;
          transition: all 0.2s ease !important;
      }
      div[data-testid="stTextInput"] div[data-baseweb="input"],
      div[data-testid="stTextInput"] div[data-baseweb="base-input"] {
          background-color: #1e293b !important;
          border: 1px solid #334155 !important;
          border-radius: 10px !important;
      }
      div[data-testid="stTextInput"] input {
          background-color: #1e293b !important;
          color: #f8fafc !important;
          caret-color: #38bdf8 !important;
          font-size: 0.95rem !important;
          font-weight: 500 !important;
          border: none !important;
      }
      div[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within {
          border-color: #38bdf8 !important;
          box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.35) !important;
      }
      div[data-testid="stTextInput"] label,
      div[data-testid="stTextInput"] label p {
          color: #94a3b8 !important;
          font-weight: 600 !important;
          font-size: 0.85rem !important;
      }
    </style>""", unsafe_allow_html=True)

    with st.container():
        left_col, right_col = st.columns([1.1, 1.1], gap="large")

        with left_col:
            st.markdown("""
            <div style="padding: 15px 5px 0 5px;">
                <h1 style="color: #f8fafc; font-size: 2.2rem; font-weight: 800; margin-bottom: 4px;">Authorized Access</h1>
                <p style="color: #94a3b8; font-size: 0.92rem; margin-bottom: 18px;">Log into Command Network by Operational Clearance</p>
            </div>
            """, unsafe_allow_html=True)

            tab_field_login, tab_admin_login = st.tabs(["👮 Field Patrol Login", "🛡️ Command Admin Login"])

            with tab_field_login:
                st.caption("Field Officers & Patrol Units: Enter credentials assigned by Division Admin.")
                with st.form("field_login_form", clear_on_submit=False):
                    f_badge = st.text_input("Patrol Badge ID", placeholder="e.g. TGH-1", key="f_login_badge")
                    f_pwd = st.text_input("Officer Password / Passcode", type="password", placeholder="••••••••", key="f_login_pwd")
                    st.write("")
                    submit_field_login = st.form_submit_button("Enter Field Reporting Deck", use_container_width=True)

                    if submit_field_login:
                        if f_badge and f_pwd:
                            success, user_data = authenticate_user(f_badge, f_pwd, expected_role="FIELD_OFFICER")
                            if success:
                                st.session_state.authenticated = True
                                st.session_state.username = f_badge
                                st.session_state.officer_name = user_data["name"]
                                st.session_state.officer_dept = user_data["dept"]
                                st.session_state.officer_role = "FIELD_OFFICER"
                                st.session_state.db_session_id = log_officer_login(f_badge, user_data["name"], "FIELD_OFFICER")
                                set_officer_assigned_location(user_data["dept"])
                                st.success(f"Duty Session Started: Welcome {user_data['name']} (Assigned: {user_data['dept']})")
                                st.rerun()
                            else:
                                st.error("Invalid Field Officer Badge ID or Password.")
                        else:
                            st.warning("Please enter your Badge ID and Password.")

            with tab_admin_login:
                st.caption("HQ Command Personnel: Full authority to monitor, enroll officers, & verify incidents.")
                with st.form("admin_login_form", clear_on_submit=False):
                    a_badge = st.text_input("Admin Badge ID", placeholder="e.g. officer_admin", key="a_login_badge")
                    a_pwd = st.text_input("HQ Master Security Key", type="password", placeholder="••••••••", key="a_login_pwd")
                    st.write("")
                    submit_admin_login = st.form_submit_button("Access HQ Command Center", use_container_width=True)

                    if submit_admin_login:
                        if a_badge and a_pwd:
                            success, user_data = authenticate_user(a_badge, a_pwd, expected_role="ADMIN")
                            if success:
                                st.session_state.authenticated = True
                                st.session_state.username = a_badge
                                st.session_state.officer_name = user_data["name"]
                                st.session_state.officer_dept = user_data["dept"]
                                st.session_state.officer_role = "ADMIN"
                                st.session_state.db_session_id = log_officer_login(a_badge, user_data["name"], "ADMIN")
                                st.success("Command Authority Authenticated. Session Logged.")
                                st.rerun()
                            else:
                                st.error("Invalid Command Admin Credentials.")
                        else:
                            st.warning("Please enter Master Admin credentials.")

            st.markdown("""
            <div style="margin-top: 18px; padding: 10px 14px; background: rgba(30, 41, 59, 0.5); border-radius: 8px; border: 1px solid rgba(148, 163, 184, 0.15); font-size: 0.8rem; color: #94a3b8;">
                🔒 <b>Notice:</b> Public enrollment is disabled. New patrol officers must be registered directly by a Sector Admin Officer from the HQ Roster.
            </div>
            """, unsafe_allow_html=True)

        with right_col:
            st.markdown("""
            <div class="showcase-panel">
                <div>
                    <span class="showcase-pill">Smart Traffic Intelligence v3.2</span>
                    <div class="showcase-title">Urban Corridor<br/>Neural Network</div>
                    <div class="showcase-desc">
                        Real-time AI telemetry, predictive V/C saturation modeling, automated dispatch operations, and multi-tier officer duty audit tracking.
                    </div>
                </div>
                <div class="showcase-footer">
                    <span style="font-size: 1.2rem;">🛡️</span>
                    <span>Restricted Govt & Municipal Operations Access</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

    st.stop()

# =====================================================================
# GEOCODING & TELEMETRY INDEX
# =====================================================================

@st.cache_data(ttl=300, show_spinner=False)
def geocode_location_google(query_text: str):
    if not query_text or not GOOGLE_MAPS_API_KEY:
        return None, None, None
    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {"address": query_text, "components": "country:IN", "key": GOOGLE_MAPS_API_KEY}
        res = requests.get(url, params=params, timeout=5).json()
        if res.get("status") == "OK" and res.get("results"):
            top = res["results"][0]
            return top["geometry"]["location"]["lat"], top["geometry"]["location"]["lng"], top["formatted_address"]
    except Exception:
        pass
    return None, None, None

def fetch_live_google_traffic(lat: float, lon: float):
    if not GOOGLE_MAPS_API_KEY:
        return None
    try:
        url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
            "X-Goog-FieldMask": "routes.duration,routes.staticDuration"
        }
        body = {
            "origin": {"location": {"latLng": {"latitude": float(lat), "longitude": float(lon)}}},
            "destination": {"location": {"latLng": {"latitude": float(lat) + 0.02, "longitude": float(lon) + 0.02}}},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE"
        }
        res = requests.post(url, headers=headers, json=body, timeout=5).json()
        if "routes" in res and len(res["routes"]) > 0:
            route = res["routes"][0]
            duration_s = float(route.get("duration", "0s").replace("s", ""))
            static_s = float(route.get("staticDuration", "0s").replace("s", ""))
            if static_s > 0:
                delay_s = max(0.0, duration_s - static_s)
                vc_ratio = round(min(1.8, max(0.2, duration_s / static_s)), 2)
                stress_index = round(min(100.0, max(0.0, ((duration_s - static_s) / static_s) * 100)), 1)
                return {
                    "duration_min": round(duration_s / 60, 1),
                    "delay_min": round(delay_s / 60, 1),
                    "vc_ratio": vc_ratio,
                    "stress_index": stress_index,
                    "status": "LIVE"
                }
    except Exception:
        pass
    return None

@st.cache_data(show_spinner=False)
def geocode_location(address_str: str):
    if not address_str:
        return None, None, None
    clean_query = address_str.strip().lower()
    for key, (lat, lon, label) in HYD_LANDMARK_COORDS.items():
        if key in clean_query:
            return lat, lon, label
    try:
        geolocator = Nominatim(user_agent="smart_traffic_intelligence_secunderabad_v2", timeout=10)
        query = address_str.strip()
        if "india" not in query.lower():
            query += ", Telangana, India"
        loc = geolocator.geocode(query, country_codes="in", exactly_one=True)
        if loc:
            return loc.latitude, loc.longitude, loc.address
    except Exception:
        pass
    return None, None, None

# =====================================================================
# FEATURE ENGINEERING & ML FORECASTING ENGINE
# =====================================================================

def process_features(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()

    if "timestamp" in out.columns:
        out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce").fillna(pd.Timestamp.now())
    else:
        out["timestamp"] = pd.Timestamp.now()

    out["hour"] = out["timestamp"].dt.hour
    out["day_of_week"] = out["timestamp"].dt.dayofweek
    out["dayofweek"] = out["timestamp"].dt.dayofweek
    out["is_weekend"] = out["dayofweek"].isin([5, 6]).astype(int)
    out["is_peak_hour"] = out["hour"].isin([8, 9, 10, 17, 18, 19, 20]).astype(int)

    if "vehicle_count" not in out.columns:
        out["vehicle_count"] = out.get("volume", out.get("count", 120))
    out["vehicle_count"] = pd.to_numeric(out["vehicle_count"], errors="coerce").fillna(120).astype(int)

    if "road_capacity" not in out.columns:
        out["road_capacity"] = out.get("capacity", 250)
    out["road_capacity"] = pd.to_numeric(out["road_capacity"], errors="coerce").replace(0, 250).fillna(250)

    if "avg_speed" not in out.columns:
        out["avg_speed"] = out.get("current_speed", out.get("speed_kmh", 32.0))
    out["avg_speed"] = pd.to_numeric(out["avg_speed"], errors="coerce").fillna(32.0)

    if "free_flow_speed" not in out.columns:
        out["free_flow_speed"] = 50.0

    out["vc_ratio"] = (out["vehicle_count"] / out["road_capacity"]).round(2)

    if "congestion_level" not in out.columns:
        out["congestion_level"] = np.clip((out["vc_ratio"] * 100.0), 5.0, 100.0).round(1)
    if "congestion_index" not in out.columns:
        out["congestion_index"] = out["congestion_level"]
    if "congestion_pct" not in out.columns:
        out["congestion_pct"] = out["congestion_level"]

    if "status" not in out.columns:
        out["status"] = np.select(
            [out["vc_ratio"] >= 0.85, out["vc_ratio"] >= 0.65, out["vc_ratio"] >= 0.45],
            ["CRITICAL", "HIGH", "MODERATE"],
            default="NORMAL"
        )
    if "congestion_status" not in out.columns:
        out["congestion_status"] = out["status"]
    if "risk_level" not in out.columns:
        out["risk_level"] = out["status"]
    if "severity" not in out.columns:
        out["severity"] = out["status"]

    if "recommended_action" not in out.columns:
        out["recommended_action"] = np.select(
            [out["vc_ratio"] >= 0.85, out["vc_ratio"] >= 0.65, out["vc_ratio"] >= 0.45],
            [
                "Deploy Field Unit + Green Wave Override (+45s)",
                "Extend Green Phase (+25s) & Alert Patrol",
                "Adaptive Signal Balancing"
            ],
            default="Standard Automated Cycle"
        )
    if "dispatch_action" not in out.columns:
        out["dispatch_action"] = out["recommended_action"]
    if "signal_adjustment" not in out.columns:
        out["signal_adjustment"] = np.where(
            out["vc_ratio"] >= 0.8, "+45 sec Green",
            np.where(out["vc_ratio"] >= 0.6, "+20 sec Green", "Optimal (0s)")
        )

    if "estimated_delay_min" not in out.columns:
        out["estimated_delay_min"] = np.maximum(0.0, (out["vc_ratio"] - 0.4) * 18.0).round(1)
    if "delay_minutes" not in out.columns:
        out["delay_minutes"] = out["estimated_delay_min"]
    if "wait_time_sec" not in out.columns:
        out["wait_time_sec"] = (out["vc_ratio"] * 95.0).round(0).astype(int)
    if "queue_length_m" not in out.columns:
        out["queue_length_m"] = (out["vehicle_count"] * 1.8).round(0).astype(int)

    if "rain_intensity" not in out.columns:
        out["rain_intensity"] = 0.0
    if "incident_flag" not in out.columns:
        out["incident_flag"] = 0
    if "bottleneck_score" not in out.columns:
        out["bottleneck_score"] = np.clip((out["vc_ratio"] * 70) + (50 - out["avg_speed"]).clip(0, 30), 0, 100).round(1)

    if "rpi_score" not in out.columns:
        out["rpi_score"] = np.clip((out["vc_ratio"] * 60.0) + (out.get("incident_flag", 0) * 30.0) + (out.get("rain_intensity", 0.0) * 0.2), 10, 100).round(1)
    if "priority_score" not in out.columns:
        out["priority_score"] = out["rpi_score"]
    if "risk_score" not in out.columns:
        out["risk_score"] = out["rpi_score"]

    return out

def train_forecasting_model():
    np.random.seed(42)
    X_sample = pd.DataFrame({
        "hour": np.random.randint(0, 24, 500),
        "day_of_week": np.random.randint(0, 7, 500),
        "rain_intensity": np.random.uniform(0, 50, 500),
        "incident_flag": np.random.randint(0, 2, 500)
    })
    y_sample = (
        X_sample["hour"] * 2.2 +
        (X_sample["day_of_week"] >= 5) * 10 +
        X_sample["rain_intensity"] * 0.5 +
        X_sample["incident_flag"] * 25 +
        np.random.normal(0, 5, size=500)
    )
    y_sample = np.clip(y_sample, 5, 250)

    clf = RandomForestRegressor(n_estimators=50, random_state=42)
    clf.fit(X_sample, y_sample)
    return clf

@st.cache_resource
def load_trained_model():
    return train_forecasting_model()

model = load_trained_model()

def predict_next_volume(row):
    try:
        ts = row.get("timestamp")
        if pd.notnull(ts):
            if not isinstance(ts, (pd.Timestamp, datetime)):
                ts = pd.to_datetime(ts, errors="coerce")
            dow = int(ts.day_of_week) if pd.notnull(ts) else int(row.get("dayofweek", row.get("day_of_week", 0)))
            hr = int(ts.hour) if pd.notnull(ts) else int(row.get("hour", 12))
        else:
            dow = int(row.get("dayofweek", row.get("day_of_week", 0)))
            hr = int(row.get("hour", 12))

        curr_vol = (
            row.get("vehicle_count") or
            row.get("volume") or
            row.get("count") or
            row.get("traffic_volume") or
            45
        )
        curr_vol = float(curr_vol) if pd.notnull(curr_vol) else 45.0
        rain = float(row.get("rain_intensity", 0.0) or 0.0)
        inc = int(row.get("incident_flag", 0) or 0)

        feature_df = pd.DataFrame([{
            "hour": hr,
            "day_of_week": dow,
            "rain_intensity": rain,
            "incident_flag": inc
        }])

        if model is not None and hasattr(model, "predict"):
            pred = float(model.predict(feature_df)[0])
            return int(max(0, pred))

        multiplier = 1.12 if (8 <= hr <= 10 or 17 <= hr <= 20) else 0.95
        return int(max(5, curr_vol * multiplier))
    except Exception:
        base_val = row.get("vehicle_count", row.get("volume", row.get("count", 40)))
        try:
            return int(float(base_val))
        except Exception:
            return 40

def assign_pillar_color(score):
    if score >= 60:
        return [230, 57, 70, 220]
    elif score >= 40:
        return [244, 162, 97, 220]
    return [42, 157, 143, 220]

def get_recommendations(corridor):
    recs = []
    if corridor["rpi_score"] >= 60:
        recs.append("🚨 Deploy rapid response traffic patrol unit.")
        recs.append("⏱️ Extend green light signal phase by +35 seconds.")
    elif corridor["rpi_score"] >= 40:
        recs.append("⚠️ Monitor corridor density and activate adaptive signal sync.")
    else:
        recs.append("🟢 Normal automated signal cycling active.")
    return recs

# =====================================================================
# PROJECT TITLE HEADER & COMMAND OPERATIONS TOP BAR
# =====================================================================
header_col1, header_col2 = st.columns([3, 1.2])

with header_col1:
    st.title("🚦 Smart City Traffic Intelligence")
    st.caption(f"Connected as **{st.session_state.get('officer_name', 'Authorized Officer')}** | Role: `{st.session_state.get('officer_role', 'FIELD_OFFICER')}` | Sector: *{st.session_state.get('officer_dept', 'General Command')}*")

with header_col2:
    st.write("")
    btn_portal_col, btn_logout_col = st.columns([1.6, 1])
    with btn_portal_col:
        portal_label = "🛡️ HQ Command & Roster" if st.session_state.get("officer_role") == "ADMIN" else "📋 Incident Center"
        if st.button(portal_label, use_container_width=True):
            show_incident_triage_dialog()
    with btn_logout_col:
        if st.button("🚪 Logout", use_container_width=True):
            log_officer_logout(st.session_state.get("db_session_id"))
            st.session_state.authenticated = False
            st.session_state.username = ""
            st.session_state.officer_role = ""
            st.rerun()

st.markdown("---")

st.markdown("### 🔍 Target Location & Sensor Synchronization")

if "search_area_box" not in st.session_state:
    st.session_state.search_area_box = st.session_state.target_area_name

def execute_location_update(query_text):
    if not query_text:
        return
    lat, lon, full_address = geocode_location_google(query_text)
    if lat is None:
        lat, lon, full_address = geocode_location(query_text)

    if lat is not None and lon is not None:
        st.session_state.target_lat = lat
        st.session_state.target_lon = lon
        st.session_state.target_area_name = full_address
        st.session_state.search_area_box = full_address
    else:
        st.warning(f"Could not locate '{query_text}'. Retaining current coordinates.")

def on_sync_gps_trigger():
    st.session_state.target_lat = 17.5206
    st.session_state.target_lon = 78.5008
    st.session_state.target_area_name = "Alwal, Secunderabad"
    st.session_state.search_area_box = "Alwal, Secunderabad"

SEARCH_SUGGESTIONS = [
    "Alwal, Secunderabad", "Bolarum, Secunderabad", "Paradise Circle, Secunderabad",
    "Trimulgherry Cross Roads, Secunderabad", "Bowenpally Junction, Secunderabad",
    "Karkhana, Secunderabad", "Tarnaka Junction, Secunderabad", "Secunderabad Railway Station",
    "Marredpally, Secunderabad", "Sainikpuri, Secunderabad", "ECIL Cross Roads, Hyderabad",
    "Malkajgiri, Hyderabad", "Kompally Junction, Hyderabad", "Begumpet Flyover, Hyderabad",
    "Panjagutta Cross Roads, Hyderabad", "Ameerpet Junction, Hyderabad", "Kukatpally Y Junction, Hyderabad",
    "Miyapur Cross Roads, Hyderabad", "Hitec City Cyber Towers, Hyderabad", "Gachibowli Junction, Hyderabad",
    "Madhapur, Hyderabad", "Jubilee Hills Checkpost, Hyderabad", "Banjara Hills Road No 1, Hyderabad",
    "Mehdipatnam Mor, Hyderabad", "Charminar, Old City, Hyderabad", "Abids, Hyderabad",
    "Uppal Ring Road, Hyderabad", "LB Nagar Cross Roads, Hyderabad", "Dilsukhnagar, Hyderabad",
    "Shamshabad, Hyderabad", "Rajiv Gandhi Intl Airport, Shamshabad"
]

options_list = list(SEARCH_SUGGESTIONS)
curr_val = st.session_state.get("target_area_name", "Alwal, Secunderabad")
if curr_val not in options_list:
    options_list.insert(0, curr_val)

s_col1, s_col2, s_col3 = st.columns([6, 2, 2])

with s_col1:
    def on_selection_change():
        selected = st.session_state.get("area_select_box")
        if selected:
            execute_location_update(selected)

    current_idx = options_list.index(curr_val) if curr_val in options_list else 0
    selected_target = st.selectbox(
        "Search & Auto-Suggest Sector / Type to Filter:",
        options=options_list,
        index=current_idx,
        key="area_select_box",
        on_change=on_selection_change
    )

with s_col2:
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
    if st.button("🎯 Locate Target", use_container_width=True):
        execute_location_update(st.session_state.get("area_select_box"))

with s_col3:
    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
    st.button("📍 Sync My GPS", on_click=on_sync_gps_trigger, use_container_width=True)

# =====================================================================
# SIDEBAR CONTROLS
# =====================================================================

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

auto_refresh = False
refresh_rate = 3
if data_mode == "Automated Ambient Simulation":
    auto_refresh = st.sidebar.checkbox("Enable Live Polling", value=True, key="check_auto_refresh")
    refresh_rate = st.sidebar.slider("Refresh Rate (seconds)", 2, 10, 3, key="slider_refresh_rate")

# =====================================================================
# RECORD PIPELINE & TELEMETRY KPI
# =====================================================================

now_ts = pd.Timestamp.now().replace(hour=sim_hour, minute=0, second=0)
active_vehicle_count = sim_count

if data_mode == "Live Targeted Area Telemetry":
    live_traffic = fetch_live_google_traffic(st.session_state.target_lat, st.session_state.target_lon)
    if live_traffic:
        active_vehicle_count = int(sim_capacity * live_traffic["vc_ratio"])
        st.sidebar.success(
            f"📡 **Google Routes Telemetry Active**\n\n"
            f"- **Live Travel Time:** {live_traffic['duration_min']} mins\n"
            f"- **Expected Delay:** +{live_traffic['delay_min']} mins\n"
            f"- **Live V/C Ratio:** {live_traffic['vc_ratio']}\n"
            f"- **Congestion Stress:** {live_traffic['stress_index']}%"
        )
    else:
        st.sidebar.warning("⚠️ Live telemetry unavailable. Using baseline simulation.")

primary_record = {
    "timestamp": now_ts,
    "junction_id": "TARGETED_ZONE",
    "junction_name": st.session_state.target_area_name,
    "latitude": float(st.session_state.target_lat),
    "longitude": float(st.session_state.target_lon),
    "vehicle_count": active_vehicle_count,
    "road_capacity": sim_capacity,
    "weather_condition": sim_weather,
    "accident_reported": 1 if sim_incident else 0,
    "incident_flag": 1 if sim_incident else 0,
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
    all_records.append({
        "timestamp": now_ts,
        "junction_id": label.replace(" ", "_"),
        "junction_name": f"{label} ({st.session_state.target_area_name[:12]})",
        "latitude": float(st.session_state.target_lat) + d_lat,
        "longitude": float(st.session_state.target_lon) + d_lon,
        "vehicle_count": v_cnt,
        "road_capacity": cap,
        "weather_condition": sim_weather,
        "accident_reported": 1 if np.random.rand() < 0.1 else 0,
        "incident_flag": 0,
    })

current_slice = process_features(pd.DataFrame(all_records))
current_slice["forecast_next_15m"] = current_slice.apply(predict_next_volume, axis=1)

target_row = current_slice[current_slice["junction_id"] == "TARGETED_ZONE"].iloc[0]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Targeted Area", st.session_state.target_area_name[:24], f"{target_row['vehicle_count']} veh")
avg_vc = target_row["vc_ratio"]
col2.metric("Area V/C Saturation", f"{avg_vc:.2f}", delta="Saturated" if avg_vc >= 0.85 else "Stable", delta_color="inverse" if avg_vc >= 0.85 else "normal")
accidents_count = int(current_slice["accident_reported"].sum())
col3.metric("Active Incidents", f"{accidents_count} Alert(s)", delta="Collision Reported" if target_row["accident_reported"] == 1 else "Normal Flow", delta_color="inverse" if target_row["accident_reported"] == 1 else "normal")
target_rpi = target_row["rpi_score"]
col4.metric("Area RPI Stress Index", f"{target_rpi:.1f} / 100", delta="High Load" if target_rpi > 60 else "Normal Load", delta_color="inverse" if target_rpi > 60 else "normal")

st.divider()

# =====================================================================
# MAP VISUALIZATION & ACTION PANELS
# =====================================================================

map_col, action_col = st.columns([3, 2])

arrow_data = pd.DataFrame([{
    "latitude": float(st.session_state.target_lat),
    "longitude": float(st.session_state.target_lon),
    "name": st.session_state.target_area_name,
    "elevation": 3200,
}])

with map_col:
    map_view_mode = st.radio("Select View:", ["Live Google Traffic", "Corridor Simulation", "3D Elevation Mesh"], horizontal=True)
    t_lat = float(st.session_state.target_lat)
    t_lon = float(st.session_state.target_lon)

    if map_view_mode in ["Live Google Traffic", "Corridor Simulation"]:
        is_sim = (map_view_mode == "Corridor Simulation")
        st.subheader("🚑 Live Corridor Transit Simulation" if is_sim else "🗺️ Live Google Traffic Network")
        st.caption(f"🎯 Center Locked: **{st.session_state.target_area_name}** ({t_lat:.4f}, {t_lon:.4f}) | Real-Time Traffic Layer Active")

        gw_gmap_coords = []
        road_polyline_points = []
        is_corridor_active = False
        route_dist_km = 16.0
        route_duration_min = 16

        try:
            conn_gw = get_db_connection()
            active_df = pd.read_sql_query("SELECT corridor_path, emergency_type FROM emergency_dispatches WHERE status = 'ACTIVE' ORDER BY dispatch_id DESC LIMIT 1", conn_gw)
            conn_gw.close()
            if not active_df.empty:
                is_corridor_active = True
                raw_path = active_df.iloc[0]["corridor_path"]
                nodes = [p.strip() for p in raw_path.split("->") if p.strip()]
                for n in nodes:
                    c_lat, c_lon, label = HYD_LANDMARK_COORDS.get(n, (0, 0, n))
                    if c_lat != 0:
                        gw_gmap_coords.append({"lat": float(c_lat), "lng": float(c_lon), "title": label, "key": n})

                if len(gw_gmap_coords) >= 2:
                    coord_str = ";".join([f"{pt['lng']},{pt['lat']}" for pt in gw_gmap_coords])
                    osrm_url = f"https://router.project-osrm.org/route/v1/driving/{coord_str}?overview=full&geometries=geojson"
                    r = requests.get(osrm_url, timeout=3).json()
                    if r.get("code") == "Ok" and r.get("routes"):
                        route_meta = r["routes"][0]
                        route_dist_km = round(route_meta.get("distance", 0) / 1000.0, 1)
                        route_duration_min = max(2, round((route_meta.get("duration", 0) / 60.0) * 0.6))
                        geo_coords = route_meta["geometry"]["coordinates"]
                        road_polyline_points = [{"lat": pt[1], "lng": pt[0]} for pt in geo_coords]
        except Exception:
            pass

        if not road_polyline_points and gw_gmap_coords:
            road_polyline_points = [{"lat": pt["lat"], "lng": pt["lng"]} for pt in gw_gmap_coords]

        # Gather city-wide junction signal profiles from junction_signals SQLite table
        junctions_payload = []
        try:
            conn_sig = get_db_connection()
            sig_rows = pd.read_sql_query("SELECT junction_key, junction_name, cycle_length_sec, green_split_sec, red_sec, pedestrian_sec, control_mode FROM junction_signals", conn_sig)
            conn_sig.close()
            sig_dict = {row["junction_key"]: row for _, row in sig_rows.iterrows()}
        except Exception:
            sig_dict = {}

        corridor_keys = {pt.get("key", "") for pt in gw_gmap_coords}
        for j_key, (j_lat, j_lon, j_title) in HYD_LANDMARK_COORDS.items():
            s_info = sig_dict.get(j_key, {})
            green_t = int(s_info.get("green_split_sec", 60))
            red_t = int(s_info.get("red_sec", 50))
            blue_t = int(s_info.get("pedestrian_sec", 15))
            cycle_t = int(s_info.get("cycle_length_sec", green_t + red_t + blue_t))
            mode_t = str(s_info.get("control_mode", "AUTO"))

            junctions_payload.append({
                "key": j_key,
                "title": j_title,
                "lat": float(j_lat),
                "lng": float(j_lon),
                "green": green_t,
                "red": red_t,
                "blue": blue_t,
                "cycle": max(30, cycle_t),
                "mode": mode_t,
                "in_corridor": j_key in corridor_keys
            })

        corridor_json = json.dumps(gw_gmap_coords)
        road_json = json.dumps(road_polyline_points)
        all_signals_json = json.dumps(junctions_payload)

        html_template = """<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <style>
      html, body {
        margin: 0;
        padding: 0;
        width: 100%;
        height: 100%;
        background: #0f172a;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        color: #f8fafc;
        overflow: hidden;
      }
      #hud-panel {
        display: __HUD_DISPLAY__;
        grid-template-columns: repeat(4, 1fr);
        background: rgba(15, 23, 42, 0.95);
        border: 1px solid rgba(56, 189, 248, 0.25);
        border-radius: 10px;
        padding: 10px 14px;
        margin-bottom: 10px;
        box-shadow: 0 4px 14px rgba(0,0,0,0.4);
      }
      .hud-card { display: flex; flex-direction: column; }
      .hud-label { font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600; letter-spacing: 0.04em; }
      .hud-value { font-size: 20px; font-weight: 800; color: #38bdf8; margin-top: 2px; }
      .hud-badge-green { color: #10b981; }
      #map-container {
        width: 100%;
        height: __MAP_HEIGHT__;
        border-radius: 12px;
        border: 1px solid rgba(255,255,255,0.08);
      }
    </style>
  </head>
  <body>
    <div id="hud-panel">
      <div class="hud-card">
        <span class="hud-label">Est. Arrival (ETA)</span>
        <span class="hud-value" id="val-eta">__TOTAL_MINS__ Mins</span>
      </div>
      <div class="hud-card">
        <span class="hud-label">Remaining Distance</span>
        <span class="hud-value" id="val-dist">__TOTAL_KM__ km</span>
      </div>
      <div class="hud-card">
        <span class="hud-label">Convoy Speed</span>
        <span class="hud-value" id="val-speed">48 km/h</span>
      </div>
      <div class="hud-card">
        <span class="hud-label">Signal Status</span>
        <span class="hud-value hud-badge-green" id="val-signals">🟢 GREEN WAVE</span>
      </div>
    </div>

    <div id="map-container"></div>

    <script>
      function initMap() {
        var centerPos = { lat: __CENTER_LAT__, lng: __CENTER_LNG__ };
        var map = new google.maps.Map(document.getElementById("map-container"), {
          zoom: 12,
          center: centerPos,
          mapTypeId: "roadmap",
          mapTypeControl: true,
          streetViewControl: false,
          fullscreenControl: true
        });

        var trafficLayer = new google.maps.TrafficLayer();
        trafficLayer.setMap(map);

        new google.maps.Marker({
          position: centerPos,
          map: map,
          title: "__TARGET_NAME__"
        });

        var roadPoints = __ROAD_JSON__;
        var junctionSignals = __ALL_SIGNALS_JSON__;
        var junctionMarkers = [];

        for (var i = 0; i < junctionSignals.length; i++) {
          var jData = junctionSignals[i];
          var marker = new google.maps.Marker({
            position: { lat: jData.lat, lng: jData.lng },
            map: map,
            title: jData.title + " | Traffic Light Cycle",
            icon: {
              path: google.maps.SymbolPath.CIRCLE,
              scale: 8,
              fillColor: "#10b981",
              fillOpacity: 1.0,
              strokeWeight: 2,
              strokeColor: "#FFFFFF"
            }
          });
          junctionMarkers.push({ marker: marker, data: jData, offset: Math.floor(Math.random() * 15) });
        }

        var globalTick = 0;
        setInterval(function() {
          globalTick++;
          for (var j = 0; j < junctionMarkers.length; j++) {
            var item = junctionMarkers[j];
            var d = item.data;

            if (d.in_corridor && __IS_SIM__) {
              item.marker.setIcon({
                path: google.maps.SymbolPath.CIRCLE,
                scale: 9,
                fillColor: "#10b981",
                fillOpacity: 1.0,
                strokeWeight: 3,
                strokeColor: "#FFFFFF"
              });
              item.marker.setTitle(d.title + " | 🟢 EMERGENCY GREEN OVERRIDE");
              continue;
            }

            var localTime = (globalTick + item.offset) % d.cycle;
            var currentColor = "#10b981";
            var currentPhase = "🟢 GO (Green)";

            if (localTime < d.green) {
              currentColor = "#10b981";
              currentPhase = "🟢 GREEN (" + (d.green - localTime) + "s left)";
            } else if (localTime < (d.green + d.red)) {
              currentColor = "#ef4444";
              currentPhase = "🔴 RED (" + ((d.green + d.red) - localTime) + "s left)";
            } else {
              currentColor = "#3b82f6";
              currentPhase = "🔵 BLUE (" + (d.cycle - localTime) + "s left)";
            }

            item.marker.setIcon({
              path: google.maps.SymbolPath.CIRCLE,
              scale: 7,
              fillColor: currentColor,
              fillOpacity: 1.0,
              strokeWeight: 2,
              strokeColor: "#FFFFFF"
            });
            item.marker.setTitle(d.title + " | " + currentPhase);
          }
        }, 1000);

        if (roadPoints && roadPoints.length >= 2) {
          var activeForwardPolyline = new google.maps.Polyline({
            path: roadPoints,
            geodesic: true,
            strokeColor: "#FF1493",
            strokeOpacity: 0.95,
            strokeWeight: 7,
            map: map
          });

          var bounds = new google.maps.LatLngBounds();
          for (var r = 0; r < roadPoints.length; r++) {
            bounds.extend(new google.maps.LatLng(roadPoints[r].lat, roadPoints[r].lng));
          }
          map.fitBounds(bounds);

          var isSimActive = __IS_SIM__;
          if (isSimActive) {
            var vehicle = new google.maps.Marker({
              position: roadPoints[0],
              map: map,
              title: "Convoy Tracking ID: EM-DISPATCH-101",
              label: {
                text: "🚑 [ID: EM-101]",
                color: "#FFFFFF",
                fontSize: "12px",
                fontWeight: "bold"
              },
              zIndex: 9999
            });

            var totalSteps = roadPoints.length;
            var totalKm = __TOTAL_KM__;
            var totalMins = __TOTAL_MINS__;
            var step = 0;

            var etaEl = document.getElementById("val-eta");
            var distEl = document.getElementById("val-dist");
            var speedEl = document.getElementById("val-speed");

            setInterval(function() {
              step = (step + 1) % totalSteps;
              var currPos = roadPoints[step];
              vehicle.setPosition(currPos);

              activeForwardPolyline.setPath(roadPoints.slice(step));

              var progressRatio = step / totalSteps;
              var remainingFraction = Math.max(0.0, 1.0 - progressRatio);
              var remKm = (totalKm * remainingFraction).toFixed(1);
              var remMins = Math.max(1, Math.round(totalMins * remainingFraction));

              if (distEl) distEl.innerText = remKm + " km";
              if (etaEl) etaEl.innerText = remMins + " Mins";
              if (speedEl) {
                var dynamicSpeed = 46 + Math.round(Math.sin(step) * 4);
                speedEl.innerText = dynamicSpeed + " km/h";
              }

              for (var k = 0; k < junctionMarkers.length; k++) {
                if (junctionMarkers[k].data.in_corridor && k < (progressRatio * junctionMarkers.length)) {
                  junctionMarkers[k].data.in_corridor = false;
                }
              }
            }, 250);
          }
        }
      }
    </script>
    <script src="https://maps.googleapis.com/maps/api/js?key=__API_KEY__&callback=initMap" async defer></script>
  </body>
</html>"""

        google_map_html = (
            html_template
            .replace("__CENTER_LAT__", str(t_lat))
            .replace("__CENTER_LNG__", str(t_lon))
            .replace("__TARGET_NAME__", st.session_state.target_area_name.replace('"', '\"'))
            .replace("__ROAD_JSON__", road_json)
            .replace("__CORRIDOR_JSON__", corridor_json)
            .replace("__ALL_SIGNALS_JSON__", all_signals_json)
            .replace("__API_KEY__", GOOGLE_MAPS_API_KEY)
            .replace("__IS_SIM__", "true" if is_sim else "false")
            .replace("__TOTAL_KM__", str(route_dist_km))
            .replace("__TOTAL_MINS__", str(route_duration_min))
            .replace("__HUD_DISPLAY__", "grid" if is_sim else "none")
            .replace("__MAP_HEIGHT__", "460px" if is_sim else "520px")
        )
        components.html(google_map_html, height=560)
    else:
        st.subheader("🌐 Real-Time 3D Network Map")
        st.caption(f"🎯 Pointer Arrow Locked: **{st.session_state.target_area_name}** ({t_lat:.4f}, {t_lon:.4f})")

        current_slice["pillar_color"] = current_slice["rpi_score"].apply(assign_pillar_color)

        view_center = pdk.ViewState(latitude=t_lat, longitude=t_lon, zoom=13.6, pitch=48, bearing=15)
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

        layers_to_render = [column_layer, arrow_pointer_layer, target_halo_layer]

        active_paths = []
        try:
            conn_gw = get_db_connection()
            active_df = pd.read_sql_query("SELECT corridor_path FROM emergency_dispatches WHERE status = 'ACTIVE' ORDER BY dispatch_id DESC LIMIT 1", conn_gw)
            conn_gw.close()
            if not active_df.empty:
                raw_path = active_df.iloc[0]["corridor_path"]
                active_paths = [p.strip() for p in raw_path.split("->") if p.strip()]
        except Exception:
            active_paths = st.session_state.get("active_green_wave", [])

        if active_paths:
            gw_coords = []
            gw_points = []
            for node in active_paths:
                c_lat, c_lon, label = HYD_LANDMARK_COORDS.get(node, (0, 0, node))
                if c_lat != 0:
                    gw_coords.append([c_lon, c_lat])
                    gw_points.append({"lon": c_lon, "lat": c_lat, "label": label})

            if len(gw_coords) >= 2:
                gw_line_df = pd.DataFrame([{"path": gw_coords}])
                gw_layer = pdk.Layer(
                    "PathLayer",
                    data=gw_line_df,
                    get_path="path",
                    get_color=[16, 185, 129, 255],
                    width_min_pixels=6,
                    pickable=False
                )
                gw_point_layer = pdk.Layer(
                    "ScatterplotLayer",
                    data=pd.DataFrame(gw_points),
                    get_position=["lon", "lat"],
                    get_radius=220,
                    get_fill_color=[16, 185, 129, 230],
                    get_line_color=[255, 255, 255, 255],
                    line_width_min_pixels=2,
                    pickable=True
                )
                layers_to_render.extend([gw_layer, gw_point_layer])

        deck_map = pdk.Deck(
            layers=layers_to_render,
            initial_view_state=view_center,
            map_style=pdk.map_styles.CARTO_DARK,
            tooltip={"html": "<b>{junction_name}</b><br/>Flow: {vehicle_count}/{road_capacity} veh<br/>RPI Score: {rpi_score}"},
        )
        st.pydeck_chart(deck_map)

with action_col:
    tab_directives, tab_signals, tab_field_cam = st.tabs(["📋 Directives", "🚦 Signal Matrix", "📷 Field Camera"])

    with tab_directives:
        status_tag = "🔴 CRITICAL" if target_row["rpi_score"] >= 60 else ("🟡 ELEVATED" if target_row["rpi_score"] >= 40 else "🟢 OPTIMAL")
        st.markdown(f"""
        <div style="background: rgba(15, 23, 42, 0.7); border-left: 4px solid #38bdf8; padding: 14px 16px; border-radius: 12px; margin-bottom: 14px; border: 1px solid rgba(56, 189, 248, 0.2);">
            <b>🎯 TARGETED SECTOR:</b> {st.session_state.target_area_name}<br>
            <span style="font-size: 13px; color: #94a3b8;">Status: <b>{status_tag}</b> | Flow: <b>{target_row['vehicle_count']}/{target_row['road_capacity']} veh</b> | RPI: <b>{target_row['rpi_score']}</b> | 15m Forecast: <b>{target_row['forecast_next_15m']} veh</b></span>
        </div>
        """, unsafe_allow_html=True)

        prioritized_corridors = current_slice.sort_values(by="rpi_score", ascending=False)
        for _, corridor in prioritized_corridors.iterrows():
            is_focused = corridor["junction_id"] == "TARGETED_ZONE"
            c_status = "🔴 CRITICAL" if corridor["rpi_score"] >= 60 else ("🟡 ELEVATED" if corridor["rpi_score"] >= 40 else "🟢 OPTIMAL")
            expander_title = f"{c_status} | {corridor['junction_name']} (RPI: {corridor['rpi_score']}) {'📍 [TARGETED]' if is_focused else ''}"

            with st.expander(expander_title, expanded=is_focused):
                c_flow, c_pred = st.columns(2)
                c_flow.metric("Current Flow", f"{corridor['vehicle_count']} / {corridor['road_capacity']} veh")
                c_pred.metric("15-Min Forecast", f"{corridor['forecast_next_15m']} veh", delta=int(corridor["forecast_next_15m"] - corridor["vehicle_count"]), delta_color="inverse")
                st.write(f"**Road State:** V/C: {corridor['vc_ratio']} | Weather: {corridor['weather_condition']}")
                st.write(f"**Incident Status:** {'🚨 Collision Active' if corridor['accident_reported'] == 1 else 'Normal'}")
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

    with tab_signals:
        st.subheader("🚦 Traffic Signal Light Controls")
        st.caption("Easily adjust how long each light stays Green, Red, or Blue (Emergency).")

        all_j_keys = sorted(list(HYD_JUNCTION_NETWORK.keys()))
        selected_j_key = st.selectbox(
            "📍 Choose an Intersection / Junction:",
            all_j_keys,
            index=all_j_keys.index("paradise") if "paradise" in all_j_keys else 0,
            key="matrix_j_select",
            format_func=lambda x: HYD_LANDMARK_COORDS.get(x, (0, 0, x.title()))[2]
        )
        j_label = HYD_LANDMARK_COORDS.get(selected_j_key, (0, 0, selected_j_key.title()))[2]
        sig_data = get_or_create_signal_state(selected_j_key, j_label)

        st.markdown(f"""
        <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(148, 163, 184, 0.25); border-radius: 10px; padding: 12px 16px; margin-bottom: 15px;">
            <div style="font-size: 16px; font-weight: 700; color: #f8fafc;">Intersection: {j_label}</div>
            <div style="font-size: 13px; color: #94a3b8; margin-top: 3px;">
                Status: <span style="color: #10b981; font-weight: bold;">🟢 Operational & Synced</span> | Last Updated: {sig_data.get('updated', 'Recently')}
            </div>
        </div>
        """, unsafe_allow_html=True)

        col_t1, col_t2 = st.columns(2)
        
        with col_t1:
            t_green = st.slider("🟢 Green Light (GO Time in seconds):", min_value=10, max_value=180, value=int(sig_data.get("green", 60)), step=5, key=f"sld_g_{selected_j_key}")
            t_red = st.slider("🔴 Red Light (STOP Time in seconds):", min_value=10, max_value=180, value=int(sig_data.get("red", 50)), step=5, key=f"sld_r_{selected_j_key}")
        
        with col_t2:
            t_blue = st.slider("🔵 Blue Light (Emergency / Priority in seconds):", min_value=0, max_value=60, value=int(sig_data.get("ped", 15)), step=5, key=f"sld_b_{selected_j_key}")
            t_cycle = t_green + t_red + t_blue
            
            st.markdown(f"""
            <div style="background: #1e293b; border-radius: 8px; padding: 14px; margin-top: 24px; border-left: 4px solid #38bdf8;">
                <div style="font-size: 12px; color: #94a3b8; text-transform: uppercase; font-weight: 600;">⏱️ TOTAL CYCLE TIME</div>
                <div style="font-size: 26px; font-weight: 800; color: #38bdf8;">{t_cycle} Seconds</div>
                <div style="font-size: 12px; color: #cbd5e1; margin-top: 2px;">(🟢 {t_green}s + 🔴 {t_red}s + 🔵 {t_blue}s)</div>
            </div>
            """, unsafe_allow_html=True)

        st.write("")
        if st.button("💾 Save & Apply Lights", key=f"btn_save_sig_{selected_j_key}", use_container_width=True):
            update_signal_timing(selected_j_key, t_cycle, t_green, 5, t_blue, "ACTIVE")
            st.success(f"Saved for {j_label}: 🟢 {t_green}s | 🔴 {t_red}s | 🔵 {t_blue}s (Total Cycle: {t_cycle}s)")
            time.sleep(0.4)
            st.rerun()

        st.markdown("##### 📋 Current Signal Timings Across City")
        conn_sig = get_db_connection()
        simple_table = pd.read_sql_query("""
            SELECT 
                junction_name AS 'Intersection',
                green_split_sec AS '🟢 Green (Go)',
                red_sec AS '🔴 Red (Stop)',
                pedestrian_sec AS '🔵 Blue (Priority)',
                cycle_length_sec AS '⏱️ Total Cycle',
                last_updated AS 'Last Updated'
            FROM junction_signals 
            ORDER BY last_updated DESC LIMIT 5
        """, conn_sig)
        conn_sig.close()

        if not simple_table.empty:
            st.dataframe(simple_table, use_container_width=True)

    with tab_field_cam:
        st.subheader("📷 Mobile Incident Reporting")
        inc_type = st.selectbox(
            "Incident Classification",
            ["Vehicle Breakdown / Stalled", "Multi-Vehicle Collision", "Waterlogging / Debris", "Illegal Parking Obstruction"],
            key="select_inc_cat"
        )
        inc_notes = st.text_input(
            "Officer Quick Observation Notes",
            placeholder="e.g. Lane 2 blocked, tow truck requested",
            key="text_inc_notes"
        )

        if "cam_counter" not in st.session_state:
            st.session_state.cam_counter = 0

        evidence_mode = st.radio(
            "Select Evidence Input Method:",
            ["📸 Live Camera (Front / Back Switch)", "📁 Browse from Local Files"],
            horizontal=True,
            key=f"evidence_mode_{st.session_state.cam_counter}"
        )

        captured_file = None

        if evidence_mode == "📸 Live Camera (Front / Back Switch)":
            c_lens1, c_lens2 = st.columns([1.5, 2.5])
            with c_lens1:
                lens_choice = st.selectbox(
                    "Switch Lens:",
                    ["📷 Rear / Traffic View (Back)", "🤳 Selfie View (Front)"],
                    key=f"lens_selector_{st.session_state.cam_counter}"
                )
            with c_lens2:
                st.caption("Tip: On phones, rear lens is selected automatically for road inspection.")

            captured_file = st.camera_input(
                "Capture Evidence Photo",
                key=f"single_live_cam_{st.session_state.cam_counter}"
            )
        else:
            st.caption("Select an existing image from your computer storage or mobile photo library.")
            captured_file = st.file_uploader(
                "Choose Evidence File (JPG, PNG, WebP):",
                type=["jpg", "jpeg", "png", "webp"],
                key=f"single_file_uploader_{st.session_state.cam_counter}"
            )

        if captured_file is not None:
            st.image(captured_file, caption="Selected Incident Evidence", use_container_width=True)
            if st.button("💾 Submit Incident Log to Central HQ", key="btn_save_incident"):
                os.makedirs("incident_media", exist_ok=True)
                img_filename = f"incident_{int(time.time())}.jpg"
                save_path = os.path.join("incident_media", img_filename)
                with open(save_path, "wb") as f_img:
                    f_img.write(captured_file.getbuffer())

                log_field_incident(
                    st.session_state.username,
                    st.session_state.target_area_name,
                    st.session_state.target_lat,
                    st.session_state.target_lon,
                    inc_type,
                    inc_notes,
                    save_path
                )
                st.session_state.cam_counter += 1
                st.success("Incident and photo evidence logged into Command Center database with GPS tag.")
                time.sleep(1.0)
                st.rerun()

        conn = get_db_connection()
        recent_logs = pd.read_sql_query("SELECT timestamp, officer_badge, incident_type, notes, status FROM field_incidents ORDER BY id DESC LIMIT 3", conn)
        conn.close()

        if not recent_logs.empty:
            st.markdown("##### 🕒 Recent Field Reports")
            st.dataframe(recent_logs)

# =====================================================================
# SIMULATION POLLING
# =====================================================================

if data_mode == "Automated Ambient Simulation" and auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()