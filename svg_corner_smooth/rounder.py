"""High-level analyze/round orchestration for SVG corner processing."""

from __future__ import annotations

import io
import time
from collections import defaultdict
from typing import Any

from . import _legacy
from .detect import detect_corners
from .fillet import FilletSettings, shrink_radius_until_valid
from .models import CornerSeverity, DiagnosticsReport, ProcessingOptions, ProcessingResult, ProcessingSummary, RejectedCorner
from .overlay import apply_overlay
from .parser import parse_svg_document, write_path_back_to_element
from .radius_profiles import RadiusContext, compute_corner_radius
from .validate import validate_processing_options


def _key(path_id: int, node_id: int) -> str:
    return f"{path_id}:{node_id}"


def _distance(a: CornerSeverity, b: CornerSeverity) -> float:
    dx = a.x - b.x
    dy = a.y - b.y
    return float((dx * dx + dy * dy) ** 0.5)


def _neighbor_distances(corners: list[CornerSeverity]) -> dict[str, tuple[float, float]]:
    """Return distance-to-prev/next-corner map per corner key."""
    by_path: dict[int, list[CornerSeverity]] = defaultdict(list)
    for corner in corners:
        by_path[corner.path_id].append(corner)

    out: dict[str, tuple[float, float]] = {}
    for path_corners in by_path.values():
        ordered = sorted(path_corners, key=lambda item: item.node_id)
        if len(ordered) == 1:
            only = ordered[0]
            out[_key(only.path_id, only.node_id)] = (float("inf"), float("inf"))
            continue

        for index, corner in enumerate(ordered):
            prev_d = float("inf")
            next_d = float("inf")
            if index > 0:
                prev_d = _distance(corner, ordered[index - 1])
            if index + 1 < len(ordered):
                next_d = _distance(corner, ordered[index + 1])
            out[_key(corner.path_id, corner.node_id)] = (prev_d, next_d)

    return out


def _legacy_candidates(entry: Any, options: ProcessingOptions) -> dict[int, Any]:
    """Build legacy corner candidates keyed by node id for rounding geometry."""
    candidates = _legacy.detect_corners_in_path(
        path=entry.path,
        path_id=entry.path_id,
        angle_threshold=0.0,
        samples_per_curve=options.samples_per_curve,
        min_segment_length=options.min_segment_length,
        debug=options.debug,
    )
    return {item.node_id: item for item in candidates}


def _compute_radius_map(
    corners: list[CornerSeverity],
    options: ProcessingOptions,
) -> dict[str, float]:
    """Compute suggested/effective radius per detected corner."""
    distances = _neighbor_distances(corners)
    radius_map: dict[str, float] = {}
    overrides = options.per_corner_radii or {}

    for corner in corners:
        key = _key(corner.path_id, corner.node_id)
        if key in overrides:
            radius = max(0.0, float(overrides[key]))
            corner.suggested_radius = radius
            radius_map[key] = radius
            continue

        prev_dist, next_dist = distances.get(key, (float("inf"), float("inf")))
        context = RadiusContext(
            distance_to_prev_corner=prev_dist,
            distance_to_next_corner=next_dist,
            collision_risk=corner.risk_score,
        )
        radius = compute_corner_radius(
            corner=corner,
            context=context,
            requested_radius=options.corner_radius,
            profile=options.radius_profile,
        )
        corner.suggested_radius = radius
        radius_map[key] = radius

    return radius_map


def _to_svg_text(tree: Any) -> str:
    output = io.BytesIO()
    tree.write(output, encoding="utf-8", xml_declaration=True)
    return output.getvalue().decode("utf-8")


def process_parsed_document(parsed_doc: Any, options: ProcessingOptions) -> ProcessingResult:
    """Process a parsed SVG document and return corner diagnostics + output SVG."""
    validate_processing_options(options)
    started = time.perf_counter()

    diagnostics = DiagnosticsReport(
        warnings=[],
        mode=options.detection_mode,
        radius_profile=options.radius_profile,
        export_mode=options.export_mode,
    )
    summary = ProcessingSummary(paths_found=len(parsed_doc.entries))

    if not parsed_doc.entries:
        diagnostics.warnings.append("No supported geometry elements found.")
        summary.processing_ms = (time.perf_counter() - started) * 1000.0
        return ProcessingResult(
            svg_text=_to_svg_text(parsed_doc.tree),
            corners=[],
            summary=summary,
            diagnostics=diagnostics,
            arc_preview=[],
        )

    severity_corners: list[CornerSeverity] = []
    legacy_selected: list[Any] = []
    legacy_by_path: dict[int, list[Any]] = defaultdict(list)

    for entry in parsed_doc.entries:
        detected = detect_corners(
            path=entry.path,
            path_id=entry.path_id,
            angle_threshold=options.angle_threshold,
            min_segment_length=options.min_segment_length,
            samples_per_curve=options.samples_per_curve,
            mode=options.detection_mode,
            debug=options.debug,
        )
        severity_corners.extend(detected)

        candidate_map = _legacy_candidates(entry, options)
        for corner in detected:
            legacy_corner = candidate_map.get(corner.node_id)
            if legacy_corner is None:
                diagnostics.warnings.append(
                    f"Missing trim candidate for path {corner.path_id} node {corner.node_id}; skipped for rounding."
                )
                continue
            legacy_selected.append(legacy_corner)
            legacy_by_path[corner.path_id].append(legacy_corner)

    summary.corners_found = len(severity_corners)
    radius_map = _compute_radius_map(severity_corners, options)

    rounded_count = 0
    skipped_count = 0

    should_round = options.apply_rounding or options.export_mode == "apply_rounding"
    if should_round and options.corner_radius <= 0.0 and not options.per_corner_radii:
        diagnostics.warnings.append("Rounding requested but corner_radius is 0; no fillets applied.")
        should_round = False

    if should_round:
        fillet_settings = FilletSettings(
            max_radius_shrink_iterations=options.max_radius_shrink_iterations,
            min_allowed_radius=options.min_allowed_radius,
            skip_invalid_corners=options.skip_invalid_corners,
            exact_curve_trim=options.exact_curve_trim,
            intersection_safety_margin=options.intersection_safety_margin,
        )

        for entry in parsed_doc.entries:
            path_corners = legacy_by_path.get(entry.path_id, [])
            if not path_corners:
                continue

            used_per_corner: dict[str, float] = {}
            accepted: list[Any] = []
            for legacy_corner in path_corners:
                key = _key(legacy_corner.path_id, legacy_corner.node_id)
                requested = radius_map.get(key, 0.0)
                if requested <= 0.0:
                    skipped_count += 1
                    diagnostics.rejected_corners.append(
                        RejectedCorner(
                            path_id=legacy_corner.path_id,
                            node_id=legacy_corner.node_id,
                            reason="radius_zero",
                            attempted_radius=requested,
                            final_radius=0.0,
                        )
                    )
                    continue

                validation = shrink_radius_until_valid(
                    corner=legacy_corner,
                    initial_radius=requested,
                    settings=fillet_settings,
                )
                if not validation.valid:
                    skipped_count += 1
                    diagnostics.rejected_corners.append(
                        RejectedCorner(
                            path_id=legacy_corner.path_id,
                            node_id=legacy_corner.node_id,
                            reason=validation.reason,
                            attempted_radius=requested,
                            final_radius=validation.radius,
                        )
                    )
                    if not options.skip_invalid_corners:
                        continue
                    continue

                accepted.append(legacy_corner)
                used_per_corner[key] = validation.radius
                rounded_count += 1

            if not accepted:
                continue

            rounded_path = _legacy.round_path_geometry(
                path=entry.path,
                path_id=entry.path_id,
                corners=accepted,
                desired_radius=0.0,
                radius_profile="fixed",
                samples_per_curve=options.samples_per_curve,
                debug=options.debug,
                per_corner_radii=used_per_corner,
            )
            entry.path = rounded_path
            write_path_back_to_element(entry, rounded_path, parsed_doc.namespace)

    export_mode = options.export_mode
    if should_round:
        export_mode = "apply_rounding"

    arc_preview = apply_overlay(
        root=parsed_doc.root,
        namespace=parsed_doc.namespace,
        legacy_corners=legacy_selected,
        severity_corners=severity_corners,
        export_mode=export_mode,
        marker_radius=options.marker_radius,
        corner_radius=options.corner_radius,
        radius_profile=options.radius_profile,
        debug=options.debug,
        diagnostics=diagnostics,
        per_corner_radii=options.per_corner_radii,
    )

    summary.corners_rounded = rounded_count
    summary.corners_skipped = skipped_count
    summary.processing_ms = (time.perf_counter() - started) * 1000.0

    return ProcessingResult(
        svg_text=_to_svg_text(parsed_doc.tree),
        corners=severity_corners,
        summary=summary,
        diagnostics=diagnostics,
        arc_preview=arc_preview,
    )


def process_svg(svg_source: str | bytes, options: ProcessingOptions) -> ProcessingResult:
    """Parse + process SVG source into diagnostics and output SVG."""
    parsed = parse_svg_document(svg_source, debug=options.debug)
    return process_parsed_document(parsed, options)


def analyze_svg(svg_source: str | bytes, options: ProcessingOptions) -> ProcessingResult:
    """Analyze-only mode wrapper that never applies geometric rounding."""
    copy = ProcessingOptions(**vars(options))
    copy.apply_rounding = False
    if copy.export_mode == "apply_rounding":
        copy.export_mode = "diagnostics_overlay"
    return process_svg(svg_source, copy)


def round_svg(svg_source: str | bytes, options: ProcessingOptions) -> ProcessingResult:
    """Force rounding mode wrapper."""
    copy = ProcessingOptions(**vars(options))
    copy.apply_rounding = True
    copy.export_mode = "apply_rounding"
    return process_svg(svg_source, copy)
