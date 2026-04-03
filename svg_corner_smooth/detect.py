"""Corner detection with fast/accurate/preserve_shape modes and severity scoring."""

from __future__ import annotations

import math
from typing import Iterable

from svgpathtools import Path

from .constants import CONTINUITY_TOLERANCE, SUPPORTED_DETECTION_MODES
from .models import CornerSeverity
from .tangents import estimate_endpoint_tangent, estimate_tangent_at_t
from .utils import clamp, normalize_vector, safe_segment_length


def split_subpaths(path: Path) -> list[tuple[int, int]]:
    """Split path into contiguous subpath index ranges."""
    ranges: list[tuple[int, int]] = []
    count = len(path)
    if count == 0:
        return ranges

    start = 0
    for index in range(1, count):
        prev_seg = path[index - 1]
        next_seg = path[index]
        if abs(prev_seg.end - next_seg.start) > CONTINUITY_TOLERANCE:
            ranges.append((start, index))
            start = index
    ranges.append((start, count))
    return ranges


def classify_join(angle_deg: float, threshold: float) -> str:
    """Classify corner type by turning angle."""
    if angle_deg < max(8.0, threshold * 0.45):
        return "smooth"
    if angle_deg >= 165.0:
        return "cusp"
    if angle_deg >= 125.0:
        return "near-cusp"
    if angle_deg >= threshold:
        return "corner"
    return "smooth"


def curvature_hint(prev_seg: object, next_seg: object, samples_per_curve: int) -> float:
    """Estimate local curvature mismatch around join point."""
    prev_t = estimate_tangent_at_t(prev_seg, 0.82, samples_per_curve)
    prev_end = estimate_tangent_at_t(prev_seg, 0.98, samples_per_curve)
    next_start = estimate_tangent_at_t(next_seg, 0.02, samples_per_curve)
    next_t = estimate_tangent_at_t(next_seg, 0.18, samples_per_curve)

    if prev_t is None or prev_end is None or next_start is None or next_t is None:
        return 0.0

    prev_curv = 1.0 - clamp((prev_t.real * prev_end.real) + (prev_t.imag * prev_end.imag), -1.0, 1.0)
    next_curv = 1.0 - clamp((next_start.real * next_t.real) + (next_start.imag * next_t.imag), -1.0, 1.0)
    return float(clamp((prev_curv + next_curv) * 0.5, 0.0, 1.0))


def severity_score(
    angle_deg: float,
    threshold: float,
    prev_len: float,
    next_len: float,
    curv_hint: float,
    mode: str,
) -> tuple[float, float, float]:
    """Compute severity/risk/local_scale tuple."""
    local_scale = max(0.001, min(prev_len, next_len))
    length_ratio = min(prev_len, next_len) / max(prev_len, next_len, 1e-9)
    sharpness = clamp((angle_deg - threshold) / max(1.0, 180.0 - threshold), 0.0, 1.0)

    mode_bias = {
        "fast": 0.9,
        "accurate": 1.0,
        "preserve_shape": 0.75,
    }.get(mode, 1.0)

    severity = (sharpness * 0.55) + ((1.0 - length_ratio) * 0.20) + (curv_hint * 0.25)
    severity *= mode_bias
    risk = clamp((1.0 - length_ratio) * 0.35 + curv_hint * 0.45 + sharpness * 0.2, 0.0, 1.0)
    return clamp(severity, 0.0, 1.0), risk, local_scale


def _mode_adjustments(mode: str, angle_threshold: float, min_segment_length: float, samples_per_curve: int) -> tuple[float, float, int]:
    if mode not in SUPPORTED_DETECTION_MODES:
        mode = "accurate"

    if mode == "fast":
        return angle_threshold, min_segment_length, max(8, min(samples_per_curve, 28))
    if mode == "preserve_shape":
        return min(175.0, angle_threshold + 8.0), min_segment_length * 1.35, max(samples_per_curve, 32)
    return max(0.0, angle_threshold - 3.0), min_segment_length * 1.05, max(samples_per_curve, 30)


def detect_corners(
    path: Path,
    path_id: int,
    angle_threshold: float,
    min_segment_length: float,
    samples_per_curve: int,
    mode: str,
    debug: bool = False,
) -> list[CornerSeverity]:
    """Detect corners and return enriched severity models."""
    threshold, min_len, sample_count = _mode_adjustments(
        mode=mode,
        angle_threshold=angle_threshold,
        min_segment_length=min_segment_length,
        samples_per_curve=samples_per_curve,
    )

    corners: list[CornerSeverity] = []
    if len(path) < 2:
        return corners

    segment_cache: dict[int, float] = {}

    def segment_length(index: int) -> float:
        if index not in segment_cache:
            segment_cache[index] = safe_segment_length(path[index])
        return segment_cache[index]

    for start, end in split_subpaths(path):
        segment_count = end - start
        if segment_count < 2:
            continue

        closed = abs(path[start].start - path[end - 1].end) <= CONTINUITY_TOLERANCE
        node_indices: Iterable[int] = range(segment_count) if closed else range(1, segment_count)

        for local_node in node_indices:
            next_index = start + local_node
            prev_index = start + (local_node - 1 if local_node > 0 else segment_count - 1)
            prev_seg = path[prev_index]
            next_seg = path[next_index]

            prev_len = segment_length(prev_index)
            next_len = segment_length(next_index)
            if prev_len <= 1e-9 or next_len <= 1e-9:
                continue

            join = next_seg.start
            if abs(prev_seg.end - join) > CONTINUITY_TOLERANCE:
                continue

            incoming = estimate_endpoint_tangent(prev_seg, at_end=True, samples_per_curve=sample_count)
            outgoing = estimate_endpoint_tangent(next_seg, at_end=False, samples_per_curve=sample_count)
            if incoming is None or outgoing is None:
                continue

            dot = clamp((incoming.real * outgoing.real) + (incoming.imag * outgoing.imag), -1.0, 1.0)
            angle_deg = math.degrees(math.acos(dot))
            join_type = classify_join(angle_deg, threshold)
            if join_type == "smooth":
                continue

            short_segment = prev_len < min_len or next_len < min_len
            if short_segment and angle_deg < max(threshold + 8.0, 55.0):
                # Keep tiny segments only when the turn is genuinely sharp.
                # This avoids dropping real corners from glyph-style outlines.
                continue

            hint = curvature_hint(prev_seg, next_seg, sample_count)
            severity, risk, local = severity_score(
                angle_deg=angle_deg,
                threshold=threshold,
                prev_len=prev_len,
                next_len=next_len,
                curv_hint=hint,
                mode=mode,
            )

            corners.append(
                CornerSeverity(
                    path_id=path_id,
                    node_id=next_index,
                    x=float(join.real),
                    y=float(join.imag),
                    angle_deg=float(angle_deg),
                    severity_score=severity,
                    local_scale=local,
                    prev_segment_length=float(prev_len),
                    next_segment_length=float(next_len),
                    curvature_hint=hint,
                    risk_score=risk,
                    join_type=join_type,
                )
            )

    corners.sort(key=lambda item: (item.path_id, item.node_id))
    if debug:
        print(f"[debug] Path {path_id}: detected {len(corners)} corners in mode={mode}")
    return corners
