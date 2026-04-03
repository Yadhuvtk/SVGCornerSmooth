"""Geometry-driven corner detection with hybrid tangent/turn/curvature evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from svgpathtools import Arc, CubicBezier, Path, QuadraticBezier

from .constants import CONTINUITY_TOLERANCE, SUPPORTED_DETECTION_MODES
from .curvature import detect_curvature_spikes, sample_curvature_profile
from .models import CornerSeverity
from .sampling import detect_turn_peaks, sample_path_uniformly
from .tangents import segment_end_tangent, segment_start_tangent, tangent_angle_degrees
from .utils import clamp, safe_segment_length


@dataclass
class _Candidate:
    path_id: int
    node_id: int
    point: complex
    source_type: str
    segment_before: int
    segment_after: int
    tangent_angle_deg: float = 0.0
    local_turn_deg: float = 0.0
    curvature_peak: float = 0.0
    tangent_score: float = 0.0
    local_score: float = 0.0
    curvature_score: float = 0.0
    endpoint_confidence: float = 0.0
    neighborhood_scale: float = 0.0
    reasons: set[str] = field(default_factory=set)
    debug: dict[str, object] = field(default_factory=dict)


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


def _mode_adjustments(
    mode: str,
    angle_threshold: float,
    min_segment_length: float,
    samples_per_curve: int,
) -> tuple[float, float, int, dict[str, float]]:
    if mode not in SUPPORTED_DETECTION_MODES:
        mode = "accurate"

    profile: dict[str, float]
    if mode == "fast":
        profile = {
            "join_gate_multiplier": 0.9,
            "short_segment_bonus": 10.0,
            "local_turn_gate_multiplier": 1.05,
            "peak_separation_scale": 0.72,
            "peak_separation_max": 8.0,
            "curvature_relative_threshold": 4.0,
            "curvature_gate": 0.42,
            "curvature_scale_factor": 0.18,
            "target_points": 120.0,
            "max_samples_per_segment": 18.0,
            "curvature_samples": 12.0,
            "locality_window": 1.0,
            "curvature_locality_window": 1.0,
            "final_threshold": 0.30,
            "angle_keep_margin": 24.0,
            "merge_tolerance_scale": 0.0009,
            "merge_tolerance_local_factor": 0.06,
            "merge_tolerance_max": 3.5,
            "max_local_peaks": 24.0,
        }
        return angle_threshold, min_segment_length, max(8, min(samples_per_curve, 26)), profile

    if mode == "preserve_shape":
        profile = {
            "join_gate_multiplier": 1.0,
            "short_segment_bonus": 16.0,
            "local_turn_gate_multiplier": 1.18,
            "peak_separation_scale": 0.9,
            "peak_separation_max": 10.0,
            "curvature_relative_threshold": 5.0,
            "curvature_gate": 0.56,
            "curvature_scale_factor": 0.16,
            "target_points": 170.0,
            "max_samples_per_segment": 28.0,
            "curvature_samples": 18.0,
            "locality_window": 2.0,
            "curvature_locality_window": 2.0,
            "final_threshold": 0.24,
            "angle_keep_margin": 22.0,
            "merge_tolerance_scale": 0.0008,
            "merge_tolerance_local_factor": 0.05,
            "merge_tolerance_max": 3.0,
            "max_local_peaks": 36.0,
        }
        return min(175.0, angle_threshold + 8.0), min_segment_length * 1.35, max(samples_per_curve, 30), profile

    if mode == "hybrid_advanced":
        profile = {
            "join_gate_multiplier": 0.72,
            "short_segment_bonus": 7.0,
            "local_turn_gate_multiplier": 0.88,
            "peak_separation_scale": 0.68,
            "peak_separation_max": 12.0,
            "curvature_relative_threshold": 2.9,
            "curvature_gate": 0.24,
            "curvature_scale_factor": 0.24,
            "target_points": 340.0,
            "max_samples_per_segment": 34.0,
            "curvature_samples": 22.0,
            "locality_window": 1.0,
            "curvature_locality_window": 1.0,
            "final_threshold": 0.16,
            "angle_keep_margin": 12.0,
            "merge_tolerance_scale": 0.0012,
            "merge_tolerance_local_factor": 0.08,
            "merge_tolerance_max": 6.0,
            "max_local_peaks": 96.0,
        }
        return max(0.0, angle_threshold - 6.0), min_segment_length * 0.9, max(samples_per_curve, 34), profile

    profile = {
        "join_gate_multiplier": 0.82,
        "short_segment_bonus": 12.0,
        "local_turn_gate_multiplier": 0.96,
        "peak_separation_scale": 0.72,
        "peak_separation_max": 10.0,
        "curvature_relative_threshold": 3.4,
        "curvature_gate": 0.34,
        "curvature_scale_factor": 0.2,
        "target_points": 220.0,
        "max_samples_per_segment": 30.0,
        "curvature_samples": 20.0,
        "locality_window": 1.0,
        "curvature_locality_window": 1.0,
        "final_threshold": 0.18,
        "angle_keep_margin": 18.0,
        "merge_tolerance_scale": 0.0010,
        "merge_tolerance_local_factor": 0.06,
        "merge_tolerance_max": 4.0,
        "max_local_peaks": 48.0,
    }
    return max(0.0, angle_threshold - 3.0), min_segment_length * 1.05, max(samples_per_curve, 30), profile


def _path_scale(path: Path) -> tuple[float, float]:
    """Return path diagonal and a local reference scale."""
    diagonal = 1.0
    try:
        xmin, xmax, ymin, ymax = path.bbox()
        width = max(0.0, xmax - xmin)
        height = max(0.0, ymax - ymin)
        diagonal = max(1.0, float(math.hypot(width, height)))
    except Exception:
        diagonal = 1.0

    lengths = sorted(safe_segment_length(segment) for segment in path if safe_segment_length(segment) > 1e-9)
    if lengths:
        median_len = lengths[len(lengths) // 2]
        lower_quartile = lengths[max(0, int((len(lengths) - 1) * 0.25))]
        core_scale = max(lower_quartile, median_len * 0.4)
    else:
        core_scale = 1.0

    local_cap = max(6.0, diagonal * 0.015)
    local_ref = clamp(core_scale, 0.25, local_cap)
    return diagonal, local_ref


def _adjacent_segment_lengths(path: Path, before_index: int, after_index: int) -> tuple[float, float]:
    prev_len = safe_segment_length(path[before_index]) if 0 <= before_index < len(path) else 0.0
    next_len = safe_segment_length(path[after_index]) if 0 <= after_index < len(path) else 0.0
    return prev_len, next_len


def _join_candidates(
    path: Path,
    *,
    path_id: int,
    threshold: float,
    min_len: float,
    profile: dict[str, float],
) -> list[_Candidate]:
    candidates: list[_Candidate] = []

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

            prev_len = safe_segment_length(prev_seg)
            next_len = safe_segment_length(next_seg)
            if prev_len <= 1e-9 or next_len <= 1e-9:
                continue

            join = complex(next_seg.start)
            if abs(prev_seg.end - join) > CONTINUITY_TOLERANCE:
                continue

            incoming, incoming_conf = segment_end_tangent(prev_seg)
            outgoing, outgoing_conf = segment_start_tangent(next_seg)
            endpoint_conf = min(incoming_conf, outgoing_conf)
            tangent_angle = tangent_angle_degrees(incoming, outgoing)

            join_gate = threshold * profile["join_gate_multiplier"]
            if tangent_angle < join_gate:
                continue

            short_segment = prev_len < min_len or next_len < min_len
            if short_segment and tangent_angle < max(threshold + profile["short_segment_bonus"], 50.0):
                continue

            tangent_score = clamp((tangent_angle - threshold) / max(1.0, 180.0 - threshold), 0.0, 1.0)
            candidates.append(
                _Candidate(
                    path_id=path_id,
                    node_id=next_index,
                    point=join,
                    source_type="join",
                    segment_before=prev_index,
                    segment_after=next_index,
                    tangent_angle_deg=tangent_angle,
                    tangent_score=tangent_score,
                    endpoint_confidence=endpoint_conf,
                    reasons={"join_tangent_discontinuity"},
                    debug={
                        "incoming_tangent": [incoming.real, incoming.imag],
                        "outgoing_tangent": [outgoing.real, outgoing.imag],
                    },
                )
            )

    return candidates


def _local_turn_candidates(
    path: Path,
    *,
    path_id: int,
    threshold: float,
    profile: dict[str, float],
    diagonal: float,
    local_ref: float,
) -> list[_Candidate]:
    target_points = int(profile["target_points"])
    target_step = max(
        diagonal / max(target_points, 24),
        min(local_ref * 0.2, 10.0),
        0.15,
    )
    samples = sample_path_uniformly(
        path,
        target_spacing=target_step,
        min_samples_per_seg=3,
        max_samples_per_seg=int(profile["max_samples_per_segment"]),
    )
    if len(samples) < 3:
        return []

    min_separation = clamp(
        target_step * profile.get("peak_separation_scale", 0.75),
        0.18,
        float(profile.get("peak_separation_max", 12.0)),
    )
    peaks = detect_turn_peaks(
        samples,
        min_angle_deg=threshold * profile["local_turn_gate_multiplier"],
        min_separation=min_separation,
        local_window=int(profile["locality_window"]),
    )
    if len(peaks) > int(profile["max_local_peaks"]):
        peaks = peaks[: int(profile["max_local_peaks"])]

    candidates: list[_Candidate] = []
    for peak in peaks:
        index = int(round(peak["index"]))
        if index <= 0 or index >= len(samples) - 1:
            continue
        center = samples[index]
        turn_deg = float(peak["turn_deg"])
        segment_before = samples[index - 1].segment_index
        segment_after = samples[index + 1].segment_index
        node_id = max(segment_after, center.segment_index)

        local_score = clamp((turn_deg - threshold) / max(1.0, 180.0 - threshold), 0.0, 1.0)
        candidates.append(
            _Candidate(
                path_id=path_id,
                node_id=node_id,
                point=center.point,
                source_type="sample_peak",
                segment_before=segment_before,
                segment_after=segment_after,
                local_turn_deg=turn_deg,
                local_score=local_score,
                endpoint_confidence=0.62,
                neighborhood_scale=max(target_step, 0.001),
                reasons={"local_turn_peak"},
                debug={"sample_s": center.s},
            )
        )
    return candidates


def _curvature_candidates(
    path: Path,
    *,
    path_id: int,
    profile: dict[str, float],
    local_ref: float,
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for segment_index, segment in enumerate(path):
        if not isinstance(segment, (CubicBezier, QuadraticBezier, Arc)):
            continue

        seg_len = safe_segment_length(segment)
        if seg_len <= 1e-9:
            continue

        base_count = int(profile["curvature_samples"])
        adaptive_extra = int(clamp(seg_len / max(local_ref * 0.75, 0.2), 0.0, 10.0))
        num_samples = int(clamp(base_count + adaptive_extra, 8.0, 42.0))
        curvature_profile = sample_curvature_profile(segment, num_samples)
        spikes = detect_curvature_spikes(
            curvature_profile,
            relative_threshold=profile["curvature_relative_threshold"],
            locality_window=int(profile["curvature_locality_window"]),
        )

        for _idx, t_value, curvature in spikes:
            curvature_score = clamp(curvature * local_ref * profile["curvature_scale_factor"], 0.0, 1.0)
            if curvature_score < profile["curvature_gate"]:
                continue

            point = complex(segment.point(t_value))
            candidates.append(
                _Candidate(
                    path_id=path_id,
                    node_id=segment_index,
                    point=point,
                    source_type="curvature_spike",
                    segment_before=segment_index,
                    segment_after=segment_index,
                    curvature_peak=curvature,
                    curvature_score=curvature_score,
                    endpoint_confidence=0.5,
                    neighborhood_scale=max(seg_len / num_samples, 0.001),
                    reasons={"localized_curvature_spike"},
                    debug={"t": t_value},
                )
            )

    return candidates


def _candidate_strength(item: _Candidate) -> float:
    return max(item.tangent_score, item.local_score, item.curvature_score)


def _merge_candidate_into(target: _Candidate, other: _Candidate) -> None:
    target.reasons.update(other.reasons)
    target.tangent_angle_deg = max(target.tangent_angle_deg, other.tangent_angle_deg)
    target.local_turn_deg = max(target.local_turn_deg, other.local_turn_deg)
    target.curvature_peak = max(target.curvature_peak, other.curvature_peak)
    target.tangent_score = max(target.tangent_score, other.tangent_score)
    target.local_score = max(target.local_score, other.local_score)
    target.curvature_score = max(target.curvature_score, other.curvature_score)
    target.endpoint_confidence = max(target.endpoint_confidence, other.endpoint_confidence)
    target.neighborhood_scale = max(target.neighborhood_scale, other.neighborhood_scale)

    if _candidate_strength(other) > _candidate_strength(target):
        target.source_type = other.source_type
        target.node_id = other.node_id
        target.segment_before = other.segment_before
        target.segment_after = other.segment_after
        target.point = other.point

    merged_debug = dict(target.debug)
    merged_debug.update(other.debug)
    target.debug = merged_debug


def _merge_candidates(candidates: list[_Candidate], tolerance: float) -> list[_Candidate]:
    if not candidates:
        return []

    merged: list[_Candidate] = []
    for candidate in sorted(candidates, key=_candidate_strength, reverse=True):
        match = None
        for existing in merged:
            if existing.path_id != candidate.path_id:
                continue
            if abs(existing.point - candidate.point) <= tolerance:
                match = existing
                break
        if match is None:
            merged.append(candidate)
            continue
        _merge_candidate_into(match, candidate)

    return merged


def _finalize_candidates(
    merged: list[_Candidate],
    *,
    path: Path,
    threshold: float,
    final_threshold: float,
    local_ref: float,
    angle_keep_margin: float,
) -> list[CornerSeverity]:
    output: list[CornerSeverity] = []

    for item in merged:
        geometric_scale = clamp(item.neighborhood_scale / max(local_ref, 1e-6), 0.0, 1.0)
        # Hybrid fusion prioritizes localized visual-turn evidence for glyph outlines.
        blended = (0.25 * item.tangent_score) + (0.55 * item.local_score) + (0.20 * item.curvature_score)
        scale_adjusted = blended * (0.9 + (0.1 * geometric_scale))
        final_score = clamp(scale_adjusted, 0.0, 1.0)

        dominant_angle = max(item.tangent_angle_deg, item.local_turn_deg)
        if dominant_angle <= 0.0 and item.curvature_score > 0.0:
            dominant_angle = threshold

        if final_score < final_threshold:
            strongest_signal = max(item.tangent_score, item.local_score, item.curvature_score)
            relaxed_join_keep = (
                item.source_type == "join"
                and item.endpoint_confidence >= 0.9
                and dominant_angle >= threshold + max(6.0, angle_keep_margin * 0.35)
            )
            if dominant_angle < threshold + angle_keep_margin and not relaxed_join_keep:
                continue
            if strongest_signal < final_threshold * 0.75 and not relaxed_join_keep:
                continue

        join_type = classify_join(dominant_angle, threshold)
        if join_type == "smooth" and final_score < final_threshold + 0.08:
            continue

        prev_len, next_len = _adjacent_segment_lengths(path, item.segment_before, item.segment_after)
        risk = clamp(
            ((1.0 - item.endpoint_confidence) * 0.45)
            + (item.local_score * 0.2)
            + (item.curvature_score * 0.35),
            0.0,
            1.0,
        )
        confidence = clamp((0.6 * final_score) + (0.4 * item.endpoint_confidence), 0.0, 1.0)
        reason_text = ",".join(sorted(item.reasons))

        output.append(
            CornerSeverity(
                path_id=item.path_id,
                node_id=item.node_id,
                x=float(item.point.real),
                y=float(item.point.imag),
                angle_deg=float(dominant_angle),
                severity_score=final_score,
                local_scale=local_ref,
                prev_segment_length=float(prev_len),
                next_segment_length=float(next_len),
                curvature_hint=item.curvature_score,
                risk_score=risk,
                join_type=join_type,
                source_type=item.source_type,
                path_index=item.path_id,
                segment_index_before=item.segment_before,
                segment_index_after=item.segment_after,
                point=item.point,
                tangent_angle_deg=float(item.tangent_angle_deg),
                local_turn_deg=float(item.local_turn_deg),
                curvature_peak=float(item.curvature_peak),
                severity=final_score,
                confidence=confidence,
                final_corner_score=final_score,
                detection_reason=reason_text,
                neighborhood_scale=item.neighborhood_scale,
                tangent_discontinuity_score=item.tangent_score,
                local_turn_score=item.local_score,
                curvature_spike_score=item.curvature_score,
                endpoint_confidence=item.endpoint_confidence,
                geometric_scale_factor=geometric_scale,
                debug=item.debug,
            )
        )

    output.sort(key=lambda corner: (corner.path_id, corner.node_id, corner.x, corner.y))
    return output


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
    threshold, min_len, _sample_count, profile = _mode_adjustments(
        mode=mode,
        angle_threshold=angle_threshold,
        min_segment_length=min_segment_length,
        samples_per_curve=samples_per_curve,
    )

    if len(path) < 2:
        return []

    diagonal, local_ref = _path_scale(path)

    candidates: list[_Candidate] = []
    candidates.extend(
        _join_candidates(
            path,
            path_id=path_id,
            threshold=threshold,
            min_len=min_len,
            profile=profile,
        )
    )

    if mode != "fast":
        candidates.extend(
            _local_turn_candidates(
                path,
                path_id=path_id,
                threshold=threshold,
                profile=profile,
                diagonal=diagonal,
                local_ref=local_ref,
            )
        )

    if mode in {"accurate", "hybrid_advanced", "preserve_shape"}:
        candidates.extend(
            _curvature_candidates(
                path,
                path_id=path_id,
                profile=profile,
                local_ref=local_ref,
            )
        )

    merge_tolerance = clamp(
        min(
            diagonal * profile["merge_tolerance_scale"],
            local_ref * profile.get("merge_tolerance_local_factor", 0.08),
        ),
        0.35,
        float(profile.get("merge_tolerance_max", 6.0)),
    )
    merged = _merge_candidates(candidates, tolerance=merge_tolerance)
    corners = _finalize_candidates(
        merged,
        path=path,
        threshold=threshold,
        final_threshold=profile["final_threshold"],
        local_ref=local_ref,
        angle_keep_margin=float(profile.get("angle_keep_margin", 20.0)),
    )

    if debug:
        print(
            f"[debug] Path {path_id}: raw_candidates={len(candidates)} merged={len(merged)} "
            f"corners={len(corners)} mode={mode}"
        )

    return corners
