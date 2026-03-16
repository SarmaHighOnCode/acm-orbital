
import numpy as np
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.simulation import SimulationEngine
from engine.models import Satellite, Debris
from config import CONJUNCTION_THRESHOLD_KM

def reproduce():
    engine = SimulationEngine()
    timestamp = "2026-03-12T11:00:00.000Z"
    
    # 2000 km away / 15.168 km/s ≈ 131.8 seconds
    objects = [
        {
          "id": "SAT-Alpha-05",
          "type": "SATELLITE",
          "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
          "v": {"x": 0.0, "y": 7.668, "z": 0.0}
        },
        {
          "id": "DEB-HEAVY-01",
          "type": "DEBRIS",
          "r": {"x": 6778.02, "y": 2000.0, "z": 0.0},
          "v": {"x": 0.0, "y": -7.5, "z": 0.0}
        }
    ]
    
    # Ingest
    engine.ingest_telemetry(timestamp, objects)
    
    # Step simulation
    engine.step(1)
    
    print(f"Number of CDMs: {len(engine.active_cdms)}")
    for cdm in engine.active_cdms:
        print(f"CDM: Sat={cdm.satellite_id}, Deb={cdm.debris_id}, Miss={cdm.miss_distance_km*1000:.2f}m, Risk={cdm.risk}, TCA={cdm.tca}")
        
    sat = engine.satellites["SAT-Alpha-05"]
    print(f"Maneuver queue length: {len(sat.maneuver_queue)}")
    for burn in sat.maneuver_queue:
        dv = burn['deltaV_vector']
        dv_mag = np.linalg.norm([dv['x'], dv['y'], dv['z']]) * 1000.0
        print(f"  Burn: {burn.get('burn_id', '???')}, Time: {burn['burnTime']}, DV: {dv_mag:.2f} m/s")

if __name__ == "__main__":
    reproduce()
