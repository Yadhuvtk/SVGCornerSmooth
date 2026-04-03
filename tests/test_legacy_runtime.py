from svgpathtools import Path, Line

from svg_corner_smooth import legacy_runtime


def test_legacy_runtime_detect_corners_in_path_basic() -> None:
    path = Path(
        Line(complex(0, 0), complex(10, 0)),
        Line(complex(10, 0), complex(10, 10)),
    )
    corners = legacy_runtime.detect_corners_in_path(
        path=path,
        path_id=0,
        angle_threshold=20.0,
        samples_per_curve=20,
        min_segment_length=0.0,
        debug=False,
    )
    assert len(corners) == 1


def test_legacy_runtime_compute_corner_arc_geometry() -> None:
    corner = legacy_runtime.CornerDetection(
        path_id=0,
        node_id=1,
        x=10.0,
        y=0.0,
        angle_deg=90.0,
        incoming_dx=1.0,
        incoming_dy=0.0,
        outgoing_dx=0.0,
        outgoing_dy=1.0,
        prev_segment_length=20.0,
        next_segment_length=20.0,
    )
    geometry = legacy_runtime.compute_corner_arc_geometry(corner, desired_radius=4.0)
    assert geometry is not None


def test_legacy_runtime_round_path_geometry_returns_path() -> None:
    path = Path(
        Line(complex(0, 0), complex(10, 0)),
        Line(complex(10, 0), complex(10, 10)),
    )
    corners = legacy_runtime.detect_corners_in_path(
        path=path,
        path_id=0,
        angle_threshold=20.0,
        samples_per_curve=20,
        min_segment_length=0.0,
        debug=False,
    )
    rounded = legacy_runtime.round_path_geometry(
        path=path,
        path_id=0,
        corners=corners,
        desired_radius=2.0,
        radius_profile='fixed',
        samples_per_curve=20,
        debug=False,
    )
    assert isinstance(rounded, Path)
