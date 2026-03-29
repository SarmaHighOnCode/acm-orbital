import numpy as np
from backend.engine.propagator import OrbitalPropagator
from backend.generate_telemetry import build_telemetry_payload

payload = build_telemetry_payload(n_satellites=50, n_debris=0, seed=42)
sats = [o for o in payload['objects'] if o['type'] == 'SATELLITE'][:20]
rng = np.random.default_rng(99)
threats = []

prop = OrbitalPropagator()

for sat in sats[:1]:
    r_sat = np.array([sat["r"]["x"], sat["r"]["y"], sat["r"]["z"]])
    v_sat = np.array([sat["v"]["x"], sat["v"]["y"], sat["v"]["z"]])
    state_sat = np.concatenate([r_sat, v_sat])
    
    future_times = [1800.0, 2400.0, 3000.0]
    
    for j, target_t in enumerate(future_times):
        col_state = prop.propagate(state_sat, target_t)
        r_col = col_state[:3]
        v_col = col_state[3:]
        
        r_mag = np.linalg.norm(r_col)
        v_mag = np.linalg.norm(v_col)
        h_vec = np.cross(r_col, v_col)
        h_hat = h_vec / np.linalg.norm(h_vec)
        r_hat = r_col / r_mag
        t_hat = np.cross(h_hat, r_hat)

        if j < 2:
            inc_offset = rng.uniform(0.1, 0.5) * (1 if j == 0 else -1)
            inc_rad = np.radians(inc_offset)
            cos_i, sin_i = np.cos(inc_rad), np.sin(inc_rad)
            v_deb_col = v_mag * (cos_i * t_hat + sin_i * h_hat)
            along_track_km = rng.uniform(0.5, 2.0) * (1 if j == 0 else -1)
            r_deb_col = r_col + t_hat * along_track_km
            r_deb_col = r_deb_col / np.linalg.norm(r_deb_col) * (r_mag + rng.uniform(-0.05, 0.05))
        else:
            inc_offset = rng.uniform(1.0, 3.0) * rng.choice([-1, 1])
            inc_rad = np.radians(inc_offset)
            cos_i, sin_i = np.cos(inc_rad), np.sin(inc_rad)
            v_deb_col = v_mag * (cos_i * t_hat + sin_i * h_hat)
            radial_offset = rng.uniform(0.01, 0.5)
            r_deb_col = r_col + r_hat * radial_offset + t_hat * rng.uniform(-1.0, 1.0)
            
        deb_t0 = prop.propagate(np.concatenate([r_deb_col, v_deb_col]), -target_t)
        
        print(f"Dist at t=0 for sat {sat['id']} threat {j} (TCA={target_t}): {np.linalg.norm(deb_t0[:3]-r_sat[:3]):.2f} km")
