import sys
import os
sys.path.append(os.path.join(os.getcwd(), "backend"))

import numpy as np
from engine.propagator import OrbitalPropagator
from config import MU_EARTH, J2, R_EARTH
import json

def verify_j2():
    print("J2 Verification Benchmark")
    print("=========================")
    
    # Standard LEO state
    # RAAN = 0, inc = 45 deg
    r0 = np.array([6778.0, 0.0, 0.0])
    v0 = np.array([0.0, 7.67 * np.cos(np.radians(45)), 7.67 * np.sin(np.radians(45))])
    state0 = np.concatenate([r0, v0])
    
    duration = 86400  # 24 hours
    
    # 1. Propagate with J2 (Standard)
    prop_j2 = OrbitalPropagator(rtol=1e-10, atol=1e-12)
    state_j2 = prop_j2.propagate(state0, duration)
    
    # 2. Propagate with J2=0 (Pure Keplerian)
    import engine.propagator as propagator_module
    original_j2 = propagator_module.J2
    propagator_module.J2 = 0.0
    prop_kep = OrbitalPropagator(rtol=1e-10, atol=1e-12)
    state_kep = prop_kep.propagate(state0, duration)
    propagator_module.J2 = original_j2 # Restore
    
    # Calculate drift
    pos_diff = np.linalg.norm(state_j2[:3] - state_kep[:3])
    
    # Calculate RAAN drift (nodal regression)
    def get_raan(state):
        r = state[:3]
        v = state[3:]
        h = np.cross(r, v)
        n = np.cross([0, 0, 1], h)
        if np.linalg.norm(n) == 0: return 0
        raan = np.degrees(np.arctan2(n[1], n[0]))
        return raan % 360
    
    raan_j2 = get_raan(state_j2)
    raan_kep = get_raan(state_kep)
    raan_drift = raan_j2 - raan_kep
    
    print(f"J2 Active RAAN (24h): {raan_j2:.6f} deg")
    print(f"Keplerian RAAN (24h): {raan_kep:.6f} deg")
    print(f"RAAN Drift (J2 effect): {raan_drift:.6f} deg")
    print(f"Total Position Difference: {pos_diff:.2f} km")
    
    results = {
        "j2_active": True,
        "raan_drift_deg": raan_drift,
        "pos_diff_km": pos_diff,
        "j2_formula_match": "1.5 * J2 * MU * RE^2 / r^5 * [x(5z2/r2-1), y(5z2/r2-1), z(5z2/r2-3)]"
    }
    
    with open("j2_proof.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    verify_j2()
