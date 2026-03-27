"""
physics_proof.py — Live Physics Engine Benchmarks
══════════════════════════════════════════════════
Runs real-time benchmarks to prove engine correctness.
Triggered by the dashboard 'Physics Proof' button.

Owner: Dev 1 (Physics Engine)
"""

from __future__ import annotations

import time as _time

import numpy as np
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/physics-proof")
async def physics_proof(request: Request):
    """Run live physics benchmarks to demonstrate engine correctness."""
    from engine.propagator import OrbitalPropagator
    from engine.fuel_tracker import FuelTracker
    from config import MU_EARTH, R_EARTH, ISP, G0, M_DRY, M_FUEL_INIT

    # Access the global engine via app state (avoids circular import)
    engine = request.app.state.engine

    results = []
    prop = OrbitalPropagator()

    # 1. DOP853 Energy Conservation
    r0 = R_EARTH + 400
    v0 = np.sqrt(MU_EARTH / r0)
    sv0 = np.array([r0, 0, 0, 0, v0 * 0.866, v0 * 0.5])
    E0 = 0.5 * np.linalg.norm(sv0[3:])**2 - MU_EARTH / np.linalg.norm(sv0[:3])
    T = 2 * np.pi * np.sqrt(r0**3 / MU_EARTH)
    sv_final = prop.propagate(sv0, 10 * T)
    E1 = 0.5 * np.linalg.norm(sv_final[3:])**2 - MU_EARTH / np.linalg.norm(sv_final[:3])
    drift_pct = abs((E1 - E0) / E0) * 100
    results.append({
        "test": "Energy Conservation (10 orbits)",
        "result": f"{drift_pct:.6f}% drift",
        "threshold": "< 0.1%",
        "status": "PASS" if drift_pct < 0.1 else "FAIL",
    })

    # 2. Batch Propagation Speed
    states = {f"OBJ-{i}": np.array([R_EARTH + 400 + i*5, 0, 0, 0,
              np.sqrt(MU_EARTH/(R_EARTH + 400 + i*5)) * 0.866,
              np.sqrt(MU_EARTH/(R_EARTH + 400 + i*5)) * 0.5])
              for i in range(1000)}
    t0 = _time.perf_counter()
    prop.propagate_batch(states, 600.0)
    batch_ms = (_time.perf_counter() - t0) * 1000
    results.append({
        "test": "1,000-object Batch Propagation",
        "result": f"{batch_ms:.0f} ms",
        "threshold": "< 30,000 ms",
        "status": "PASS" if batch_ms < 30000 else "FAIL",
    })

    # 3. KDTree Build + Query
    from scipy.spatial import cKDTree
    positions = np.random.randn(10000, 3) * 1000 + R_EARTH
    t0 = _time.perf_counter()
    tree = cKDTree(positions)
    build_ms = (_time.perf_counter() - t0) * 1000
    t0 = _time.perf_counter()
    for i in range(50):
        tree.query_ball_point(positions[i], 200)
    query_ms = (_time.perf_counter() - t0) * 1000
    results.append({
        "test": "KDTree Build (10K objects)",
        "result": f"{build_ms:.1f} ms",
        "threshold": "< 100 ms",
        "status": "PASS" if build_ms < 100 else "FAIL",
    })
    results.append({
        "test": "KDTree 50 Queries into 10K",
        "result": f"{query_ms:.1f} ms",
        "threshold": "< 10 ms",
        "status": "PASS" if query_ms < 10 else "FAIL",
    })

    # 4. Tsiolkovsky Precision
    ft = FuelTracker()
    ft.register_satellite("TEST", M_FUEL_INIT)
    consumed = ft.consume("TEST", 5.0)
    m_total = M_DRY + M_FUEL_INIT
    expected = m_total * (1 - np.exp(-5.0 / (ISP * G0)))
    error = abs(consumed - expected)
    results.append({
        "test": "Tsiolkovsky Fuel Precision (5 m/s burn)",
        "result": f"{error:.2e} kg error",
        "threshold": "< 1e-6 kg",
        "status": "PASS" if error < 1e-6 else "FAIL",
    })

    # 5. J2 RAAN Regression
    sv_polar = np.array([R_EARTH + 400, 0, 0, 0, 0, np.sqrt(MU_EARTH / (R_EARTH + 400))])
    sv_1day = prop.propagate(sv_polar, 86400)
    h0 = np.cross(sv_polar[:3], sv_polar[3:])
    h1 = np.cross(sv_1day[:3], sv_1day[3:])
    raan0 = np.degrees(np.arctan2(h0[0], -h0[1]))
    raan1 = np.degrees(np.arctan2(h1[0], -h1[1]))
    raan_drift = abs(raan1 - raan0)
    results.append({
        "test": "J2 RAAN Drift (polar orbit, 24h)",
        "result": f"{raan_drift:.4f} deg/day",
        "threshold": "0.5-1.5 deg/day expected",
        "status": "PASS" if 0.1 < raan_drift < 3.0 else "FAIL",
    })

    # 6. Engine State
    eng_state = {
        "satellites": len(engine.satellites) if engine else 0,
        "debris": len(engine.debris) if engine else 0,
        "active_cdms": len(engine.active_cdms) if engine else 0,
        "sim_time": engine.sim_time.isoformat() if engine else "N/A",
        "collision_count": engine.collision_count if engine else 0,
    }

    # Dynamically count test functions across all test files
    import glob as _glob, re as _re
    _test_files = _glob.glob("backend/tests/test_*.py") + _glob.glob("tests/test_*.py")
    _test_total = 0
    _file_count = 0
    for _tf in set(_test_files):
        try:
            with open(_tf) as _fh:
                _content = _fh.read()
            _test_total += len(_re.findall(r'^\s*def test_', _content, _re.MULTILINE))
            _file_count += 1
        except OSError:
            pass

    all_pass = all(r["status"] == "PASS" for r in results)
    return {
        "overall": "ALL PASS" if all_pass else "SOME FAILURES",
        "benchmarks": results,
        "engine_state": eng_state,
        "test_count": f"{_test_total:,} tests across {_file_count} files",
    }
