"""Radius profile calculations for per-corner fillet sizing."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import SUPPORTED_RADIUS_PROFILES
from .models import CornerSeverity
from .utils import clamp


@dataclass
class RadiusContext:
    """Context values used by radius profile functions."""

    distance_to_prev_corner: float
    distance_to_next_corner: float
    collision_risk: float


def _legacy_vectorizer(corner: CornerSeverity, requested_radius: float) -> float:
    angle = corner.angle_deg
    if angle >= 120.0:
        angle_scale = 0.28
    elif angle >= 105.0:
        angle_scale = 0.38
    elif angle >= 90.0:
        angle_scale = 0.55
    elif angle >= 75.0:
        angle_scale = 0.75
    else:
        angle_scale = 1.0

    local_length = min(corner.prev_segment_length, corner.next_segment_length)
    length_scale = clamp(local_length / (requested_radius * 4.0 + 1e-12), 0.35, 1.0)
    adapted = requested_radius * angle_scale * length_scale
    return max(max(0.5, requested_radius * 0.12), adapted)


def compute_corner_radius(
    corner: CornerSeverity,
    context: RadiusContext,
    requested_radius: float,
    profile: str,
) -> float:
    """Compute effective corner radius according to selected profile."""
    if requested_radius <= 0.0:
        return 0.0

    selected = profile if profile in SUPPORTED_RADIUS_PROFILES else "adaptive"
    local_min = min(corner.prev_segment_length, corner.next_segment_length)
    neighborhood = min(context.distance_to_prev_corner, context.distance_to_next_corner)

    if selected == "fixed":
        radius = requested_radius
    elif selected == "vectorizer_legacy":
        radius = _legacy_vectorizer(corner, requested_radius)
    elif selected == "preserve_shape":
        density_scale = clamp(neighborhood / (requested_radius * 5.0 + 1e-9), 0.22, 1.0)
        angle_scale = clamp((180.0 - corner.angle_deg) / 180.0, 0.25, 0.9)
        radius = requested_radius * angle_scale * density_scale
    elif selected == "aggressive":
        safe_scale = clamp(1.2 - context.collision_risk, 0.45, 1.45)
        radius = requested_radius * safe_scale
    else:
        # adaptive
        angle_weight = clamp((180.0 - corner.angle_deg) / 145.0, 0.30, 1.1)
        density_weight = clamp(neighborhood / (requested_radius * 4.0 + 1e-9), 0.30, 1.0)
        curvature_weight = clamp(1.0 - corner.curvature_hint * 0.45, 0.52, 1.0)
        risk_weight = clamp(1.0 - context.collision_risk * 0.6, 0.35, 1.0)
        radius = requested_radius * angle_weight * density_weight * curvature_weight * risk_weight

    radius = min(radius, local_min * 0.95)
    return max(0.0, radius)
