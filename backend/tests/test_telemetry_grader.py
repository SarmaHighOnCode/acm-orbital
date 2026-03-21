
import sys
import os
from datetime import datetime, timezone
import numpy as np

# Add backend to path
sys.path.append(os.getcwd())

from engine.simulation import SimulationEngine
from schemas import TelemetryRequest, TelemetryObject, Vector3D

def test_telemetry_grader_checks():
    engine = SimulationEngine()
    
    # Payload from USER_REQUEST
    payload_json = {
      "timestamp": "2026-03-12T08:00:02.000Z",
      "objects": [
        {"id": "SAT-Alpha-01", "type": "SATELLITE", "r": {"x": 6778.5, "y": 1.0, "z": 0.0}, "v": {"x": 0.0, "y": 7.668, "z": 0.0}},
        {"id": "SAT-Alpha-01", "type": "SATELLITE", "r": {"x": 6778.8, "y": 2.0, "z": 0.0}, "v": {"x": 0.0, "y": 7.668, "z": 0.0}},
        {"id": "DEB-REENTRY", "type": "DEBRIS", "r": {"x": 6200.0, "y": 0.0, "z": 0.0}, "v": {"x": 0.0, "y": 8.0, "z": 0.0}},
        {"id": "DEB-MISSING-V", "type": "DEBRIS", "r": {"x": 6900.0, "y": 0.0, "z": 0.0}}
      ]
    }
    
    # Simulate Pydantic parsing
    request = TelemetryRequest(**payload_json)
    
    print(f"Ingesting {len(request.objects)} objects...")
    result = engine.ingest_telemetry(
        timestamp=request.timestamp.isoformat(),
        objects=request.objects
    )
    
    print(f"Result: {result}")
    
    # Check 1: Duplicate SAT-Alpha-01 (Latest state x=6778.8)
    assert "SAT-Alpha-01" in engine.satellites
    sat = engine.satellites["SAT-Alpha-01"]
    assert sat.position[0] == 6778.8
    assert sat.position[1] == 2.0
    print("✓ Check: Duplicate SAT-Alpha-01 uses latest state")
    
    # Check 2: DEB-REENTRY at ~178km filtered
    # R_earth = 6378.137. 6200 is below surface?
    # Wait, 6200 km radius. 6200 - 6378.137 = -178 km altitude.
    # The prompt says ~178 km altitude. If it meant radius=6200, then it's way below surface.
    # If it meant altitude=178, radius would be 6378+178 = 6556.
    # Let's check what the engine does. Our filter is alt < 200.
    assert "DEB-REENTRY" not in engine.debris
    print("✓ Check: DEB-REENTRY filtered (altitude < 200km)")
    
    # Check 3: DEB-MISSING-V not crash, use default
    assert "DEB-MISSING-V" in engine.debris
    deb = engine.debris["DEB-MISSING-V"]
    assert np.all(deb.velocity == 0.0)
    print("✓ Check: DEB-MISSING-V uses zero velocity instead of crashing")
    
    # Check 4: Processed count (SAT-Alpha-01 latest, DEB-MISSING-V latest)
    # Deduplicated set: SAT-Alpha-01 (latest), DEB-REENTRY, DEB-MISSING-V.
    # Filtered: DEB-REENTRY.
    # Count should be 2.
    assert result["processed_count"] == 2
    print(f"✓ Check: processed_count is {result['processed_count']} (expected 2)")

if __name__ == "__main__":
    try:
        test_telemetry_grader_checks()
        print("\nALL GRADER CHECKS PASSED")
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
