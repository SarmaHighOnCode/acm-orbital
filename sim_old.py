import numpy as np
from backend.engine.propagator import OrbitalPropagator
from backend.generate_telemetry import build_telemetry_payload
from backend.engine.collision import ConjunctionAssessor
import time

payload = build_telemetry_payload(n_satellites=50, n_debris=0, seed=42)
sats = [o for o in payload['objects'] if o['type'] == 'SATELLITE'][:20]
rng = np.random.default_rng(99)
threats = []

for sat in sats:
    r_sat = np.array([sat["r"]["x"], sat["r"]["y"], sat["r"]["z"]])
    v_sat = np.array([sat["v"]["x"], sat["v"]["y"], sat["v"]["z"]])
    r_mag = np.linalg.norm(r_sat)
    v_mag = np.linalg.norm(v_sat)
    h = np.cross(r_sat, v_sat)
    h_hat = h / np.linalg.norm(h)
    r_hat = r_sat / r_mag
    t_hat = np.cross(h_hat, r_hat)

    for j in range(2):
        inc_offset = rng.uniform(0.1, 0.5) * (1 if j == 0 else -1)
        inc_rad = np.radians(inc_offset)
        cos_i, sin_i = np.cos(inc_rad), np.sin(inc_rad)
        v_deb = v_mag * (cos_i * t_hat + sin_i * h_hat)
        along_track_km = rng.uniform(0.5, 2.0) * (1 if j == 0 else -1)
        r_deb = r_sat + t_hat * along_track_km
        r_deb = r_deb / np.linalg.norm(r_deb) * (r_mag + rng.uniform(-0.05, 0.05))
        threats.append({"id": f"T-{sat['id']}-{j}", "r": {"x": r_deb[0], "y": r_deb[1], "z": r_deb[2]}, "v": {"x": v_deb[0], "y": v_deb[1], "z": v_deb[2]}})

    inc_offset = rng.uniform(1.0, 3.0) * rng.choice([-1, 1])
    inc_rad = np.radians(inc_offset)
    cos_i, sin_i = np.cos(inc_rad), np.sin(inc_rad)
    v_deb2 = v_mag * (cos_i * t_hat + sin_i * h_hat)
    radial_offset = rng.uniform(0.01, 0.5)
    r_deb2 = r_sat + r_hat * radial_offset + t_hat * rng.uniform(-1.0, 1.0)
    threats.append({"id": f"T-{sat['id']}-2", "r": {"x": r_deb2[0], "y": r_deb2[1], "z": r_deb2[2]}, "v": {"x": v_deb2[0], "y": v_deb2[1], "z": v_deb2[2]}})

prop = OrbitalPropagator()
ca = ConjunctionAssessor(prop)
sat_states = {s['id']: np.array([s['r']['x'], s['r']['y'], s['r']['z'], s['v']['x'], s['v']['y'], s['v']['z']]) for s in sats}
deb_states = {t['id']: np.array([t['r']['x'], t['r']['y'], t['r']['z'], t['v']['x'], t['v']['y'], t['v']['z']]) for t in threats}

from datetime import datetime, timezone
now = datetime.now(timezone.utc)
cdms = ca.assess(sat_states, deb_states, 86400.0, current_time=now)
print(f"Total old CDMs: {len(cdms)}")
for c in cdms[:15]:
    dt = (c.tca - now).total_seconds()
    print(f"Miss: {c.miss_distance_km:.3f} km, risk: {c.risk}, tca: {dt:.1f}s")
