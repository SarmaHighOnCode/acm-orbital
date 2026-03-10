import sys
from datetime import datetime
import numpy as np

from engine.models import Satellite, Debris
from engine.maneuver_planner import ManeuverPlanner
from engine.collision import ConjunctionAssessor
from engine.propagator import OrbitalPropagator

def _run_tests():
    print("--- VERIFYING PROPORTIONAL BURNS ---")
    planner = ManeuverPlanner()
    sat = Satellite(id="TEST-SAT", position=np.array([6778.0, 0.0, 0.0]), velocity=np.array([0.0, 7.67, 0.0]))
    deb = Debris(id="TEST-DEB", position=np.array([6778.0, 0.0, 0.0]), velocity=np.array([0.0, 7.67, 0.0]))
    tca = datetime.utcnow()
    
    # Test 1: Direct hit (0m miss) -> Should be 2.0 m/s
    burns_0 = planner.plan_evasion(sat, deb, tca, 0.0, tca)
    dv0 = np.linalg.norm(list(burns_0[0]["deltaV_vector"].values())) * 1000
    print(f"Miss:   0.0 km -> Evasion DV: {dv0:.4f} m/s (Expected: ~2.0)")

    # Test 2: Near miss (0.05 km / 50m) -> Should be 1.0 m/s
    burns_50 = planner.plan_evasion(sat, deb, tca, 0.05, tca)
    dv50 = np.linalg.norm(list(burns_50[0]["deltaV_vector"].values())) * 1000
    print(f"Miss:  50.0 m  -> Evasion DV: {dv50:.4f} m/s (Expected: ~1.0)")

    # Test 3: Graze miss (0.09 km / 90m) -> Should be 0.2 m/s
    burns_90 = planner.plan_evasion(sat, deb, tca, 0.09, tca)
    dv90 = np.linalg.norm(list(burns_90[0]["deltaV_vector"].values())) * 1000
    print(f"Miss:  90.0 m  -> Evasion DV: {dv90:.4f} m/s (Expected: ~0.2)")

    # Test 4: Borderline safe (0.099 km / 99m) -> Should be 0.02 m/s
    burns_99 = planner.plan_evasion(sat, deb, tca, 0.099, tca)
    dv99 = np.linalg.norm(list(burns_99[0]["deltaV_vector"].values())) * 1000
    print(f"Miss:  99.0 m  -> Evasion DV: {dv99:.4f} m/s (Expected: ~0.02)")


    print("\n--- VERIFYING 24-HOUR LOOKAHEAD TOLERANCES ---")
    prop = OrbitalPropagator(rtol=1e-6, atol=1e-8)
    assessor = ConjunctionAssessor(prop)
    
    # Ensure tolerances aren't permanently corrupted
    assert prop.rtol == 1e-6
    assert prop.atol == 1e-8
    
    # We will trigger a fake collision assessment to see if it survives a 86400s lookahead
    # without blowing up the memory or taking minutes.
    sat_states = {"SAT1": np.array([6778.0, 0.0, 0.0, 0.0, 7.67, 0.0])}
    deb_states = {"DEB1": np.array([6778.0, 0.0, 0.0, 0.0, 7.67, 0.0])}
    
    print("Running 24-hour (86,400s) dense propagation check via assess()...")
    import time
    t0 = time.time()
    # It will trigger the loose tolerance block for decompression
    cdms = assessor.assess(sat_states, deb_states, lookahead_s=86400.0)
    t1 = time.time()
    
    print(f"Time taken to assess 24h: {t1 - t0:.4f} seconds.")
    print(f"CDMs generated: {len(cdms)}")
    if cdms:
        print(f"Risk: {cdms[0].risk}, Miss: {cdms[0].miss_distance_km:.6f} km")
        
    print(f"Post-assess Propagator rtol: {prop.rtol} (Expected: 1e-6)")
    print(f"Post-assess Propagator atol: {prop.atol} (Expected: 1e-8)")

if __name__ == "__main__":
    _run_tests()
