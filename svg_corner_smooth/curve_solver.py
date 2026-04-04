"""Curve-aware fillet solver used as a robust fallback for rounding."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from svgpathtools import Arc

from .constants import EPSILON, MIN_FILLET_RADIUS
from .tangents import estimate_tangent_at_t, safe_unit_vector, tangent_angle_degrees
from .utils import (
    clamp,
    find_t_at_length_from_start,
    intersect_lines,
    left_normal,
    right_normal,
    safe_segment_length,
)


@dataclass
class CurveFillet:
    """Curve-trim fillet geometry result."""

    prev_trim_t: float
    next_trim_t: float
    arc_center: complex
    arc_radius: float
    arc_start: complex
    arc_end: complex
    sweep_flag: int
    quality_score: float


def _dot(a: complex, b: complex) -> float:
    return float((a.real * b.real) + (a.imag * b.imag))


def _angle_between(a: complex, b: complex) -> float:
    ua = safe_unit_vector(a)
    ub = safe_unit_vector(b)
    return float(math.acos(clamp(_dot(ua, ub), -1.0, 1.0)))


def _join_is_at_end(segment: Any, corner_point: complex) -> bool:
    return abs(complex(segment.end) - corner_point) <= abs(complex(segment.start) - corner_point)


def _segment_tangent(segment: Any, t_value: float, samples_per_curve: int = 32) -> Optional[complex]:
    tangent = estimate_tangent_at_t(segment, t_value, samples_per_curve=samples_per_curve)
    if tangent is not None:
        return safe_unit_vector(tangent)

    for delta in (1e-5, 3e-5, 8e-5, 2e-4, 5e-4):
        t0 = clamp(t_value - delta, 0.0, 1.0)
        t1 = clamp(t_value + delta, 0.0, 1.0)
        if abs(t1 - t0) <= 1e-12:
            continue
        try:
            vec = complex(segment.point(t1) - segment.point(t0))
        except Exception:
            continue
        if abs(vec) > 1e-9:
            return safe_unit_vector(vec)

    return None


def _oriented_tangent_for_join(segment: Any, corner_point: complex, *, incoming: bool) -> Optional[complex]:
    join_at_end = _join_is_at_end(segment, corner_point)
    join_t = 1.0 if join_at_end else 0.0
    tangent = _segment_tangent(segment, join_t)
    if tangent is None:
        return None

    # incoming: direction towards join on this segment
    # outgoing: direction away from join on this segment
    if incoming:
        return tangent if join_at_end else -tangent
    return -tangent if join_at_end else tangent


def _oriented_tangent_at_distance(
    segment: Any,
    corner_point: complex,
    distance_from_join: float,
    *,
    incoming: bool,
) -> Optional[complex]:
    trim_t = _target_trim_t(segment, corner_point, max(0.0, float(distance_from_join)))
    if trim_t is None:
        return None

    join_at_end = _join_is_at_end(segment, corner_point)
    tangent = _segment_tangent(segment, trim_t)
    if tangent is None:
        return None

    if incoming:
        return tangent if join_at_end else -tangent
    return -tangent if join_at_end else tangent


def _target_trim_t(segment: Any, corner_point: complex, trim_distance: float) -> Optional[float]:
    total = safe_segment_length(segment)
    if total <= EPSILON:
        return None

    trim_distance = clamp(trim_distance, 0.0, total * 0.99)
    join_at_end = _join_is_at_end(segment, corner_point)

    if join_at_end:
        target = total - trim_distance
    else:
        target = trim_distance
    return float(find_t_at_length_from_start(segment, target))


def _segment_points_for_intrusion(segment: Any, start_t: float, end_t: float, samples: int = 18) -> list[complex]:
    start_t = clamp(start_t, 0.0, 1.0)
    end_t = clamp(end_t, 0.0, 1.0)
    if abs(end_t - start_t) <= 1e-8:
        return []

    points: list[complex] = []
    for i in range(1, max(2, samples) + 1):
        ratio = i / (samples + 1)
        t = start_t + ((end_t - start_t) * ratio)
        try:
            points.append(complex(segment.point(t)))
        except Exception:
            continue
    return points


def _intrusion_ratio(
    prev_segment: Any,
    next_segment: Any,
    corner_point: complex,
    prev_trim_t: float,
    next_trim_t: float,
    center: complex,
    radius: float,
) -> float:
    if radius <= EPSILON:
        return 1.0

    prev_join_at_end = _join_is_at_end(prev_segment, corner_point)
    next_join_at_end = _join_is_at_end(next_segment, corner_point)

    if prev_join_at_end:
        prev_range = (0.0, prev_trim_t)
    else:
        prev_range = (prev_trim_t, 1.0)

    if next_join_at_end:
        next_range = (0.0, next_trim_t)
    else:
        next_range = (next_trim_t, 1.0)

    max_intrusion = 0.0
    for point in _segment_points_for_intrusion(prev_segment, *prev_range) + _segment_points_for_intrusion(next_segment, *next_range):
        inside = radius - abs(point - center)
        if inside > max_intrusion:
            max_intrusion = inside

    return max(0.0, max_intrusion / max(radius, EPSILON))


def _choose_sweep_flag(
    arc_start: complex,
    arc_end: complex,
    radius: float,
    target_center: complex,
    start_tangent: complex,
    end_tangent: complex,
) -> Optional[int]:
    best_sweep: Optional[int] = None
    best_score = math.inf

    for sweep in (0, 1):
        try:
            arc = Arc(
                start=arc_start,
                radius=complex(radius, radius),
                rotation=0.0,
                large_arc=False,
                sweep=bool(sweep),
                end=arc_end,
            )
        except Exception:
            continue

        center_error = abs(complex(arc.center) - target_center)
        try:
            arc_start_tangent = safe_unit_vector(complex(arc.derivative(0.0)))
            arc_end_tangent = safe_unit_vector(complex(arc.derivative(1.0)))
        except Exception:
            continue

        dot_start = clamp(_dot(arc_start_tangent, safe_unit_vector(start_tangent)), -1.0, 1.0)
        dot_end = clamp(_dot(arc_end_tangent, safe_unit_vector(end_tangent)), -1.0, 1.0)
        tangent_penalty = (1.0 - dot_start) + (1.0 - dot_end)
        score = center_error + (35.0 * tangent_penalty)

        if score < best_score:
            best_score = score
            best_sweep = sweep

    return best_sweep


def solve_curve_fillet(
    prev_segment: Any,
    next_segment: Any,
    desired_radius: float,
    corner_point: complex,
    max_iterations: int = 6,
) -> Optional[CurveFillet]:
    """Solve a curve-aware fillet between any two segment types."""
    if desired_radius <= 0.0:
        return None

    prev_length = safe_segment_length(prev_segment)
    next_length = safe_segment_length(next_segment)
    if prev_length <= 1e-6 or next_length <= 1e-6:
        return None

    incoming_join = _oriented_tangent_for_join(prev_segment, corner_point, incoming=True)
    outgoing_join = _oriented_tangent_for_join(next_segment, corner_point, incoming=False)
    if incoming_join is None or outgoing_join is None:
        return None

    ray_prev = -safe_unit_vector(incoming_join)
    ray_next = safe_unit_vector(outgoing_join)
    corner_theta = _angle_between(ray_prev, ray_next)
    if corner_theta <= math.radians(5.0) or corner_theta >= math.radians(175.0):
        # Curve joins can be C1-continuous exactly at the endpoint while still
        # bending quickly nearby. Probe slightly away from the join before
        # concluding this corner is effectively straight/parallel.
        probe_distance = max(0.25, min(prev_length, next_length) * 0.03)
        incoming_probe = _oriented_tangent_at_distance(
            prev_segment,
            corner_point,
            probe_distance,
            incoming=True,
        )
        outgoing_probe = _oriented_tangent_at_distance(
            next_segment,
            corner_point,
            probe_distance,
            incoming=False,
        )
        if incoming_probe is None or outgoing_probe is None:
            return None
        ray_prev = -safe_unit_vector(incoming_probe)
        ray_next = safe_unit_vector(outgoing_probe)
        corner_theta = _angle_between(ray_prev, ray_next)
        if corner_theta <= math.radians(5.0) or corner_theta >= math.radians(175.0):
            return None

    tan_half = math.tan(corner_theta * 0.5)
    if abs(tan_half) <= 1e-9:
        return None

    max_radius = min(prev_length, next_length) * tan_half * 0.98
    current_radius = min(float(desired_radius), float(max_radius))
    if current_radius < MIN_FILLET_RADIUS:
        return None

    bisector = safe_unit_vector(ray_prev + ray_next)
    best_result: Optional[CurveFillet] = None

    for _ in range(max(1, int(max_iterations))):
        if current_radius < MIN_FILLET_RADIUS:
            break

        trim_distance = current_radius / tan_half
        trim_distance = min(trim_distance, prev_length * 0.95, next_length * 0.95)
        if trim_distance <= 1e-7:
            break

        prev_trim_t = _target_trim_t(prev_segment, corner_point, trim_distance)
        next_trim_t = _target_trim_t(next_segment, corner_point, trim_distance)
        if prev_trim_t is None or next_trim_t is None:
            current_radius *= 0.78
            continue

        try:
            arc_start = complex(prev_segment.point(prev_trim_t))
            arc_end = complex(next_segment.point(next_trim_t))
        except Exception:
            current_radius *= 0.78
            continue

        prev_join_at_end = _join_is_at_end(prev_segment, corner_point)
        next_join_at_end = _join_is_at_end(next_segment, corner_point)

        prev_tangent_raw = _segment_tangent(prev_segment, prev_trim_t)
        next_tangent_raw = _segment_tangent(next_segment, next_trim_t)
        if prev_tangent_raw is None or next_tangent_raw is None:
            current_radius *= 0.78
            continue

        prev_tangent = prev_tangent_raw if prev_join_at_end else -prev_tangent_raw
        next_tangent = -next_tangent_raw if next_join_at_end else next_tangent_raw

        best_center: Optional[complex] = None
        best_center_radius = 0.0
        best_center_score = math.inf

        for prev_normal in (left_normal(prev_tangent), right_normal(prev_tangent)):
            for next_normal in (left_normal(next_tangent), right_normal(next_tangent)):
                center = intersect_lines(arc_start, prev_normal, arc_end, next_normal)
                if center is None:
                    continue

                radius_prev = abs(center - arc_start)
                radius_next = abs(center - arc_end)
                if radius_prev <= 1e-8 or radius_next <= 1e-8:
                    continue

                radius = 0.5 * (radius_prev + radius_next)
                mismatch = abs(radius_prev - radius_next) / max(radius, EPSILON)
                side_dot = _dot(center - corner_point, bisector)
                side_penalty = 0.0 if side_dot > 0.0 else 10.0 + abs(side_dot)
                radius_penalty = abs(radius - current_radius) / max(current_radius, EPSILON)
                score = (mismatch * 18.0) + (radius_penalty * 7.5) + side_penalty
                if score < best_center_score:
                    best_center_score = score
                    best_center = center
                    best_center_radius = radius

        if best_center is None or best_center_radius <= 1e-8:
            current_radius *= 0.78
            continue

        sweep_flag = _choose_sweep_flag(
            arc_start=arc_start,
            arc_end=arc_end,
            radius=best_center_radius,
            target_center=best_center,
            start_tangent=prev_tangent,
            end_tangent=next_tangent,
        )
        if sweep_flag is None:
            current_radius *= 0.78
            continue

        intrusion = _intrusion_ratio(
            prev_segment=prev_segment,
            next_segment=next_segment,
            corner_point=corner_point,
            prev_trim_t=prev_trim_t,
            next_trim_t=next_trim_t,
            center=best_center,
            radius=best_center_radius,
        )

        radius_error = abs(best_center_radius - desired_radius) / max(desired_radius, EPSILON)
        tangent_mismatch = 0.5
        try:
            arc = Arc(
                start=arc_start,
                radius=complex(best_center_radius, best_center_radius),
                rotation=0.0,
                large_arc=False,
                sweep=bool(sweep_flag),
                end=arc_end,
            )
            arc_start_tangent = safe_unit_vector(complex(arc.derivative(0.0)))
            arc_end_tangent = safe_unit_vector(complex(arc.derivative(1.0)))
            dot_start = clamp(_dot(arc_start_tangent, safe_unit_vector(prev_tangent)), -1.0, 1.0)
            dot_end = clamp(_dot(arc_end_tangent, safe_unit_vector(next_tangent)), -1.0, 1.0)
            tangent_mismatch = 0.5 * ((1.0 - dot_start) + (1.0 - dot_end))
        except Exception:
            pass

        quality = clamp(
            1.0 - ((0.52 * radius_error) + (0.28 * intrusion) + (0.20 * tangent_mismatch)),
            0.0,
            1.0,
        )

        result = CurveFillet(
            prev_trim_t=float(prev_trim_t),
            next_trim_t=float(next_trim_t),
            arc_center=complex(best_center),
            arc_radius=float(best_center_radius),
            arc_start=complex(arc_start),
            arc_end=complex(arc_end),
            sweep_flag=int(sweep_flag),
            quality_score=float(quality),
        )

        if best_result is None or result.quality_score > best_result.quality_score:
            best_result = result

        if intrusion <= 0.05 and quality >= 0.85:
            return result

        current_radius *= 0.78

    if best_result is not None and best_result.quality_score >= 0.35:
        return best_result
    return None


def solve_fillet_for_corner_rounding(
    path: Any,
    corner: Any,
    desired_radius: float,
    max_iterations: int = 6,
) -> Optional[dict[str, float | int]]:
    """Last-resort helper: validate corner with curve solver and return legacy-corner payload."""
    if path is None or len(path) == 0:
        return None

    prev_index = int(getattr(corner, "segment_index_before", -1))
    next_index = int(getattr(corner, "segment_index_after", getattr(corner, "node_id", -1)))
    if prev_index < 0 or next_index < 0 or prev_index >= len(path) or next_index >= len(path):
        return None

    corner_point = complex(float(corner.x), float(corner.y))
    prev_segment = path[prev_index]
    next_segment = path[next_index]

    solved = solve_curve_fillet(
        prev_segment=prev_segment,
        next_segment=next_segment,
        desired_radius=desired_radius,
        corner_point=corner_point,
        max_iterations=max_iterations,
    )
    if solved is None:
        return None

    incoming = _oriented_tangent_for_join(prev_segment, corner_point, incoming=True)
    outgoing = _oriented_tangent_for_join(next_segment, corner_point, incoming=False)
    if incoming is None or outgoing is None:
        return None

    return {
        "path_id": int(getattr(corner, "path_id", 0)),
        "node_id": int(next_index),
        "x": float(corner_point.real),
        "y": float(corner_point.imag),
        "angle_deg": float(tangent_angle_degrees(incoming, outgoing)),
        "incoming_dx": float(incoming.real),
        "incoming_dy": float(incoming.imag),
        "outgoing_dx": float(outgoing.real),
        "outgoing_dy": float(outgoing.imag),
        "prev_segment_length": float(safe_segment_length(prev_segment)),
        "next_segment_length": float(safe_segment_length(next_segment)),
    }
