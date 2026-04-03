"""Fillet validation helpers with iterative radius shrinking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .constants import MIN_FILLET_RADIUS
from .models import FilletValidationResult

from . import _legacy


@dataclass
class FilletSettings:
    """Safety controls for fillet application."""

    max_radius_shrink_iterations: int = 8
    min_allowed_radius: float = MIN_FILLET_RADIUS
    skip_invalid_corners: bool = True
    exact_curve_trim: bool = True
    intersection_safety_margin: float = 0.01


def _compute_fillet(corner: Any, radius: float, settings: FilletSettings) -> FilletValidationResult:
    """Compute fillet geometry and return structured status."""
    geometry = _legacy.compute_corner_arc_geometry(corner, desired_radius=radius)
    if geometry is None:
        return FilletValidationResult(
            status="skipped",
            reason="geometry_unstable",
            corner=corner,
            attempted_radius=radius,
            final_radius=radius,
            iterations=0,
        )

    arc_start, arc_end, _center, used_radius = geometry
    if used_radius < settings.min_allowed_radius:
        return FilletValidationResult(
            status="skipped",
            reason="effective_radius_below_min",
            corner=corner,
            attempted_radius=radius,
            final_radius=used_radius,
            iterations=0,
        )

    chord = abs(arc_end - arc_start)
    if chord <= settings.intersection_safety_margin:
        return FilletValidationResult(
            status="skipped",
            reason="degenerate_chord",
            corner=corner,
            attempted_radius=radius,
            final_radius=used_radius,
            iterations=0,
        )

    status = "shrunk" if used_radius < radius else "ok"
    return FilletValidationResult(
        status=status,
        reason="ok",
        corner=corner,
        attempted_radius=radius,
        final_radius=used_radius,
        iterations=0,
    )


def validate_fillet(corner: Any, radius: float, settings: FilletSettings) -> FilletValidationResult:
    """Validate if fillet geometry can be built for a corner and radius."""
    if radius < settings.min_allowed_radius:
        return FilletValidationResult(
            status="skipped",
            reason="radius_below_min",
            corner=corner,
            attempted_radius=radius,
            final_radius=radius,
            iterations=0,
        )

    try:
        return _compute_fillet(corner=corner, radius=radius, settings=settings)
    except (ValueError, RuntimeError, ZeroDivisionError, FloatingPointError) as exc:
        return FilletValidationResult(
            status="skipped",
            reason=f"solver_error: {type(exc).__name__}: {exc}",
            corner=corner,
            attempted_radius=radius,
            final_radius=radius,
            iterations=0,
        )


def shrink_radius_until_valid(corner: Any, initial_radius: float, settings: FilletSettings) -> FilletValidationResult:
    """Iteratively shrink radius until fillet becomes valid or fails permanently."""
    radius = initial_radius
    for iteration in range(settings.max_radius_shrink_iterations + 1):
        result = validate_fillet(corner, radius=radius, settings=settings)
        result.iterations = iteration
        if result.valid:
            return result
        radius *= 0.82
        if radius < MIN_FILLET_RADIUS:
            return FilletValidationResult(
                status="skipped",
                reason=f"radius_too_small: {radius:.4f}px after shrink",
                corner=corner,
                attempted_radius=initial_radius,
                final_radius=radius,
                iterations=iteration,
            )

    return FilletValidationResult(
        status="skipped",
        reason="max_shrink_iterations_reached",
        corner=corner,
        attempted_radius=initial_radius,
        final_radius=radius,
        iterations=settings.max_radius_shrink_iterations,
    )
