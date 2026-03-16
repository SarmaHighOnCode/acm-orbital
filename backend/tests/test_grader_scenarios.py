"""
test_grader_scenarios.py — Verification of Grader Requirements
══════════════════════════════════════════════════════════════
Tests for 24h simulation steps, LEO altitude constraints, and snapshot performance.
"""

import pytest
import time
import json
from datetime import datetime, timedelta, timezone
import numpy as np
from engine.simulation import SimulationEngine

def test_24h_simulation_step():
    """Verify that a 24-hour step executes without blow-up and within time limits."""
    engine = SimulationEngine()
    
    # Ingest 50 satellites in LEO
    objects = []
    for i in range(50):
        objects.append({
            "id": f"SAT-{i:02d}",
            "type": "SATELLITE",
            "r": {"x": 6778.0 + i, "y": 0.0, "z": 0.0},
            "v": {"x": 0.0, "y": 7.67, "z": 0.0}
        })
    
    engine.ingest_telemetry(
        timestamp="2026-01-01T00:00:00Z",
        objects=objects
    )
    
    start_time = time.time()
    result = engine.step(step_seconds=86400)
    duration = time.time() - start_time
    
    assert result["status"] == "STEP_COMPLETE"
    assert duration < 30.0  # Grader limit < 30s
    
    # Check altitude constraints for all satellites
    snapshot = engine.get_snapshot()
    for sat in snapshot["satellites"]:
        assert 200.0 <= sat["alt_km"] <= 2000.0, f"Satellite {sat['id']} altitude {sat['alt_km']} out of LEO range"

def test_maneuver_chronological_order():
    """Verify that maneuvers are executed in chronological order even if queued out of order."""
    engine = SimulationEngine()
    engine.ingest_telemetry(
        timestamp="2026-01-01T00:00:00Z",
        objects=[{
            "id": "SAT-01",
            "type": "SATELLITE",
            "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
            "v": {"x": 0.0, "y": 7.67, "z": 0.0}
        }]
    )
    
    sat = engine.satellites["SAT-01"]
    t0 = engine.sim_time
    
    # Queue burns out of order
    burn2 = {
        "burn_id": "BURN-2",
        "burnTime": (t0 + timedelta(seconds=1200)).isoformat(),
        "deltaV_vector": {"x": 0.001, "y": 0.0, "z": 0.0}
    }
    burn1 = {
        "burn_id": "BURN-1",
        "burnTime": (t0 + timedelta(seconds=600)).isoformat(),
        "deltaV_vector": {"x": 0.001, "y": 0.0, "z": 0.0}
    }
    
    # Append in reverse chronological order
    sat.maneuver_queue.append(burn2)
    sat.maneuver_queue.append(burn1)
    
    # Step 24h
    engine.step(step_seconds=86400)
    
    # Check log for order
    executed_burns = [m for m in engine.maneuver_log if m["satellite_id"] == "SAT-01"]
    assert len(executed_burns) == 2
    assert executed_burns[0]["burn_id"] == "BURN-1"
    assert executed_burns[1]["burn_id"] == "BURN-2"

def test_snapshot_performance_and_format():
    """Verify snapshot response time, size, and debris cloud format."""
    engine = SimulationEngine()
    
    # Ingest 50 satellites and 1000 debris objects (for size check)
    objects = []
    for i in range(50):
        objects.append({
            "id": f"SAT-{i:02d}",
            "type": "SATELLITE",
            "r": {"x": 6778.0 + i, "y": 0.0, "z": 0.0},
            "v": {"x": 0.0, "y": 7.67, "z": 0.0}
        })
    for i in range(1000):
        objects.append({
            "id": f"DEB-{i:04d}",
            "type": "DEBRIS",
            "r": {"x": 7000.0 + i * 0.1, "y": 100.0, "z": 50.0},
            "v": {"x": 0.1, "y": 7.5, "z": 0.0}
        })
    
    engine.ingest_telemetry(timestamp="2026-01-01T00:00:00Z", objects=objects)
    
    start_time = time.time()
    snapshot = engine.get_snapshot()
    duration = time.time() - start_time
    
    assert duration < 0.5  # Grader limit < 500ms
    
    # Check debris format: ["DEB-ID", lat, lon, alt]
    assert len(snapshot["debris_cloud"]) == 1000
    first_deb = snapshot["debris_cloud"][0]
    assert isinstance(first_deb, list)
    assert len(first_deb) == 4
    assert first_deb[0].startswith("DEB-")
    
    # Check payload size
    payload_size = len(json.dumps(snapshot))
    assert payload_size < 5 * 1024 * 1024  # Grader limit < 5MB

def test_fuel_not_negative():
    """Verify fuel_kg is never negative in snapshot."""
    engine = SimulationEngine()
    engine.ingest_telemetry(
        timestamp="2026-01-01T00:00:00Z",
        objects=[{
            "id": "SAT-01",
            "type": "SATELLITE",
            "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
            "v": {"x": 0.0, "y": 7.67, "z": 0.0}
        }]
    )
    
    # Force negative fuel (hypothetically)
    engine.fuel_tracker.register_satellite("SAT-01", fuel_kg=-1.0)
    
    snapshot = engine.get_snapshot()
    assert snapshot["satellites"][0]["fuel_kg"] >= 0.0
