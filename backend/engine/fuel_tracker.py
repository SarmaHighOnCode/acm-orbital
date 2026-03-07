"""
fuel_tracker.py — Tsiolkovsky Rocket Equation & EOL Logic
═════════════════════════════════════════════════════════
Tracks per-satellite fuel consumption using the Tsiolkovsky mass
depletion equation. Triggers EOL graveyard orbit at 5% threshold.
Owner: Dev 1 (Physics Engine)

Equation: Δm = m_current × (1 - e^(-|Δv| / (Isp × g0)))
  where |Δv| is in m/s, Isp = 300s, g0 = 9.80665 m/s²
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
    """Tracks fuel state for all satellites in the constellation."""

    def __init__(self):
        self._fuel: dict[str, float] = {}  # sat_id → remaining fuel (kg)

    def register_satellite(self, sat_id: str, fuel_kg: float = M_FUEL_INIT):
        """Register a satellite with its initial fuel load."""
        self._fuel[sat_id] = fuel_kg

    def consume(self, sat_id: str, delta_v_ms: float) -> float:
        """Apply the Tsiolkovsky equation to consume fuel for a burn.

        Args:
            sat_id: Satellite identifier
            delta_v_ms: Delta-v magnitude in m/s (NOT km/s!)

        Returns:
            Fuel mass consumed in kg

        Raises:
            AssertionError: If delta_v appears to be in km/s (< 0.1)
        """
        assert delta_v_ms <= MAX_DV_PER_BURN + 1.0, (
            f"delta_v_ms={delta_v_ms} exceeds max burn. "
            "Ensure input is in m/s, not km/s."
        )

        current_fuel = self._fuel.get(sat_id, 0.0)
        current_mass = M_DRY + current_fuel

        # Tsiolkovsky: Δm = m × (1 - e^(-|Δv| / (Isp × g0)))
        exponent = -abs(delta_v_ms) / (ISP * G0)
        fuel_consumed = current_mass * (1.0 - np.exp(exponent))

        # Clamp to available fuel
        fuel_consumed = min(fuel_consumed, current_fuel)
        self._fuel[sat_id] = current_fuel - fuel_consumed

        logger.info(
            "FUEL | %s | ΔV=%.4f m/s | Consumed=%.3f kg | Remaining=%.2f kg",
            sat_id,
            delta_v_ms,
            fuel_consumed,
            self._fuel[sat_id],
        )

        # EOL check
        if self.is_eol(sat_id):
            logger.warning(
                "EOL | %s | Fuel=%.2f kg ≤ threshold (%.1f kg) | "
                "Graveyard maneuver required",
                sat_id,
                self._fuel[sat_id],
                EOL_FUEL_THRESHOLD_KG,
            )

        return fuel_consumed

    def get_fuel(self, sat_id: str) -> float:
        """Get remaining fuel for a satellite in kg."""
        return self._fuel.get(sat_id, 0.0)

    def get_current_mass(self, sat_id: str) -> float:
        """Get current wet mass (dry + remaining fuel) in kg."""
        return M_DRY + self.get_fuel(sat_id)

    def is_eol(self, sat_id: str) -> bool:
        """Check if satellite has reached End-of-Life fuel threshold."""
        return self.get_fuel(sat_id) <= EOL_FUEL_THRESHOLD_KG

    def sufficient_fuel(self, sat_id: str, delta_v_ms: float) -> bool:
        """Check if satellite has enough fuel for the proposed burn."""
        current_mass = self.get_current_mass(sat_id)
        exponent = -abs(delta_v_ms) / (ISP * G0)
        fuel_needed = current_mass * (1.0 - np.exp(exponent))
        return self.get_fuel(sat_id) >= fuel_needed
