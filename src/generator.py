import pandas as pd
import numpy as np

def generate_synthetic_data(output_path="data/traffic_data.csv"):
    np.random.seed(42)
    
    junctions = [
        {"id": "J_CBD_01", "name": "Central Business Hub", "lat": 17.4435, "lon": 78.3772, "capacity": 300},
        {"id": "J_TECH_02", "name": "Tech Corridor Junction", "lat": 17.4504, "lon": 78.3808, "capacity": 250},
        {"id": "J_IND_03", "name": "Industrial Ring Road", "lat": 17.4200, "lon": 78.3489, "capacity": 200},
        {"id": "J_RES_04", "name": "Suburban Arterial Gate", "lat": 17.4720, "lon": 78.3550, "capacity": 180},
        {"id": "J_EXP_05", "name": "Expressway Interchange", "lat": 17.4110, "lon": 78.4000, "capacity": 350}
    ]
    
    date_range = pd.date_range(start="2026-10-15 00:00:00", end="2026-10-21 23:45:00", freq="15min")
    records = []
    weathers = ["Clear", "Rain", "Fog"]
    weather_probs = [0.80, 0.15, 0.05]
    
    for ts in date_range:
        hour = ts.hour
        is_weekend = ts.weekday() >= 5
        
        if 8 <= hour <= 10:
            time_factor = 0.85 if not is_weekend else 0.40
        elif 17 <= hour <= 20:
            time_factor = 0.95 if not is_weekend else 0.55
        elif 0 <= hour <= 5:
            time_factor = 0.10
        else:
            time_factor = 0.50
            
        weather = np.random.choice(weathers, p=weather_probs)
        
        for j in junctions:
            cap = j["capacity"]
            base_count = int(cap * time_factor)
            noise = np.random.randint(-15, 20)
            count = max(5, base_count + noise)
            
            if weather == "Rain":
                count = int(count * 1.15)
                
            accident_prob = 0.04 if (weather == "Rain" and (8 <= hour <= 10 or 17 <= hour <= 20)) else 0.008
            has_accident = 1 if np.random.rand() < accident_prob else 0
            
            if has_accident:
                count = int(count * 1.35)
                
            count = min(count, int(cap * 1.4))
            
            records.append({
                "timestamp": ts,
                "junction_id": j["id"],
                "junction_name": j["name"],
                "latitude": j["lat"],
                "longitude": j["lon"],
                "vehicle_count": count,
                "road_capacity": cap,
                "weather_condition": weather,
                "accident_reported": has_accident
            })
            
    df = pd.DataFrame(records)
    df.to_csv(output_path, index=False)
    print(f"Data saved to {output_path} ({len(df)} records).")

if __name__ == "__main__":
    generate_synthetic_data()