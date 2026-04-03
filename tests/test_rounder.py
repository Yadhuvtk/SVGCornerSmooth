from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from svgpathtools import parse_path

from svg_corner_smooth import _legacy
from svg_corner_smooth.models import CornerSeverity
from svg_corner_smooth.parser import extract_namespace
from svg_corner_smooth.parser import parse_svg_document
from svg_corner_smooth.rounder import _allow_rounding, _match_legacy_corner, analyze_svg, process_svg
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


def test_round_geometry_keeps_closed_path_continuous_when_segment_trims_overlap() -> None:
    path = parse_path("M0,0 L8,0 L8,1 L0,1 Z")
    corners = _legacy.detect_corners_in_path(
        path=path,
        path_id=0,
        angle_threshold=20.0,
        samples_per_curve=25,
        min_segment_length=0.0,
        debug=False,
    )

    rounded = _legacy.round_path_geometry(
        path=path,
        path_id=0,
        corners=corners,
        desired_radius=4.0,
        radius_profile="fixed",
        samples_per_curve=25,
        debug=False,
    )

    ranges = _legacy.split_subpaths(rounded)
    assert len(ranges) == 1
    start, end = ranges[0]
    assert abs(rounded[start].start - rounded[end - 1].end) <= _legacy.CONTINUITY_TOLERANCE


def _sample_corner(**overrides) -> CornerSeverity:
    base = dict(
        path_id=0,
        node_id=0,
        x=0.0,
        y=0.0,
        angle_deg=90.0,
        severity_score=0.2,
        local_scale=4.0,
        prev_segment_length=10.0,
        next_segment_length=10.0,
        curvature_hint=0.0,
        risk_score=0.2,
        join_type="corner",
        neighborhood_scale=2.0,
        final_corner_score=0.2,
    )
    base.update(overrides)
    return CornerSeverity(**base)


def test_rounding_gate_blocks_low_confidence_mild_turn() -> None:
    corner = _sample_corner(angle_deg=52.0, final_corner_score=0.08, severity_score=0.08)
    allowed, reason = _allow_rounding(corner, angle_threshold=45.0)
    assert allowed is False
    assert reason == "low_angle_low_confidence"


def test_round_match_uses_geometry_not_node_only() -> None:
    corner = _sample_corner(node_id=185, x=3693.27, y=411.0, local_scale=12.0, neighborhood_scale=2.5)

    # Same node id but geometrically far should be rejected.
    far_same_node = [SimpleNamespace(node_id=185, x=4153.71, y=11.89)]
    assert _match_legacy_corner(corner, far_same_node) is None

    # Nearby corner with different node id should still match by geometry.
    nearby_other_node = far_same_node + [SimpleNamespace(node_id=300, x=3693.20, y=411.05)]
    matched = _match_legacy_corner(corner, nearby_other_node)
    assert matched is not None
    assert matched.node_id == 300


def test_markers_overlay_uses_all_detected_corners() -> None:
    svg_bytes = (FIXTURE_DIR / "tiny_detail.svg").read_bytes()
    options = build_options(
        angle_threshold=35.0,
        min_segment_length=0.5,
        corner_radius=0.0,
        detection_mode="hybrid_advanced",
        export_mode="markers_only",
        apply_rounding=False,
    )
    result = process_svg(svg_bytes, options)
    assert len(result.corners) >= 1

    root = ET.fromstring(result.svg_text)
    ns = extract_namespace(root.tag)
    group_path = f".//{{{ns}}}g[@id='detected-corners-overlay']" if ns else ".//g[@id='detected-corners-overlay']"
    group = root.find(group_path)
    assert group is not None

    circle_tag = f"{{{ns}}}circle" if ns else "circle"
    marker_count = sum(1 for child in list(group) if child.tag == circle_tag)
    assert marker_count == len(result.corners)


def test_preview_arcs_renders_for_all_detected_corners() -> None:
    svg_bytes = (FIXTURE_DIR / "tiny_detail.svg").read_bytes()
    options = build_options(
        angle_threshold=35.0,
        min_segment_length=0.5,
        corner_radius=6.0,
        detection_mode="hybrid_advanced",
        export_mode="preview_arcs",
        apply_rounding=False,
    )
    result = process_svg(svg_bytes, options)
    assert len(result.corners) >= 1
    assert len(result.arc_preview) == len(result.corners)
