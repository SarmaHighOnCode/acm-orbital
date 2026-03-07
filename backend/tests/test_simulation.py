"""
test_simulation.py — SimulationEngine Integration Tests
═══════════════════════════════════════════════════════
Owner: Dev 1 (Physics Engine)
"""

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
