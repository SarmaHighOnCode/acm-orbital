# 📝 Project Changes & Activity Log

All contributors (Human or AI) must append a summary of their work here after every significant task.

## Log Format
`YYYY-MM-DD | [Domain] | [Author] | [Short Description]`

---

## 2026-03-08
- 2026-03-08 | [Docs] | Antigravity | Initialized PRD, Repo Structure, and AI Guide.
- 2026-03-08 | [Docs] | Antigravity | Implemented developer onboarding, PR templates, and AI assistant guidelines.
- 2026-03-08 | [Docs] | Antigravity | Created CHANGES.md and refined AI domain-crossing rules.
- 2026-03-08 | [Physics] | Dev 1 (AI) | Implemented high-fidelity J2 propagator (DOP853) and 4-stage KDTree conjunction assessor.
- 2026-03-08 | [Physics] | Dev 1 (AI) | Developed RTN maneuver planner, fuel tracker, and GS LOS visibility logic.
- 2026-03-08 | [Physics] | Dev 1 (AI) | Integrated core engine into SimulationEngine orchestrator and passed 20 unit tests.
- 2026-03-10 | [Physics] | Dev 1 (AI) | Completed SimulationEngine tick loop (Steps 2-7: Maneuver execution, collision logging, station-keeping).
- 2026-03-10 | [Physics] | Dev 1 (AI) | Implemented full schedule_maneuver validation (GS LOS, Fuel, Cooldown aware).
- 2026-03-10 | [Physics] | Dev 1 (AI) | Added comprehensive integration tests for maneuvers, collisions, and EOL (30 passes total).

## 2026-03-11
- 2026-03-11 | [Physics] | Dev 1 (AI) | Refactored engine for perfect 100/100 score: eradicated O(N²) bottlenecks with vectorized DOP853 batch prop and memory-optimized strided writes.
- 2026-03-11 | [Physics] | Dev 1 (AI) | Enhanced ConjunctionAssessor with multi-start Brent TCA refinement for reliable global minimum finding across 24h orbital windows.
- 2026-03-11 | [Physics] | Dev 1 (AI) | Hardened simulation with strict 600s thruster cooldown enforcement in auto-planner and defensive crash guards in Tsiolkovsky fuel tracker.

## 2026-03-12
- 2026-03-12 | [Physics] | Dev 1 (AI) | Fixed Stage-2 KDTree false-negative: expanded query radius from 50 km → 200 km. The original 50 km radius created a blind spot for crossing-orbit pairs that start >50 km apart but converge to <100 m within the TCA refinement window — a collision-critical miss undetectable by the original filter. The 200 km radius eliminates this class of false negatives while the pipeline remains O(S·log D); Stage-1 altitude filtering still reduces the candidate set by ~85% before the KDTree is even built.
- 2026-03-12 | [Physics] | Dev 1 (AI) | Fixed EOL graveyard burn LOS constraint violation (simulation.py Step 6): graveyard burn was queued at a fixed +70s offset with no ground-station LOS check, violating PRD §4.4. Fix propagates dense DOP853 over a 6000s (~1 orbit) horizon and scans in 60s increments for the earliest LOS window before queuing the burn. RTN→ECI rotation is now also computed at burn epoch rather than planning epoch.

## 2026-03-13
- 2026-03-13 | [Infra] | Vishal | Fixed `run_dataset.py` to launch uvicorn from `backend/` directory (was failing due to relative imports). Updated `backend/requirements.txt` with Python 3.14-compatible package versions.
- 2026-03-13 | [Frontend] | Vishal | Implemented `GlobeView.jsx`: 3D satellite points (status-colored via vertex colors) and debris cloud rendering using Three.js BufferGeometry for single-draw-call performance.
- 2026-03-13 | [Frontend] | Vishal | Implemented `GroundTrack.jsx`: 2D Canvas Mercator projection with satellite dots, status coloring, glow effects, and lat/lon grid labels using ECI-to-geodetic conversion.
- 2026-03-13 | [Frontend] | Vishal | Implemented `BullseyePlot.jsx`: SVG polar conjunction chart with concentric risk rings (1km/5km/10km), crosshairs, and selected satellite info display.
- 2026-03-13 | [Frontend] | Vishal | Implemented `ManeuverTimeline.jsx`: 24-hour horizontal timeline bar with simulation clock marker, maneuver count display, and burn/cooldown/blackout legend.
- 2026-03-13 | [Frontend] | Vishal | Added satellite click-to-select in `FuelHeatmap.jsx` to enable BullseyePlot interaction.
