"""General utilities shared across parser/detector/rounder layers."""

from __future__ import annotations

import math
import re
from typing import Iterable, Optional

from svgpathtools import Arc, CubicBezier, Line, Path, QuadraticBezier

from .constants import EPSILON


TRANSFORM_RE = re.compile(r"([a-zA-Z]+)\(([^\)]*)\)")


def clamp(value: float, min_value: float, max_value: float) -> float:
    """Clamp numeric value into an inclusive range."""
    return max(min_value, min(max_value, value))


def normalize_vector(vector: complex) -> Optional[complex]:
    """Return normalized vector or None if its magnitude is tiny."""
    magnitude = abs(vector)
    if magnitude <= EPSILON:
        return None
    return vector / magnitude


def complex_cross(a: complex, b: complex) -> float:
    """2D cross product of two complex vectors."""
    return (a.real * b.imag) - (a.imag * b.real)


def left_normal(direction: complex) -> complex:
    """Left-hand normal."""
    return complex(-direction.imag, direction.real)


def right_normal(direction: complex) -> complex:
    """Right-hand normal."""
    return complex(direction.imag, -direction.real)


def intersect_lines(point_a: complex, dir_a: complex, point_b: complex, dir_b: complex) -> Optional[complex]:
    """Intersect infinite lines point_a+t*dir_a and point_b+u*dir_b."""
    denominator = complex_cross(dir_a, dir_b)
    if abs(denominator) <= EPSILON:
        return None
    t_value = complex_cross(point_b - point_a, dir_b) / denominator
    return point_a + (dir_a * t_value)


def safe_segment_length(segment: object) -> float:
    """Get segment length robustly for line/bezier/arc/mixed segments."""
    if isinstance(segment, Line):
        return float(abs(segment.end - segment.start))

    try:
        return float(segment.length(error=1e-6))
    except TypeError:
        try:
            return float(segment.length())
        except Exception:
            pass
    except Exception:
        pass

    samples = 20
    total = 0.0
    try:
        previous = segment.point(0.0)
        for index in range(1, samples + 1):
            t_value = index / samples
            current = segment.point(t_value)
            total += abs(current - previous)
            previous = current
    except Exception:
        return 0.0
    return float(total)


def segment_length_between(segment: object, t_start: float, t_end: float) -> float:
    """Length of segment sub-interval [t_start, t_end]."""
    t_start = clamp(t_start, 0.0, 1.0)
    t_end = clamp(t_end, 0.0, 1.0)
    if t_end < t_start:
        t_start, t_end = t_end, t_start
    if abs(t_end - t_start) <= EPSILON:
        return 0.0

    try:
        return float(segment.length(t_start, t_end, error=1e-6))
    except TypeError:
        try:
            return float(segment.length(t_start, t_end))
        except Exception:
            pass
    except Exception:
        pass

    samples = 50
    total = 0.0
    previous = complex(segment.point(t_start))
    for index in range(1, samples + 1):
        t_value = t_start + ((t_end - t_start) * (index / samples))
        current = complex(segment.point(t_value))
        total += abs(current - previous)
        previous = current
    return float(total)


def find_t_at_length_from_start(segment: object, target_length: float) -> float:
    """Find parameter t where distance from segment start equals target_length."""
    total_length = safe_segment_length(segment)
    if total_length <= EPSILON:
        return 0.0
    if target_length <= 0.0:
        return 0.0
    if target_length >= total_length:
        return 1.0

    low = 0.0
    high = 1.0
    for _ in range(42):
        mid = 0.5 * (low + high)
        length_mid = segment_length_between(segment, 0.0, mid)
        if length_mid < target_length:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def parse_bool(value: str | None, default: bool = False) -> bool:
    """Parse truthy/falsey text values."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_float(value: str | None, default: float) -> float:
    """Parse float with default fallback for empty values."""
    if value is None or value == "":
        return default
    return float(value)


def parse_int(value: str | None, default: int) -> int:
    """Parse int with default fallback for empty values."""
    if value is None or value == "":
        return default
    return int(value)


def matrix_multiply(left: tuple[float, float, float, float, float, float], right: tuple[float, float, float, float, float, float]) -> tuple[float, float, float, float, float, float]:
    """Multiply SVG affine matrices represented as (a,b,c,d,e,f)."""
    a1, b1, c1, d1, e1, f1 = left
    a2, b2, c2, d2, e2, f2 = right
    return (
        (a1 * a2) + (c1 * b2),
        (b1 * a2) + (d1 * b2),
        (a1 * c2) + (c1 * d2),
        (b1 * c2) + (d1 * d2),
        (a1 * e2) + (c1 * f2) + e1,
        (b1 * e2) + (d1 * f2) + f1,
    )


def parse_transform(transform_value: str | None) -> tuple[float, float, float, float, float, float]:
    """Parse common SVG transform syntax into affine matrix (a,b,c,d,e,f)."""
    identity = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not transform_value:
        return identity

    matrix = identity
    for command, raw_args in TRANSFORM_RE.findall(transform_value):
        values = [float(part) for part in re.split(r"[\s,]+", raw_args.strip()) if part]
        cmd = command.lower()
        if cmd == "matrix" and len(values) == 6:
            current = tuple(values)
        elif cmd == "translate":
            tx = values[0] if values else 0.0
            ty = values[1] if len(values) > 1 else 0.0
            current = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif cmd == "scale":
            sx = values[0] if values else 1.0
            sy = values[1] if len(values) > 1 else sx
            current = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif cmd == "rotate":
            angle = math.radians(values[0] if values else 0.0)
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            if len(values) >= 3:
                cx, cy = values[1], values[2]
                translate_to = (1.0, 0.0, 0.0, 1.0, cx, cy)
                rotate = (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)
                translate_back = (1.0, 0.0, 0.0, 1.0, -cx, -cy)
                current = matrix_multiply(matrix_multiply(translate_to, rotate), translate_back)
            else:
                current = (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)
        else:
            continue
        matrix = matrix_multiply(matrix, current)
    return matrix


def apply_matrix_to_point(point: complex, matrix: tuple[float, float, float, float, float, float]) -> complex:
    """Apply affine transform matrix (a,b,c,d,e,f) to point."""
    a, b, c, d, e, f = matrix
    x = point.real
    y = point.imag
    return complex((a * x) + (c * y) + e, (b * x) + (d * y) + f)


def transform_segment(segment: object, matrix: tuple[float, float, float, float, float, float]) -> list[object]:
    """Transform segment; arcs are approximated into cubic curves for robustness."""
    if isinstance(segment, Line):
        return [Line(apply_matrix_to_point(segment.start, matrix), apply_matrix_to_point(segment.end, matrix))]
    if isinstance(segment, CubicBezier):
        return [
            CubicBezier(
                apply_matrix_to_point(segment.start, matrix),
                apply_matrix_to_point(segment.control1, matrix),
                apply_matrix_to_point(segment.control2, matrix),
                apply_matrix_to_point(segment.end, matrix),
            )
        ]
    if isinstance(segment, QuadraticBezier):
        return [
            QuadraticBezier(
                apply_matrix_to_point(segment.start, matrix),
                apply_matrix_to_point(segment.control, matrix),
                apply_matrix_to_point(segment.end, matrix),
            )
        ]
    if isinstance(segment, Arc):
        output: list[object] = []
        for cubic in segment.as_cubic_curves():
            output.extend(transform_segment(cubic, matrix))
        return output

    # Unknown segment type fallback.
    start = apply_matrix_to_point(segment.start, matrix)
    end = apply_matrix_to_point(segment.end, matrix)
    return [Line(start, end)]


def transform_path(path: Path, matrix: tuple[float, float, float, float, float, float]) -> Path:
    """Apply affine transform to path segments and return a new path."""
    transformed_segments: list[object] = []
    for segment in path:
        transformed_segments.extend(transform_segment(segment, matrix))
    return Path(*transformed_segments)


def flatten(items: Iterable[Iterable[object]]) -> list[object]:
    """Flatten nested iterables into a simple list."""
    output: list[object] = []
    for group in items:
        output.extend(group)
    return output
