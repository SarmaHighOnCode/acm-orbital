
import json
from datetime import datetime, timezone, timedelta
import numpy as np
import sys
import os

import logging
logging.basicConfig(level=logging.INFO)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from engine.simulation import SimulationEngine
from find_blind_spot import lla_to_eci

def run_repro_blackout():
    engine = SimulationEngine()
    ts = datetime(2026, 3, 12, 8, 1, 0, tzinfo=timezone.utc)
    
    # Satellite at Lat -60, Lon -135 (Pacific Dark Spot)
    sat_pos = lla_to_eci(-60, -135, 400, ts)
    # Roughly circular velocity in ECI (assuming it's moving along Y-axis at X-axis point)
    # Actually let's just use a standard LEO velocity vector
    r_mag = np.linalg.norm(sat_pos)
    v_mag = np.sqrt(398600.4418 / r_mag)
    # Direction: perpendicular to sat_pos and Z-axis
    v_dir = np.cross(sat_pos, [0, 0, 1])
    v_dir = v_dir / np.linalg.norm(v_dir)
    sat_vel = v_dir * v_mag
    
    # Use engine's propagator for accurate TCA placement
    tca_s = 1200.0
    sat_state_tca = engine.propagator.propagate(np.concatenate([sat_pos, sat_vel]), tca_s)
    sat_pos_tca = sat_state_tca[:3]
    
    # Place debris at same spot at TCA, moving retrograde
    deb_vel_tca = -sat_state_tca[3:]
    # Propagate debris BACKWARDS to t=0
    deb_state_0 = engine.propagator.propagate(np.concatenate([sat_pos_tca, deb_vel_tca]), -tca_s)
    deb_pos = deb_state_0[:3]
    deb_vel = deb_state_0[3:]
    
    telemetry_data = {
      "timestamp": ts.isoformat(),
      "objects": [
        {
          "id": "SAT-DARK-01",
          "type": "SATELLITE",
          "r": {"x": sat_pos[0], "y": sat_pos[1], "z": sat_pos[2]},
          "v": {"x": sat_vel[0], "y": sat_vel[1], "z": sat_vel[2]}
        },
        {
          "id": "DEB-DARK-01",
          "type": "DEBRIS",
          "r": {"x": deb_pos[0], "y": deb_pos[1], "z": deb_pos[2]},
          "v": {"x": deb_vel[0], "y": deb_vel[1], "z": deb_vel[2]}
        }
      ]
    }
    
    # 1. Ingest Telemetry
    print("Ingesting telemetry...")
    ingest_result = engine.ingest_telemetry(telemetry_data["timestamp"], telemetry_data["objects"])
    
    detail_cdms = []
    for cdm in engine.active_cdms:
        detail_cdms.append({
            "sat_id": cdm.satellite_id,
            "deb_id": cdm.debris_id,
            "tca": cdm.tca.isoformat(),
            "miss_km": cdm.miss_distance_km,
            "risk": cdm.risk
        })
    
    sat = engine.satellites["SAT-DARK-01"]
    queue = list(sat.maneuver_queue)
    
    report = {
        "detail_cdms": detail_cdms,
        "queue_after_ingest": queue,
        "sat_status": sat.status
    }
    
    with open("repro_blackout_results.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Report saved to repro_blackout_results.json")

if __name__ == "__main__":
    run_repro_blackout()
