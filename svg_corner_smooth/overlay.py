"""Overlay rendering helpers for markers, previews, and diagnostics layers."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Optional

from .models import CornerSeverity, DiagnosticsReport
from .parser import svg_tag

from . import legacy_runtime as _legacy


def _severity_color(score: float) -> str:
    if score >= 0.78:
        return "#ff3157"
    if score >= 0.50:
        return "#ff8f1f"
    return "#ffd60a"


def append_arc_preview_from_severity(
    root: ET.Element,
    namespace: str,
    corners: list[CornerSeverity],
    legacy_corners: list[Any],
    corner_radius: float,
    radius_profile: str,
    per_corner_radii: Optional[dict[str, float]],
) -> list[dict[str, float]]:
    """
    Draw arc preview circles for detected corners with geometry-aware centers.

    Uses legacy corner tangent geometry when available (for meaningful arc center).
    Falls back to a small corner-centered circle when geometry is unavailable.
    """
    overlay_group = ET.Element(svg_tag(namespace, "g"), {"id": "arc-preview-overlay"})
    root.append(overlay_group)

    arc_circles: list[dict[str, float]] = []
    min_visible_radius = 1.6
    normalized_profile = "vectorizer" if radius_profile == "vectorizer_legacy" else radius_profile
    remaining_legacy = list(legacy_corners)

    def _legacy_point(item: Any) -> complex:
        return complex(float(item.x), float(item.y))

    def _pick_legacy(corner: CornerSeverity) -> Any | None:
        if not remaining_legacy:
            return None
        corner_point = complex(float(corner.x), float(corner.y))
        candidates = [item for item in remaining_legacy if int(item.path_id) == int(corner.path_id)]
        if not candidates:
            return None

        nearest = min(candidates, key=lambda item: abs(_legacy_point(item) - corner_point))
        distance = float(abs(_legacy_point(nearest) - corner_point))
        local_hint = max(
            1.2,
            float(corner.neighborhood_scale or 0.0),
            float(corner.local_scale or 0.0) * 0.18 if float(corner.local_scale or 0.0) > 0 else 1.2,
        )
        tolerance = max(
            0.9,
            min(
                8.0,
                local_hint,
            ),
        )
        if distance > tolerance:
            return None
        remaining_legacy.remove(nearest)
        return nearest

    for corner in corners:
        key = f"{corner.path_id}:{corner.node_id}"
        if per_corner_radii is not None and key in per_corner_radii:
            desired_radius = float(per_corner_radii[key])
        elif float(corner.suggested_radius) > 0.0:
            desired_radius = float(corner.suggested_radius)
        else:
            desired_radius = float(corner_radius)

        if desired_radius <= 0.0:
            continue

        legacy_corner = _pick_legacy(corner)
        cx = float(corner.x)
        cy = float(corner.y)
        used_radius = max(min_visible_radius, desired_radius)
        geometry_source = "fallback"

        if legacy_corner is not None:
            if per_corner_radii is not None and key in per_corner_radii:
                desired_for_geometry = desired_radius
            else:
                desired_for_geometry = _legacy.effective_corner_radius(
                    legacy_corner,
                    desired_radius,
                    radius_profile=normalized_profile,
                )
            arc_geometry = _legacy.compute_corner_arc_geometry(legacy_corner, desired_for_geometry)
            if arc_geometry is not None:
                _arc_start, _arc_end, arc_center, geometry_radius = arc_geometry
                cx = float(arc_center.real)
                cy = float(arc_center.imag)
                used_radius = max(min_visible_radius, float(geometry_radius))
                geometry_source = "legacy_arc_center"

        overlay_group.append(
            ET.Element(
                svg_tag(namespace, "circle"),
                {
                    "cx": f"{cx:.4f}",
                    "cy": f"{cy:.4f}",
                    "r": f"{used_radius:.4f}",
                    "fill": "none",
                    "stroke": "#e53e3e",
                    "stroke-width": "2",
                    "opacity": "0.95",
                    "vector-effect": "non-scaling-stroke",
                },
            )
        )

        arc_circles.append(
            {
                "path_id": int(corner.path_id),
                "node_id": int(corner.node_id),
                "center_x": round(cx, 4),
                "center_y": round(cy, 4),
                "used_radius": round(float(used_radius), 4),
                "desired_radius": round(float(desired_radius), 4),
                "source": geometry_source,
            }
        )

    return arc_circles


def append_severity_markers(
    root: ET.Element,
    namespace: str,
    corners: list[CornerSeverity],
    marker_radius: float,
    debug: bool = False,
) -> None:
    """Render simple corner markers directly from severity corner output."""
    group = ET.Element(svg_tag(namespace, "g"), {"id": "detected-corners-overlay"})
    root.append(group)

    radius = max(0.9, marker_radius * 0.55)
    for corner in corners:
        group.append(
            ET.Element(
                svg_tag(namespace, "circle"),
                {
                    "cx": f"{corner.x:.6f}",
                    "cy": f"{corner.y:.6f}",
                    "r": f"{radius:.4f}",
                    "fill": "red",
                    "stroke": "none",
                },
            )
        )
        if debug:
            label = ET.Element(
                svg_tag(namespace, "text"),
                {
                    "x": f"{corner.x + (marker_radius * 1.4):.6f}",
                    "y": f"{corner.y - (marker_radius * 1.4):.6f}",
                    "fill": "red",
                    "font-size": f"{max(8.0, marker_radius * 3.0):.2f}",
                },
            )
            label.text = f"{corner.angle_deg:.1f} deg"
            group.append(label)


def append_diagnostics_overlay(
    root: ET.Element,
    namespace: str,
    corners: list[CornerSeverity],
    diagnostics: DiagnosticsReport,
    debug: bool = False,
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
        label.text = (
            f"f={corner.final_corner_score:.2f} "
            f"t={corner.tangent_angle_deg:.1f} "
            f"l={corner.local_turn_deg:.1f} "
            f"c={corner.curvature_peak:.3f}"
        )
        group.append(label)

        if debug:
            incoming = corner.debug.get("incoming_tangent")
            outgoing = corner.debug.get("outgoing_tangent")
            if isinstance(incoming, list) and len(incoming) == 2:
                ix = float(incoming[0])
                iy = float(incoming[1])
                group.append(
                    ET.Element(
                        svg_tag(namespace, "line"),
                        {
                            "x1": f"{corner.x:.6f}",
                            "y1": f"{corner.y:.6f}",
                            "x2": f"{corner.x - (ix * 8.0):.6f}",
                            "y2": f"{corner.y - (iy * 8.0):.6f}",
                            "stroke": "#6fc3ff",
                            "stroke-width": "1",
                        },
                    )
                )
            if isinstance(outgoing, list) and len(outgoing) == 2:
                ox = float(outgoing[0])
                oy = float(outgoing[1])
                group.append(
                    ET.Element(
                        svg_tag(namespace, "line"),
                        {
                            "x1": f"{corner.x:.6f}",
                            "y1": f"{corner.y:.6f}",
                            "x2": f"{corner.x + (ox * 8.0):.6f}",
                            "y2": f"{corner.y + (oy * 8.0):.6f}",
                            "stroke": "#88ffb6",
                            "stroke-width": "1",
                        },
                    )
                )

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
        arc_preview_data = append_arc_preview_from_severity(
            root=root,
            namespace=namespace,
            corners=severity_corners,
            legacy_corners=legacy_corners,
            corner_radius=corner_radius,
            radius_profile=radius_profile,
            per_corner_radii=per_corner_radii,
        )
        return arc_preview_data

    if export_mode in {"markers_only", "diagnostics_overlay"}:
        append_severity_markers(
            root=root,
            namespace=namespace,
            corners=severity_corners,
            marker_radius=marker_radius,
            debug=debug,
        )

    if export_mode == "diagnostics_overlay":
        append_diagnostics_overlay(
            root=root,
            namespace=namespace,
            corners=severity_corners,
            diagnostics=diagnostics,
            debug=debug,
        )

    return arc_preview_data
