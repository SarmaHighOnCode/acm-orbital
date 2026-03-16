
import json
from datetime import datetime, timezone, timedelta
import sys
import os
import numpy as np

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from engine.simulation import SimulationEngine

def run_repro():
    engine = SimulationEngine()
    
    telemetry_data = {
      "timestamp": "2026-03-12T08:01:00.000Z",
      "objects": [
        {
          "id": "SAT-Alpha-01",
          "type": "SATELLITE",
          "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
          "v": {"x": 0.0, "y": 7.668, "z": 0.0}
        },
        {
          "id": "DEB-KILL-01",
          "type": "DEBRIS",
          "r": {"x": 6778.5, "y": 850.0, "z": 0.0},
          "v": {"x": 0.0, "y": -7.2, "z": 0.0}
        }
      ]
    }
    
    # 1. Ingest Telemetry
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
    sat_after_ingest = engine.satellites["SAT-Alpha-01"]
    queue_after_ingest = list(sat_after_ingest.maneuver_queue)
    
    # 2. First 10s step
    step_10s_result = engine.step(10)
    
    # 3. One hour step
    step_3600s_result = engine.step(3600)
    
    # 4. Final snapshot
    snapshot = engine.get_snapshot()
    sat = next(s for s in snapshot["satellites"] if s["id"] == "SAT-Alpha-01")
    
    report = {
        "telemetry_ingest": ingest_result,
        "detail_cdms": detail_cdms,
        "queue_after_ingest": queue_after_ingest,
        "step_10s": step_10s_result,
        "step_3600s": step_3600s_result,
        "final_snapshot": sat
    }
    
    with open("repro_results.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Report saved to repro_results.json")

if __name__ == "__main__":
    run_repro()
