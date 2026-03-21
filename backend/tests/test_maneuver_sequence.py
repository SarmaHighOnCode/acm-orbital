import numpy as np
from datetime import datetime, timezone, timedelta
from engine.simulation import SimulationEngine
from config import ISP, G0, M_DRY, M_FUEL_INIT

def test_sequential_fuel_consumption():
    engine = SimulationEngine()
    sat_id = "SAT-Alpha-01"
    
    # Ingest telemetry for the satellite
    engine.ingest_telemetry(
        datetime.now(timezone.utc).isoformat(),
        [{
            "id": sat_id,
            "type": "SATELLITE",
            "r": {"x": 7000.0, "y": 0.0, "z": 0.0},
            "v": {"x": 0.0, "y": 7.5, "z": 0.0}
        }]
    )
    
    # Mock ground station LOS to always be True for this test
    engine.gs_network.check_line_of_sight = lambda pos, time: True
    
    # Define a sequence of 3 burns
    # burn 1: 0.010 km/s (10 m/s)
    # burn 2: 0.010 km/s (10 m/s)
    # burn 3: 0.010 km/s (10 m/s)
    
    burn_time1 = engine.sim_time + timedelta(seconds=600)
    burn_time2 = burn_time1 + timedelta(seconds=700)
    burn_time3 = burn_time2 + timedelta(seconds=700)
    
    sequence = [
        {
            "burn_id": "BURN_1",
            "burnTime": burn_time1.isoformat(),
            "deltaV_vector": {"x": 0.0, "y": 0.010, "z": 0.0}
        },
        {
            "burn_id": "BURN_2",
            "burnTime": burn_time2.isoformat(),
            "deltaV_vector": {"x": 0.0, "y": 0.010, "z": 0.0}
        },
        {
            "burn_id": "BURN_3",
            "burnTime": burn_time3.isoformat(),
            "deltaV_vector": {"x": 0.0, "y": 0.010, "z": 0.0}
        }
    ]
    
    # Manual calculation (Tsiolkovsky)
    # Initial fuel = 50.0 kg, Initial wet mass = 550.0 kg
    # Burn 1: dm1 = 550 * (1 - exp(-10 / (300 * 9.80665)))
    #         = 550 * (1 - exp(-10 / 2941.995))
    #         = 550 * (1 - exp(-0.003399))
    #         = 550 * 0.003393 = 1.86615 kg
    # Mass after 1: 550 - 1.86615 = 548.13385 kg
    # Burn 2: dm2 = 548.13385 * (1 - exp(-10 / 2941.995))
    #         = 548.13385 * 0.003393 = 1.85984 kg
    # Mass after 2: 548.13385 - 1.85984 = 546.27401 kg
    # Burn 3: dm3 = 546.27401 * (1 - exp(-10 / 2941.995))
    #         = 546.27401 * 0.003393 = 1.85354 kg
    # Mass after 3: 546.27401 - 1.85354 = 544.42047 kg

    result = engine.schedule_maneuver(sat_id, sequence)
    
    print(f"Status: {result['status']}")
    projected_mass = result['validation']['projected_mass_remaining_kg']
    print(f"Projected mass remaining: {projected_mass:.5f} kg")
    print(f"Expected mass remaining: 544.42047 kg")
    
    assert result['status'] == "SCHEDULED"
    # Tolerance 0.05 kg — accounts for mass-aware Tsiolkovsky coupling
    assert abs(projected_mass - 544.42047) < 0.05

if __name__ == "__main__":
    test_sequential_fuel_consumption()
    print("Test passed!")
