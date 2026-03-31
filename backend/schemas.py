"""Request parsing and schema helpers for API endpoints."""

from __future__ import annotations

import json
from typing import Any, Mapping

from svg_corner_smooth.utils import parse_bool, parse_float, parse_int
from svg_corner_smooth.validate import build_options


def _value(data: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data:
            return data.get(key)
    return default


def _as_text(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value)
    if text.strip() == "":
        return default
    return text


def parse_corner_overrides(raw: str | None) -> dict[str, float] | None:
    """Parse per-corner radius overrides JSON payload."""
    if not raw:
        return None
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("cornerRadiusOverridesJson must be a JSON object")

    out: dict[str, float] = {}
    for key, value in payload.items():
        radius = float(value)
        if radius > 0.0:
            out[str(key)] = radius
    return out or None


def parse_options_from_mapping(data: Mapping[str, Any]) -> Any:
    """Build ProcessingOptions from multipart form or JSON mapping."""
    apply_rounding = parse_bool(_as_text(_value(data, "applyRounding", "apply_rounding", default="false"), "false"), False)
    preview_arcs = parse_bool(_as_text(_value(data, "previewArcs", "preview_arcs", default="false"), "false"), False)

    skip_invalid = parse_bool(_as_text(_value(data, "skipInvalidCorners", "skip_invalid_corners", default="true"), "true"), True)
    exact_curve_trim = parse_bool(_as_text(_value(data, "exactCurveTrim", "exact_curve_trim", default="true"), "true"), True)

    return build_options(
        angle_threshold=parse_float(_as_text(_value(data, "angleThreshold", "angle_threshold", default="45.0"), "45.0"), 45.0),
        samples_per_curve=parse_int(_as_text(_value(data, "samplesPerCurve", "samples_per_curve", default="25"), "25"), 25),
        marker_radius=parse_float(_as_text(_value(data, "markerRadius", "marker_radius", default="3.0"), "3.0"), 3.0),
        min_segment_length=parse_float(
            _as_text(_value(data, "minSegmentLength", "min_segment_length", default="1.0"), "1.0"),
            1.0,
        ),
        corner_radius=parse_float(_as_text(_value(data, "cornerRadius", "corner_radius", default="12.0"), "12.0"), 12.0),
        radius_profile=_as_text(_value(data, "radiusProfile", "radius_profile", default="adaptive"), "adaptive"),
        detection_mode=_as_text(_value(data, "detectionMode", "detection_mode", default="accurate"), "accurate"),
        export_mode=_as_text(_value(data, "exportMode", "export_mode", default="markers_only"), "markers_only"),
        apply_rounding=apply_rounding,
        preview_arcs=preview_arcs,
        debug=parse_bool(_as_text(_value(data, "debug", default="false"), "false"), False),
        max_radius_shrink_iterations=parse_int(
            _as_text(_value(data, "maxRadiusShrinkIterations", "max_radius_shrink_iterations", default="10"), "10"),
            10,
        ),
        min_allowed_radius=parse_float(
            _as_text(_value(data, "minAllowedRadius", "min_allowed_radius", default="0.25"), "0.25"),
            0.25,
        ),
        skip_invalid_corners=skip_invalid,
        exact_curve_trim=exact_curve_trim,
        intersection_safety_margin=parse_float(
            _as_text(_value(data, "intersectionSafetyMargin", "intersection_safety_margin", default="0.01"), "0.01"),
            0.01,
        ),
        per_corner_radii=parse_corner_overrides(
            _value(data, "cornerRadiusOverridesJson", "corner_radius_overrides_json", default=None)
        ),
    )
