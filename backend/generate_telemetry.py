"""
generate_telemetry.py — Realistic Debris State Vector Generator
═══════════════════════════════════════════════════════════════
Generates large-scale, physically realistic ECI debris state vectors
for stress testing the ACM physics engine.

Outputs:
  - JSON payloads compatible with POST /api/telemetry
  - Direct engine streaming benchmarks
  - Multiple distribution modes (LEO, mixed, worst-case cluster)

Usage:
    python generate_telemetry.py --n 100000 --output debris.json
    python generate_telemetry.py --n 15000  --mode mixed --benchmark
    python generate_telemetry.py --n 100000 --mode worst --benchmark
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

# ── Physical constants (mirrored from config.py for standalone use) ───────────
MU_EARTH: float = 398600.4418  # km³/s²
R_EARTH: float  = 6378.137     # km


# ═══════════════════════════════════════════════════════════════════════════════
# ORBITAL MECHANICS HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _circular_leo_state(
    r_km: float,
    inc_rad: float,
    raan_rad: float,
    nu_rad: float,
) -> list[float]:
    """
    Generate a physically correct ECI state vector for a circular orbit.

    Converts Keplerian elements (a, i, Ω, ν) → ECI [x, y, z, vx, vy, vz]
    using the standard perifocal-to-ECI rotation matrices (no argument of
    perigee needed for circular orbits).

    Args:
        r_km:      Orbital radius (R_Earth + altitude) in km.
        inc_rad:   Inclination in radians [0, π].
        raan_rad:  Right ascension of ascending node in radians [0, 2π].
        nu_rad:    True anomaly in radians [0, 2π].

    Returns:
        [x, y, z, vx, vy, vz] in km and km/s.
    """
    v = math.sqrt(MU_EARTH / r_km)          # circular speed km/s

    cos_raan, sin_raan = math.cos(raan_rad), math.sin(raan_rad)
    cos_inc,  sin_inc  = math.cos(inc_rad),  math.sin(inc_rad)
    cos_nu,   sin_nu   = math.cos(nu_rad),   math.sin(nu_rad)

    # Perifocal coordinates
    x_pf,  y_pf  =  r_km * cos_nu,  r_km * sin_nu
    vx_pf, vy_pf = -v    * sin_nu,  v    * cos_nu

    # Perifocal → ECI via Rz(-RAAN) × Rx(-inc)
    x  = cos_raan * x_pf  - sin_raan * cos_inc * y_pf
    y  = sin_raan * x_pf  + cos_raan * cos_inc * y_pf
    z  =                      sin_inc           * y_pf
    vx = cos_raan * vx_pf - sin_raan * cos_inc * vy_pf
    vy = sin_raan * vx_pf + cos_raan * cos_inc * vy_pf
    vz =                     sin_inc            * vy_pf

    return [x, y, z, vx, vy, vz]


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH GENERATORS
# ═══════════════════════════════════════════════════════════════════════════════

def generate_debris_batch(
    n: int = 100_000,
    mode: str = "leo",
    seed: int = 42,
) -> list[dict]:
    """
    Generate N debris objects as telemetry payload dicts.

    Modes
    -----
    "leo"    Circular orbits, 300–600 km altitude, random i ∈ [0°, 180°] and
             RAAN/ν uniform over [0, 2π].  Most physically realistic LEO population.

    "mixed"  70 % circular LEO (300–600 km) + 20 % elliptical (apogee 800–2000 km)
             + 10 % near-GEO shell (35 000–36 500 km).  Tests altitude band filter.

    "worst"  All objects jitter-packed inside a ±5 km cube around one LEO point.
             Maximum collision-detection stress; every object is a KDTree neighbour.

    Args:
        n:    Number of debris objects.
        mode: One of "leo" | "mixed" | "worst".
        seed: NumPy random seed for reproducibility.

    Returns:
        List of dicts with keys: id, type, r{x,y,z}, v{x,y,z}.
    """
    rng = np.random.default_rng(seed)
    objects: list[dict] = []

    # ── LEO circular population ───────────────────────────────────────────────
    if mode == "leo":
        alts  = rng.uniform(300.0, 600.0, n)
        incs  = rng.uniform(0.0, math.pi, n)
        raans = rng.uniform(0.0, 2 * math.pi, n)
        nus   = rng.uniform(0.0, 2 * math.pi, n)

        for i in range(n):
            sv = _circular_leo_state(R_EARTH + alts[i], incs[i], raans[i], nus[i])
            objects.append({
                "id":   f"DEB-{i:07d}",
                "type": "DEBRIS",
                "r":    {"x": sv[0], "y": sv[1], "z": sv[2]},
                "v":    {"x": sv[3], "y": sv[4], "z": sv[5]},
            })

    # ── Mixed population (LEO + elliptical + near-GEO) ────────────────────────
    elif mode == "mixed":
        n_leo = int(n * 0.70)
        n_ell = int(n * 0.20)
        n_geo = n - n_leo - n_ell

        # LEO slice
        alts  = rng.uniform(300.0, 600.0, n_leo)
        incs  = rng.uniform(0.0, math.pi, n_leo)
        raans = rng.uniform(0.0, 2 * math.pi, n_leo)
        nus   = rng.uniform(0.0, 2 * math.pi, n_leo)
        for i in range(n_leo):
            sv = _circular_leo_state(R_EARTH + alts[i], incs[i], raans[i], nus[i])
            objects.append({
                "id": f"LEO-{i:07d}", "type": "DEBRIS",
                "r": {"x": sv[0], "y": sv[1], "z": sv[2]},
                "v": {"x": sv[3], "y": sv[4], "z": sv[5]},
            })

        # Elliptical slice — velocity scaled 5–15% above circular to give eccentricity
        smas   = R_EARTH + rng.uniform(400.0, 1200.0, n_ell)
        incs   = rng.uniform(0.0, math.pi, n_ell)
        raans  = rng.uniform(0.0, 2 * math.pi, n_ell)
        nus    = rng.uniform(0.0, 2 * math.pi, n_ell)
        vscale = rng.uniform(1.05, 1.15, n_ell)   # >1 → elliptical, not circular
        for i in range(n_ell):
            sv = _circular_leo_state(smas[i], incs[i], raans[i], nus[i])
            objects.append({
                "id": f"ELL-{i:07d}", "type": "DEBRIS",
                "r": {"x": sv[0], "y": sv[1], "z": sv[2]},
                "v": {"x": sv[3] * vscale[i], "y": sv[4] * vscale[i],
                      "z": sv[5] * vscale[i]},
            })

        # Near-GEO slice — equatorial, geostationary-ish
        for i in range(n_geo):
            r_km = R_EARTH + rng.uniform(35_000.0, 36_500.0)
            v    = math.sqrt(MU_EARTH / r_km)
            th   = rng.uniform(0, 2 * math.pi)
            objects.append({
                "id": f"GEO-{i:07d}", "type": "DEBRIS",
                "r": {"x": r_km * math.cos(th), "y": r_km * math.sin(th), "z": 0.0},
                "v": {"x": -v * math.sin(th), "y": v * math.cos(th), "z": 0.0},
            })

    # ── Worst-case cluster (maximum KDTree stress) ────────────────────────────
    elif mode == "worst":
        r_base = R_EARTH + 400.0
        v_base = math.sqrt(MU_EARTH / r_base)
        jitter_pos = rng.uniform(-5.0, 5.0, (n, 3))    # ±5 km
        jitter_vel = rng.uniform(-0.05, 0.05, (n, 3))  # ±50 m/s

        for i in range(n):
            objects.append({
                "id":   f"CLUST-{i:07d}",
                "type": "DEBRIS",
                "r":    {
                    "x": r_base + jitter_pos[i, 0],
                    "y":          jitter_pos[i, 1],
                    "z":          jitter_pos[i, 2],
                },
                "v":    {
                    "x": jitter_vel[i, 0],
                    "y": v_base + jitter_vel[i, 1],
                    "z": jitter_vel[i, 2],
                },
            })

    else:
        raise ValueError(f"Unknown mode '{mode}'. Choose: leo | mixed | worst")

    return objects


def generate_satellite_batch(n: int = 50, seed: int = 0) -> list[dict]:
    """
    Generate N satellites in circular LEO at ISS-like altitude (400 km).

    Inclinations are drawn from [45°, 98°] — realistic for sun-synchronous and
    mid-inclination constellation designs.

    Args:
        n:    Number of satellites.
        seed: Random seed.

    Returns:
        List of satellite telemetry dicts.
    """
    rng = np.random.default_rng(seed)
    objects: list[dict] = []
    r_km = R_EARTH + 400.0

    for i in range(n):
        inc  = rng.uniform(math.radians(45.0), math.radians(98.0))
        raan = rng.uniform(0.0, 2 * math.pi)
        nu   = rng.uniform(0.0, 2 * math.pi)
        sv   = _circular_leo_state(r_km, inc, raan, nu)
        objects.append({
            "id":   f"SAT-{i:03d}",
            "type": "SATELLITE",
            "r":    {"x": sv[0], "y": sv[1], "z": sv[2]},
            "v":    {"x": sv[3], "y": sv[4], "z": sv[5]},
        })

    return objects


# ═══════════════════════════════════════════════════════════════════════════════
# PAYLOAD BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def build_telemetry_payload(
    n_satellites: int = 50,
    n_debris: int = 100_000,
    mode: str = "leo",
    seed: int = 42,
    timestamp: str | None = None,
) -> dict:
    """
    Build a complete POST /api/telemetry JSON payload.

    Args:
        n_satellites: Number of satellites to include.
        n_debris:     Number of debris objects to include.
        mode:         Debris distribution mode (leo | mixed | worst).
        seed:         Random seed.
        timestamp:    ISO-8601 UTC string. Defaults to current time.

    Returns:
        Dict matching the TelemetryRequest Pydantic schema.
    """
    if timestamp is None:
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).isoformat()

    objects = generate_satellite_batch(n_satellites, seed=seed)
    objects += generate_debris_batch(n_debris, mode=mode, seed=seed + 1)

    return {"timestamp": timestamp, "objects": objects}


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE STREAMING BENCHMARK
# ═══════════════════════════════════════════════════════════════════════════════

def stream_to_engine(
    engine,
    n_debris: int = 100_000,
    batch_size: int = 10_000,
    mode: str = "leo",
    seed: int = 42,
    verbose: bool = True,
) -> dict:
    """
    Stream N debris objects into a SimulationEngine in batches.

    Mimics a live grader telemetry flood: objects arrive in `batch_size`
    packets, each processed by engine.ingest_telemetry() independently.
    Measures total wall-clock throughput.

    Args:
        engine:     SimulationEngine instance (must be pre-constructed).
        n_debris:   Total debris objects to stream.
        batch_size: Objects per network packet / API call.
        mode:       Debris distribution mode.
        seed:       Random seed.
        verbose:    Print per-batch progress.

    Returns:
        {total_objects, elapsed_s, objects_per_second, batches, batch_size}
    """
    from datetime import datetime, timezone

    all_debris = generate_debris_batch(n_debris, mode=mode, seed=seed)
    ts         = datetime.now(timezone.utc).isoformat()
    t_start    = time.perf_counter()
    n_batches  = 0

    for start in range(0, n_debris, batch_size):
        batch = all_debris[start:start + batch_size]
        engine.ingest_telemetry(ts, batch)
        n_batches += 1
        if verbose:
            done = min(start + batch_size, n_debris)
            print(f"  Batch {n_batches:3d}: ingested {done:>7,}/{n_debris:,} objects")

    elapsed = time.perf_counter() - t_start
    return {
        "total_objects":      n_debris,
        "elapsed_s":          elapsed,
        "objects_per_second": n_debris / elapsed,
        "batches":            n_batches,
        "batch_size":         batch_size,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate debris telemetry payloads for ACM physics engine testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_telemetry.py --n 100000 --output flood.json
  python generate_telemetry.py --n 15000  --mode mixed --benchmark
  python generate_telemetry.py --n 100000 --mode worst --benchmark --batch 5000
        """,
    )
    parser.add_argument("--n",         type=int,  default=100_000, help="Debris object count")
    parser.add_argument("--sats",      type=int,  default=50,      help="Satellite count")
    parser.add_argument("--mode",      type=str,  default="leo",   help="leo | mixed | worst")
    parser.add_argument("--output",    type=str,  default=None,    help="Output JSON file")
    parser.add_argument("--benchmark", action="store_true",        help="Benchmark engine ingest")
    parser.add_argument("--batch",     type=int,  default=10_000,  help="Batch size for streaming")
    parser.add_argument("--seed",      type=int,  default=42,      help="Random seed")
    args = parser.parse_args()

    # ── Generation ────────────────────────────────────────────────────────────
    print(f"[GENERATOR] Building {args.n:,} debris + {args.sats} satellites "
          f"(mode={args.mode}, seed={args.seed})")
    t0 = time.perf_counter()
    payload = build_telemetry_payload(
        n_satellites=args.sats,
        n_debris=args.n,
        mode=args.mode,
        seed=args.seed,
    )
    gen_elapsed = time.perf_counter() - t0
    n_total = len(payload["objects"])

    print(f"[GENERATOR] Generated {n_total:,} objects in {gen_elapsed:.2f}s "
          f"({n_total / gen_elapsed:,.0f} obj/s)")

    # ── Optional JSON output ──────────────────────────────────────────────────
    if args.output:
        out_path = Path(args.output)
        print(f"[GENERATOR] Writing {out_path} ...")
        with out_path.open("w") as f:
            json.dump(payload, f)
        size_mb = out_path.stat().st_size / 1e6
        print(f"[GENERATOR] Wrote {size_mb:.1f} MB → {out_path}")

    # ── Optional engine streaming benchmark ──────────────────────────────────
    if args.benchmark:
        sys.path.insert(0, str(Path(__file__).parent))
        from engine.simulation import SimulationEngine

        engine = SimulationEngine()
        print(f"\n[BENCHMARK] Streaming {args.n:,} debris → SimulationEngine "
              f"(batch_size={args.batch:,}) ...")
        result = stream_to_engine(
            engine,
            n_debris=args.n,
            batch_size=args.batch,
            mode=args.mode,
            seed=args.seed,
        )
        print(f"\n[BENCHMARK] ═══════════════════════════════════")
        print(f"[BENCHMARK] Total objects : {result['total_objects']:>10,}")
        print(f"[BENCHMARK] Elapsed       : {result['elapsed_s']:>10.3f} s")
        print(f"[BENCHMARK] Throughput    : {result['objects_per_second']:>10,.0f} obj/s")
        print(f"[BENCHMARK] Batches sent  : {result['batches']:>10,}")
        print(f"[BENCHMARK] Satellites    : {len(engine.satellites):>10,}")
        print(f"[BENCHMARK] Debris stored : {len(engine.debris):>10,}")
        print(f"[BENCHMARK] ═══════════════════════════════════")

        # Print PASS/FAIL verdict
        if result["elapsed_s"] < 5.0:
            print("[BENCHMARK] ✓ PASS: 100K ingest < 5s")
        else:
            print(f"[BENCHMARK] ✗ FAIL: {result['elapsed_s']:.2f}s > 5s limit")
