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

    # Target the first 20 satellites for maximum dashboard activity
    targets = satellites[:min(20, len(satellites))]

    for sat in targets:
        r_sat = np.array([sat["r"]["x"], sat["r"]["y"], sat["r"]["z"]])
        v_sat = np.array([sat["v"]["x"], sat["v"]["y"], sat["v"]["z"]])

        for j in range(n_threats_per_sat):
            # Place debris 2-8 km away in a random direction
            offset_dir = rng.normal(0, 1, 3)
            offset_dir /= np.linalg.norm(offset_dir)
            offset_km = rng.uniform(2.0, 8.0)
            r_deb = r_sat + offset_dir * offset_km

            # Give it a velocity that converges toward the satellite
            # Start with the satellite's velocity, then add a small
            # closing component (retrograde intercept approach)
            closing_speed = rng.uniform(0.001, 0.005)  # 1-5 m/s closing
            v_deb = v_sat - offset_dir * closing_speed

            # Add some cross-track perturbation for realism
            perturb = rng.normal(0, 0.0005, 3)  # ~0.5 m/s random
            v_deb += perturb

            threats.append({
                "id": f"THREAT-{sat['id']}-{j:02d}",
                "type": "DEBRIS",
                "r": {"x": float(r_deb[0]), "y": float(r_deb[1]), "z": float(r_deb[2])},
                "v": {"x": float(v_deb[0]), "y": float(v_deb[1]), "z": float(v_deb[2])},
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
    print("\n[2/3] Injecting 20 threat debris on near-collision courses...")
    threats = generate_threat_debris(sat_objects, n_threats_per_sat=1, seed=99)
    payload["objects"].extend(threats)
    print(f"       Added {len(threats)} threats targeting SAT-000 through SAT-019")
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
    print("\n[3/3] Running 5 simulation steps (600s each = 50 min total)...")
    print("       This triggers: propagation -> conjunction assessment -> "
          "auto-evasion -> fuel burn -> recovery\n")
    total_collisions = 0
    total_maneuvers = 0
    for i in range(5):
        print(f"       Step {i+1}/5: POST /api/simulate/step (600s) ...")
        t0 = time.perf_counter()
        result = post("simulate/step", {"step_seconds": 600})
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
