"""Overlay rendering helpers for markers, previews, and diagnostics layers."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Optional

from .models import CornerSeverity, DiagnosticsReport
from .parser import svg_tag

from . import _legacy


def _severity_color(score: float) -> str:
    if score >= 0.78:
        return "#ff3157"
    if score >= 0.50:
        return "#ff8f1f"
    return "#19c37d"


def append_diagnostics_overlay(
    root: ET.Element,
    namespace: str,
    corners: list[CornerSeverity],
    diagnostics: DiagnosticsReport,
) -> None:
    """Append diagnostics severity overlay group."""
    group = ET.Element(svg_tag(namespace, "g"), {"id": "diagnostics-overlay"})
    root.append(group)

    for corner in corners:
        color = _severity_color(corner.severity_score)
        group.append(
            ET.Element(
                svg_tag(namespace, "circle"),
                {
                    "cx": f"{corner.x:.6f}",
                    "cy": f"{corner.y:.6f}",
                    "r": "2.8",
                    "fill": color,
                    "stroke": "none",
                },
            )
        )
        label = ET.Element(
            svg_tag(namespace, "text"),
            {
                "x": f"{corner.x + 3.2:.6f}",
                "y": f"{corner.y - 3.2:.6f}",
                "fill": color,
                "font-size": "8",
            },
        )
        label.text = f"a={corner.angle_deg:.1f} s={corner.severity_score:.2f}"
        group.append(label)

    if diagnostics.rejected_corners:
        rejected_group = ET.Element(svg_tag(namespace, "g"), {"id": "rejected-corners"})
        root.append(rejected_group)
        rejected_map = {(item.path_id, item.node_id): item for item in diagnostics.rejected_corners}
        for corner in corners:
            key = (corner.path_id, corner.node_id)
            if key not in rejected_map:
                continue
            rejected_group.append(
                ET.Element(
                    svg_tag(namespace, "circle"),
                    {
                        "cx": f"{corner.x:.6f}",
                        "cy": f"{corner.y:.6f}",
                        "r": "4.6",
                        "fill": "none",
                        "stroke": "#ffd60a",
                        "stroke-width": "1.2",
                    },
                )
            )


def apply_overlay(
    root: ET.Element,
    namespace: str,
    legacy_corners: list[Any],
    severity_corners: list[CornerSeverity],
    export_mode: str,
    marker_radius: float,
    corner_radius: float,
    radius_profile: str,
    debug: bool,
    diagnostics: DiagnosticsReport,
    per_corner_radii: Optional[dict[str, float]] = None,
) -> list[dict[str, float]]:
    """Apply requested export overlay mode to SVG tree."""
    arc_preview_data: list[dict[str, float]] = []

    if export_mode == "preview_arcs":
        arc_preview_data = _legacy.append_arc_preview_circles(
            root=root,
            namespace=namespace,
            corners=legacy_corners,
            corner_radius=corner_radius,
            radius_profile=("vectorizer" if radius_profile == "vectorizer_legacy" else radius_profile),
            per_corner_radii=per_corner_radii,
            debug=debug,
        )
        return arc_preview_data

    if export_mode in {"markers_only", "diagnostics_overlay"}:
        _legacy.append_corner_markers(
            root=root,
            namespace=namespace,
            corners=legacy_corners,
            marker_radius=marker_radius,
            corner_radius=0.0,
            radius_profile=("vectorizer" if radius_profile == "vectorizer_legacy" else radius_profile),
            debug=debug,
        )

    if export_mode == "diagnostics_overlay":
        append_diagnostics_overlay(root=root, namespace=namespace, corners=severity_corners, diagnostics=diagnostics)

    return arc_preview_data
