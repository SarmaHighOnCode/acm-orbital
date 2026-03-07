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
