"""
fuel_tracker.py — Tsiolkovsky Rocket Equation & EOL Logic
═════════════════════════════════════════════════════════
Tracks per-satellite propellant consumption using the Tsiolkovsky mass
depletion equation, and triggers End-of-Life graveyard orbit logic at
the 5 % fuel threshold.
Owner: Dev 1 (Physics Engine)

Mass depletion equation (Problem Statement §4.3):
    Δm = m_current × (1 − e^(−|Δv| / (Isp × g₀)))

    where:
        m_current  = M_dry + m_fuel_remaining  (current wet mass, kg)
        |Δv|       = delta-v magnitude          (m/s — NOT km/s)
        Isp        = 300 s                      (monopropellant specific impulse)
        g₀         = 9.80665 m/s²               (standard gravity)

EOL threshold: m_fuel ≤ 2.5 kg  (≡ 5 % of 50 kg initial propellant load).
"""

from __future__ import annotations

import logging

import numpy as np

from config import (
    ISP,
    G0,
    M_DRY,
    M_FUEL_INIT,
    EOL_FUEL_THRESHOLD_KG,
    MAX_DV_PER_BURN,
)

logger = logging.getLogger("acm.engine.fuel")


class FuelTracker:
    """Tracks propellant state for every satellite in the constellation.

    All fuel quantities are in kg.  Delta-v inputs must be in m/s.
    """

    def __init__(self) -> None:
        # {sat_id → remaining propellant mass (kg)}
        self._fuel: dict[str, float] = {}

    def register_satellite(self, sat_id: str, fuel_kg: float = M_FUEL_INIT) -> None:
        """Register a satellite with its initial propellant load.

        Args:
            sat_id:   Unique satellite identifier.
            fuel_kg:  Initial propellant mass in kg (default: 50 kg per PRD §4.3).
        """
        self._fuel[sat_id] = fuel_kg

    def estimate_fuel_consumption(self, sat_id: str, delta_v_ms: float) -> float:
        """Estimate propellant required for a burn without consuming it.

        Args:
            sat_id:      Satellite identifier.
            delta_v_ms:  Delta-v magnitude in m/s.

        Returns:
            Propellant mass required (kg).
        """
        current_fuel: float = self._fuel.get(sat_id, 0.0)
        current_mass: float = M_DRY + current_fuel
        exponent: float = -abs(delta_v_ms) / (ISP * G0)
        fuel_needed: float = current_mass * (1.0 - np.exp(exponent))
        return float(fuel_needed)

    def consume(self, sat_id: str, delta_v_ms: float) -> float:
        """Apply the Tsiolkovsky equation and deduct fuel for a completed burn.

        Implements Problem Statement §4.3:
            Δm = m_current × (1 − e^(−|Δv| / (Isp × g₀)))

        Args:
            sat_id:      Satellite identifier.
            delta_v_ms:  Delta-v magnitude in **m/s**.  Passing km/s will silently
                         under-consume fuel; validation guards against this.

        Returns:
            Propellant mass consumed (kg).

        Raises:
            ValueError: If delta_v_ms exceeds MAX_DV_PER_BURN + 1.0 m/s,
                        which is almost certainly a unit error (km/s passed as m/s).
        """
        if delta_v_ms > MAX_DV_PER_BURN + 1.0:
            logger.critical(
                "FUEL | %s | delta_v_ms=%.4f exceeds max burn (%.1f m/s) — "
                "rejecting burn execution.",
                sat_id, delta_v_ms, MAX_DV_PER_BURN,
            )
            raise ValueError(f"Burn delta-v {delta_v_ms:.4f} m/s exceeds limit of {MAX_DV_PER_BURN} m/s")

        current_fuel: float = self._fuel.get(sat_id, 0.0)
        fuel_consumed = self.estimate_fuel_consumption(sat_id, delta_v_ms)

        # Clamp to available propellant — cannot consume more than we have
        fuel_consumed = min(fuel_consumed, current_fuel)
        self._fuel[sat_id] = current_fuel - fuel_consumed

        logger.info(
            "FUEL | %s | ΔV=%.4f m/s | Consumed=%.3f kg | Remaining=%.2f kg",
            sat_id, delta_v_ms, fuel_consumed, self._fuel[sat_id],
        )

        if self.is_eol(sat_id):
            logger.warning(
                "EOL | %s | Fuel=%.2f kg ≤ threshold (%.1f kg) | "
                "Graveyard maneuver required",
                sat_id, self._fuel[sat_id], EOL_FUEL_THRESHOLD_KG,
            )

        return fuel_consumed

    def get_fuel(self, sat_id: str) -> float:
        """Return remaining propellant mass for a satellite (kg).

        Returns 0.0 for unknown satellites (safe default).
        """
        return self._fuel.get(sat_id, 0.0)

    def get_current_mass(self, sat_id: str) -> float:
        """Return current wet mass (dry mass + remaining propellant) in kg."""
        return M_DRY + self.get_fuel(sat_id)

    def is_eol(self, sat_id: str) -> bool:
        """Return True if satellite has reached the End-of-Life fuel threshold.

        EOL threshold: m_fuel ≤ 2.5 kg  (5 % of 50 kg initial load, PRD §4.6).
        """
        return self.get_fuel(sat_id) <= EOL_FUEL_THRESHOLD_KG

    def sufficient_fuel(self, sat_id: str, delta_v_ms: float) -> bool:
        """Return True if the satellite has enough propellant for the proposed burn.

        Uses the Tsiolkovsky equation to compute required fuel before committing.

        Args:
            sat_id:      Satellite identifier.
            delta_v_ms:  Requested delta-v magnitude in m/s.

        Returns:
            True if current fuel ≥ required fuel for the burn.
        """
        fuel_needed = self.estimate_fuel_consumption(sat_id, delta_v_ms)
        return self.get_fuel(sat_id) >= fuel_needed
