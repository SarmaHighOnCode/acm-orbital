import pytest
import numpy as np
from datetime import datetime, timezone, timedelta
from engine.simulation import SimulationEngine
from unittest.mock import MagicMock

def test_rts_precision():
    """
    Verify that the Hill's equations (C-W) based recovery maneuver
    accurately returns a satellite from a 20km offset to its nominal slot.
    """
    engine = SimulationEngine()
    # Mock GS for bypass
    engine.gs_network.check_line_of_sight = MagicMock(return_value=True)
    
    # 1. Setup satellite at a known nominal slot
    sat_id = "SAT-RECOVER-01"
    # Pure circular equatorial orbit at 500km altitude
    r_mag = 6378.137 + 500.0
    v_mag = np.sqrt(398600.4418 / r_mag)
    
    r_nom = np.array([r_mag, 0.0, 0.0])
    v_nom = np.array([0.0, v_mag, 0.0])
    
    # Force the module constant to -1 so that any offset triggers RECOVERING
    import engine.simulation as engine_sim
    engine_sim.STATION_KEEPING_RADIUS_KM = -1.0

    # INJECT SATELLITE WITH OFFSET
    # 20km along-track offset (correctly rotated for circularity)
    theta = 20.0 / r_mag
    s, c = np.sin(theta), np.cos(theta)
    
    # Rotate nominal r and v
    r_sat = np.array([r_mag * c, r_mag * s, 0.0])
    v_sat = np.array([-v_mag * s, v_mag * c, 0.0])
    
    telemetry = [
        {
            "id": sat_id,
            "type": "SATELLITE",
            "r": {"x": r_sat[0], "y": r_sat[1], "z": r_sat[2]},
            "v": {"x": v_sat[0], "y": v_sat[1], "z": v_sat[2]}
        }
    ]
    engine.ingest_telemetry("2026-03-12T10:00:00Z", telemetry)
    
    # Explicitly set nominal state (since we want to test recovery to this)
    sat = engine.satellites[sat_id]
    sat.nominal_state = np.concatenate([r_nom, v_nom])
    
    initial_offset = np.linalg.norm(sat.position - sat.nominal_state[:3])
    print(f"\nInitial offset: {initial_offset:.2f} km")
    
    # 2. Step forward 60s to trigger Step 4 (Station-keeping check)
    print("--- Step 1: Trigger RTS Planning ---")
    engine.step(60)
    
    assert sat.status == "RECOVERING"
    assert len(sat.maneuver_queue) == 2
    print(f"Maneuvers queued: {len(sat.maneuver_queue)}")
    
    # 3. Execute first burn
    # RTS_1 is at T+60 + 10 = T+70
    print("--- Step 2: Execute Burn 1 ---")
    engine.step(60) # Moves to T+120
    
    # 4. Step forward to reach Burn 2 time (5400s later)
    # Burn 2 is at T+70 + 5400 = T+5470
    # We step in 10-minute intervals to simulate real operations
    print("--- Stepping through transfer (5400s) ---")
    for _ in range(9):
        engine.step(600)
        curr_offset = np.linalg.norm(sat.position - sat.nominal_state[:3])
        print(f"Time: {engine.sim_time}, Offset: {curr_offset:.4f} km")
    
    print("\nManeuver Log:")
    for entry in engine.maneuver_log:
        print(f"  {entry['timestamp']}: {entry['burn_id']} executed (dV={entry['delta_v_magnitude_ms']:.2f} m/s)")
    
    final_offset = np.linalg.norm(sat.position - sat.nominal_state[:3])
    print(f"Final offset: {final_offset:.4f} km")
    
    # Verify precision
    # Hill logic should get us very close (<1.5km) despite J2 and numerical integration
    engine_sim.STATION_KEEPING_RADIUS_KM = 10.0
    engine.step(1)
    
    assert final_offset < 1.5, f"Recovery failed: offset {final_offset:.2f}km > 1.5km"
    assert sat.status == "NOMINAL"

if __name__ == "__main__":
    test_rts_precision()
