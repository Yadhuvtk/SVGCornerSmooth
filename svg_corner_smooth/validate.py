"""Validation and normalization helpers for CLI/backend processing options."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .constants import (
    DEFAULT_ANGLE_THRESHOLD,
    DEFAULT_CORNER_RADIUS,
    DEFAULT_DETECTION_MODE,
    DEFAULT_EXPORT_MODE,
    DEFAULT_MARKER_RADIUS,
    DEFAULT_MIN_SEGMENT_LENGTH,
    DEFAULT_RADIUS_PROFILE,
    DEFAULT_SAMPLES_PER_CURVE,
    SUPPORTED_DETECTION_MODES,
    SUPPORTED_EXPORT_MODES,
    SUPPORTED_RADIUS_PROFILES,
)
from .models import ProcessingOptions


def normalize_radius_profile(profile: str | None) -> str:
    """Normalize profile aliases and fallback to default."""
    value = (profile or "").strip().lower()
    if value == "vectorizer":
        return "vectorizer_legacy"
    if value in SUPPORTED_RADIUS_PROFILES:
        return value
    return DEFAULT_RADIUS_PROFILE


def normalize_detection_mode(mode: str | None) -> str:
    """Normalize detection mode with default fallback."""
    value = (mode or "").strip().lower()
    if value in SUPPORTED_DETECTION_MODES:
        return value
    return DEFAULT_DETECTION_MODE


def normalize_export_mode(export_mode: str | None, *, apply_rounding: bool, preview_arcs: bool) -> str:
    """Pick effective export mode using explicit mode or compatibility flags."""
    mode = (export_mode or "").strip().lower()
    if preview_arcs:
        return "preview_arcs"
    if apply_rounding:
        return "apply_rounding"
    if mode in SUPPORTED_EXPORT_MODES:
        return mode
    return DEFAULT_EXPORT_MODE


def build_options(
    *,
    angle_threshold: float = DEFAULT_ANGLE_THRESHOLD,
    samples_per_curve: int = DEFAULT_SAMPLES_PER_CURVE,
    marker_radius: float = DEFAULT_MARKER_RADIUS,
    min_segment_length: float = DEFAULT_MIN_SEGMENT_LENGTH,
    corner_radius: float = DEFAULT_CORNER_RADIUS,
    radius_profile: str = DEFAULT_RADIUS_PROFILE,
    detection_mode: str = DEFAULT_DETECTION_MODE,
    export_mode: str = DEFAULT_EXPORT_MODE,
    apply_rounding: bool = False,
    preview_arcs: bool = False,
    preview_only: bool = False,
    debug: bool = False,
    max_radius_shrink_iterations: int = 10,
    min_allowed_radius: float = 0.25,
    skip_invalid_corners: bool = True,
    exact_curve_trim: bool = True,
    intersection_safety_margin: float = 0.01,
    per_corner_radii: dict[str, float] | None = None,
) -> ProcessingOptions:
    """Construct normalized processing options dataclass."""
    return ProcessingOptions(
        angle_threshold=float(angle_threshold),
        samples_per_curve=int(samples_per_curve),
        marker_radius=float(marker_radius),
        min_segment_length=float(min_segment_length),
        corner_radius=float(corner_radius),
        radius_profile=normalize_radius_profile(radius_profile),
        detection_mode=normalize_detection_mode(detection_mode),
        export_mode=normalize_export_mode(
            export_mode,
            apply_rounding=bool(apply_rounding),
            preview_arcs=bool(preview_arcs),
        ),
        apply_rounding=bool(apply_rounding),
        preview_only=bool(preview_only),
        debug=bool(debug),
        max_radius_shrink_iterations=int(max_radius_shrink_iterations),
        min_allowed_radius=float(min_allowed_radius),
        skip_invalid_corners=bool(skip_invalid_corners),
        exact_curve_trim=bool(exact_curve_trim),
        intersection_safety_margin=float(intersection_safety_margin),
        per_corner_radii=per_corner_radii,
    )


def validate_processing_options(options: ProcessingOptions) -> None:
    """Validate options and raise ValueError on invalid input."""
    if not (0.0 <= options.angle_threshold <= 180.0):
        raise ValueError("angle_threshold must be between 0 and 180")
    if options.samples_per_curve < 2:
        raise ValueError("samples_per_curve must be at least 2")
    if options.marker_radius <= 0.0:
        raise ValueError("marker_radius must be greater than 0")
    if options.min_segment_length < 0.0:
        raise ValueError("min_segment_length must be non-negative")
    if options.corner_radius < 0.0:
        raise ValueError("corner_radius must be non-negative")
    if options.max_radius_shrink_iterations < 0:
        raise ValueError("max_radius_shrink_iterations must be >= 0")
    if options.min_allowed_radius < 0.0:
        raise ValueError("min_allowed_radius must be non-negative")
    if options.intersection_safety_margin < 0.0:
        raise ValueError("intersection_safety_margin must be non-negative")


def validate_svg_bytes(data: bytes, max_size_bytes: int) -> None:
    """Validate uploaded SVG bytes including size and XML structure."""
    if not data:
        raise ValueError("Uploaded file is empty")
    if len(data) > max_size_bytes:
        raise ValueError(f"Uploaded file exceeds limit ({max_size_bytes} bytes)")

    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid SVG/XML: {exc}") from exc

    tag = root.tag.split("}", 1)[-1].lower() if isinstance(root.tag, str) else ""
    if tag != "svg":
        raise ValueError("Root element must be <svg>")
