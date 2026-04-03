"""Tangent estimation helpers for joins and curve endpoints."""

from __future__ import annotations

from typing import Optional

from svgpathtools import Arc, CubicBezier, Line, QuadraticBezier

from .utils import clamp

_MIN_TANGENT_MAG = 1e-9


def safe_normalize(vec: complex, fallback: complex = (1 + 0j)) -> complex:
    """Normalize vector safely, using normalized fallback for tiny vectors."""
    magnitude = abs(vec)
    if magnitude < _MIN_TANGENT_MAG:
        fallback_magnitude = abs(fallback)
        if fallback_magnitude < _MIN_TANGENT_MAG:
            return 1 + 0j
        return fallback / fallback_magnitude
    return vec / magnitude


def sample_endpoint_vector(segment: object, at_end: bool, step: float) -> complex:
    """Sample directional vector near segment endpoint."""
    step = clamp(step, 1e-6, 0.5)
    if at_end:
        return complex(segment.point(1.0) - segment.point(1.0 - step))
    return complex(segment.point(step) - segment.point(0.0))


def estimate_endpoint_tangent(segment: object, at_end: bool, samples_per_curve: int) -> Optional[complex]:
    """Estimate stable tangent direction at a segment endpoint."""
    if isinstance(segment, Line):
        direction = complex(segment.end - segment.start)
        if abs(direction) < _MIN_TANGENT_MAG:
            return None
        return safe_normalize(direction)

    candidates: list[complex] = []
    derivative_t = 1.0 if at_end else 0.0
    use_derivative = isinstance(segment, (CubicBezier, QuadraticBezier)) or not isinstance(segment, Arc)

    if use_derivative:
        try:
            candidates.append(complex(segment.derivative(derivative_t)))
        except Exception:
            pass

    base_step = 1.0 / max(2, samples_per_curve)
    for factor in (1.0, 2.0, 4.0, 8.0):
        try:
            candidate = sample_endpoint_vector(segment, at_end=at_end, step=base_step * factor)
            if abs(candidate) < _MIN_TANGENT_MAG:
                continue
            candidates.append(candidate)
        except Exception:
            continue

    for vector in candidates:
        if abs(vector) < _MIN_TANGENT_MAG:
            continue
        return safe_normalize(vector)

    return None


def estimate_tangent_at_t(segment: object, t_value: float, samples_per_curve: int) -> Optional[complex]:
    """Estimate stable tangent at arbitrary segment parameter t."""
    t_value = clamp(t_value, 0.0, 1.0)

    try:
        derivative = complex(segment.derivative(t_value))
        if abs(derivative) >= _MIN_TANGENT_MAG:
            return safe_normalize(derivative)
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
        return safe_normalize(sampled)
    except Exception:
        return None
