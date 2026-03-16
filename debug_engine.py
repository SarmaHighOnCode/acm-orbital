import sys
import os
sys.path.append(os.path.join(os.getcwd(), "backend"))

from engine.simulation import SimulationEngine
import numpy as np
import json

def debug():
    print("Initializing Engine...")
    engine = SimulationEngine()
    
    print("Ingesting Satellites...")
    objects = []
    for i in range(50):
        objects.append({
            "id": f"SAT-{i:02d}",
            "type": "SATELLITE",
            "r": {"x": 6778.0 + i, "y": 0.0, "z": 0.0},
            "v": {"x": 0.0, "y": 7.67, "z": 0.0}
        })
    engine.ingest_telemetry(timestamp="2026-01-01T00:00:00Z", objects=objects)
    
    print("Stepping 24h...")
    import time
    start = time.time()
    try:
        result = engine.step(step_seconds=86400)
        end = time.time()
        result_pkg = {
            "step_result": result,
            "step_duration": end - start
        }
    except Exception as e:
        print(f"Step Error: {e}")
        import traceback
        traceback.print_exc()
        return

    print("Generating Snapshot...")
    start = time.time()
    try:
        snapshot = engine.get_snapshot()
        end = time.time()
        result_pkg["snapshot_duration"] = end - start
        result_pkg["snapshot_sample"] = snapshot["satellites"][0]
        result_pkg["snapshot_debris_count"] = len(snapshot["debris_cloud"])
        
        with open("debug_results.json", "w") as f:
            json.dump(result_pkg, f, indent=2)
        print("Results saved to debug_results.json")
    except Exception as e:
        print(f"Snapshot Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug()
