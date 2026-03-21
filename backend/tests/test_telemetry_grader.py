
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
    
    # Payload with valid objects (Pydantic enforces schema)
    payload_json = {
      "timestamp": "2026-03-12T08:00:02.000Z",
      "objects": [
        {"id": "SAT-Alpha-01", "type": "SATELLITE", "r": {"x": 6778.5, "y": 1.0, "z": 0.0}, "v": {"x": 0.0, "y": 7.668, "z": 0.0}},
        {"id": "SAT-Alpha-01", "type": "SATELLITE", "r": {"x": 6778.8, "y": 2.0, "z": 0.0}, "v": {"x": 0.0, "y": 7.668, "z": 0.0}},
        {"id": "DEB-REENTRY", "type": "DEBRIS", "r": {"x": 6200.0, "y": 0.0, "z": 0.0}, "v": {"x": 0.0, "y": 8.0, "z": 0.0}},
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
    print("Check: Duplicate SAT-Alpha-01 uses latest state")

    # Check 2: DEB-REENTRY at negative altitude filtered
    assert "DEB-REENTRY" not in engine.debris
    print("Check: DEB-REENTRY filtered (radius < R_earth)")

    # Check 3: Missing velocity field rejected by Pydantic
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TelemetryRequest(**{
            "timestamp": "2026-03-12T08:00:02.000Z",
            "objects": [{"id": "DEB-NO-V", "type": "DEBRIS", "r": {"x": 6900.0, "y": 0.0, "z": 0.0}}]
        })
    print("Check: Missing velocity correctly rejected by Pydantic schema")

if __name__ == "__main__":
    try:
        test_telemetry_grader_checks()
        print("\nALL GRADER CHECKS PASSED")
    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
