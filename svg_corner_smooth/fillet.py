"""Fillet validation helpers with iterative radius shrinking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import FilletValidationResult

from . import _legacy


@dataclass
class FilletSettings:
    """Safety controls for fillet application."""

    max_radius_shrink_iterations: int = 8
    min_allowed_radius: float = 0.25
    skip_invalid_corners: bool = True
    exact_curve_trim: bool = True
    intersection_safety_margin: float = 0.01


def validate_fillet(corner: Any, radius: float, settings: FilletSettings) -> FilletValidationResult:
    """Validate if fillet geometry can be built for a corner and radius."""
    if radius < settings.min_allowed_radius:
        return FilletValidationResult(valid=False, reason="radius_below_min", radius=radius, iterations=0)

    geometry = _legacy.compute_corner_arc_geometry(corner, desired_radius=radius)
    if geometry is None:
        return FilletValidationResult(valid=False, reason="geometry_unstable", radius=radius, iterations=0)

    arc_start, arc_end, _center, used_radius = geometry
    if used_radius < settings.min_allowed_radius:
        return FilletValidationResult(valid=False, reason="effective_radius_below_min", radius=used_radius, iterations=0)

    chord = abs(arc_end - arc_start)
    if chord <= settings.intersection_safety_margin:
        return FilletValidationResult(valid=False, reason="degenerate_chord", radius=used_radius, iterations=0)

    return FilletValidationResult(valid=True, reason="ok", radius=used_radius, iterations=0)


def shrink_radius_until_valid(corner: Any, initial_radius: float, settings: FilletSettings) -> FilletValidationResult:
    """Iteratively shrink radius until fillet becomes valid or fails permanently."""
    radius = initial_radius
    for iteration in range(settings.max_radius_shrink_iterations + 1):
        result = validate_fillet(corner, radius=radius, settings=settings)
        result.iterations = iteration
        if result.valid:
            return result
        radius *= 0.82
        if radius < settings.min_allowed_radius:
            return FilletValidationResult(
                valid=False,
                reason="radius_shrunk_below_min",
                radius=radius,
                iterations=iteration,
            )

    return FilletValidationResult(valid=False, reason="max_shrink_iterations_reached", radius=radius, iterations=settings.max_radius_shrink_iterations)
