"""
test_collision.py — ConjunctionAssessor Unit Tests
═══════════════════════════════════════════════════
Owner: Dev 1 (Physics Engine)
"""

import numpy as np
import pytest

from engine.collision import ConjunctionAssessor


def test_classify_risk_critical():
    """Objects within 100m should be CRITICAL."""
    assert ConjunctionAssessor._classify_risk(0.05) == "CRITICAL"


def test_classify_risk_red():
    """Objects within 1km but above 100m should be RED."""
    assert ConjunctionAssessor._classify_risk(0.5) == "RED"


def test_classify_risk_yellow():
    """Objects within 5km but above 1km should be YELLOW."""
    assert ConjunctionAssessor._classify_risk(3.0) == "YELLOW"


def test_classify_risk_green():
    """Objects above 5km should be GREEN."""
    assert ConjunctionAssessor._classify_risk(10.0) == "GREEN"


def test_assess_returns_list(propagator):
    """assess() must return a list of CDM objects."""
    assessor = ConjunctionAssessor(propagator)
    result = assessor.assess(
        sat_states={"SAT-01": np.array([6778.0, 0, 0, 0, 7.67, 0])},
        debris_states={"DEB-01": np.array([6778.0, 100, 0, 0, 7.67, 0])},
        lookahead_s=3600.0,
    )
    assert isinstance(result, list)


def test_assess_emits_cdm_for_close_approach(propagator):
    """Objects within 1 km and identical velocity → CDM emitted with YELLOW risk."""
    assessor = ConjunctionAssessor(propagator)
    # Debris 1 km ahead along x-axis; same velocity → constant separation → TCA miss ≈ 1 km
    result = assessor.assess(
        sat_states={"SAT-01": np.array([6778.0, 0.0, 0.0, 0.0, 7.67, 0.0])},
        debris_states={"DEB-01": np.array([6779.0, 0.0, 0.0, 0.0, 7.67, 0.0])},
        lookahead_s=3600.0,
    )
    assert len(result) >= 1, "Should emit at least one YELLOW CDM"
    assert result[0].satellite_id == "SAT-01"
    assert result[0].debris_id == "DEB-01"
    assert result[0].risk == "YELLOW"


def test_kdtree_filters_distant_objects(propagator):
    """Objects 100 km apart must not produce a CDM (outside KDTree 50 km radius)."""
    assessor = ConjunctionAssessor(propagator)
    result = assessor.assess(
        sat_states={"SAT-01": np.array([6778.0, 0.0, 0.0, 0.0, 7.67, 0.0])},
        debris_states={"DEB-01": np.array([6778.0, 100.0, 0.0, 0.0, 7.67, 0.0])},
        lookahead_s=3600.0,
    )
    assert result == []


def test_classify_risk_boundary_at_threshold(propagator):
    """Miss distance exactly at CONJUNCTION_THRESHOLD_KM (0.1 km) → RED, not CRITICAL."""
    from config import CONJUNCTION_THRESHOLD_KM
    assert ConjunctionAssessor._classify_risk(CONJUNCTION_THRESHOLD_KM) == "RED"


def test_assess_emits_critical_cdm_for_near_collision(propagator):
    """Objects 0.05 km apart with identical velocity → CRITICAL CDM emitted."""
    assessor = ConjunctionAssessor(propagator)
    result = assessor.assess(
        sat_states={"SAT-01": np.array([6778.000, 0.0, 0.0, 0.0, 7.67, 0.0])},
        debris_states={"DEB-01": np.array([6778.050, 0.0, 0.0, 0.0, 7.67, 0.0])},
        lookahead_s=3600.0,
    )
    assert len(result) >= 1, "Should emit at least one CRITICAL CDM"
    assert result[0].risk == "CRITICAL"
