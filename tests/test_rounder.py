from pathlib import Path

from svg_corner_smooth.parser import parse_svg_document
from svg_corner_smooth.rounder import analyze_svg, process_svg
from svg_corner_smooth.validate import build_options


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def test_round_pipeline_keeps_svg_parseable() -> None:
    svg_bytes = (FIXTURE_DIR / "dense_corners.svg").read_bytes()
    options = build_options(
        angle_threshold=30.0,
        min_segment_length=0.3,
        corner_radius=8.0,
        radius_profile="adaptive",
        detection_mode="accurate",
        apply_rounding=True,
        export_mode="apply_rounding",
    )
    result = process_svg(svg_bytes, options)

    assert result.summary.paths_found >= 1
    assert result.summary.corners_found >= 1
    assert isinstance(result.svg_text, str)
    reparsed = parse_svg_document(result.svg_text)
    assert len(reparsed.entries) >= 1


def test_analyze_pipeline_returns_diagnostics() -> None:
    svg_bytes = (FIXTURE_DIR / "tiny_detail.svg").read_bytes()
    options = build_options(
        angle_threshold=35.0,
        min_segment_length=0.5,
        corner_radius=4.0,
        detection_mode="preserve_shape",
        export_mode="diagnostics_overlay",
    )
    result = analyze_svg(svg_bytes, options)
    assert result.summary.paths_found >= 1
    assert result.diagnostics.mode == "preserve_shape"
