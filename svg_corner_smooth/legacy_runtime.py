#!/usr/bin/env python3
# Install: pip install svgpathtools
"""Detect sharp corners in SVG paths and optionally mark them in a new SVG."""

from __future__ import annotations

import argparse
import math
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from svgpathtools import Arc, CubicBezier, Line, Path, QuadraticBezier, parse_path


EPSILON = 1e-12
CONTINUITY_TOLERANCE = 1e-9


@dataclass
class CornerDetection:
    """Represents a detected corner on a path join."""

    path_id: int
    node_id: int
    x: float
    y: float
    angle_deg: float
    incoming_dx: float
    incoming_dy: float
    outgoing_dx: float
    outgoing_dy: float
    prev_segment_length: float
    next_segment_length: float


@dataclass
class CornerRounding:
    """Stores per-corner trimming and arc data for rounded path reconstruction."""

    node_id: int
    prev_index: int
    next_index: int
    prev_trim_t: float
    next_trim_t: float
    arc_segment: Arc
    used_radius: float


@dataclass
class PlotBounds:
    """Simple axis-aligned bounds used by the live window canvas."""

    min_x: float
    max_x: float
    min_y: float
    max_y: float


def build_cli_parser() -> argparse.ArgumentParser:
    """Create the command-line parser for the script."""
    parser = argparse.ArgumentParser(
        description=(
            "Read an SVG file, detect sharp corners on <path> geometry, and optionally "
            "write an output SVG with red corner markers."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python detect_svg_corners.py input.svg\n"
            "  python detect_svg_corners.py input.svg output.svg --angle-threshold 35 --debug\n"
            "  python detect_svg_corners.py input.svg --realtime\n"
            "  python detect_svg_corners.py input.svg --live-window\n"
            "  python detect_svg_corners.py input.svg output.svg --corner-radius 12 --live-window\n"
            "  python detect_svg_corners.py input.svg rounded.svg --corner-radius 12 --apply-rounding\n"
            "  python detect_svg_corners.py input.svg rounded.svg --corner-radius 18 "
            "--radius-profile vectorizer --apply-rounding"
        ),
    )
    parser.add_argument("input_svg", help="Path to input SVG file.")
    parser.add_argument("output_svg", nargs="?", default=None, help="Optional output SVG path.")
    parser.add_argument(
        "--angle-threshold",
        type=float,
        default=45.0,
        help="Minimum turning angle in degrees to classify as sharp corner (default: 45.0).",
    )
    parser.add_argument(
        "--samples-per-curve",
        type=int,
        default=25,
        help="Sampling density used for endpoint tangent fallback (default: 25).",
    )
    parser.add_argument(
        "--marker-radius",
        type=float,
        default=3.0,
        help="Radius of red corner markers in output SVG (default: 3.0).",
    )
    parser.add_argument(
        "--corner-radius",
        type=float,
        default=0.0,
        help=(
            "If > 0, draw rounded-corner arc markers with this radius in SVG units "
            "instead of point dots."
        ),
    )
    parser.add_argument(
        "--radius-profile",
        choices=("fixed", "vectorizer"),
        default="fixed",
        help=(
            "Corner-radius behavior: 'fixed' keeps one radius value, 'vectorizer' "
            "adapts radius by angle/geometry for smoother high-quality results."
        ),
    )
    parser.add_argument(
        "--apply-rounding",
        action="store_true",
        help=(
            "When writing output SVG, replace sharp corners in path geometry with "
            "rounded fillet arcs (uses --corner-radius)."
        ),
    )
    parser.add_argument(
        "--min-segment-length",
        type=float,
        default=1.0,
        help="Ignore joins where adjacent segment length is below this value (default: 1.0).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print diagnostic info to stderr and add angle text labels in output SVG.",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="Stream each detected corner to stdout as soon as it is found.",
    )
    parser.add_argument(
        "--live-window",
        action="store_true",
        help="Show a GUI window and update detected corners live during scanning.",
    )
    return parser


def debug_log(enabled: bool, message: str) -> None:
    """Print a debug message to stderr when debug mode is enabled."""
    if enabled:
        print(f"[debug] {message}", file=sys.stderr, flush=True)


def extract_namespace(tag: str) -> str:
    """Extract XML namespace URI from a tag like '{namespace}svg'."""
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return ""


def svg_tag(namespace: str, local_name: str) -> str:
    """Return namespaced tag if namespace exists, otherwise plain tag."""
    if namespace:
        return f"{{{namespace}}}{local_name}"
    return local_name


def clamp(value: float, min_value: float, max_value: float) -> float:
    """Clamp a number to a closed interval."""
    return max(min_value, min(max_value, value))


def normalize_vector(vector: complex) -> Optional[complex]:
    """Normalize a complex vector; return None for near-zero vectors."""
    magnitude = abs(vector)
    if magnitude <= EPSILON:
        return None
    return vector / magnitude


def effective_corner_radius(corner: CornerDetection, requested_radius: float, radius_profile: str) -> float:
    """
    Compute corner-specific radius from a base request.

    `fixed`: returns requested radius.
    `vectorizer`: adapts radius so wider turns (around 100-120 degrees) get
    smaller fillets, which usually preserves silhouette quality better.

    Note: this legacy helper only knows `fixed` and `vectorizer`.
    Modern profiles (`adaptive`, `preserve_shape`, `aggressive`, etc.) are
    treated as `fixed` to avoid unintended aggressive shrink in legacy overlays.
    """
    if requested_radius <= 0.0:
        return 0.0

    if radius_profile not in {"fixed", "vectorizer"}:
        return requested_radius

    if radius_profile == "fixed":
        return requested_radius

    angle = corner.angle_deg
    if angle >= 120.0:
        angle_scale = 0.28
    elif angle >= 105.0:
        angle_scale = 0.38
    elif angle >= 90.0:
        angle_scale = 0.55
    elif angle >= 75.0:
        angle_scale = 0.75
    else:
        angle_scale = 1.0

    local_length = min(corner.prev_segment_length, corner.next_segment_length)
    length_scale = clamp(local_length / (requested_radius * 4.0 + EPSILON), 0.35, 1.0)
    adapted = requested_radius * angle_scale * length_scale

    min_radius = max(0.5, requested_radius * 0.12)
    return max(min_radius, adapted)


def safe_segment_length(segment: Any) -> float:
    """
    Get segment length robustly across segment types.

    Uses analytic length when available; falls back to polyline approximation.
    """
    if isinstance(segment, Line):
        return float(abs(segment.end - segment.start))

    try:
        return float(segment.length(error=1e-6))
    except TypeError:
        try:
            return float(segment.length())
        except Exception:
            pass
    except Exception:
        pass

    samples = 20
    total = 0.0
    try:
        prev = segment.point(0.0)
        for index in range(1, samples + 1):
            t_value = index / samples
            current = segment.point(t_value)
            total += abs(current - prev)
            prev = current
    except Exception:
        return 0.0
    return float(total)


def sample_endpoint_vector(segment: Any, at_end: bool, step: float) -> complex:
    """
    Sample a directional vector near a segment endpoint.

    For incoming direction (at_end=True), returns point(1) - point(1-step).
    For outgoing direction (at_end=False), returns point(step) - point(0).
    """
    step = clamp(step, 1e-6, 0.5)
    if at_end:
        return complex(segment.point(1.0) - segment.point(1.0 - step))
    return complex(segment.point(step) - segment.point(0.0))


def estimate_endpoint_tangent(segment: Any, at_end: bool, samples_per_curve: int) -> Optional[complex]:
    """
    Estimate a stable tangent direction at a segment endpoint.

    Strategy:
    - `Line`: exact endpoint difference.
    - Bezier curves: endpoint derivative first, then sampled fallback.
    - `Arc`: sampled fallback (robust and simple).
    - Any other segment: derivative when available, then sampled fallback.
    """
    if isinstance(segment, Line):
        return normalize_vector(segment.end - segment.start)

    candidates: list[complex] = []
    derivative_t = 1.0 if at_end else 0.0

    uses_derivative = isinstance(segment, (CubicBezier, QuadraticBezier)) or not isinstance(segment, Arc)
    if uses_derivative:
        try:
            candidates.append(complex(segment.derivative(derivative_t)))
        except Exception:
            pass

    base_step = 1.0 / max(2, samples_per_curve)
    for factor in (1.0, 2.0, 4.0, 8.0):
        try:
            candidates.append(sample_endpoint_vector(segment, at_end=at_end, step=base_step * factor))
        except Exception:
            continue

    for vector in candidates:
        normalized = normalize_vector(vector)
        if normalized is not None:
            return normalized

    return None


def split_subpaths(path: Path) -> list[tuple[int, int]]:
    """
    Split a Path into contiguous segment index ranges.

    A new range starts where previous.end and current.start are disconnected
    (typically after an SVG 'M' move command).
    """
    ranges: list[tuple[int, int]] = []
    segment_count = len(path)
    if segment_count == 0:
        return ranges

    start_index = 0
    for index in range(1, segment_count):
        previous = path[index - 1]
        current = path[index]
        if abs(previous.end - current.start) > CONTINUITY_TOLERANCE:
            ranges.append((start_index, index))
            start_index = index
    ranges.append((start_index, segment_count))
    return ranges


def detect_corners_in_path(
    path: Path,
    path_id: int,
    angle_threshold: float,
    samples_per_curve: int,
    min_segment_length: float,
    debug: bool,
    on_corner: Optional[Callable[[CornerDetection], None]] = None,
) -> list[CornerDetection]:
    """
    Detect sharp corners for one parsed path.

    Corners are joins between adjacent segments where turning angle is above
    `angle_threshold` and both neighboring segments are long enough.
    """
    corners: list[CornerDetection] = []
    if len(path) < 2:
        return corners

    segment_length_cache: dict[int, float] = {}

    def segment_length(index: int) -> float:
        if index not in segment_length_cache:
            segment_length_cache[index] = safe_segment_length(path[index])
        return segment_length_cache[index]

    for start, end in split_subpaths(path):
        segment_count = end - start
        if segment_count < 2:
            continue

        subpath_closed = abs(path[start].start - path[end - 1].end) <= CONTINUITY_TOLERANCE
        node_indices: Iterable[int]
        if subpath_closed:
            node_indices = range(segment_count)
        else:
            node_indices = range(1, segment_count)

        for local_node in node_indices:
            next_index = start + local_node
            prev_index = start + (local_node - 1 if local_node > 0 else segment_count - 1)

            previous_segment = path[prev_index]
            next_segment = path[next_index]

            prev_length = segment_length(prev_index)
            next_length = segment_length(next_index)
            if prev_length < min_segment_length or next_length < min_segment_length:
                debug_log(
                    debug,
                    (
                        f"Skipped path {path_id} node {next_index}: short segment "
                        f"(prev={prev_length:.4f}, next={next_length:.4f})"
                    ),
                )
                continue

            join_point = next_segment.start
            if abs(previous_segment.end - join_point) > CONTINUITY_TOLERANCE:
                debug_log(
                    debug,
                    f"Skipped path {path_id} node {next_index}: disconnected segments.",
                )
                continue

            incoming = estimate_endpoint_tangent(previous_segment, at_end=True, samples_per_curve=samples_per_curve)
            outgoing = estimate_endpoint_tangent(next_segment, at_end=False, samples_per_curve=samples_per_curve)
            if incoming is None or outgoing is None:
                debug_log(
                    debug,
                    f"Skipped path {path_id} node {next_index}: unstable tangent estimate.",
                )
                continue

            dot_value = clamp((incoming.real * outgoing.real) + (incoming.imag * outgoing.imag), -1.0, 1.0)
            angle_deg = math.degrees(math.acos(dot_value))

            if angle_deg > angle_threshold:
                corner = CornerDetection(
                    path_id=path_id,
                    node_id=next_index,
                    x=float(join_point.real),
                    y=float(join_point.imag),
                    angle_deg=float(angle_deg),
                    incoming_dx=float(incoming.real),
                    incoming_dy=float(incoming.imag),
                    outgoing_dx=float(outgoing.real),
                    outgoing_dy=float(outgoing.imag),
                    prev_segment_length=float(prev_length),
                    next_segment_length=float(next_length),
                )
                corners.append(corner)
                if on_corner is not None:
                    on_corner(corner)
                debug_log(
                    debug,
                    f"Detected corner path={path_id} node={next_index} angle={angle_deg:.2f}",
                )

    return corners


def print_corner_table(corners: list[CornerDetection]) -> None:
    """Print detected corners as a terminal table."""
    headers = ["path_id", "node_id", "x", "y", "angle_deg"]
    rows = [
        [
            str(corner.path_id),
            str(corner.node_id),
            f"{corner.x:.4f}",
            f"{corner.y:.4f}",
            f"{corner.angle_deg:.2f}",
        ]
        for corner in corners
    ]

    column_widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            column_widths[index] = max(column_widths[index], len(value))

    header_line = "  ".join(header.ljust(column_widths[index]) for index, header in enumerate(headers))
    divider_line = "  ".join("-" * column_widths[index] for index in range(len(headers)))
    print(header_line)
    print(divider_line)

    if not rows:
        print("(no corners detected)")
        return

    for row in rows:
        print("  ".join(value.ljust(column_widths[index]) for index, value in enumerate(row)))


def append_corner_markers(
    root: ET.Element,
    namespace: str,
    corners: list[CornerDetection],
    marker_radius: float,
    corner_radius: float,
    radius_profile: str,
    debug: bool,
) -> None:
    """Append marker circles (and optional labels) to SVG root."""
    overlay_group = ET.Element(svg_tag(namespace, "g"), {"id": "detected-corners-overlay"})
    root.append(overlay_group)

    font_size = max(8.0, marker_radius * 3.0)
    x_offset = marker_radius * 1.4
    y_offset = marker_radius * 1.4

    for corner in corners:
        used_arc_radius: Optional[float] = None
        if corner_radius > 0.0:
            target_radius = effective_corner_radius(corner, corner_radius, radius_profile=radius_profile)
            arc_geometry = compute_corner_arc_geometry(corner, desired_radius=target_radius)
            if arc_geometry is not None:
                arc_start, arc_end, arc_center, used_radius = arc_geometry
                arc_path_d = build_svg_arc_path_d(
                    start=arc_start,
                    end=arc_end,
                    center=arc_center,
                    radius=used_radius,
                )
                if arc_path_d is not None:
                    arc_attributes = {
                        "d": arc_path_d,
                        "fill": "none",
                        "stroke": "red",
                        "stroke-width": "2",
                        "stroke-linecap": "round",
                    }
                    overlay_group.append(ET.Element(svg_tag(namespace, "path"), arc_attributes))
                    used_arc_radius = used_radius
                else:
                    used_arc_radius = None

        if used_arc_radius is None:
            cx_s = f"{corner.x:.4f}"
            cy_s = f"{corner.y:.4f}"
            r_dot = marker_radius * 0.55
            r_ring_start = marker_radius
            r_ring_end = marker_radius * 3.2
            sw = max(1.0, marker_radius * 0.28)
            dur = "1.6s"

            # Solid inner dot
            dot = ET.Element(svg_tag(namespace, "circle"), {
                "cx": cx_s, "cy": cy_s,
                "r": f"{r_dot:.3f}",
                "fill": "red",
            })
            overlay_group.append(dot)

            # Animated expanding ring (sonar ping)
            ring = ET.Element(svg_tag(namespace, "circle"), {
                "cx": cx_s, "cy": cy_s,
                "r": f"{r_ring_start:.3f}",
                "fill": "none",
                "stroke": "red",
                "stroke-width": f"{sw:.3f}",
            })
            ring.append(ET.Element(svg_tag(namespace, "animate"), {
                "attributeName": "r",
                "from": f"{r_ring_start:.3f}",
                "to": f"{r_ring_end:.3f}",
                "dur": dur, "repeatCount": "indefinite",
            }))
            ring.append(ET.Element(svg_tag(namespace, "animate"), {
                "attributeName": "opacity",
                "from": "0.85", "to": "0",
                "dur": dur, "repeatCount": "indefinite",
            }))
            overlay_group.append(ring)

        if debug:
            text_attributes = {
                "x": f"{corner.x + x_offset:.6f}",
                "y": f"{corner.y - y_offset:.6f}",
                "fill": "red",
                "font-size": f"{font_size:.2f}",
            }
            text_element = ET.Element(svg_tag(namespace, "text"), text_attributes)
            if used_arc_radius is not None:
                text_element.text = f"{corner.angle_deg:.1f} deg r={used_arc_radius:.1f}"
            else:
                text_element.text = f"{corner.angle_deg:.1f} deg"
            overlay_group.append(text_element)


def append_arc_preview_circles(
    root: ET.Element,
    namespace: str,
    corners: list[CornerDetection],
    corner_radius: float,
    radius_profile: str,
    per_corner_radii: Optional[dict[str, float]],
    debug: bool,
) -> list[dict]:
    """
    Draw simple full-circle previews for arc-preview mode.

    For each corner this overlays:
      - A clean circle outline centered on the fillet center point
    Returns a list of dicts with arc-circle metadata for the UI table.
    """
    overlay_group = ET.Element(svg_tag(namespace, "g"), {"id": "arc-preview-overlay"})
    root.append(overlay_group)

    arc_circles: list[dict] = []

    for corner in corners:
        key = f"{corner.path_id}:{corner.node_id}"
        if per_corner_radii is not None and key in per_corner_radii:
            desired = per_corner_radii[key]
            effective = desired   # override is the final circle size, no profile scaling
        else:
            desired = corner_radius
            effective = effective_corner_radius(corner, desired, radius_profile=radius_profile)

        arc_geometry = compute_corner_arc_geometry(corner, desired_radius=effective)
        if arc_geometry is None:
            debug_log(debug, f"Path {corner.path_id} node {corner.node_id}: arc geometry unavailable for preview.")
            continue

        _arc_start, _arc_end, arc_center, used_radius = arc_geometry
        cx = arc_center.real
        cy = arc_center.imag

        # Minimal arc preview: circle only (no tangent dots / arc path clutter).
        overlay_group.append(ET.Element(svg_tag(namespace, "circle"), {
            "cx": f"{cx:.4f}",
            "cy": f"{cy:.4f}",
            "r": f"{used_radius:.4f}",
            "fill": "none",
            "stroke": "#e53e3e",
            "stroke-width": "2",
            "opacity": "0.95",
            "vector-effect": "non-scaling-stroke",
        }))

        arc_circles.append({
            "path_id": corner.path_id,
            "node_id": corner.node_id,
            "center_x": round(cx, 4),
            "center_y": round(cy, 4),
            "used_radius": round(used_radius, 4),
            "desired_radius": round(effective, 4),
        })

    return arc_circles


def list_path_elements(root: ET.Element, namespace: str) -> list[ET.Element]:
    """Find all SVG <path> elements."""
    query = f".//{{{namespace}}}path" if namespace else ".//path"
    return list(root.findall(query))


def parse_svg_paths(root: ET.Element, namespace: str, debug: bool) -> list[tuple[int, Path]]:
    """Extract and parse all <path> elements into svgpathtools Path objects."""
    path_elements = list_path_elements(root, namespace=namespace)
    parsed: list[tuple[int, Path]] = []

    for path_id, path_element in enumerate(path_elements):
        path_data = path_element.get("d")
        if not path_data:
            debug_log(debug, f"Skipped path {path_id}: missing 'd' attribute.")
            continue

        try:
            parsed_path = parse_path(path_data)
        except Exception as exc:
            debug_log(debug, f"Skipped path {path_id}: parse error ({exc}).")
            continue

        if len(parsed_path) == 0:
            debug_log(debug, f"Skipped path {path_id}: no drawable segments.")
            continue

        parsed.append((path_id, parsed_path))

    return parsed


def apply_rounding_to_svg_paths(
    root: ET.Element,
    namespace: str,
    parsed_paths: list[tuple[int, Path]],
    corners: list[CornerDetection],
    corner_radius: float,
    radius_profile: str,
    samples_per_curve: int,
    debug: bool,
    per_corner_radii: Optional[dict[str, float]] = None,
) -> int:
    """Apply rounded-corner geometry back into SVG path `d` attributes."""
    path_elements = list_path_elements(root, namespace=namespace)
    corners_by_path: dict[int, list[CornerDetection]] = {}
    for corner in corners:
        corners_by_path.setdefault(corner.path_id, []).append(corner)

    updated_count = 0
    for path_id, parsed_path in parsed_paths:
        path_corners = corners_by_path.get(path_id, [])
        if not path_corners:
            continue
        if path_id < 0 or path_id >= len(path_elements):
            continue

        rounded_path = round_path_geometry(
            path=parsed_path,
            path_id=path_id,
            corners=path_corners,
            desired_radius=corner_radius,
            radius_profile=radius_profile,
            samples_per_curve=samples_per_curve,
            debug=debug,
            per_corner_radii=per_corner_radii,
        )
        path_elements[path_id].set("d", rounded_path.d())
        updated_count += 1

    return updated_count


def validate_args(args: argparse.Namespace) -> None:
    """Validate CLI arguments and raise ValueError when invalid."""
    if args.angle_threshold < 0.0 or args.angle_threshold > 180.0:
        raise ValueError("--angle-threshold must be between 0 and 180 degrees.")
    if args.samples_per_curve < 2:
        raise ValueError("--samples-per-curve must be at least 2.")
    if args.marker_radius <= 0.0:
        raise ValueError("--marker-radius must be greater than 0.")
    if args.corner_radius < 0.0:
        raise ValueError("--corner-radius must be non-negative.")
    if args.min_segment_length < 0.0:
        raise ValueError("--min-segment-length must be non-negative.")
    if args.apply_rounding and args.corner_radius <= 0.0:
        raise ValueError("--apply-rounding requires --corner-radius greater than 0.")


def print_realtime_header() -> None:
    """Print header for realtime corner stream output."""
    print("realtime corner stream:", flush=True)
    print("path_id\tnode_id\tx\ty\tangle_deg", flush=True)


def print_realtime_corner(corner: CornerDetection) -> None:
    """Print one detected corner immediately."""
    print(
        f"{corner.path_id}\t{corner.node_id}\t{corner.x:.4f}\t{corner.y:.4f}\t{corner.angle_deg:.2f}",
        flush=True,
    )


def compute_plot_bounds(parsed_paths: list[tuple[int, Path]]) -> PlotBounds:
    """Compute global bounds for displaying corner points in the live window."""
    min_x = math.inf
    max_x = -math.inf
    min_y = math.inf
    max_y = -math.inf

    for _, parsed_path in parsed_paths:
        try:
            path_min_x, path_max_x, path_min_y, path_max_y = parsed_path.bbox()
        except Exception:
            continue

        values = (path_min_x, path_max_x, path_min_y, path_max_y)
        if any(math.isinf(value) or math.isnan(value) for value in values):
            continue

        min_x = min(min_x, path_min_x)
        max_x = max(max_x, path_max_x)
        min_y = min(min_y, path_min_y)
        max_y = max(max_y, path_max_y)

    if math.isinf(min_x) or math.isinf(max_x) or math.isinf(min_y) or math.isinf(max_y):
        return PlotBounds(min_x=0.0, max_x=100.0, min_y=0.0, max_y=100.0)

    if abs(max_x - min_x) <= EPSILON:
        min_x -= 1.0
        max_x += 1.0
    if abs(max_y - min_y) <= EPSILON:
        min_y -= 1.0
        max_y += 1.0

    return PlotBounds(min_x=min_x, max_x=max_x, min_y=min_y, max_y=max_y)


def sample_segment_points_for_display(segment: Any, samples_per_curve: int) -> list[complex]:
    """
    Sample points along a segment for 2D canvas drawing.

    Lines are drawn exactly using endpoints; curves/arcs are approximated by
    a polyline with `samples_per_curve` subdivisions.
    """
    if isinstance(segment, Line):
        return [complex(segment.start), complex(segment.end)]

    sample_count = max(8, samples_per_curve)
    points: list[complex] = []
    for index in range(sample_count + 1):
        t_value = index / sample_count
        try:
            points.append(complex(segment.point(t_value)))
        except Exception:
            continue

    if len(points) < 2:
        return [complex(segment.start), complex(segment.end)]
    return points


def compute_corner_arc_geometry(
    corner: CornerDetection,
    desired_radius: float,
) -> Optional[tuple[complex, complex, complex, float]]:
    """
    Build a fillet-arc geometry for a detected corner.

    Returns (arc_start, arc_end, arc_center, used_radius) or None when arc
    construction is unstable or impossible for the given radius.
    """
    if desired_radius <= 0.0:
        return None

    incoming = normalize_vector(complex(corner.incoming_dx, corner.incoming_dy))
    outgoing = normalize_vector(complex(corner.outgoing_dx, corner.outgoing_dy))
    if incoming is None or outgoing is None:
        return None

    # Corner rays from the node: backward along previous segment, forward along next segment.
    ray_prev = -incoming
    ray_next = outgoing
    dot_value = clamp((ray_prev.real * ray_next.real) + (ray_prev.imag * ray_next.imag), -1.0, 1.0)
    corner_theta = math.acos(dot_value)

    min_theta = math.radians(5.0)
    max_theta = math.radians(175.0)
    if corner_theta <= min_theta or corner_theta >= max_theta:
        return None

    tan_half = math.tan(corner_theta / 2.0)
    sin_half = math.sin(corner_theta / 2.0)
    if abs(tan_half) <= EPSILON or abs(sin_half) <= EPSILON:
        return None

    max_radius = min(corner.prev_segment_length, corner.next_segment_length) * tan_half * 0.98
    if max_radius <= EPSILON:
        return None

    used_radius = min(desired_radius, max_radius)
    if used_radius <= EPSILON:
        return None

    tangent_distance = used_radius / tan_half
    center_distance = used_radius / sin_half
    bisector = normalize_vector(ray_prev + ray_next)
    if bisector is None:
        return None

    node = complex(corner.x, corner.y)
    arc_start = node + (ray_prev * tangent_distance)
    arc_end = node + (ray_next * tangent_distance)
    arc_center = node + (bisector * center_distance)
    return arc_start, arc_end, arc_center, used_radius


def sample_short_arc_points(
    center: complex,
    start: complex,
    end: complex,
    radius: float,
    max_angle_step_deg: float = 10.0,
) -> list[complex]:
    """Sample the shorter circular arc from start to end around center."""
    if radius <= EPSILON:
        return [start, end]

    start_angle = math.atan2((start - center).imag, (start - center).real)
    end_angle = math.atan2((end - center).imag, (end - center).real)

    delta = end_angle - start_angle
    while delta <= -math.pi:
        delta += 2.0 * math.pi
    while delta > math.pi:
        delta -= 2.0 * math.pi

    step_count = max(2, int(abs(math.degrees(delta)) / max_angle_step_deg) + 1)
    points: list[complex] = []
    for index in range(step_count + 1):
        t_value = index / step_count
        angle = start_angle + (delta * t_value)
        points.append(center + (radius * complex(math.cos(angle), math.sin(angle))))
    return points


def complex_cross(a: complex, b: complex) -> float:
    """2D cross product of complex vectors."""
    return (a.real * b.imag) - (a.imag * b.real)


def left_normal(direction: complex) -> complex:
    """Left-hand unit normal for a direction vector."""
    return complex(-direction.imag, direction.real)


def right_normal(direction: complex) -> complex:
    """Right-hand unit normal for a direction vector."""
    return complex(direction.imag, -direction.real)


def intersect_lines(point_a: complex, dir_a: complex, point_b: complex, dir_b: complex) -> Optional[complex]:
    """Intersect infinite lines point_a+t*dir_a and point_b+u*dir_b."""
    denominator = complex_cross(dir_a, dir_b)
    if abs(denominator) <= EPSILON:
        return None
    t_value = complex_cross(point_b - point_a, dir_b) / denominator
    return point_a + (dir_a * t_value)


def segment_length_between(segment: Any, t_start: float, t_end: float) -> float:
    """Length of a segment interval [t_start, t_end], with numeric fallback."""
    t_start = clamp(t_start, 0.0, 1.0)
    t_end = clamp(t_end, 0.0, 1.0)
    if t_end < t_start:
        t_start, t_end = t_end, t_start
    if abs(t_end - t_start) <= EPSILON:
        return 0.0

    try:
        return float(segment.length(t_start, t_end, error=1e-6))
    except TypeError:
        try:
            return float(segment.length(t_start, t_end))
        except Exception:
            pass
    except Exception:
        pass

    samples = 50
    total = 0.0
    prev = complex(segment.point(t_start))
    for index in range(1, samples + 1):
        t_value = t_start + ((t_end - t_start) * (index / samples))
        current = complex(segment.point(t_value))
        total += abs(current - prev)
        prev = current
    return float(total)


def find_t_at_length_from_start(segment: Any, target_length: float) -> float:
    """Parameter t where arc length from start equals target_length."""
    total_length = safe_segment_length(segment)
    if total_length <= EPSILON:
        return 0.0
    if target_length <= 0.0:
        return 0.0
    if target_length >= total_length:
        return 1.0

    low = 0.0
    high = 1.0
    for _ in range(42):
        mid = 0.5 * (low + high)
        current_length = segment_length_between(segment, 0.0, mid)
        if current_length < target_length:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def estimate_tangent_at_t(segment: Any, t_value: float, samples_per_curve: int) -> Optional[complex]:
    """Estimate stable tangent direction at arbitrary segment parameter t."""
    t_value = clamp(t_value, 0.0, 1.0)

    try:
        derivative = complex(segment.derivative(t_value))
        normalized = normalize_vector(derivative)
        if normalized is not None:
            return normalized
    except Exception:
        pass

    dt = 1.0 / max(12, samples_per_curve * 4)
    t0 = clamp(t_value - dt, 0.0, 1.0)
    t1 = clamp(t_value + dt, 0.0, 1.0)
    if abs(t1 - t0) <= EPSILON:
        return None
    try:
        return normalize_vector(complex(segment.point(t1) - segment.point(t0)))
    except Exception:
        return None


def choose_svg_arc_sweep_flag(
    start: complex,
    end: complex,
    radius: float,
    target_center: complex,
    start_tangent: Optional[complex] = None,
    end_tangent: Optional[complex] = None,
) -> Optional[int]:
    """
    Choose SVG arc sweep flag (0/1) whose computed center best matches target_center.
    """
    best_sweep: Optional[int] = None
    best_error = math.inf

    for sweep in (0, 1):
        try:
            arc_segment = Arc(
                start=start,
                radius=complex(radius, radius),
                rotation=0.0,
                large_arc=False,
                sweep=bool(sweep),
                end=end,
            )
        except Exception:
            continue

        center_error = abs(complex(arc_segment.center) - target_center)
        tangent_penalty = 0.0

        if start_tangent is not None:
            arc_start_tangent = normalize_vector(complex(arc_segment.derivative(0.0)))
            if arc_start_tangent is not None:
                dot_start = clamp(
                    (arc_start_tangent.real * start_tangent.real) + (arc_start_tangent.imag * start_tangent.imag),
                    -1.0,
                    1.0,
                )
                tangent_penalty += (1.0 - dot_start) * 50.0

        if end_tangent is not None:
            arc_end_tangent = normalize_vector(complex(arc_segment.derivative(1.0)))
            if arc_end_tangent is not None:
                dot_end = clamp(
                    (arc_end_tangent.real * end_tangent.real) + (arc_end_tangent.imag * end_tangent.imag),
                    -1.0,
                    1.0,
                )
                tangent_penalty += (1.0 - dot_end) * 50.0

        score = center_error + tangent_penalty
        if score < best_error:
            best_error = score
            best_sweep = sweep

    return best_sweep


def build_svg_arc_path_d(
    start: complex,
    end: complex,
    center: complex,
    radius: float,
) -> Optional[str]:
    """Build a smooth SVG path command for a circular arc marker."""
    if radius <= EPSILON:
        return None

    sweep_flag = choose_svg_arc_sweep_flag(start=start, end=end, radius=radius, target_center=center)
    if sweep_flag is None:
        return None

    return (
        f"M {start.real:.6f} {start.imag:.6f} "
        f"A {radius:.6f} {radius:.6f} 0 0 {sweep_flag} {end.real:.6f} {end.imag:.6f}"
    )


def sample_svg_arc_points_for_display(
    start: complex,
    end: complex,
    center: complex,
    radius: float,
    max_angle_step_deg: float = 4.0,
) -> list[complex]:
    """Sample points from a true SVG circular arc for smooth live display."""
    if radius <= EPSILON:
        return [start, end]

    sweep_flag = choose_svg_arc_sweep_flag(start=start, end=end, radius=radius, target_center=center)
    if sweep_flag is None:
        return sample_short_arc_points(center=center, start=start, end=end, radius=radius, max_angle_step_deg=4.0)

    try:
        arc_segment = Arc(
            start=start,
            radius=complex(radius, radius),
            rotation=0.0,
            large_arc=False,
            sweep=bool(sweep_flag),
            end=end,
        )
    except Exception:
        return sample_short_arc_points(center=center, start=start, end=end, radius=radius, max_angle_step_deg=4.0)

    start_angle = math.atan2((start - center).imag, (start - center).real)
    end_angle = math.atan2((end - center).imag, (end - center).real)
    delta = end_angle - start_angle
    while delta <= -math.pi:
        delta += 2.0 * math.pi
    while delta > math.pi:
        delta -= 2.0 * math.pi

    step_count = max(12, int(abs(math.degrees(delta)) / max_angle_step_deg) + 1)
    points: list[complex] = []
    for index in range(step_count + 1):
        t_value = index / step_count
        points.append(complex(arc_segment.point(t_value)))
    return points


def crop_segment(segment: Any, t_start: float, t_end: float) -> Optional[Any]:
    """Crop a segment safely; fallback to a line if native crop fails."""
    t_start = clamp(t_start, 0.0, 1.0)
    t_end = clamp(t_end, 0.0, 1.0)
    if t_end - t_start <= 1e-6:
        return None

    try:
        return segment.cropped(t_start, t_end)
    except Exception:
        try:
            start_point = complex(segment.point(t_start))
            end_point = complex(segment.point(t_end))
        except Exception:
            return None
        if abs(end_point - start_point) <= EPSILON:
            return None
        return Line(start_point, end_point)


_ARC_START_SNAP_TOLERANCE = 1e-9
_COLLINEAR_COS_THRESHOLD = math.cos(math.radians(0.5))


def _arc_with_snapped_start(arc: Arc, new_start: complex) -> Arc:
    """Return copy of arc with start snapped to new_start to fix de Casteljau float error."""
    return Arc(
        start=new_start,
        radius=arc.radius,
        rotation=arc.rotation,
        large_arc=arc.large_arc,
        sweep=arc.sweep,
        end=arc.end,
    )


def _merge_collinear_lines(segments: list[Any]) -> list[Any]:
    """Merge consecutive collinear Line segments and drop zero-length ones."""
    if len(segments) <= 1:
        return segments

    merged: list[Any] = []
    for seg in segments:
        if abs(seg.end - seg.start) <= EPSILON:
            continue  # drop zero-length
        if merged and isinstance(merged[-1], Line) and isinstance(seg, Line):
            dir_prev = normalize_vector(merged[-1].end - merged[-1].start)
            dir_curr = normalize_vector(seg.end - seg.start)
            if dir_prev is not None and dir_curr is not None:
                dot = (dir_prev.real * dir_curr.real) + (dir_prev.imag * dir_curr.imag)
                if dot >= _COLLINEAR_COS_THRESHOLD:
                    merged[-1] = Line(merged[-1].start, seg.end)
                    continue
        merged.append(seg)

    return merged if merged else segments


def build_corner_rounding(
    path: Path,
    corner: CornerDetection,
    prev_index: int,
    next_index: int,
    desired_radius: float,
    radius_profile: str,
    samples_per_curve: int,
) -> Optional[CornerRounding]:
    """Construct trimming + arc geometry for one detected corner."""
    target_radius = effective_corner_radius(corner, desired_radius, radius_profile=radius_profile)
    previous_segment = path[prev_index]
    next_segment = path[next_index]

    rough_geometry = compute_corner_arc_geometry(corner, desired_radius=target_radius)
    prev_is_curve = isinstance(previous_segment, (CubicBezier, QuadraticBezier, Arc))
    next_is_curve = isinstance(next_segment, (CubicBezier, QuadraticBezier, Arc))
    if rough_geometry is None or prev_is_curve or next_is_curve:
        try:
            from .curve_solver import solve_curve_fillet

            curve_result = solve_curve_fillet(
                prev_segment=previous_segment,
                next_segment=next_segment,
                desired_radius=target_radius,
                corner_point=complex(corner.x, corner.y),
            )
        except Exception:
            curve_result = None

        if curve_result is not None and curve_result.quality_score >= 0.5:
            try:
                arc_segment = Arc(
                    start=curve_result.arc_start,
                    radius=complex(curve_result.arc_radius, curve_result.arc_radius),
                    rotation=0.0,
                    large_arc=False,
                    sweep=bool(curve_result.sweep_flag),
                    end=curve_result.arc_end,
                )
                return CornerRounding(
                    node_id=corner.node_id,
                    prev_index=prev_index,
                    next_index=next_index,
                    prev_trim_t=curve_result.prev_trim_t,
                    next_trim_t=curve_result.next_trim_t,
                    arc_segment=arc_segment,
                    used_radius=curve_result.arc_radius,
                )
            except Exception:
                pass

    if rough_geometry is None:
        return None

    rough_arc_start, _rough_arc_end, rough_center, rough_radius = rough_geometry
    node_point = complex(corner.x, corner.y)
    trim_distance = abs(node_point - rough_arc_start)
    if trim_distance <= EPSILON:
        return None

    prev_total_length = safe_segment_length(previous_segment)
    next_total_length = safe_segment_length(next_segment)
    if prev_total_length <= EPSILON or next_total_length <= EPSILON:
        return None

    trim_distance = min(trim_distance, prev_total_length * 0.95, next_total_length * 0.95)
    if trim_distance <= EPSILON:
        return None

    prev_trim_t = find_t_at_length_from_start(previous_segment, prev_total_length - trim_distance)
    next_trim_t = find_t_at_length_from_start(next_segment, trim_distance)
    prev_trim_point = complex(previous_segment.point(prev_trim_t))
    next_trim_point = complex(next_segment.point(next_trim_t))

    prev_tangent = estimate_tangent_at_t(previous_segment, prev_trim_t, samples_per_curve=samples_per_curve)
    next_tangent = estimate_tangent_at_t(next_segment, next_trim_t, samples_per_curve=samples_per_curve)
    if prev_tangent is None or next_tangent is None:
        return None

    best_center: Optional[complex] = None
    best_radius = 0.0
    best_score = math.inf
    for prev_normal in (left_normal(prev_tangent), right_normal(prev_tangent)):
        for next_normal in (left_normal(next_tangent), right_normal(next_tangent)):
            center = intersect_lines(prev_trim_point, prev_normal, next_trim_point, next_normal)
            if center is None:
                continue

            radius_prev = abs(center - prev_trim_point)
            radius_next = abs(center - next_trim_point)
            if radius_prev <= EPSILON or radius_next <= EPSILON:
                continue

            radius = 0.5 * (radius_prev + radius_next)
            mismatch = abs(radius_prev - radius_next)
            score = (mismatch * 25.0) + abs(center - rough_center) + (abs(radius - rough_radius) * 0.5)
            if score < best_score:
                best_score = score
                best_center = center
                best_radius = radius

    if best_center is None or best_radius <= EPSILON:
        return None

    sweep_flag = choose_svg_arc_sweep_flag(
        start=prev_trim_point,
        end=next_trim_point,
        radius=best_radius,
        target_center=best_center,
        start_tangent=prev_tangent,
        end_tangent=next_tangent,
    )
    if sweep_flag is None:
        return None

    try:
        arc_segment = Arc(
            start=prev_trim_point,
            radius=complex(best_radius, best_radius),
            rotation=0.0,
            large_arc=False,
            sweep=bool(sweep_flag),
            end=next_trim_point,
        )
    except Exception:
        return None

    return CornerRounding(
        node_id=corner.node_id,
        prev_index=prev_index,
        next_index=next_index,
        prev_trim_t=prev_trim_t,
        next_trim_t=next_trim_t,
        arc_segment=arc_segment,
        used_radius=best_radius,
    )


def round_path_geometry(
    path: Path,
    path_id: int,
    corners: list[CornerDetection],
    desired_radius: float,
    radius_profile: str,
    samples_per_curve: int,
    debug: bool,
    per_corner_radii: Optional[dict[str, float]] = None,
) -> Path:
    """Return a new Path with selected sharp corners replaced by fillet arcs."""
    if desired_radius <= 0.0 and not per_corner_radii or not corners:
        return path

    corner_by_node = {corner.node_id: corner for corner in corners}
    rounded_segments: list[Any] = []

    for start, end in split_subpaths(path):
        segment_count = end - start
        if segment_count <= 0:
            continue

        subpath_closed = abs(path[start].start - path[end - 1].end) <= CONTINUITY_TOLERANCE
        candidate_nodes: Iterable[int]
        if subpath_closed:
            candidate_nodes = range(segment_count)
        else:
            candidate_nodes = range(1, segment_count)

        rounding_by_node: dict[int, CornerRounding] = {}
        for local_node in candidate_nodes:
            node_index = start + local_node
            corner = corner_by_node.get(node_index)
            if corner is None:
                continue

            # Per-corner override bypasses the radius profile (user set it directly).
            key = f"{path_id}:{corner.node_id}"
            if per_corner_radii is not None and key in per_corner_radii:
                node_radius = per_corner_radii[key]
                node_profile = "fixed"
            else:
                node_radius = desired_radius
                node_profile = radius_profile

            prev_index = start + (local_node - 1 if local_node > 0 else segment_count - 1)
            next_index = node_index
            rounding = build_corner_rounding(
                path=path,
                corner=corner,
                prev_index=prev_index,
                next_index=next_index,
                desired_radius=node_radius,
                radius_profile=node_profile,
                samples_per_curve=samples_per_curve,
            )
            if rounding is None:
                debug_log(debug, f"Path {path_id} node {node_index}: could not build fillet geometry.")
                continue
            rounding_by_node[node_index] = rounding

        # Prevent neighboring corners from over-trimming the same segment.
        # When t_start >= t_end on a segment, that segment collapses and may break
        # path continuity (causing large fill artifacts on closed shapes).
        if len(rounding_by_node) > 1:
            changed = True
            conflict_tolerance = 1e-6
            while changed:
                changed = False
                for local_segment in range(segment_count):
                    segment_index = start + local_segment
                    if subpath_closed:
                        end_node_index = start + ((local_segment + 1) % segment_count)
                    else:
                        end_node_index = start + local_segment + 1
                        if end_node_index >= end:
                            continue

                    start_rounding = rounding_by_node.get(segment_index)
                    end_rounding = rounding_by_node.get(end_node_index)
                    if start_rounding is None or end_rounding is None:
                        continue

                    t_start = clamp(start_rounding.next_trim_t, 0.0, 1.0)
                    t_end = clamp(end_rounding.prev_trim_t, 0.0, 1.0)
                    if t_start + conflict_tolerance < t_end:
                        continue

                    # Drop whichever corner trims more of this shared segment.
                    start_trim = max(0.0, t_start)
                    end_trim = max(0.0, 1.0 - t_end)
                    if start_trim >= end_trim:
                        removed_node = segment_index
                    else:
                        removed_node = end_node_index

                    removed_rounding = rounding_by_node.pop(removed_node, None)
                    if removed_rounding is None:
                        continue
                    retry_applied = False
                    retry_corner = corner_by_node.get(removed_node)
                    retry_radius = removed_rounding.used_radius * 0.5
                    if retry_corner is not None and retry_radius >= 0.5:
                        retry_rounding = build_corner_rounding(
                            path=path,
                            corner=retry_corner,
                            prev_index=removed_rounding.prev_index,
                            next_index=removed_rounding.next_index,
                            desired_radius=retry_radius,
                            radius_profile="fixed",
                            samples_per_curve=samples_per_curve,
                        )
                        if retry_rounding is not None:
                            rounding_by_node[removed_node] = retry_rounding
                            retry_applied = True

                    changed = True
                    if debug:
                        if retry_applied:
                            debug_log(
                                debug,
                                (
                                    f"Path {path_id} node {removed_node}: overlap retry with smaller fillet "
                                    f"(segment={segment_index}, t_start={t_start:.4f}, t_end={t_end:.4f}, "
                                    f"radius={retry_radius:.4f})."
                                ),
                            )
                        else:
                            debug_log(
                                debug,
                                (
                                    f"Path {path_id} node {removed_node}: dropped overlapping fillet "
                                    f"(segment={segment_index}, t_start={t_start:.4f}, t_end={t_end:.4f})."
                                ),
                            )
                    break

        subpath_segments: list[Any] = []
        for local_segment in range(segment_count):
            segment_index = start + local_segment
            segment = path[segment_index]

            start_rounding = rounding_by_node.get(segment_index)
            t_start = start_rounding.next_trim_t if start_rounding is not None else 0.0

            if subpath_closed:
                end_node_index = start + ((local_segment + 1) % segment_count)
            else:
                end_node_index = start + local_segment + 1
            end_rounding = rounding_by_node.get(end_node_index)
            t_end = end_rounding.prev_trim_t if end_rounding is not None else 1.0

            cropped_segment = crop_segment(segment, t_start, t_end)
            if cropped_segment is not None:
                subpath_segments.append(cropped_segment)
            elif debug:
                debug_log(
                    debug,
                    (
                        f"Path {path_id} segment {segment_index}: collapsed after trimming "
                        f"(t_start={t_start:.4f}, t_end={t_end:.4f})."
                    ),
                )

            if subpath_closed:
                corner_after = rounding_by_node.get(end_node_index)
                if corner_after is not None and corner_after.prev_index == segment_index:
                    arc = corner_after.arc_segment
                    if subpath_segments:
                        prev_end = subpath_segments[-1].end
                        if arc.start != prev_end and abs(arc.start - prev_end) < _ARC_START_SNAP_TOLERANCE:
                            arc = _arc_with_snapped_start(arc, prev_end)
                    subpath_segments.append(arc)
            else:
                if end_node_index < end:
                    corner_after = rounding_by_node.get(end_node_index)
                    if corner_after is not None and corner_after.prev_index == segment_index:
                        arc = corner_after.arc_segment
                        if subpath_segments:
                            prev_end = subpath_segments[-1].end
                            if arc.start != prev_end and abs(arc.start - prev_end) < _ARC_START_SNAP_TOLERANCE:
                                arc = _arc_with_snapped_start(arc, prev_end)
                        subpath_segments.append(arc)

        rounded_segments.extend(_merge_collinear_lines(subpath_segments))

    if not rounded_segments:
        return path
    return Path(*rounded_segments)


class LiveCornerWindow:
    """Tkinter window that displays detected corners in real time."""

    def __init__(self, bounds: PlotBounds, corner_radius: float, radius_profile: str) -> None:
        try:
            import tkinter as tk
            from tkinter import ttk
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(f"Failed to initialize Tkinter window: {exc}") from exc

        self._tk = tk
        self._ttk = ttk
        self._closed = False

        self.root = tk.Tk()
        self.root.title("SVG Corner Detection - Live")
        self.root.geometry("980x760")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.bounds = bounds
        self.canvas_width = 700
        self.canvas_height = 620
        self.canvas_margin = 24.0
        self.point_radius = 3.0
        self.corner_radius = max(0.0, corner_radius)
        self.radius_profile = radius_profile
        self._detected_count = 0
        self._scale = 1.0
        self._offset_x = self.canvas_margin
        self._offset_y = self.canvas_margin

        container = ttk.Frame(self.root, padding=10)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=3)
        container.columnconfigure(1, weight=2)
        container.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            container,
            width=self.canvas_width,
            height=self.canvas_height,
            bg="white",
            highlightthickness=1,
            highlightbackground="#cccccc",
        )
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        side_panel = ttk.Frame(container)
        side_panel.grid(row=0, column=1, sticky="nsew")
        side_panel.rowconfigure(1, weight=1)

        title = ttk.Label(side_panel, text="Detected Corners", font=("Segoe UI", 12, "bold"))
        title.grid(row=0, column=0, sticky="w")

        columns = ("path_id", "node_id", "x", "y", "angle_deg", "arc_r")
        self.tree = ttk.Treeview(side_panel, columns=columns, show="headings", height=24)
        for column, width in zip(columns, (64, 64, 88, 88, 88, 72)):
            self.tree.heading(column, text=column)
            self.tree.column(column, anchor="center", width=width, minwidth=60)
        self.tree.grid(row=1, column=0, sticky="nsew", pady=(8, 8))

        y_scroll = ttk.Scrollbar(side_panel, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_scroll.set)
        y_scroll.grid(row=1, column=1, sticky="ns", pady=(8, 8))

        self.status_var = tk.StringVar(value="Scanning paths...")
        self.status_label = ttk.Label(side_panel, textvariable=self.status_var)
        self.status_label.grid(row=2, column=0, sticky="w")

        self._setup_view_transform()
        self._draw_canvas_frame()
        self.refresh()

    def _on_close(self) -> None:
        self._closed = True
        try:
            self.root.destroy()
        except Exception:
            pass

    def _draw_canvas_frame(self) -> None:
        data_width = self.bounds.max_x - self.bounds.min_x
        data_height = self.bounds.max_y - self.bounds.min_y
        frame_left = self._offset_x
        frame_top = self._offset_y
        frame_right = frame_left + (data_width * self._scale)
        frame_bottom = frame_top + (data_height * self._scale)
        self.canvas.create_rectangle(
            frame_left,
            frame_top,
            frame_right,
            frame_bottom,
            outline="#dddddd",
            width=1,
        )
        self.canvas.create_text(
            frame_left + 4,
            frame_top - 10,
            text=(
                f"x:[{self.bounds.min_x:.2f}, {self.bounds.max_x:.2f}]  "
                f"y:[{self.bounds.min_y:.2f}, {self.bounds.max_y:.2f}]"
            ),
            anchor="w",
            fill="#666666",
            font=("Segoe UI", 9),
        )

    def _setup_view_transform(self) -> None:
        """Compute scale and offset to fit the SVG bounds while preserving aspect ratio."""
        usable_width = self.canvas_width - (2.0 * self.canvas_margin)
        usable_height = self.canvas_height - (2.0 * self.canvas_margin)

        data_width = max(self.bounds.max_x - self.bounds.min_x, EPSILON)
        data_height = max(self.bounds.max_y - self.bounds.min_y, EPSILON)

        self._scale = min(usable_width / data_width, usable_height / data_height)
        drawn_width = data_width * self._scale
        drawn_height = data_height * self._scale
        self._offset_x = self.canvas_margin + ((usable_width - drawn_width) / 2.0)
        self._offset_y = self.canvas_margin + ((usable_height - drawn_height) / 2.0)

    def _map_point(self, x: float, y: float) -> tuple[float, float]:
        screen_x = self._offset_x + ((x - self.bounds.min_x) * self._scale)
        # SVG Y axis increases downward; invert to keep geometry orientation.
        screen_y = self._offset_y + ((self.bounds.max_y - y) * self._scale)
        return screen_x, screen_y

    def draw_paths(self, parsed_paths: list[tuple[int, Path]], samples_per_curve: int) -> None:
        """Render parsed SVG paths to the canvas as light-gray outlines."""
        if self._closed:
            return

        self.status_var.set("Rendering SVG paths...")
        for _, parsed_path in parsed_paths:
            for segment in parsed_path:
                points = sample_segment_points_for_display(segment, samples_per_curve=samples_per_curve)
                if len(points) < 2:
                    continue

                coordinates: list[float] = []
                for point in points:
                    mapped_x, mapped_y = self._map_point(float(point.real), float(point.imag))
                    coordinates.extend([mapped_x, mapped_y])

                self.canvas.create_line(
                    *coordinates,
                    fill="#303030",
                    width=1,
                )

        self.status_var.set("Scanning paths...")
        self.refresh()

    def add_corner(self, corner: CornerDetection) -> None:
        """Add one corner row and one plotted point in the live window."""
        if self._closed:
            return

        arc_radius_label = "-"
        if self.corner_radius > 0.0:
            target_radius = effective_corner_radius(corner, self.corner_radius, radius_profile=self.radius_profile)
            arc_geometry = compute_corner_arc_geometry(corner, desired_radius=target_radius)
            if arc_geometry is not None:
                arc_start, arc_end, arc_center, used_radius = arc_geometry
                arc_points = sample_svg_arc_points_for_display(
                    start=arc_start,
                    end=arc_end,
                    center=arc_center,
                    radius=used_radius,
                )
                coordinates: list[float] = []
                for point in arc_points:
                    mapped_x, mapped_y = self._map_point(float(point.real), float(point.imag))
                    coordinates.extend([mapped_x, mapped_y])
                self.canvas.create_line(*coordinates, fill="red", width=2)
                arc_radius_label = f"{used_radius:.2f}"
            else:
                canvas_x, canvas_y = self._map_point(corner.x, corner.y)
                radius = self.point_radius
                self.canvas.create_oval(
                    canvas_x - radius,
                    canvas_y - radius,
                    canvas_x + radius,
                    canvas_y + radius,
                    fill="red",
                    outline="",
                )
        else:
            canvas_x, canvas_y = self._map_point(corner.x, corner.y)
            radius = self.point_radius
            self.canvas.create_oval(
                canvas_x - radius,
                canvas_y - radius,
                canvas_x + radius,
                canvas_y + radius,
                fill="red",
                outline="",
            )

        self.tree.insert(
            "",
            "end",
            values=(
                corner.path_id,
                corner.node_id,
                f"{corner.x:.3f}",
                f"{corner.y:.3f}",
                f"{corner.angle_deg:.2f}",
                arc_radius_label,
            ),
        )
        self._detected_count += 1
        self.status_var.set(f"Scanning... corners found: {self._detected_count}")
        self.refresh()

    def set_finished(self) -> None:
        """Update status when scanning is complete."""
        if self._closed:
            return
        self.status_var.set(f"Scan complete. corners found: {self._detected_count} (close window to exit)")
        self.refresh()

    def refresh(self) -> None:
        """Process pending GUI events without blocking."""
        if self._closed:
            return
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            self._closed = True

    def run_until_closed(self) -> None:
        """Keep the window open after scanning until user closes it."""
        if self._closed:
            return
        self.root.mainloop()


def run_detection(args: argparse.Namespace) -> int:
    """Run the corner detection workflow and return process exit code."""
    validate_args(args)

    if not os.path.exists(args.input_svg):
        raise FileNotFoundError(f"Input file not found: {args.input_svg}")

    try:
        tree = ET.parse(args.input_svg)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid SVG/XML file: {exc}") from exc

    root = tree.getroot()
    namespace = extract_namespace(root.tag)
    if namespace:
        ET.register_namespace("", namespace)

    parsed_paths = parse_svg_paths(root, namespace=namespace, debug=args.debug)
    if not parsed_paths:
        raise ValueError("No valid <path> elements found in the SVG.")

    all_corners: list[CornerDetection] = []
    emitters: list[Callable[[CornerDetection], None]] = []

    realtime_emitter: Optional[Callable[[CornerDetection], None]] = None
    if args.realtime:
        print_realtime_header()
        realtime_emitter = print_realtime_corner
        emitters.append(print_realtime_corner)

    live_window: Optional[LiveCornerWindow] = None
    if args.live_window:
        plot_bounds = compute_plot_bounds(parsed_paths)
        live_window = LiveCornerWindow(
            plot_bounds,
            corner_radius=args.corner_radius,
            radius_profile=args.radius_profile,
        )
        live_window.draw_paths(parsed_paths, samples_per_curve=args.samples_per_curve)
        emitters.append(live_window.add_corner)

    if not emitters:
        realtime_emitter = None
    elif len(emitters) == 1:
        realtime_emitter = emitters[0]
    else:
        def combined_emitter(corner: CornerDetection) -> None:
            for emitter in emitters:
                emitter(corner)
        realtime_emitter = combined_emitter

    for path_id, parsed_path in parsed_paths:
        corners = detect_corners_in_path(
            path=parsed_path,
            path_id=path_id,
            angle_threshold=args.angle_threshold,
            samples_per_curve=args.samples_per_curve,
            min_segment_length=args.min_segment_length,
            debug=args.debug,
            on_corner=realtime_emitter,
        )
        all_corners.extend(corners)

    all_corners.sort(key=lambda item: (item.path_id, item.node_id))
    print_corner_table(all_corners)

    if args.output_svg:
        if args.apply_rounding:
            updated_count = apply_rounding_to_svg_paths(
                root=root,
                namespace=namespace,
                parsed_paths=parsed_paths,
                corners=all_corners,
                corner_radius=args.corner_radius,
                radius_profile=args.radius_profile,
                samples_per_curve=args.samples_per_curve,
                debug=args.debug,
            )
            debug_log(args.debug, f"Applied rounded-corner geometry to {updated_count} path(s).")
        else:
            append_corner_markers(
                root=root,
                namespace=namespace,
                corners=all_corners,
                marker_radius=args.marker_radius,
                corner_radius=args.corner_radius,
                radius_profile=args.radius_profile,
                debug=args.debug,
            )
        tree.write(args.output_svg, encoding="utf-8", xml_declaration=True)
        if args.apply_rounding:
            print(f"\nWrote rounded SVG: {args.output_svg}")
        else:
            print(f"\nWrote output SVG with markers: {args.output_svg}")

    if live_window is not None:
        live_window.set_finished()
        live_window.run_until_closed()

    return 0


def main() -> int:
    """Program entry point."""
    parser = build_cli_parser()
    args = parser.parse_args()

    try:
        return run_detection(args)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error: failed to read/write SVG file: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # Last-resort guard for unexpected runtime errors.
        print(f"Error: unexpected failure: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


# Example usage:
#   python detect_svg_corners.py input.svg
#   python detect_svg_corners.py input.svg output.svg --angle-threshold 35 --debug
#   python detect_svg_corners.py input.svg --realtime
#   python detect_svg_corners.py input.svg --live-window
#   python detect_svg_corners.py input.svg output.svg --corner-radius 12 --live-window --debug
#   python detect_svg_corners.py input.svg rounded.svg --corner-radius 12 --apply-rounding
#   python detect_svg_corners.py input.svg rounded.svg --corner-radius 18 --radius-profile vectorizer --apply-rounding

