"""Values derived from a blood pressure reading (no Home Assistant imports)."""

from __future__ import annotations

BP_CATEGORIES = (
    "normal",
    "elevated",
    "hypertension_stage_1",
    "hypertension_stage_2",
    "hypertensive_crisis",
)


def pulse_pressure(systolic: int, diastolic: int) -> int:
    return systolic - diastolic


def mean_arterial_pressure(systolic: int, diastolic: int) -> float:
    return round(diastolic + (systolic - diastolic) / 3, 1)


def bp_category(systolic: int, diastolic: int) -> str:
    """ACC/AHA 2017 category; when the two values disagree, the more severe one wins."""
    if systolic > 180 or diastolic > 120:
        return "hypertensive_crisis"
    if systolic >= 140 or diastolic >= 90:
        return "hypertension_stage_2"
    if systolic >= 130 or diastolic >= 80:
        return "hypertension_stage_1"
    if systolic >= 120:
        return "elevated"
    return "normal"
