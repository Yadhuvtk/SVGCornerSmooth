"""Curvature estimation and localized spike detection helpers."""

from __future__ import annotations

import math

from svgpathtools import Arc, CubicBezier, QuadraticBezier

from .utils import clamp


def _cross(a: complex, b: complex) -> float:
    return abs((a.real * b.imag) - (a.imag * b.real))


def _first_derivative(segment: object, t_value: float) -> complex | None:
    try:
        return complex(segment.derivative(t_value))
    except Exception:
        return None


def _second_derivative_numeric(segment: object, t_value: float, dt: float = 1e-4) -> complex | None:
    t0 = clamp(t_value - dt, 0.0, 1.0)
    t1 = clamp(t_value + dt, 0.0, 1.0)
    if abs(t1 - t0) < 1e-12:
        return None

    d0 = _first_derivative(segment, t0)
    d1 = _first_derivative(segment, t1)
    if d0 is None or d1 is None:
        return None
    return (d1 - d0) / (t1 - t0)


def _curvature_from_derivatives(first: complex, second: complex) -> float:
    denom = abs(first) ** 3
    if denom <= 1e-12:
        return 0.0
    return float(_cross(first, second) / denom)


def bezier_curvature(segment: CubicBezier | QuadraticBezier, t: float) -> float:
    """Curvature for a bezier segment at parameter t."""
    t = clamp(t, 0.0, 1.0)
    first = _first_derivative(segment, t)
    if first is None:
        return 0.0
    second = _second_derivative_numeric(segment, t)
    if second is None:
        return 0.0
    return _curvature_from_derivatives(first, second)


def arc_curvature(segment: Arc, t: float) -> float:
    """
    Approximate curvature for an arc segment at t.

    For elliptical arcs curvature varies along the sweep; we use a stable
    proxy from local derivatives with a radius fallback.
    """
    t = clamp(t, 0.0, 1.0)
    first = _first_derivative(segment, t)
    second = _second_derivative_numeric(segment, t)
    if first is not None and second is not None:
        value = _curvature_from_derivatives(first, second)
        if value > 0.0:
            return value

    rx = abs(segment.radius.real)
    ry = abs(segment.radius.imag)
    min_radius = max(min(rx, ry), 1e-9)
    return float(1.0 / min_radius)


def _segment_curvature(segment: object, t: float) -> float:
    if isinstance(segment, (CubicBezier, QuadraticBezier)):
        return bezier_curvature(segment, t)
    if isinstance(segment, Arc):
        return arc_curvature(segment, t)

    first = _first_derivative(segment, t)
    second = _second_derivative_numeric(segment, t)
    if first is None or second is None:
        return 0.0
    return _curvature_from_derivatives(first, second)


def sample_curvature_profile(segment: object, num_samples: int) -> list[tuple[float, float]]:
    """Sample a segment curvature profile as (t, curvature)."""
    if num_samples < 5:
        num_samples = 5
    profile: list[tuple[float, float]] = []
    for index in range(num_samples):
        t_value = index / (num_samples - 1)
        profile.append((t_value, _segment_curvature(segment, t_value)))
    return profile


def detect_curvature_spikes(
    profile: list[tuple[float, float]],
    relative_threshold: float,
    locality_window: int,
) -> list[tuple[int, float, float]]:
    """
    Detect localized curvature spikes from a profile.

    Returns tuples of (index, t, curvature).
    """
    if len(profile) < 5:
        return []

    values = [value for _, value in profile]
    baseline = max(sum(values) / len(values), 1e-9)
    spikes: list[tuple[int, float, float]] = []

    for index in range(1, len(profile) - 1):
        t_value, current = profile[index]
        if current <= 0.0:
            continue

        left = max(0, index - locality_window)
        right = min(len(profile) - 1, index + locality_window)
        neighborhood = values[left : right + 1]
        local_mean = max(sum(neighborhood) / len(neighborhood), 1e-9)
        local_max = max(neighborhood)

        if current + 1e-12 < local_max:
            continue

        spike_ratio = current / max(local_mean, baseline)
        if spike_ratio < relative_threshold:
            continue

        # Avoid broad smooth bends by requiring local contrast.
        left_neighbor = values[index - 1]
        right_neighbor = values[index + 1]
        contrast = current / max((left_neighbor + right_neighbor) * 0.5, 1e-9)
        if contrast < 1.15:
            continue

        spikes.append((index, t_value, current))

    return spikes
