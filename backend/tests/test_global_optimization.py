import pytest
import numpy as np
from datetime import datetime, timezone, timedelta
from engine.simulation import SimulationEngine
from engine.models import Satellite
from unittest.mock import MagicMock

def test_sat_vs_sat_detection_and_prioritization():
    """
    Verify that:
    1. Sat-vs-Sat conjunctions are detected.
    2. The healthier satellite (more fuel) is prioritized for evasion.
    """
    engine = SimulationEngine()
    
    # Mock GS LOS to always be True to focus on planning logic
    engine.gs_network.check_line_of_sight = MagicMock(return_value=True)
    
    # Define a collision course at ~400km altitude
    # SAT-VULNERABLE (Less fuel: 3.5kg)
    # SAT-HEALTHY (More fuel: 45kg)
    
    t0 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # Sat 1: 3.5 kg fuel (Vulnerable)
    # State: [7000, 0, 0, 0, 7.5, 0]
    s1_id = "SAT-VULNERABLE"
    engine.ingest_telemetry(t0.isoformat(), [
        {
            "id": s1_id, "type": "SATELLITE",
            "r": {"x": 7000.0, "y": 0.0, "z": 0.0},
            "v": {"x": 0.0, "y": 7.5, "z": 0.0}
        }
    ])
    engine.fuel_tracker.register_satellite(s1_id, fuel_kg=3.5)
    engine.satellites[s1_id].fuel_kg = 3.5
    
    # Sat 2: 45.0 kg fuel (Healthy)
    # Positions it to collide head-on in ~3000 seconds
    # Dist = 100km, Relative Vel = 15km/s -> TCA in 6.6s? No, let's make it 30 mins away
    # Relative velocity ~15km/s. To have TCA in 1800s, need dist ~27000km. 
    # Let's just put them closer.
    s2_id = "SAT-HEALTHY"
    engine.ingest_telemetry(t0.isoformat(), [
        {
            "id": s2_id, "type": "SATELLITE",
            "r": {"x": 7000.0, "y": 100.0, "z": 0.0},
            "v": {"x": 0.0, "y": -7.5, "z": 0.0}
        }
    ])
    engine.fuel_tracker.register_satellite(s2_id, fuel_kg=45.0)
    engine.satellites[s2_id].fuel_kg = 45.0

    # Step the simulation to trigger assessment
    # A small step will run Step 3a and Step 5
    res = engine.step(60)
    
    # 1. Verify Sat-vs-Sat CDM was emitted
    # In assess_sat_vs_sat, we should see one CDM
    sat_vs_sat_cdms = [c for c in engine.active_cdms if c.satellite_id in [s1_id, s2_id] and c.debris_id in [s1_id, s2_id]]
    assert len(sat_vs_sat_cdms) >= 1, "Should detect Sat-vs-Sat conjunction"
    
    # 2. Verify prioritization
    # SAT-HEALTHY (45kg) should have a maneuver queued
    # SAT-VULNERABLE (3.5kg) should NOT have a maneuver queued for this threat
    
    s1_queue = engine.satellites[s1_id].maneuver_queue
    s2_queue = engine.satellites[s2_id].maneuver_queue
    
    print(f"S1 ({s1_id}) queue depth: {len(s1_queue)}")
    print(f"S2 ({s2_id}) queue depth: {len(s2_queue)}")
    
    assert len(s2_queue) > 0, f"Healthy satellite {s2_id} should have planned an evasion"
    assert len(s1_queue) == 0, f"Vulnerable satellite {s1_id} should have yielded the maneuver"

    # 3. Verify the logged message (optional, but good for confidence)
    # We can't easily check logger output here without more setup, but the queue presence is the ground truth.

if __name__ == "__main__":
    test_sat_vs_sat_detection_and_prioritization()
