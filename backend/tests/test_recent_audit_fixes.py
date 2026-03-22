import math
from datetime import datetime, timedelta, timezone

import numpy as np

from config import MU_EARTH, R_EARTH
from engine.simulation import SimulationEngine


def test_maneuver_queue_cap():
    """Verify that auto-planner caps the maneuver_queue to 20 entries."""
    engine = SimulationEngine()
    r = R_EARTH + 400.0
    v = math.sqrt(MU_EARTH / r)
    
    engine.ingest_telemetry("2026-03-12T08:00:00.000Z", [
        {"id": "SAT-CAP", "type": "SATELLITE",
         "r": {"x": r, "y": 0.0, "z": 0.0},
         "v": {"x": 0.0, "y": v, "z": 0.0}},
    ])
    
    sat = engine.satellites["SAT-CAP"]
    base = engine.sim_time
    
    # Intentionally overflow the queue
    for i in range(50):
        sat.maneuver_queue.append({
            "burn_id": f"TEST_BURN_{i}",
            "burnTime": (base + timedelta(hours=i)).isoformat(),
            "deltaV_vector": {"x": 0.1, "y": 0.0, "z": 0.0}
        })
        
    engine.step(1)
    
    # The step() function should cap it to 20
    assert len(sat.maneuver_queue) <= 20, f"Queue not capped, size={len(sat.maneuver_queue)}"
    # The remaining burns should be the chronological soonest ones
    assert sat.maneuver_queue[0]["burn_id"] == "TEST_BURN_1"

def test_logs_bounded_to_500():
    """Verify collision and maneuver logs are deques with maxlen 500."""
    engine = SimulationEngine()
    
    for i in range(1000):
        engine.collision_log.append({"id": i})
        engine.maneuver_log.append({"id": i})
        
    assert len(engine.collision_log) == 500
    assert len(engine.maneuver_log) == 500
