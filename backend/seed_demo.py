"""
seed_demo.py — Populate the running ACM backend with demo data via its REST API.

Usage (while backend is running on port 8000):
    python backend/seed_demo.py

This sends:
  1. POST /api/telemetry  — 50 satellites + 10,000 debris (realistic LEO orbits)
     PLUS ~20 "threat" debris deliberately placed on near-collision courses
  2. POST /api/simulate/step — several steps to trigger the full physics pipeline:
     propagation, conjunction assessment, auto-evasion, fuel burn, recovery

After running, the frontend dashboard should show:
  - Satellite positions + debris cloud on the Ground Track
  - Active CDMs on the Bullseye Plot
  - Evasion/recovery burns on the Maneuver Timeline
  - Fuel depletion on the Fuel Heatmap
  - Delta-V cost curve on the DeltaV Chart
"""

import sys
import math
import time
import json

import numpy as np

try:
    import httpx
except ImportError:
    print("httpx not installed — falling back to urllib")
    httpx = None

sys.path.insert(0, "backend")
from generate_telemetry import build_telemetry_payload, generate_satellite_batch

API = "http://localhost:8000/api"


def post(endpoint, payload):
    """POST JSON to the API and return the response dict."""
    url = f"{API}/{endpoint}"
    if httpx:
        r = httpx.post(url, json=payload, timeout=120.0)
        r.raise_for_status()
        return r.json()
    else:
        import urllib.request
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())


def generate_threat_debris(satellites, n_threats_per_sat=1, seed=99):
    """
    Create debris objects on near-collision courses with satellites.

    For each targeted satellite, places debris ~2-8 km away with a
    relative velocity vector that will close the distance within
    the 24-hour conjunction lookahead window. This guarantees CDM
    generation and triggers the full evasion pipeline.
    """
    rng = np.random.default_rng(seed)
    threats = []

    # Target all satellites for maximum dashboard activity
    targets = satellites

    for sat in targets:
        r_sat = np.array([sat["r"]["x"], sat["r"]["y"], sat["r"]["z"]])
        v_sat = np.array([sat["v"]["x"], sat["v"]["y"], sat["v"]["z"]])
        r_mag = np.linalg.norm(r_sat)
        v_mag = np.linalg.norm(v_sat)

        # Orbital frame: h = r × v (angular momentum), then build R/T/N
        h = np.cross(r_sat, v_sat)
        h_hat = h / np.linalg.norm(h)  # Normal to orbital plane
        r_hat = r_sat / r_mag
        t_hat = np.cross(h_hat, r_hat)  # Transverse (approx velocity dir)

        # Type 1: YELLOW-band (5 per sat)
        for j in range(5):
            inc_offset = rng.uniform(3.0, 7.0) * (1 if j % 2 == 0 else -1)
            inc_rad = np.radians(inc_offset)
            cos_i, sin_i = np.cos(inc_rad), np.sin(inc_rad)
            v_deb = v_mag * (cos_i * t_hat + sin_i * h_hat)
            along_track_km = rng.uniform(40, 250) * (1 if j % 2 == 0 else -1)
            r_deb = r_sat + t_hat * along_track_km
            r_deb = r_deb / np.linalg.norm(r_deb) * r_mag

            threats.append({
                "id": f"THREAT-{sat['id']}-Y{j:02d}",
                "type": "DEBRIS",
                "r": {"x": float(r_deb[0]), "y": float(r_deb[1]), "z": float(r_deb[2])},
                "v": {"x": float(v_deb[0]), "y": float(v_deb[1]), "z": float(v_deb[2])},
            })

        # Type 2: RED-band (4 per sat)
        for j in range(4):
            inc_offset = rng.uniform(12, 18) * rng.choice([-1, 1])
            inc_rad = np.radians(inc_offset)
            cos_i, sin_i = np.cos(inc_rad), np.sin(inc_rad)
            v_deb2 = v_mag * (cos_i * t_hat + sin_i * h_hat)
            radial_offset = rng.uniform(0.5, 2.0)
            along_track_km = rng.uniform(30, 150) * rng.choice([-1, 1])
            r_deb2 = r_sat + r_hat * radial_offset + t_hat * along_track_km
            
            threats.append({
                "id": f"THREAT-{sat['id']}-R{j:02d}",
                "type": "DEBRIS",
                "r": {"x": float(r_deb2[0]), "y": float(r_deb2[1]), "z": float(r_deb2[2])},
                "v": {"x": float(v_deb2[0]), "y": float(v_deb2[1]), "z": float(v_deb2[2])},
            })
            
        # Type 3: CRITICAL fast-crossing (2 per sat)
        for j in range(2):
            inc_offset = rng.uniform(25, 30) * rng.choice([-1, 1])
            inc_rad = np.radians(inc_offset)
            cos_i, sin_i = np.cos(inc_rad), np.sin(inc_rad)
            v_deb3 = v_mag * (cos_i * t_hat + sin_i * h_hat)
            radial_offset = rng.uniform(0.1, 0.4)
            along_track_km = rng.uniform(20, 100) * rng.choice([-1, 1])
            r_deb3 = r_sat + r_hat * radial_offset + t_hat * along_track_km
            
            threats.append({
                "id": f"THREAT-{sat['id']}-C{j:02d}",
                "type": "DEBRIS",
                "r": {"x": float(r_deb3[0]), "y": float(r_deb3[1]), "z": float(r_deb3[2])},
                "v": {"x": float(v_deb3[0]), "y": float(v_deb3[1]), "z": float(v_deb3[2])},
            })

    return threats


def main():
    print("=" * 60)
    print("  ACM-Orbital Demo Seeder (with threat debris)")
    print("=" * 60)

    # Step 1: Generate base telemetry
    print("\n[1/3] Generating 50 satellites + 10,000 debris (LEO mode)...")
    t0 = time.perf_counter()
    payload = build_telemetry_payload(
        n_satellites=50,
        n_debris=10_000,
        mode="leo",
        seed=42,
        timestamp="2026-03-12T08:00:00.000Z",
    )

    # Extract satellite objects for threat generation
    sat_objects = [o for o in payload["objects"] if o["type"] == "SATELLITE"]

    gen_t = time.perf_counter() - t0
    print(f"       Generated {len(payload['objects']):,} objects in {gen_t:.2f}s")

    # Step 2: Add threat debris on collision courses
    threats = generate_threat_debris(sat_objects, n_threats_per_sat=11, seed=99)
    payload["objects"].extend(threats)
    print(f"\n[2/3] Injecting {len(threats)} threat debris on near-collision courses...")
    print(f"       Added {len(threats)} threats targeting all satellites")
    print(f"       Total objects: {len(payload['objects']):,}")

    # Ingest everything
    print("\n       Sending POST /api/telemetry ...")
    t0 = time.perf_counter()
    result = post("telemetry", payload)
    ingest_t = time.perf_counter() - t0
    print(f"       -> status={result['status']} | "
          f"processed={result['processed_count']} | "
          f"CDM warnings={result['active_cdm_warnings']}")
    print(f"       Ingested in {ingest_t:.2f}s")

    # Step 3: Run simulation steps
    print("\n[3/3] Running 20 simulation steps (900s each = 5 hours total)...")
    print("       This triggers: propagation -> conjunction assessment -> ")
    print("       auto-evasion -> fuel burn -> recovery\n")
    total_collisions = 0
    total_maneuvers = 0
    for i in range(20):
        print(f"       Step {i+1}/20: POST /api/simulate/step (900s) ...")
        t0 = time.perf_counter()
        result = post("simulate/step", {"step_seconds": 900})
        step_t = time.perf_counter() - t0
        total_collisions += result.get("collisions_detected", 0)
        total_maneuvers += result.get("maneuvers_executed", 0)
        print(f"         -> t={result['new_timestamp']} | "
              f"collisions={result['collisions_detected']} | "
              f"maneuvers={result['maneuvers_executed']} | {step_t:.2f}s")

    # Summary
    print("\n" + "=" * 60)
    print("  SEED COMPLETE — Dashboard should now show:")
    print(f"    Satellites:  50 (positions on Ground Track)")
    print(f"    Debris:      10,020 (cloud on Ground Track)")
    print(f"    CDMs:        {result.get('active_cdm_warnings', '?')} active warnings")
    print(f"    Collisions:  {total_collisions}")
    print(f"    Maneuvers:   {total_maneuvers} burns executed")
    print(f"    Sim time:    2026-03-12T08:50:00Z")
    print("=" * 60)
    print("\nOpen http://localhost:5173 to see the full Orbital Insight dashboard.")


if __name__ == "__main__":
    main()
