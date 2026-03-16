import json
from datetime import datetime, timedelta, timezone
import sys
import os
import numpy as np

# Add the current directory to sys.path to import local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from engine.simulation import SimulationEngine

def run_test():
    engine = SimulationEngine()
    
    # User-provided telemetry
    test_data = {
      "timestamp": "2026-03-12T09:00:00.000Z",
      "objects": [
        {
          "id": "SAT-Alpha-03",
          "type": "SATELLITE",
          "r": {"x": -2500.0, "y": -2800.0, "z": 5900.0},
          "v": {"x": 5.1, "y": -4.3, "z": -2.8}
        },
        {
          "id": "DEB-OCEAN-01",
          "type": "DEBRIS",
          "r": {"x": -2480.0, "y": -2750.0, "z": 5920.0},
          "v": {"x": 4.9, "y": -4.5, "z": -2.6}
        }
      ]
    }
    
    print("--- 1. Ingesting Telemetry ---")
    result = engine.ingest_telemetry(test_data["timestamp"], test_data["objects"])
    print(f"Processed: {result['processed_count']}")
    
    print("\n--- 2. Triggering Auto-Planning (Step 60s) ---")
    step_result = engine.step(60)
    print(f"New Timestamp: {step_result['new_timestamp']}")
    
    sat = engine.satellites["SAT-Alpha-03"]
    if sat.maneuver_queue:
        print(f"\n--- 3. Scheduled Maneuvers for {sat.id} ---")
        for i, burn in enumerate(sat.maneuver_queue):
            bt = burn["burnTime"]
            dv = burn["deltaV_vector"]
            print(f"Burn {i+1}: Time={bt}, DV={dv}")
            
            # Verify LOS at scheduled time
            bt_dt = datetime.fromisoformat(bt.replace("Z", "+00:00"))
            dt = (bt_dt - engine.sim_time).total_seconds()
            if dt > 0:
                burn_pos = engine.propagator.propagate(sat.state_vector, dt)[:3]
            else:
                burn_pos = sat.position
            has_los = engine.gs_network.check_line_of_sight(burn_pos, bt_dt)
            print(f"  LOS Verification: {has_los}")
            if not has_los:
                print(f"  CRITICAL FAILURE: Burn scheduled without LOS!")
    else:
        print("\n--- 3. No maneuvers scheduled! ---")
        # Check if CDM was detected
        print(f"Active CDMs: {len(engine.active_cdms)}")
        for cdm in engine.active_cdms:
            print(f"  CDM: {cdm.satellite_id} x {cdm.debris_id}, Risk: {cdm.risk}, Miss: {cdm.miss_distance_km:.4f} km")

    print("\n--- 4. Simulating until TCA (45 ticks of 60s) ---")
    total_collisions = 0
    for tick in range(45):
        step_result = engine.step(60)
        total_collisions += step_result['collisions_detected']
        if step_result['maneuvers_executed'] > 0:
            print(f"Tick {tick+1}: Maneuver executed at {engine.sim_time.isoformat()}")

    print(f"\n--- 5. Final Report ---")
    print(f"Total Collisions Detected: {total_collisions}")
    print(f"Satellite Status: {sat.status}")
    print(f"Fuel Remaining: {sat.fuel_kg:.2f} kg")

    if total_collisions == 0:
        print("\nSUCCESS: Evasion successful with zero collisions.")
    else:
        print("\nFAILURE: Collisions detected.")

if __name__ == "__main__":
    run_test()
