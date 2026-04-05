"""
config.py — Physical Constants & System Parameters
═══════════════════════════════════════════════════
FROZEN AFTER DAY 1. This file is the SINGLE SOURCE OF TRUTH for all
physical constants. Every module imports from here. DO NOT duplicate
these values anywhere in the codebase.

Source: Problem Statement PDF + PRD Section 4.2
"""

# ── Earth & Gravity ──────────────────────────────────────────────────────
MU_EARTH: float = 398600.4418          # km³/s² — Earth gravitational parameter
J2: float = 1.08263e-3                 # J2 zonal harmonic coefficient (dimensionless)
R_EARTH: float = 6378.137             # km — Earth equatorial radius

# ── Propulsion ───────────────────────────────────────────────────────────
G0: float = 9.80665                    # m/s² — standard gravity (for Tsiolkovsky)
ISP: float = 300.0                     # s — specific impulse (monopropellant thruster)
M_DRY: float = 500.0                   # kg — satellite dry mass (empty)
M_FUEL_INIT: float = 50.0             # kg — initial propellant mass per satellite
M_WET_INIT: float = 550.0             # kg — initial wet mass (M_DRY + M_FUEL_INIT)
MAX_DV_PER_BURN: float = 15.0         # m/s — maximum delta-v per single burn command
RTOL: float = 1e-10                  # Relative tolerance for DOP853
ATOL: float = 1e-12                  # Absolute tolerance for DOP853

# ── Operational Constraints ──────────────────────────────────────────────
THRUSTER_COOLDOWN_S: float = 600.0     # seconds — mandatory rest between burns
SIGNAL_LATENCY_S: float = 10.0        # seconds — command uplink delay
CONJUNCTION_THRESHOLD_KM: float = 0.100  # km (100 m) — critical miss distance
STATION_KEEPING_RADIUS_KM: float = 10.0  # km — nominal slot bounding sphere
EOL_FUEL_THRESHOLD_KG: float = 2.5    # kg — 5% of 50 kg → graveyard orbit trigger
LOOKAHEAD_HOURS: float = 24.0         # hours — conjunction prediction window

# ── Collision Assessment Tuning ──────────────────────────────────────────
CA_KDTREE_RADIUS_MAX_KM: float = 2000.0   # km — KDTree search radius cap
CA_KDTREE_RADIUS_MIN_KM: float = 200.0    # km — KDTree search radius floor
CA_MAX_DENSE_DEBRIS: int = 2000            # Max debris for Stage-3 dense propagation
CA_COARSE_GRID_SPACING_S: float = 200.0    # seconds — coarse sweep grid spacing
CA_THREATENING_DIST_KM: float = 50.0       # km — threshold for Stage-4 TCA refinement
CA_SAT_VS_SAT_RADIUS_KM: float = 2000.0   # km — KDTree radius for sat-vs-sat checks
CA_MULTISTART_WINDOW_S: float = 14400.0    # seconds — 4h multi-start Brent window
CA_ORBITAL_SHELL_BUFFER_KM: float = 5.0    # km — per-pair orbital shell altitude buffer
CA_ALTITUDE_SHELL_MARGIN_KM: float = 50.0  # km — Stage 1 altitude band margin
CA_BRENT_WINDOW_HALF_S: float = 600.0      # seconds — ±10 min TCA refinement half-window

# ── Maneuver Planner Tuning ─────────────────────────────────────────────
RTS_TRANSFER_DURATION_S: float = 5400.0    # seconds — return-to-slot CW transfer (~90 min)
RECOVERY_TRIGGER_DISTANCE_KM: float = 50.0 # km — min debris separation to start recovery
STATION_KEEPING_PREDICTIVE_THRESHOLD_KM: float = 7.0  # km — predictive SK correction trigger
GRAVEYARD_TARGET_PERIGEE_KM: float = 150.0 # km — EOL deorbit perigee target
EOL_GS_SEARCH_WINDOW_S: float = 6000.0     # seconds — EOL ground station opportunity window

# ── Kessler Risk Assessment ─────────────────────────────────────────────
KESSLER_SHELL_WIDTH_KM: float = 50.0       # km — altitude band width per shell
KESSLER_MIN_ALT_KM: float = 200.0          # km — lowest LEO shell
KESSLER_MAX_ALT_KM: float = 2000.0         # km — highest LEO shell
KESSLER_AVG_CROSS_SECTION_M2: float = 10.0 # m² — average collision cross-section
KESSLER_AVG_REL_VELOCITY_KMS: float = 10.0 # km/s — average LEO relative velocity
KESSLER_ASSESSMENT_WINDOW_S: float = 86400.0  # seconds — 24h risk window
KESSLER_NASA_CRITICAL_DENSITY: float = 1.0e-8 # objects/km³ — NASA stability threshold

# ── Derived Constants (computed once) ────────────────────────────────────
G0_KM: float = G0 * 1e-3              # km/s² — standard gravity in km units
LOOKAHEAD_SECONDS: float = LOOKAHEAD_HOURS * 3600.0  # seconds
