"""Typed models for corner analysis and rounding."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import MIN_FILLET_RADIUS


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
    diagnostic_notes: list[str] = field(default_factory=list)
    # Advanced detection evidence fields (backward-compatible extensions).
    source_type: str = "join"
    path_index: int = -1
    segment_index_before: int = -1
    segment_index_after: int = -1
    point: complex = 0 + 0j
    tangent_angle_deg: float = 0.0
    local_turn_deg: float = 0.0
    curvature_peak: float = 0.0
    severity: float = 0.0
    confidence: float = 0.0
    final_corner_score: float = 0.0
    detection_reason: str = ""
    neighborhood_scale: float = 0.0
    tangent_discontinuity_score: float = 0.0
    local_turn_score: float = 0.0
    curvature_spike_score: float = 0.0
    endpoint_confidence: float = 0.0
    geometric_scale_factor: float = 0.0
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass
class RejectedCorner:
    """Corner that was detected but skipped during rounding."""

    path_id: int
    node_id: int
    reason: str
    attempted_radius: float
    final_radius: float


@dataclass
class FilletResult:
    """Result for a fillet attempt, including skip/shrink diagnostics."""

    status: str  # "ok", "skipped", "shrunk"
    reason: str
    corner: Any | None
    attempted_radius: float
    final_radius: float
    iterations: int

    @property
    def valid(self) -> bool:
        return self.status in {"ok", "shrunk"}

    @property
    def radius(self) -> float:
        return self.final_radius


# Backward compatibility alias used across current code/tests.
FilletValidationResult = FilletResult


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
    min_allowed_radius: float = MIN_FILLET_RADIUS
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
class PathAdjacencyGraph:
    """Adjacency relationships between path endpoints."""

    # maps path_index -> list of (neighbor_path_index, shared_point)
    adjacency: dict[int, list[tuple[int, complex]]]


@dataclass
class ProcessingResult:
    """Final process result returned by rounder and backend endpoints."""

    svg_text: str
    corners: list[CornerSeverity]
    summary: ProcessingSummary
    diagnostics: DiagnosticsReport
    arc_preview: list[dict[str, float]] = field(default_factory=list)
    adjacency: list[dict[str, float]] = field(default_factory=list)
