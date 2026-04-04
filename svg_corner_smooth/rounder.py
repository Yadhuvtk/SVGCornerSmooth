"""High-level analyze/round orchestration for SVG corner processing."""

from __future__ import annotations

import io
import time
from collections import defaultdict
from typing import Any

from svgpathtools import Path as SvgPath

from . import legacy_runtime as _legacy
from .curve_solver import solve_fillet_for_corner_rounding
from .detect import detect_corners
from .fillet import FilletSettings, shrink_radius_until_valid
from .models import CornerSeverity, DiagnosticsReport, ProcessingOptions, ProcessingResult, ProcessingSummary, RejectedCorner
from .overlay import apply_overlay
from .parser import build_adjacency_graph, parse_svg_document, write_path_back_to_element
from .radius_profiles import RadiusContext, compute_corner_radius
from .tangents import segment_end_tangent, segment_start_tangent, tangent_angle_degrees
from .utils import safe_segment_length
from .validate import validate_processing_options


def _key(path_id: int, node_id: int) -> str:
    return f"{path_id}:{node_id}"


def _split_corner_key(key: str, fallback_path_id: int, fallback_node_id: int) -> tuple[int, int]:
    """Parse `path_id:node_id` key safely with a legacy fallback."""
    try:
        path_raw, node_raw = key.split(":", 1)
        return int(path_raw), int(node_raw)
    except (ValueError, TypeError):
        return int(fallback_path_id), int(fallback_node_id)


def _requested_radius_for_legacy_corner(
    legacy_corner: Any,
    radius_map: dict[str, float],
    legacy_origin_key_by_id: dict[int, str],
) -> tuple[float, str, str]:
    """
    Resolve requested radius for a legacy trim corner.

    Returns `(requested_radius, legacy_key, source_key)` where:
    - `legacy_key` is the trim corner id used by legacy fillet geometry
    - `source_key` is the original detected corner id used for scoring/radius
    """
    legacy_key = _key(legacy_corner.path_id, legacy_corner.node_id)
    source_key = legacy_origin_key_by_id.get(id(legacy_corner), legacy_key)
    requested = radius_map.get(source_key)
    if requested is None:
        requested = radius_map.get(legacy_key, 0.0)
    return float(requested), legacy_key, source_key


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


def _legacy_candidates(entry: Any, options: ProcessingOptions) -> list[Any]:
    """Build legacy corner candidates used by the legacy fillet geometry engine."""
    relaxed_min_segment = max(0.0, options.min_segment_length * 0.2)
    candidates = _legacy.detect_corners_in_path(
        path=entry.path,
        path_id=entry.path_id,
        angle_threshold=0.0,
        samples_per_curve=options.samples_per_curve,
        min_segment_length=relaxed_min_segment,
        debug=options.debug,
    )
    return list(candidates)


def _corner_point(corner: Any) -> complex:
    return complex(float(corner.x), float(corner.y))


def _match_legacy_corner(
    corner: CornerSeverity,
    legacy_candidates: list[Any],
) -> Any | None:
    """Match detected corner to legacy trim corner using geometry-first logic."""
    if not legacy_candidates:
        return None

    corner_pt = _corner_point(corner)
    local_hint = max(
        0.35,
        float(corner.neighborhood_scale or 0.0),
        float(corner.local_scale or 0.0) * 0.18,
    )
    tolerance = max(0.35, min(local_hint, 7.5))

    def _nearest(candidates: list[Any]) -> tuple[Any, float] | None:
        if not candidates:
            return None
        picked = min(candidates, key=lambda item: abs(_corner_point(item) - corner_pt))
        return picked, float(abs(_corner_point(picked) - corner_pt))

    node_matches = [item for item in legacy_candidates if int(item.node_id) == int(corner.node_id)]
    nearest_node = _nearest(node_matches)
    if nearest_node is not None and nearest_node[1] <= tolerance:
        return nearest_node[0]

    nearest_any = _nearest(legacy_candidates)
    if nearest_any is not None and nearest_any[1] <= tolerance:
        return nearest_any[0]

    return None


def _synthesize_legacy_corner(corner: CornerSeverity, path: Any) -> Any | None:
    """
    Build a legacy-style trim corner from detected geometric evidence.

    This keeps rounding available when strict/hybrid detection finds a corner
    that the legacy candidate scan skipped due tiny local segments.
    """
    if path is None or len(path) < 2:
        return None

    raw_next = int(corner.segment_index_after if corner.segment_index_after >= 0 else corner.node_id)
    raw_prev = int(corner.segment_index_before)
    if raw_next < 0 or raw_next >= len(path):
        return None
    if raw_prev < 0 or raw_prev >= len(path):
        raw_prev = (raw_next - 1) % len(path)

    corner_point = complex(float(corner.x), float(corner.y))

    def _candidate_indices(seed: int) -> list[int]:
        out: list[int] = []
        for index in (seed - 1, seed, seed + 1):
            if 0 <= index < len(path) and index not in out:
                out.append(index)
        return out

    prev_options = _candidate_indices(raw_prev)
    next_options = _candidate_indices(raw_next)

    best_pair: tuple[int, int, complex, float] | None = None
    for prev_index in prev_options:
        prev_seg = path[prev_index]
        prev_end = complex(prev_seg.end)
        for next_index in next_options:
            if next_index == prev_index:
                continue
            next_seg = path[next_index]
            next_start = complex(next_seg.start)
            gap = abs(prev_end - next_start)
            if gap > 2.0:
                continue
            join_point = (prev_end + next_start) * 0.5
            point_distance = abs(join_point - corner_point)
            fit_score = (gap * 2.0) + point_distance
            if best_pair is None or fit_score < best_pair[3]:
                best_pair = (prev_index, next_index, join_point, fit_score)

    if best_pair is None:
        return None

    prev_index, next_index, join_point, _ = best_pair
    prev_seg = path[prev_index]
    next_seg = path[next_index]

    incoming_vec: complex | None = None
    outgoing_vec: complex | None = None
    incoming_debug = corner.debug.get("incoming_tangent")
    outgoing_debug = corner.debug.get("outgoing_tangent")
    if isinstance(incoming_debug, list) and len(incoming_debug) == 2:
        incoming_vec = complex(float(incoming_debug[0]), float(incoming_debug[1]))
    if isinstance(outgoing_debug, list) and len(outgoing_debug) == 2:
        outgoing_vec = complex(float(outgoing_debug[0]), float(outgoing_debug[1]))

    if incoming_vec is None:
        incoming_vec, incoming_conf = segment_end_tangent(prev_seg)
        if incoming_conf <= 0.0:
            return None
    if outgoing_vec is None:
        outgoing_vec, outgoing_conf = segment_start_tangent(next_seg)
        if outgoing_conf <= 0.0:
            return None

    prev_len = float(corner.prev_segment_length or safe_segment_length(prev_seg))
    next_len = float(corner.next_segment_length or safe_segment_length(next_seg))
    if prev_len <= 1e-9 or next_len <= 1e-9:
        return None

    angle = float(corner.angle_deg or tangent_angle_degrees(incoming_vec, outgoing_vec))
    return _legacy.CornerDetection(
        path_id=int(corner.path_id),
        node_id=int(next_index),
        x=float(join_point.real),
        y=float(join_point.imag),
        angle_deg=angle,
        incoming_dx=float(incoming_vec.real),
        incoming_dy=float(incoming_vec.imag),
        outgoing_dx=float(outgoing_vec.real),
        outgoing_dy=float(outgoing_vec.imag),
        prev_segment_length=prev_len,
        next_segment_length=next_len,
    )


def _allow_rounding(corner: CornerSeverity, angle_threshold: float) -> tuple[bool, str | None]:
    """
    Gate fragile corners before geometric fillet application.

    Hybrid detection can include low-confidence mild turns that are useful for
    diagnostics but unsafe to fillet with large radii.
    """
    score = float(corner.final_corner_score or corner.severity_score or 0.0)
    if score < 0.02:
        return False, "low_confidence_corner"

    mild_turn_limit = max(55.0, angle_threshold + 10.0)
    if corner.angle_deg < mild_turn_limit and score < 0.06:
        return False, "low_angle_low_confidence"

    return True, None


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
        # Keep neighboring rounded corners compatible on short spans:
        # if two corners are close, cap radius so both fillets can coexist
        # instead of one being dropped later by overlap conflict resolution.
        nearest_neighbor = min(prev_dist, next_dist)
        if nearest_neighbor != float("inf"):
            safe_cap = max(0.0, nearest_neighbor * 0.45)
            if radius > safe_cap:
                radius = safe_cap
                corner.diagnostic_notes.append(
                    f"radius_capped_by_neighbor_spacing:{safe_cap:.4f}"
                )
        corner.suggested_radius = radius
        radius_map[key] = radius

    return radius_map


def _to_svg_text(tree: Any) -> str:
    output = io.BytesIO()
    tree.write(output, encoding="utf-8", xml_declaration=True)
    return output.getvalue().decode("utf-8")


def _find_corner_near_shared_point(
    corners: list[CornerSeverity],
    path_id: int,
    shared_point: complex,
    tolerance: float,
) -> CornerSeverity | None:
    best: CornerSeverity | None = None
    best_distance = float("inf")
    for corner in corners:
        if corner.path_id != path_id:
            continue
        distance = abs(complex(corner.x, corner.y) - shared_point)
        if distance > tolerance:
            continue
        if distance < best_distance:
            best = corner
            best_distance = distance
    return best


def _apply_adjacency_constraints(
    corners: list[CornerSeverity],
    radius_map: dict[str, float],
    paths: list[Any],
    diagnostics: DiagnosticsReport,
    tolerance: float = 0.5,
) -> list[dict[str, float]]:
    """Constrain shared-endpoint corners to the same radius across adjacent paths."""
    graph = build_adjacency_graph(paths, tolerance=tolerance)
    adjacency_payload: list[dict[str, float]] = []
    seen_edges: set[tuple[int, int, int, int]] = set()

    for path_a, neighbors in graph.adjacency.items():
        for path_b, shared_point in neighbors:
            if path_a == path_b:
                continue

            lo, hi = sorted((path_a, path_b))
            edge_key = (
                lo,
                hi,
                int(round(shared_point.real * 10)),
                int(round(shared_point.imag * 10)),
            )
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            corner_a = _find_corner_near_shared_point(corners, path_a, shared_point, tolerance=tolerance)
            corner_b = _find_corner_near_shared_point(corners, path_b, shared_point, tolerance=tolerance)
            if corner_a is None or corner_b is None:
                continue

            key_a = _key(corner_a.path_id, corner_a.node_id)
            key_b = _key(corner_b.path_id, corner_b.node_id)
            radius_a = radius_map.get(key_a, 0.0)
            radius_b = radius_map.get(key_b, 0.0)
            constrained = min(radius_a, radius_b)

            if constrained > 0.0:
                radius_map[key_a] = constrained
                radius_map[key_b] = constrained
                corner_a.suggested_radius = constrained
                corner_b.suggested_radius = constrained
                note = (
                    f"constrained by adjacency with {key_b} at "
                    f"({shared_point.real:.3f},{shared_point.imag:.3f})"
                )
                diagnostics.warnings.append(f"corner {key_a} {note}")
                corner_a.diagnostic_notes.append(note)
                corner_b.diagnostic_notes.append(
                    f"constrained by adjacency with {key_a} at "
                    f"({shared_point.real:.3f},{shared_point.imag:.3f})"
                )

            adjacency_payload.append(
                {
                    "path_a": int(path_a),
                    "path_b": int(path_b),
                    "shared_point_x": float(shared_point.real),
                    "shared_point_y": float(shared_point.imag),
                }
            )

    return adjacency_payload


def _stitch_tiny_path_gaps(path: Any, tolerance: float = 1e-6) -> None:
    """
    Snap near-contiguous segment joins to exact continuity.

    Rounding can introduce tiny floating-point gaps (for example ~1e-13) between
    adjacent segment endpoints. Some SVG serializers emit new `M` commands for
    these gaps, which can create visible fill artifacts. This stitch keeps real
    subpath breaks intact while removing micro-gaps.
    """
    if path is None or len(path) < 2:
        return

    tol = max(1e-12, float(tolerance))

    # Pass 1: snap adjacent joins when gap is tiny.
    for index in range(1, len(path)):
        prev_seg = path[index - 1]
        curr_seg = path[index]
        gap = abs(complex(curr_seg.start) - complex(prev_seg.end))
        if gap <= tol:
            curr_seg.start = prev_seg.end

    # Pass 2: close each near-closed contiguous run.
    run_start = 0
    for index in range(1, len(path) + 1):
        boundary = index == len(path)
        if not boundary:
            gap = abs(complex(path[index].start) - complex(path[index - 1].end))
            boundary = gap > tol

        if not boundary:
            continue

        run_end = index - 1
        if run_end > run_start:
            closure_gap = abs(complex(path[run_start].start) - complex(path[run_end].end))
            if closure_gap <= tol:
                path[run_start].start = path[run_end].end
        run_start = index


def _sanitize_path_segments(path: Any, length_tolerance: float = 1e-9) -> Any:
    """
    Remove degenerate near-zero-length segments from a path.

    Zero-length segments are common in exported glyph outlines and can break
    corner indexing in fillet construction (the "previous segment" becomes a
    zero segment). Keeping only drawable segments stabilizes rounding behavior.
    """
    if path is None or len(path) == 0:
        return path

    tol = max(1e-12, float(length_tolerance))
    kept = [segment for segment in path if safe_segment_length(segment) > tol]
    if not kept:
        return path
    if len(kept) == len(path):
        return path
    return SvgPath(*kept)


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
    should_round = options.apply_rounding or options.export_mode == "apply_rounding"
    needs_legacy_candidates = should_round or options.export_mode == "preview_arcs"

    if not parsed_doc.entries:
        diagnostics.warnings.append("No supported geometry elements found.")
        summary.processing_ms = (time.perf_counter() - started) * 1000.0
        return ProcessingResult(
            svg_text=_to_svg_text(parsed_doc.tree),
            corners=[],
            summary=summary,
            diagnostics=diagnostics,
            arc_preview=[],
            adjacency=[],
        )

    severity_corners: list[CornerSeverity] = []
    legacy_selected: list[Any] = []
    legacy_by_path: dict[int, list[Any]] = defaultdict(list)
    legacy_origin_key_by_id: dict[int, str] = {}
    sanitize_length_tolerance = max(1e-9, min(0.25, float(options.min_segment_length) * 0.05))
    stitch_tolerance = max(1e-6, sanitize_length_tolerance * 2.0)

    for entry in parsed_doc.entries:
        entry.path = _sanitize_path_segments(entry.path, length_tolerance=sanitize_length_tolerance)
        _stitch_tiny_path_gaps(entry.path, tolerance=stitch_tolerance)
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

        if not needs_legacy_candidates:
            continue

        candidate_pool = _legacy_candidates(entry, options)
        for corner in detected:
            if should_round:
                can_round, gate_reason = _allow_rounding(corner, options.angle_threshold)
                if not can_round:
                    diagnostics.warnings.append(
                        f"Skipped rounding gate for path {corner.path_id} node {corner.node_id}: {gate_reason}."
                    )
                    continue

            legacy_corner = _match_legacy_corner(corner, candidate_pool)
            if legacy_corner is None:
                synthesized = _synthesize_legacy_corner(corner, entry.path)
                if synthesized is None:
                    # Last-resort fallback: validate directly with curve solver and
                    # create a minimal legacy-compatible trim candidate.
                    direct_payload = solve_fillet_for_corner_rounding(
                        path=entry.path,
                        corner=corner,
                        desired_radius=max(0.5, float(options.corner_radius)),
                    )
                    if direct_payload is None:
                        diagnostics.warnings.append(
                            f"Missing trim candidate for path {corner.path_id} node {corner.node_id}; skipped for rounding."
                        )
                        continue
                    legacy_corner = _legacy.CornerDetection(**direct_payload)
                    diagnostics.warnings.append(
                        f"Curve-solver fallback trim candidate for path {corner.path_id} node {corner.node_id}."
                    )
                else:
                    legacy_corner = synthesized
                    diagnostics.warnings.append(
                        f"Synthesized trim candidate for path {corner.path_id} node {corner.node_id}."
                    )
            elif legacy_corner in candidate_pool:
                # Keep one-to-one mapping between detected and trim candidates.
                candidate_pool.remove(legacy_corner)

            legacy_selected.append(legacy_corner)
            legacy_origin_key_by_id[id(legacy_corner)] = _key(corner.path_id, corner.node_id)
            if should_round:
                legacy_by_path[corner.path_id].append(legacy_corner)

    summary.corners_found = len(severity_corners)
    radius_map = _compute_radius_map(severity_corners, options)
    adjacency_payload = _apply_adjacency_constraints(
        corners=severity_corners,
        radius_map=radius_map,
        paths=[entry.path for entry in parsed_doc.entries],
        diagnostics=diagnostics,
    )

    rounded_count = 0
    skipped_count = 0

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
                requested, legacy_key, source_key = _requested_radius_for_legacy_corner(
                    legacy_corner=legacy_corner,
                    radius_map=radius_map,
                    legacy_origin_key_by_id=legacy_origin_key_by_id,
                )

                source_path_id, source_node_id = _split_corner_key(
                    source_key,
                    fallback_path_id=legacy_corner.path_id,
                    fallback_node_id=legacy_corner.node_id,
                )
                if requested <= 0.0:
                    skipped_count += 1
                    diagnostics.rejected_corners.append(
                        RejectedCorner(
                            path_id=source_path_id,
                            node_id=source_node_id,
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
                            path_id=source_path_id,
                            node_id=source_node_id,
                            reason=validation.reason,
                            attempted_radius=requested,
                            final_radius=validation.radius,
                        )
                    )
                    if not options.skip_invalid_corners:
                        continue
                    continue

                accepted.append(legacy_corner)
                used_per_corner[legacy_key] = validation.radius
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
            rounded_path = _sanitize_path_segments(rounded_path, length_tolerance=sanitize_length_tolerance)
            _stitch_tiny_path_gaps(rounded_path, tolerance=stitch_tolerance)
            entry.path = rounded_path
            write_path_back_to_element(entry, rounded_path, parsed_doc.namespace)

    export_mode = options.export_mode
    if should_round:
        export_mode = "apply_rounding"

    path_lookup = {int(entry.path_id): entry.path for entry in parsed_doc.entries}
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
        path_lookup=path_lookup,
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
        adjacency=adjacency_payload,
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
