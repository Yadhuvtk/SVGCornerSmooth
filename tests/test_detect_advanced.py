from pathlib import Path as FsPath

from svgpathtools import CubicBezier, Line, Path, parse_path

from svg_corner_smooth.detect import detect_corners
from svg_corner_smooth.parser import parse_svg_document


FIXTURE_DIR = FsPath(__file__).resolve().parent / "fixtures"


def _run_detect(
    path: Path,
    *,
    mode: str = "hybrid_advanced",
    angle_threshold: float = 35.0,
    min_segment_length: float = 0.3,
) -> list:
    return detect_corners(
        path=path,
        path_id=0,
        angle_threshold=angle_threshold,
        min_segment_length=min_segment_length,
        samples_per_curve=32,
        mode=mode,
    )


def test_line_line_90_degree_corner_detected() -> None:
    path = parse_path("M 0,0 L 12,0 L 12,12")
    corners = _run_detect(path)
    assert len(corners) >= 1
    assert any(80.0 <= corner.angle_deg <= 100.0 for corner in corners)


def test_line_line_shallow_turn_not_detected_in_preserve_shape() -> None:
    path = parse_path("M 0,0 L 12,0 L 24,1")
    corners = _run_detect(path, mode="preserve_shape", angle_threshold=30.0)
    assert corners == []


def test_line_cubic_sharp_join_detected() -> None:
    path = Path(
        Line(complex(0, 0), complex(10, 0)),
        CubicBezier(complex(10, 0), complex(10, 5), complex(12, 8), complex(15, 10)),
    )
    corners = _run_detect(path)
    assert len(corners) >= 1


def test_cubic_line_sharp_join_detected() -> None:
    path = Path(
        CubicBezier(complex(0, 0), complex(4, 0), complex(10, 5), complex(10, 10)),
        Line(complex(10, 10), complex(16, 10)),
    )
    corners = _run_detect(path)
    assert len(corners) >= 1


def test_cubic_cubic_cusp_like_join_detected() -> None:
    path = Path(
        CubicBezier(complex(0, 0), complex(4, 0), complex(8, 0), complex(10, 0)),
        CubicBezier(complex(10, 0), complex(9, 0), complex(7, 3), complex(6, 6)),
    )
    corners = _run_detect(path)
    assert len(corners) >= 1
    assert any(corner.tangent_angle_deg >= 150.0 for corner in corners)


def test_smooth_continuous_bezier_join_not_detected() -> None:
    path = Path(
        CubicBezier(complex(0, 0), complex(3, 0), complex(6, 3), complex(9, 6)),
        CubicBezier(complex(9, 6), complex(12, 9), complex(15, 9), complex(18, 6)),
    )
    corners = _run_detect(path, mode="preserve_shape", angle_threshold=28.0, min_segment_length=0.2)
    assert corners == []


def test_curved_glyph_like_terminal_detects_sharp_corner() -> None:
    path = parse_path("M 0,0 C 0,20 20,24 20,8 L 32,8")
    corners = _run_detect(path, mode="hybrid_advanced", angle_threshold=30.0, min_segment_length=0.1)
    assert len(corners) >= 1


def test_rounded_rectangle_not_flagged_as_sharp() -> None:
    path = parse_path(
        "M 2,0 L 8,0 A 2,2 0 0 1 10,2 L 10,8 A 2,2 0 0 1 8,10 "
        "L 2,10 A 2,2 0 0 1 0,8 L 0,2 A 2,2 0 0 1 2,0 Z"
    )
    corners = _run_detect(path, mode="preserve_shape", angle_threshold=35.0, min_segment_length=0.1)
    assert corners == []


def test_tiny_degenerate_segments_do_not_crash() -> None:
    path = Path(
        Line(complex(0, 0), complex(0, 0)),
        Line(complex(0, 0), complex(0.000001, 0.000001)),
        Line(complex(0.000001, 0.000001), complex(2, 0)),
    )
    corners = _run_detect(path, mode="hybrid_advanced", min_segment_length=0.0)
    assert isinstance(corners, list)


def test_duplicate_candidates_are_merged_to_single_corner() -> None:
    path = parse_path("M 0,0 L 12,0 L 12,12")
    corners = _run_detect(path, mode="hybrid_advanced", angle_threshold=30.0, min_segment_length=0.1)
    assert len(corners) == 1


def test_hybrid_advanced_finds_more_corners_than_fast_on_glyph_like_fixture() -> None:
    doc = parse_svg_document(str(FIXTURE_DIR / "glyph_like.svg"))
    path = doc.entries[0].path

    fast = _run_detect(path, mode="fast", angle_threshold=35.0, min_segment_length=0.1)
    hybrid = _run_detect(path, mode="hybrid_advanced", angle_threshold=35.0, min_segment_length=0.1)

    assert len(hybrid) > len(fast)


def test_close_corners_are_not_collapsed_on_large_path_scale() -> None:
    path = parse_path("M0,0 L5000,0 L5000,100 L0,100 Z M5100,0 L5120,0 L5120,20 L5100,20 Z")
    corners = _run_detect(path, mode="hybrid_advanced", angle_threshold=35.0, min_segment_length=0.1)

    near_small_rect = [corner for corner in corners if 5095.0 <= corner.x <= 5125.0 and -5.0 <= corner.y <= 25.0]
    assert len(near_small_rect) >= 4


def test_strict_junction_detects_closure_corner_and_dedupes() -> None:
    path = parse_path("M 0,0 L 20,0 L 20,20 L 0,20 Z")
    corners = _run_detect(path, mode="strict_junction", angle_threshold=20.0, min_segment_length=0.1)
    assert len(corners) == 4
    assert any(abs(corner.x - 0.0) < 1e-6 and abs(corner.y - 0.0) < 1e-6 for corner in corners)
    assert all(80.0 <= corner.angle_deg <= 100.0 for corner in corners)


def test_strict_junction_ignores_tiny_noise_segments() -> None:
    path = parse_path("M0,0 L20,0 L20,0.02 L20,20")
    corners = _run_detect(path, mode="strict_junction", angle_threshold=20.0, min_segment_length=0.0)
    assert len(corners) == 1
    assert 80.0 <= corners[0].angle_deg <= 100.0
