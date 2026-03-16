import json
from datetime import datetime, timezone
import sys
import os

# Add the current directory to sys.path to import local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from engine.simulation import SimulationEngine

def run_test():
    engine = SimulationEngine()
    
    test_data = {
      "timestamp": "2026-03-12T08:00:00.000Z",
      "objects": [
        {
          "id": "SAT-Alpha-01",
          "type": "SATELLITE",
          "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
          "v": {"x": 0.0, "y": 7.668, "z": 0.0}
        },
        {
          "id": "SAT-Alpha-02",
          "type": "SATELLITE",
          "r": {"x": -3200.0, "y": 5890.0, "z": 1200.0},
          "v": {"x": -5.12, "y": -3.44, "z": 4.88}
        }
      ]
    }
    
    print("--- Ingesting Telemetry ---")
    result = engine.ingest_telemetry(test_data["timestamp"], test_data["objects"])
    print(json.dumps(result, indent=2))
    
    print("\n--- Initial Snapshot ---")
    snapshot = engine.get_snapshot()
    print(json.dumps(snapshot, indent=2))
    
    print("\n--- Running 60s Step ---")
    step_result = engine.step(60)
    print(json.dumps(step_result, indent=2))
    
    print("\n--- Final Snapshot ---")
    snapshot = engine.get_snapshot()
    print(json.dumps(snapshot, indent=2))

if __name__ == "__main__":
    run_test()
