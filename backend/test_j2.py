import numpy as np
from engine.propagator import OrbitalPropagator
from config import MU_EARTH, R_EARTH
import time

def test_j2_drift():
    # Construct a LEO orbit
    # a = 7000 km, e = 0.001, i = 45 deg, RAAN = 0, arg_pe = 0
    a = 7000.0
    v_circ = np.sqrt(MU_EARTH / a)
    
    # 45 degrees inclination
    inc = np.radians(45.0)
    
    pos = np.array([a, 0.0, 0.0])
    # Velocity in y and z to get 45 deg inc
    vel = np.array([0.0, v_circ * np.cos(inc), v_circ * np.sin(inc)])
    
    state_init = np.concatenate([pos, vel])
    
    prop = OrbitalPropagator(rtol=1e-8, atol=1e-10)
    
    # Propagate 24 hours
    dt = 86400.0
    state_final = prop.propagate(state_init, dt)
    
    # Calculate RAAN (Right Ascension of Ascending Node)
    h_init = np.cross(pos, vel)
    n_init = np.array([-h_init[1], h_init[0], 0])
    raan_init = np.arctan2(n_init[1], n_init[0]) if np.linalg.norm(n_init) > 1e-5 else 0.0
    
    pos_f = state_final[:3]
    vel_f = state_final[3:]
    h_f = np.cross(pos_f, vel_f)
    n_f = np.array([-h_f[1], h_f[0], 0])
    raan_final = np.arctan2(n_f[1], n_f[0])
    
    print(f"Initial RAAN: {np.degrees(raan_init):.4f} deg")
    print(f"Final RAAN: {np.degrees(raan_final):.4f} deg")
    
    delta_raan = np.degrees(raan_final - raan_init)
    if delta_raan > 180: delta_raan -= 360
    if delta_raan < -180: delta_raan += 360
    print(f"ΔRAAN over 24h: {delta_raan:.4f} deg")
    
    # Theoretical nodal regression rate (deg/day)
    # J2 nodal regression: ΔΩ = -1.5 * n * J2 * (Re/p)^2 * cos(i)
    # where n is mean motion, p = a(1-e^2), Re is Earth radius
    # For roughly circular (e=0): p = a
    n_mm = np.sqrt(MU_EARTH / a**3)
    p = a
    from config import J2
    rate_rad_sec = -1.5 * n_mm * J2 * (R_EARTH / p)**2 * np.cos(inc)
    expected_delta_raan = np.degrees(rate_rad_sec * 86400)
    
    print(f"Expected theoretical ΔRAAN: {expected_delta_raan:.4f} deg")
    diff = abs(delta_raan - expected_delta_raan)
    print(f"Difference: {diff:.6f} deg")
    if diff > 0.1:
        print("ERROR: J2 Nodal Regression does not match theory!")
    else:
        print("SUCCESS: J2 Drift verified against theory.")

if __name__ == '__main__':
    test_j2_drift()
