
from datetime import datetime, timezone, timedelta
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from engine.ground_stations import GroundStationNetwork
from engine.simulation import SimulationEngine

def R_z(theta):
    return np.array([
        [np.cos(theta), -np.sin(theta), 0],
        [np.sin(theta), np.cos(theta), 0],
        [0, 0, 1]
    ])

def lla_to_eci(lat_deg, lon_deg, alt_km, timestamp):
    R_EARTH = 6378.137
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)
    r = R_EARTH + alt_km
    ecef = r * np.array([
        np.cos(lat) * np.cos(lon),
        np.cos(lat) * np.sin(lon),
        np.sin(lat)
    ])
    j2000_epoch = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    dt_seconds = (timestamp - j2000_epoch).total_seconds()
    gmst_deg = 280.46061837 + 360.98564736629 * (dt_seconds / 86400.0)
    theta = np.radians(gmst_deg % 360.0)
    return R_z(theta) @ ecef

def find_blind_spot():
    engine = SimulationEngine()
    gs_network = engine.gs_network
    ts = datetime(2026, 3, 12, 8, 1, 0, tzinfo=timezone.utc)
    
    # Search grid
    for lat in range(-60, 60, 20):
        for lon in range(-180, 180, 45):
            pos_0 = lla_to_eci(lat, lon, 400, ts)
            # Velocity: circular, Eastwards
            r_mag = np.linalg.norm(pos_0)
            v_mag = np.sqrt(398600.4418 / r_mag)
            v_dir = np.cross(pos_0, [0, 0, 1])
            if np.linalg.norm(v_dir) < 1.0: # polar case
                v_dir = [0, 1, 0]
            v_dir = v_dir / np.linalg.norm(v_dir)
            vel_0 = v_dir * v_mag
            state_0 = np.concatenate([pos_0, vel_0])
            
            # Check for 30 minutes window with propagation
            is_dark = True
            for dt in range(0, 1800, 60):
                t = ts + timedelta(seconds=dt)
                # Proper propagation
                state_t = engine.propagator.propagate(state_0, dt)
                if gs_network.check_line_of_sight(state_t[:3], t):
                    is_dark = False
                    break
            if is_dark:
                print(f"Found dark spot: Lat {lat}, Lon {lon}")
                return lat, lon
    return None, None

if __name__ == "__main__":
    find_blind_spot()
