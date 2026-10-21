"""Derived blood pressure values."""

import pytest

from custom_components.ihealth_bp.derived import (
    bp_category,
    mean_arterial_pressure,
    pulse_pressure,
)


@pytest.mark.parametrize(
    ("sys", "dia", "category"),
    [
        (119, 79, "normal"),
        (120, 79, "elevated"),
        (129, 79, "elevated"),
        (130, 79, "hypertension_stage_1"),
        (129, 80, "hypertension_stage_1"),
        (139, 89, "hypertension_stage_1"),
        (140, 80, "hypertension_stage_2"),
        (120, 90, "hypertension_stage_2"),
        (180, 120, "hypertension_stage_2"),
        (181, 80, "hypertensive_crisis"),
        (120, 121, "hypertensive_crisis"),
    ],
)
def test_bp_category_boundaries(sys, dia, category):
    assert bp_category(sys, dia) == category


def test_map_and_pulse_pressure():
    assert pulse_pressure(125, 64) == 61
    assert mean_arterial_pressure(125, 64) == 84.3
    assert mean_arterial_pressure(121, 71) == 87.7
