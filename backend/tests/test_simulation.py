"""
test_simulation.py — SimulationEngine Integration Tests
═══════════════════════════════════════════════════════
Owner: Dev 1 (Physics Engine)
"""

from datetime import datetime, timedelta, timezone

import pytest


def test_engine_initializes(engine):
    """SimulationEngine should initialize without errors."""
    assert engine is not None
    assert engine.sim_time is not None


def test_ingest_telemetry_returns_ack(engine):
    """ingest_telemetry should return ACK with correct counts."""
    result = engine.ingest_telemetry(
        timestamp="2026-01-01T00:00:00Z",
        objects=[
            {"id": "SAT-01", "type": "SATELLITE",
             "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": 7.67, "z": 0.0}},
        ],
    )
    assert result["status"] == "ACK"
    assert result["processed_count"] == 1


def test_step_advances_time(engine):
    """step() should advance simulation clock."""
    t0 = engine.sim_time
    result = engine.step(step_seconds=60)
    assert result["status"] == "STEP_COMPLETE"
    assert engine.sim_time > t0


def test_get_snapshot_returns_valid_structure(engine):
    """get_snapshot should return a dict with required keys."""
    snap = engine.get_snapshot()
    assert "timestamp" in snap
    assert "satellites" in snap
    assert "debris_cloud" in snap
    assert "active_cdm_count" in snap
    assert "maneuver_queue_depth" in snap


def test_step_executes_scheduled_maneuver(engine):
    """A burn queued before step target time must be executed and counted."""
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    engine.ingest_telemetry(
        timestamp=t0.isoformat(),
        objects=[{"id": "SAT-01", "type": "SATELLITE",
                  "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
                  "v": {"x": 0.0, "y": 7.67, "z": 0.0}}],
    )
    burn_time = t0 + timedelta(seconds=30)
    engine.satellites["SAT-01"].maneuver_queue.append({
        "burn_id": "TEST-BURN",
        "burnTime": burn_time.isoformat(),
        "deltaV_vector": {"x": 0.001, "y": 0.0, "z": 0.0},
    })
    result = engine.step(step_seconds=60)
    assert result["maneuvers_executed"] == 1


def test_step_detects_collision_event(engine):
    """Satellite and debris at the same position must trigger a collision event."""
    engine.ingest_telemetry(
        timestamp="2026-01-01T00:00:00Z",
        objects=[
            {"id": "SAT-01", "type": "SATELLITE",
             "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": 7.67, "z": 0.0}},
            {"id": "DEB-01", "type": "DEBRIS",
             "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
             "v": {"x": 0.0, "y": 7.67, "z": 0.0}},
        ],
    )
    result = engine.step(step_seconds=60)
    assert result["collisions_detected"] >= 1


def test_eol_status_set_when_fuel_exhausted(engine):
    """Satellite fuel below EOL threshold must transition to EOL status on next tick."""
    engine.ingest_telemetry(
        timestamp="2026-01-01T00:00:00Z",
        objects=[{"id": "SAT-01", "type": "SATELLITE",
                  "r": {"x": 6778.0, "y": 0.0, "z": 0.0},
                  "v": {"x": 0.0, "y": 7.67, "z": 0.0}}],
    )
    # Force fuel below EOL threshold (2.5 kg)
    engine.fuel_tracker.register_satellite("SAT-01", fuel_kg=1.0)
    engine.step(step_seconds=60)
    assert engine.satellites["SAT-01"].status == "EOL"
