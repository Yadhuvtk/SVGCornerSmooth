from svgpathtools import Arc, CubicBezier, Line, Path

from svg_corner_smooth.detect import detect_corners
from svg_corner_smooth.tangents import (
    estimate_endpoint_tangent,
    safe_unit_vector,
    segment_end_tangent,
    segment_start_tangent,
    tangent_angle_degrees,
)


def test_line_endpoint_tangent() -> None:
    segment = Line(complex(0, 0), complex(10, 0))
    tangent = estimate_endpoint_tangent(segment, at_end=True, samples_per_curve=20)
    assert tangent is not None
    assert abs(tangent.real - 1.0) < 1e-9
    assert abs(tangent.imag) < 1e-9


def test_curve_and_arc_tangent_stability() -> None:
    cubic = CubicBezier(complex(0, 0), complex(10, 0), complex(10, 10), complex(20, 10))
    arc = Arc(start=complex(0, 0), radius=complex(10, 10), rotation=0.0, large_arc=False, sweep=True, end=complex(10, 10))

    tangent_cubic = estimate_endpoint_tangent(cubic, at_end=False, samples_per_curve=24)
    tangent_arc = estimate_endpoint_tangent(arc, at_end=False, samples_per_curve=24)

    assert tangent_cubic is not None
    assert tangent_arc is not None


def test_endpoint_tangent_confidence_helpers() -> None:
    segment = Line(complex(0, 0), complex(0, 10))
    start, start_conf = segment_start_tangent(segment)
    end, end_conf = segment_end_tangent(segment)

    assert start_conf > 0.9
    assert end_conf > 0.9
    assert abs(start.imag - 1.0) < 1e-9
    assert abs(end.imag - 1.0) < 1e-9


def test_tangent_angle_degrees_for_perpendicular_vectors() -> None:
    angle = tangent_angle_degrees(complex(1, 0), complex(0, 1))
    assert 89.9 <= angle <= 90.1


def test_safe_unit_vector_fallback_for_tiny_input() -> None:
    unit = safe_unit_vector(0 + 0j, fallback=complex(0, 2))
    assert abs(unit.real) < 1e-9
    assert abs(unit.imag - 1.0) < 1e-9


def test_degenerate_consecutive_points_do_not_raise() -> None:
    # Two consecutive identical points create a zero-length segment.
    path = Path(
        Line(complex(0, 0), complex(0, 0)),
        Line(complex(0, 0), complex(12, 0)),
    )

    corners = detect_corners(
        path=path,
        path_id=0,
        angle_threshold=10.0,
        min_segment_length=0.0,
        samples_per_curve=24,
        mode='accurate',
    )

    assert corners == []
