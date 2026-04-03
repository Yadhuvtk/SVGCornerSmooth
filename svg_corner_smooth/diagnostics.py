"""Diagnostics helpers for summaries, tables, and API payload conversion."""

from __future__ import annotations

from typing import Any

from .models import CornerSeverity, DiagnosticsReport, ProcessingSummary, RejectedCorner


def corner_to_dict(corner: CornerSeverity) -> dict[str, Any]:
    """Serialize a corner model into JSON-friendly dict."""
    return {
        "path_id": corner.path_id,
        "node_id": corner.node_id,
        "x": round(corner.x, 4),
        "y": round(corner.y, 4),
        "angle_deg": round(corner.angle_deg, 3),
        "severity_score": round(corner.severity_score, 4),
        "local_scale": round(corner.local_scale, 4),
        "prev_segment_length": round(corner.prev_segment_length, 4),
        "next_segment_length": round(corner.next_segment_length, 4),
        "curvature_hint": round(corner.curvature_hint, 4),
        "risk_score": round(corner.risk_score, 4),
        "join_type": corner.join_type,
        "suggested_radius": round(corner.suggested_radius, 4),
        "diagnostic_notes": list(corner.diagnostic_notes),
        "source_type": corner.source_type,
        "path_index": corner.path_index,
        "segment_index_before": corner.segment_index_before,
        "segment_index_after": corner.segment_index_after,
        "point": {"x": round(corner.point.real, 4), "y": round(corner.point.imag, 4)},
        "tangent_angle_deg": round(corner.tangent_angle_deg, 3),
        "local_turn_deg": round(corner.local_turn_deg, 3),
        "curvature_peak": round(corner.curvature_peak, 6),
        "severity": round(corner.severity, 4),
        "confidence": round(corner.confidence, 4),
        "final_corner_score": round(corner.final_corner_score, 4),
        "detection_reason": corner.detection_reason,
        "neighborhood_scale": round(corner.neighborhood_scale, 4),
        "tangent_discontinuity_score": round(corner.tangent_discontinuity_score, 4),
        "local_turn_score": round(corner.local_turn_score, 4),
        "curvature_spike_score": round(corner.curvature_spike_score, 4),
        "endpoint_confidence": round(corner.endpoint_confidence, 4),
        "geometric_scale_factor": round(corner.geometric_scale_factor, 4),
        "debug": corner.debug,
    }


def rejected_to_dict(item: RejectedCorner) -> dict[str, Any]:
    """Serialize a rejected-corner record."""
    return {
        "path_id": item.path_id,
        "node_id": item.node_id,
        "reason": item.reason,
        "attempted_radius": round(item.attempted_radius, 4),
        "final_radius": round(item.final_radius, 4),
    }


def diagnostics_to_dict(diagnostics: DiagnosticsReport) -> dict[str, Any]:
    """Serialize diagnostics report."""
    return {
        "warnings": diagnostics.warnings,
        "mode": diagnostics.mode,
        "radius_profile": diagnostics.radius_profile,
        "export_mode": diagnostics.export_mode,
        "rejected_corners": [rejected_to_dict(item) for item in diagnostics.rejected_corners],
    }


def summary_to_dict(summary: ProcessingSummary) -> dict[str, Any]:
    """Serialize processing summary."""
    return {
        "paths_found": summary.paths_found,
        "corners_found": summary.corners_found,
        "corners_rounded": summary.corners_rounded,
        "corners_skipped": summary.corners_skipped,
        "processing_ms": round(summary.processing_ms, 3),
    }


def print_corner_table(corners: list[CornerSeverity]) -> None:
    """Print concise terminal table for detected corners."""
    headers = ("path_id", "node_id", "x", "y", "angle_deg")
    print("\t".join(headers))
    for corner in corners:
        print(
            f"{corner.path_id}\t{corner.node_id}\t"
            f"{corner.x:.4f}\t{corner.y:.4f}\t{corner.angle_deg:.2f}"
        )
