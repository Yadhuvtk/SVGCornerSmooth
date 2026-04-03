"""Tangent estimation helpers for joins and curve endpoints."""

from __future__ import annotations

import math
from typing import Optional

from svgpathtools import Line

from .utils import clamp

_MIN_TANGENT_MAG = 1e-9


def safe_unit_vector(vector: complex, fallback: complex = (1 + 0j)) -> complex:
    """Return a safe unit vector, using fallback when the input magnitude is tiny."""
    magnitude = abs(vector)
    if magnitude < _MIN_TANGENT_MAG:
        fb_mag = abs(fallback)
        if fb_mag < _MIN_TANGENT_MAG:
            return 1 + 0j
        return fallback / fb_mag
    return vector / magnitude


def safe_normalize(vec: complex, fallback: complex = (1 + 0j)) -> complex:
    """Backwards-compatible alias for safe unit normalization."""
    return safe_unit_vector(vec, fallback=fallback)


def tangent_angle_degrees(vector_a: complex, vector_b: complex) -> float:
    """Angle in degrees between two tangent vectors."""
    ua = safe_unit_vector(vector_a)
    ub = safe_unit_vector(vector_b)
    dot = clamp((ua.real * ub.real) + (ua.imag * ub.imag), -1.0, 1.0)
    return float(math.degrees(math.acos(dot)))


def _normalize_with_confidence(
    vector: complex,
    *,
    primary_confidence: float,
    fallback: complex = (1 + 0j),
    fallback_confidence: float = 0.1,
) -> tuple[complex, float]:
    magnitude = abs(vector)
    if magnitude < _MIN_TANGENT_MAG:
        return safe_unit_vector(fallback), fallback_confidence
    return vector / magnitude, primary_confidence


def _probe_direction(segment: object, t_value: float, eps: float) -> tuple[complex, float]:
    """Probe tangent by finite difference around a parameter value."""
    t0 = clamp(t_value - eps, 0.0, 1.0)
    t1 = clamp(t_value + eps, 0.0, 1.0)
    if abs(t1 - t0) < 1e-12:
        return 1 + 0j, 0.0
    try:
        sampled = complex(segment.point(t1) - segment.point(t0))
    except Exception:
        return 1 + 0j, 0.0
    return _normalize_with_confidence(sampled, primary_confidence=0.45)


def _endpoint_tangent(segment: object, *, at_end: bool, eps: float) -> tuple[complex, float]:
    """Robust endpoint tangent and confidence for all supported segment types."""
    if isinstance(segment, Line):
        direction = complex(segment.end - segment.start)
        if abs(direction) < _MIN_TANGENT_MAG:
            return 1 + 0j, 0.0
        return safe_unit_vector(direction), 1.0

    t_value = 1.0 if at_end else 0.0
    try:
        derivative = complex(segment.derivative(t_value))
        if abs(derivative) >= _MIN_TANGENT_MAG:
            return safe_unit_vector(derivative), 1.0
    except Exception:
        pass

    # Endpoint derivatives can be degenerate for some glyph outlines.
    # Probe close-by parameters before falling back to finite differences.
    probe_steps = (eps, eps * 3.0, eps * 8.0, eps * 16.0)
    probe_t_values: list[float] = []
    if at_end:
        probe_t_values.extend(clamp(1.0 - step, 0.0, 1.0) for step in probe_steps)
    else:
        probe_t_values.extend(clamp(step, 0.0, 1.0) for step in probe_steps)

    for probe_t in probe_t_values:
        try:
            derivative = complex(segment.derivative(probe_t))
        except Exception:
            continue
        if abs(derivative) >= _MIN_TANGENT_MAG:
            return safe_unit_vector(derivative), 0.72

    return _probe_direction(segment, t_value=t_value, eps=max(eps, 1e-6))


def segment_start_tangent(segment: object, eps: float = 1e-5) -> tuple[complex, float]:
    """Start-point tangent and confidence for a segment."""
    return _endpoint_tangent(segment, at_end=False, eps=eps)


def segment_end_tangent(segment: object, eps: float = 1e-5) -> tuple[complex, float]:
    """End-point tangent and confidence for a segment."""
    return _endpoint_tangent(segment, at_end=True, eps=eps)


def sample_endpoint_vector(segment: object, at_end: bool, step: float) -> complex:
    """Sample directional vector near segment endpoint."""
    step = clamp(step, 1e-6, 0.5)
    if at_end:
        return complex(segment.point(1.0) - segment.point(1.0 - step))
    return complex(segment.point(step) - segment.point(0.0))


def estimate_endpoint_tangent(segment: object, at_end: bool, samples_per_curve: int) -> Optional[complex]:
    """Estimate stable tangent direction at a segment endpoint."""
    _ = samples_per_curve  # kept for signature compatibility
    tangent, confidence = segment_end_tangent(segment) if at_end else segment_start_tangent(segment)
    if confidence <= 0.0:
        return None
    return tangent


def estimate_tangent_at_t(segment: object, t_value: float, samples_per_curve: int) -> Optional[complex]:
    """Estimate stable tangent at arbitrary segment parameter t."""
    t_value = clamp(t_value, 0.0, 1.0)

    try:
        derivative = complex(segment.derivative(t_value))
        if abs(derivative) >= _MIN_TANGENT_MAG:
            return safe_unit_vector(derivative)
    except Exception:
        pass

    dt = 1.0 / max(12, samples_per_curve * 4)
    t0 = clamp(t_value - dt, 0.0, 1.0)
    t1 = clamp(t_value + dt, 0.0, 1.0)
    if abs(t1 - t0) <= 1e-12:
        return None

    try:
        sampled = complex(segment.point(t1) - segment.point(t0))
        if abs(sampled) < _MIN_TANGENT_MAG:
            return None
        return safe_unit_vector(sampled)
    except Exception:
        return None
