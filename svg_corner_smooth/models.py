"""Typed models for corner analysis and rounding."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CornerSeverity:
    """Enriched corner detection result with severity and risk metadata."""

    path_id: int
    node_id: int
    x: float
    y: float
    angle_deg: float
    severity_score: float
    local_scale: float
    prev_segment_length: float
    next_segment_length: float
    curvature_hint: float
    risk_score: float
    join_type: str
    suggested_radius: float = 0.0


@dataclass
class RejectedCorner:
    """Corner that was detected but skipped during rounding."""

    path_id: int
    node_id: int
    reason: str
    attempted_radius: float
    final_radius: float


@dataclass
class FilletValidationResult:
    """Validation result for a proposed fillet."""

    valid: bool
    reason: str
    radius: float
    iterations: int


@dataclass
class ProcessingSummary:
    """Compact summary for API response and diagnostics panel."""

    paths_found: int = 0
    corners_found: int = 0
    corners_rounded: int = 0
    corners_skipped: int = 0
    processing_ms: float = 0.0


@dataclass
class DiagnosticsReport:
    """Diagnostic output bundle for API and UI."""

    warnings: list[str] = field(default_factory=list)
    rejected_corners: list[RejectedCorner] = field(default_factory=list)
    mode: str = "accurate"
    radius_profile: str = "adaptive"
    export_mode: str = "markers_only"


@dataclass
class ProcessingOptions:
    """Unified processing options for analyze/round/process pipelines."""

    angle_threshold: float
    samples_per_curve: int
    marker_radius: float
    min_segment_length: float
    corner_radius: float
    radius_profile: str
    detection_mode: str
    export_mode: str
    apply_rounding: bool
    preview_only: bool
    debug: bool
    max_radius_shrink_iterations: int = 10
    min_allowed_radius: float = 0.25
    skip_invalid_corners: bool = True
    exact_curve_trim: bool = True
    intersection_safety_margin: float = 0.01
    per_corner_radii: dict[str, float] | None = None


@dataclass
class ParsedPathEntry:
    """Path geometry extracted from a specific SVG element."""

    path_id: int
    source_tag: str
    element: Any
    path: Any


@dataclass
class ParsedSvgDocument:
    """Parsed SVG tree and converted path entries."""

    tree: Any
    root: Any
    namespace: str
    entries: list[ParsedPathEntry]


@dataclass
class ProcessingResult:
    """Final process result returned by rounder and backend endpoints."""

    svg_text: str
    corners: list[CornerSeverity]
    summary: ProcessingSummary
    diagnostics: DiagnosticsReport
    arc_preview: list[dict[str, float]] = field(default_factory=list)
