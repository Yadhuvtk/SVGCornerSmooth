from pathlib import Path

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
