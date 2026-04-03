from pathlib import Path

from svgpathtools import parse_path

from svg_corner_smooth.detect import detect_corners
from svg_corner_smooth.parser import parse_svg_document


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def test_detection_modes_on_dense_shape() -> None:
    doc = parse_svg_document(str(FIXTURE_DIR / "dense_corners.svg"))
    path = doc.entries[0].path

    fast = detect_corners(
        path=path,
        path_id=0,
        angle_threshold=32.0,
        min_segment_length=0.5,
        samples_per_curve=24,
        mode="fast",
    )
    preserve = detect_corners(
        path=path,
        path_id=0,
        angle_threshold=32.0,
        min_segment_length=0.5,
        samples_per_curve=24,
        mode="preserve_shape",
    )

    assert len(fast) > 0
    assert len(fast) >= len(preserve)
    assert any(corner.join_type in {"corner", "near-cusp", "cusp"} for corner in fast)


def test_detection_handles_bezier_path() -> None:
    doc = parse_svg_document(str(FIXTURE_DIR / "bezier_logo.svg"))
    corners = detect_corners(
        path=doc.entries[0].path,
        path_id=0,
        angle_threshold=30.0,
        min_segment_length=0.25,
        samples_per_curve=30,
        mode="accurate",
    )
    assert isinstance(corners, list)


def test_detection_keeps_sharp_corner_even_with_short_adjacent_segment() -> None:
    path = parse_path("M 0,0 L 20,0 L 20,0.2 L 15,0.2")
    corners = detect_corners(
        path=path,
        path_id=0,
        angle_threshold=35.0,
        min_segment_length=1.0,
        samples_per_curve=25,
        mode="accurate",
    )
    assert len(corners) >= 1
    assert any(corner.angle_deg >= 80.0 for corner in corners)
