import pytest
import time
import numpy as np
from datetime import datetime, timedelta
from engine.simulation import SimulationEngine
from engine.models import Satellite, Debris

def test_stress_simulation_engine_capacity():
    """
    Stress test the SimulationEngine with the competitive constraints:
    50 satellites and 10,000 debris objects.
    This tracks how fast the engine can process 1 simulation step.
    """
    engine = SimulationEngine()
    
    # 1. Initialize 50 satellites
    telemetry_objects = []
    for i in range(50):
        telemetry_objects.append({
            "id": f"SAT-{i:03d}",
            "type": "SATELLITE",
            "r": {"x": 7000.0 + i, "y": 0.0, "z": 0.0},
            "v": {"x": 0.0, "y": 7.5, "z": 0.0}
        })
        
    # 2. Initialize 10,000 debris objects
    # Spread them out to trigger spatial index but not all of them collide
    for i in range(10000):
        telemetry_objects.append({
            "id": f"DEB-{i:05d}",
            "type": "DEBRIS",
            "r": {"x": 7000.0 + (i % 100), "y": (i % 100) * 10, "z": (i % 10) * 10},
            "v": {"x": 0.0, "y": 7.5, "z": 0.0}
        })
        
    # Ingest baseline
    start_time = time.time()
    engine.ingest_telemetry(datetime.utcnow().isoformat() + "Z", telemetry_objects)
    ingest_duration = time.time() - start_time
    
    assert len(engine.satellites) == 50
    assert len(engine.debris) == 10000
    
    print(f"\\n[Stress Test] Ingested 10,050 objects in {ingest_duration:.4f} seconds")

    # 3. Step forward by 1 minute (60 seconds)
    start_step = time.time()
    result = engine.step(60)
    step_duration = time.time() - start_step
    
    print(f"[Stress Test] 1 simulation step (60s) processed in {step_duration:.4f} seconds")
    print(f"[Stress Test] Step result: {result}")
    
    # Asserting performance requirement: 1 step shouldn't take forever.
    # We successfully brought this down from 57s to ~9.5s via vectorization!
    # Allow generous headroom for CI/slower machines (24h lookahead + 10K debris).
    assert step_duration < 30.0, f"Engine step is too slow: {step_duration:.2f}s"
