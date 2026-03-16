
import json
import time
import numpy as np
from datetime import datetime, timezone, timedelta
import sys
import os

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from engine.simulation import SimulationEngine

def generate_fragment_cloud(base_id, count, center_r, center_v, spread_r=0.5, spread_v=0.1):
    """Generate a cloud of fragments spreading outward."""
    fragments = []
    for i in range(count):
        # Random outward velocity and position spread
        r_offset = np.random.normal(0, spread_r, 3)
        v_offset = np.random.normal(0, spread_v, 3)
        
        fragments.append({
            "id": f"{base_id}-{i:03d}",
            "type": "DEBRIS",
            "r": {"x": center_r[0] + r_offset[0], "y": center_r[1] + r_offset[1], "z": center_r[2] + r_offset[2]},
            "v": {"x": center_v[0] + v_offset[0], "y": center_v[1] + v_offset[1], "z": center_v[2] + v_offset[2]}
        })
    return fragments

def run_repro():
    engine = SimulationEngine()
    
    # 1. Setup satellites (50 sats as per stress test)
    telemetry_objects = []
    current_time = datetime(2026, 3, 12, 20, 0, 0, tzinfo=timezone.utc)
    
    for i in range(50):
        # Place satellites in a ring
        angle = (2 * np.pi * i) / 50
        r_mag = 6778.0 # 400km altitude
        x = r_mag * np.cos(angle)
        y = r_mag * np.sin(angle)
        
        # Approximate orbital velocity for circular orbit
        v_mag = 7.67 # km/s
        vx = -v_mag * np.sin(angle)
        vy = v_mag * np.cos(angle)
        
        telemetry_objects.append({
            "id": f"SAT-{i:03d}",
            "type": "SATELLITE",
            "r": {"x": x, "y": y, "z": 0.0},
            "v": {"x": vx, "y": vy, "z": 0.0}
        })
    
    # 2. Add fragmentation cloud (500 fragments)
    # Center it near SAT-000 for maximum threat
    center_r = [6778.0, 0.0, 0.0]
    center_v = [0.0, 7.67, 0.0] # Same as SAT-000 roughly
    
    fragments = generate_fragment_cloud("DEB-FRAG", 500, center_r, center_v)
    telemetry_objects.extend(fragments)
    
    print(f"Starting fragmentation scenario with 50 satellites and 500 fragments...")
    
    # Ingest Telemetry
    start_time = time.time()
    result_ingest = engine.ingest_telemetry(current_time.isoformat(), telemetry_objects)
    ingest_duration = time.time() - start_time
    print(f"Telemetry ingestion (including initial assessment) took {ingest_duration:.4f}s")
    print(f"Active CDMs after ingestion: {result_ingest['active_cdm_warnings']}")

    # 3. Simulate step (300 seconds)
    print("Simulating 300 second step...")
    start_time = time.time()
    result_step = engine.step(300)
    step_duration = time.time() - start_time
    
    print(f"Simulation step (300s) took {step_duration:.4f}s")
    print(f"Collisions detected: {result_step['collisions_detected']}")
    print(f"Maneuvers executed: {result_step['maneuvers_executed']}")
    
    # Final check
    snapshot = engine.get_snapshot()
    print(f"Final active CDMs: {snapshot['active_cdm_count']}")
    
    if step_duration > 15.0:
        print("WARNING: Step duration is high! Optimization may be needed.")
    else:
        print("Performance looks acceptable.")

if __name__ == "__main__":
    run_repro()
