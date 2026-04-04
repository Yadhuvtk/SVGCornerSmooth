"""Tests for the curve-curve fillet solver."""

from __future__ import annotations

from svgpathtools import CubicBezier, Line

from svg_corner_smooth.curve_solver import CurveFillet, solve_curve_fillet


def test_line_line_90_degree() -> None:
    """Basic right-angle between two lines should produce a valid fillet."""
    prev = Line(start=complex(-50, 0), end=complex(0, 0))
    next_seg = Line(start=complex(0, 0), end=complex(0, 50))
    result = solve_curve_fillet(prev, next_seg, desired_radius=8.0, corner_point=complex(0, 0))
    assert isinstance(result, CurveFillet)
    assert result.quality_score >= 0.8
    assert result.arc_radius > 0


def test_cubic_cubic_corner() -> None:
    """Two CubicBeziers meeting at a sharp corner."""
    prev = CubicBezier(
        start=complex(-60, 10),
        control1=complex(-30, 10),
        control2=complex(-8, 24),
        end=complex(0, 0),
    )
    next_seg = CubicBezier(
        start=complex(0, 0),
        control1=complex(12, -4),
        control2=complex(30, -20),
        end=complex(60, -30),
    )
    result = solve_curve_fillet(prev, next_seg, desired_radius=6.0, corner_point=complex(0, 0))
    assert result is not None
    assert result.quality_score >= 0.5
    assert result.arc_radius > 0


def test_line_cubic_corner() -> None:
    """Line meeting a CubicBezier."""
    prev = Line(start=complex(-40, 0), end=complex(0, 0))
    next_seg = CubicBezier(
        start=complex(0, 0),
        control1=complex(5, -15),
        control2=complex(20, -30),
        end=complex(40, -40),
    )
    result = solve_curve_fillet(prev, next_seg, desired_radius=5.0, corner_point=complex(0, 0))
    assert result is not None
    assert result.arc_radius > 0


def test_near_parallel_returns_none() -> None:
    """Near-parallel segments should return None, not crash."""
    prev = Line(start=complex(-50, 0), end=complex(0, 0))
    next_seg = Line(start=complex(0, 0), end=complex(50, 0.001))
    result = solve_curve_fillet(prev, next_seg, desired_radius=5.0, corner_point=complex(0, 0))
    assert result is None


def test_tiny_segments_return_none() -> None:
    """Segments shorter than epsilon should not crash."""
    prev = Line(start=complex(-0.0001, 0), end=complex(0, 0))
    next_seg = Line(start=complex(0, 0), end=complex(0.0001, 0))
    result = solve_curve_fillet(prev, next_seg, desired_radius=5.0, corner_point=complex(0, 0))
    assert result is None


def test_radius_shrink_on_tight_corner() -> None:
    """When desired radius is too large, solver should shrink and still succeed."""
    prev = Line(start=complex(-10, 0), end=complex(0, 0))
    next_seg = Line(start=complex(0, 0), end=complex(0, 10))
    result = solve_curve_fillet(prev, next_seg, desired_radius=50.0, corner_point=complex(0, 0))
    assert result is not None
    assert result.arc_radius < 50.0
    assert result.arc_radius > 0


def test_arc_endpoints_on_curves() -> None:
    """Arc start/end should actually lie on the original curves."""
    prev = CubicBezier(
        start=complex(-80, 20),
        control1=complex(-40, 20),
        control2=complex(-12, 28),
        end=complex(0, 0),
    )
    next_seg = CubicBezier(
        start=complex(0, 0),
        control1=complex(16, -12),
        control2=complex(40, -20),
        end=complex(80, -20),
    )
    result = solve_curve_fillet(prev, next_seg, desired_radius=8.0, corner_point=complex(0, 0))
    assert result is not None
    expected_start = complex(prev.point(result.prev_trim_t))
    assert abs(result.arc_start - expected_start) < 0.01
    expected_end = complex(next_seg.point(result.next_trim_t))
    assert abs(result.arc_end - expected_end) < 0.01
