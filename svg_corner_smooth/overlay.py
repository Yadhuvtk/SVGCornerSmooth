"""Overlay rendering helpers for markers, previews, and diagnostics layers."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Optional

from .constants import CONTINUITY_TOLERANCE
from .models import CornerSeverity, DiagnosticsReport
from .parser import svg_tag
from .tangents import safe_unit_vector, segment_end_tangent, segment_start_tangent

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
    path_lookup: Optional[dict[int, Any]] = None,
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
    if corners:
        min_x = min(float(corner.x) for corner in corners)
        max_x = max(float(corner.x) for corner in corners)
        min_y = min(float(corner.y) for corner in corners)
        max_y = max(float(corner.y) for corner in corners)
        geometry_diag = math.hypot(max_x - min_x, max_y - min_y)
    else:
        geometry_diag = 0.0

    # Arc preview circles are visual guidance only, so keep a scale-aware floor
    # to avoid nearly invisible rings on large-coordinate SVGs.
    scale_floor = geometry_diag * 0.0022 if geometry_diag > 0.0 else 0.0
    profile_floor = float(corner_radius) * 0.28 if float(corner_radius) > 0.0 else 3.0
    min_display_radius = max(3.0, profile_floor, scale_floor)
    min_display_radius = min(min_display_radius, max(18.0, float(corner_radius) * 1.8))
    normalized_profile = "vectorizer" if radius_profile == "vectorizer_legacy" else radius_profile
    remaining_legacy = list(legacy_corners)

    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

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

    def _estimate_bisector_center(corner: CornerSeverity, desired_radius: float) -> tuple[complex, float, str] | None:
        if path_lookup is None:
            return None

        path = path_lookup.get(int(corner.path_id))
        if path is None:
            return None

        before_index = int(corner.segment_index_before)
        after_index = int(corner.segment_index_after)
        if len(path) < 1:
            return None

        corner_point = complex(float(corner.x), float(corner.y))
        local_hint = max(
            1.0,
            float(corner.neighborhood_scale or 0.0),
            float(corner.local_scale or 0.0) * 0.25,
            float(desired_radius) * 1.15,
        )
        max_endpoint_gap = max(2.0, min(32.0, local_hint * 3.0))

        segment_pairs: list[tuple[int, int]] = []

        def _add_pair(prev_idx: int, next_idx: int) -> None:
            if prev_idx < 0 or next_idx < 0:
                return
            if prev_idx >= len(path) or next_idx >= len(path):
                return
            pair = (int(prev_idx), int(next_idx))
            if pair not in segment_pairs:
                segment_pairs.append(pair)

        _add_pair(before_index, after_index)

        node_index = int(corner.node_id)
        if 0 < node_index < len(path):
            _add_pair(node_index - 1, node_index)
        elif node_index == 0 and len(path) >= 2:
            is_closed = abs(complex(path[-1].end) - complex(path[0].start)) <= max(1e-3, local_hint * 0.2)
            if is_closed:
                _add_pair(len(path) - 1, 0)

        _add_pair(after_index - 1, after_index)
        _add_pair(before_index, before_index + 1)

        if before_index == after_index and len(path) >= 2:
            _add_pair(before_index - 1, before_index)
            _add_pair(before_index, before_index + 1)

        if not segment_pairs:
            return None

        def _estimate_from_pair(prev_idx: int, next_idx: int) -> tuple[complex, float, str, float] | None:
            prev_seg = path[prev_idx]
            next_seg = path[next_idx]

            prev_options: list[tuple[complex, complex]] = []
            next_options: list[tuple[complex, complex]] = []

            try:
                prev_end, _ = segment_end_tangent(prev_seg)
                prev_options.append((complex(prev_seg.end), safe_unit_vector(-prev_end)))
            except Exception:
                pass
            try:
                prev_start, _ = segment_start_tangent(prev_seg)
                prev_options.append((complex(prev_seg.start), safe_unit_vector(prev_start)))
            except Exception:
                pass
            try:
                next_start, _ = segment_start_tangent(next_seg)
                next_options.append((complex(next_seg.start), safe_unit_vector(next_start)))
            except Exception:
                pass
            try:
                next_end, _ = segment_end_tangent(next_seg)
                next_options.append((complex(next_seg.end), safe_unit_vector(-next_end)))
            except Exception:
                pass

            if not prev_options or not next_options:
                return None

            best_combo: tuple[complex, float, str, float] | None = None

            for prev_point, prev_ray in prev_options:
                for next_point, next_ray in next_options:
                    endpoint_gap = float(abs(prev_point - next_point))
                    endpoint_to_corner = float(min(abs(prev_point - corner_point), abs(next_point - corner_point)))

                    if endpoint_gap <= max_endpoint_gap or endpoint_gap <= CONTINUITY_TOLERANCE:
                        join_point = (prev_point + next_point) * 0.5
                    else:
                        if endpoint_to_corner > max_endpoint_gap:
                            continue
                        join_point = corner_point

                    bisector = prev_ray + next_ray
                    if abs(bisector) <= 1e-9:
                        continue

                    dot = _clamp(
                        (prev_ray.real * next_ray.real) + (prev_ray.imag * next_ray.imag),
                        -1.0,
                        1.0,
                    )
                    theta = math.acos(dot)
                    if theta < math.radians(18.0) or theta > math.radians(176.0):
                        continue

                    used = max(min_visible_radius, float(desired_radius))
                    sin_half = math.sin(theta * 0.5)
                    if sin_half <= 1e-6:
                        continue

                    offset = used / sin_half
                    max_offset = max(used * 5.0, local_hint * 5.0)
                    source = "estimated_bisector_center"
                    if offset > max_offset:
                        offset = max_offset
                        source = "estimated_bisector_center_clamped"

                    center = join_point + (safe_unit_vector(bisector) * offset)
                    fit_score = endpoint_gap + endpoint_to_corner + (0.25 * abs(join_point - corner_point))

                    candidate = (center, used, source, fit_score)
                    if best_combo is None or candidate[3] < best_combo[3]:
                        best_combo = candidate

            return best_combo

        best: tuple[complex, float, str, float] | None = None
        for prev_idx, next_idx in segment_pairs:
            estimate = _estimate_from_pair(prev_idx, next_idx)
            if estimate is None:
                continue
            if best is None or estimate[3] < best[3]:
                best = estimate

        if best is None:
            return None
        return best[0], best[1], best[2]

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
        display_radius = max(float(used_radius), float(min_display_radius))
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
                display_radius = max(float(used_radius), float(min_display_radius))
                geometry_source = "legacy_arc_center"

        if geometry_source == "fallback":
            estimated = _estimate_bisector_center(corner, desired_radius)
            if estimated is not None:
                center, estimated_radius, estimated_source = estimated
                cx = float(center.real)
                cy = float(center.imag)
                used_radius = max(min_visible_radius, float(estimated_radius))
                display_radius = max(float(used_radius), float(min_display_radius))
                geometry_source = estimated_source

        # For unresolved fallback corners with tiny computed radii, keep marker
        # visible but avoid an oversized "wrong-looking" ring.
        if geometry_source == "fallback" and desired_radius < 0.5:
            display_radius = max(3.0, min_display_radius * 0.45)

        overlay_group.append(
            ET.Element(
                svg_tag(namespace, "circle"),
                {
                    "cx": f"{cx:.4f}",
                    "cy": f"{cy:.4f}",
                    "r": f"{display_radius:.4f}",
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
                "display_radius": round(float(display_radius), 4),
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
    path_lookup: Optional[dict[int, Any]] = None,
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
            path_lookup=path_lookup,
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
