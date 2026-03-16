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

# ── Derived Constants (computed once) ────────────────────────────────────
G0_KM: float = G0 * 1e-3              # km/s² — standard gravity in km units
LOOKAHEAD_SECONDS: float = LOOKAHEAD_HOURS * 3600.0  # seconds
