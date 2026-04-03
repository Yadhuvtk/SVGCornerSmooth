"""Arc-length-aware path sampling helpers for local corner analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from svgpathtools import Arc, CubicBezier, Line, Path, QuadraticBezier

from .utils import clamp, find_t_at_length_from_start, safe_segment_length

_POINT_EPS = 1e-6


@dataclass
class SamplePoint:
    """One sampled point on a path with arc-length metadata."""

    point: complex
    s: float
    segment_index: int
    t: float


def _is_curved_segment(segment: object) -> bool:
    return isinstance(segment, (Arc, CubicBezier, QuadraticBezier))


def dedupe_close_points(points: Iterable[complex], eps: float = _POINT_EPS) -> list[complex]:
    """Deduplicate nearly identical points."""
    tolerance = eps
    deduped: list[complex] = []
    for point in points:
        if deduped and abs(point - deduped[-1]) <= tolerance:
            continue
        deduped.append(point)
    return deduped


def sample_segment_by_arclength(segment: object, num_samples: int) -> list[tuple[float, complex]]:
    """
    Sample a segment approximately uniformly by arc length.

    Returns tuples of (t, point).
    """
    if num_samples < 2:
        num_samples = 2

    total_length = safe_segment_length(segment)
    if total_length <= 1e-12:
        start = complex(segment.point(0.0))
        return [(0.0, start), (1.0, start)]

    samples: list[tuple[float, complex]] = []
    for index in range(num_samples):
        if index == 0:
            t_value = 0.0
        elif index == num_samples - 1:
            t_value = 1.0
        else:
            target_length = total_length * (index / (num_samples - 1))
            t_value = find_t_at_length_from_start(segment, target_length)
        samples.append((t_value, complex(segment.point(t_value))))
    return samples


def sample_path_adaptive(
    path: Path,
    *,
    target_step: float,
    min_samples_per_segment: int = 3,
    max_samples_per_segment: int = 40,
) -> list[SamplePoint]:
    """Sample a path with adaptive density bounded for production performance."""
    sampled: list[SamplePoint] = []
    cumulative_s = 0.0

    for segment_index, segment in enumerate(path):
        seg_len = safe_segment_length(segment)
        if seg_len <= 1e-12:
            continue

        curved_multiplier = 1.6 if _is_curved_segment(segment) else 1.0
        density_samples = int(math.ceil((seg_len / max(target_step, 1e-6)) * curved_multiplier))
        count = int(clamp(density_samples, min_samples_per_segment, max_samples_per_segment))

        segment_samples = sample_segment_by_arclength(segment, count)
        for sample_idx, (t_value, point) in enumerate(segment_samples):
            # Avoid duplicating shared boundary points between adjacent segments.
            if sampled and sample_idx == 0 and abs(point - sampled[-1].point) <= _POINT_EPS:
                continue
            local_s = seg_len * (sample_idx / max(1, len(segment_samples) - 1))
            sampled.append(
                SamplePoint(
                    point=point,
                    s=cumulative_s + local_s,
                    segment_index=segment_index,
                    t=t_value,
                )
            )
        cumulative_s += seg_len

    if not sampled and len(path) > 0:
        start = complex(path[0].start)
        sampled.append(SamplePoint(point=start, s=0.0, segment_index=0, t=0.0))

    return sampled


def sample_path_uniformly(
    path: Path,
    target_spacing: float,
    min_samples_per_seg: int = 4,
    max_samples_per_seg: int = 80,
) -> list[SamplePoint]:
    """Compatibility API for adaptive path sampling with target spacing."""
    return sample_path_adaptive(
        path,
        target_step=max(target_spacing, 1e-6),
        min_samples_per_segment=min_samples_per_seg,
        max_samples_per_segment=max_samples_per_seg,
    )


def sample_path_local_window(path: Path, center_s: float, radius_s: float, num_samples: int) -> list[SamplePoint]:
    """Sample points in an arc-length neighborhood around a center location."""
    if len(path) == 0:
        return []
    if num_samples < 3:
        num_samples = 3

    total_length = sum(safe_segment_length(segment) for segment in path)
    if total_length <= 1e-12:
        return []

    target_step = max(radius_s * 2.0 / num_samples, total_length / max(num_samples, 8))
    all_samples = sample_path_adaptive(
        path,
        target_step=target_step,
        min_samples_per_segment=3,
        max_samples_per_segment=36,
    )
    if not all_samples:
        return []

    start_s = max(0.0, center_s - radius_s)
    end_s = min(total_length, center_s + radius_s)
    window = [sample for sample in all_samples if start_s <= sample.s <= end_s]
    if len(window) >= 3:
        return window

    # Fallback: return nearest points if window is too sparse.
    nearest = sorted(all_samples, key=lambda item: abs(item.s - center_s))
    return sorted(nearest[: max(3, num_samples // 2)], key=lambda item: item.s)


def sample_path_window(path: Path, center_s: float, radius_s: float, num_samples: int) -> list[SamplePoint]:
    """Compatibility alias for local-window path sampling."""
    return sample_path_local_window(path, center_s=center_s, radius_s=radius_s, num_samples=num_samples)


def compute_turn_angle(point_a: complex, point_b: complex, point_c: complex) -> float:
    """Turning angle (degrees) at B for triplet A-B-C."""
    ab = point_b - point_a
    bc = point_c - point_b
    if abs(ab) <= 1e-12 or abs(bc) <= 1e-12:
        return 0.0

    u = ab / abs(ab)
    v = bc / abs(bc)
    dot = clamp((u.real * v.real) + (u.imag * v.imag), -1.0, 1.0)
    return float(math.degrees(math.acos(dot)))


def detect_local_turn_peaks(
    samples: list[SamplePoint],
    *,
    min_turn_deg: float = 20.0,
    locality_window: int = 1,
    max_peaks: int = 64,
) -> list[dict[str, float]]:
    """Detect local turn-angle maxima in sampled points."""
    if len(samples) < 3:
        return []

    turns: list[tuple[int, float]] = []
    for index in range(1, len(samples) - 1):
        turn_deg = compute_turn_angle(samples[index - 1].point, samples[index].point, samples[index + 1].point)
        turns.append((index, turn_deg))

    peaks: list[dict[str, float]] = []
    for index, turn_deg in turns:
        if turn_deg < min_turn_deg:
            continue
        left = max(1, index - locality_window)
        right = min(len(samples) - 2, index + locality_window)
        neighborhood = [value for idx, value in turns if left <= idx <= right]
        if not neighborhood:
            continue
        if turn_deg + 1e-9 < max(neighborhood):
            continue

        center = samples[index]
        peaks.append(
            {
                "index": float(index),
                "s": center.s,
                "turn_deg": turn_deg,
                "x": center.point.real,
                "y": center.point.imag,
                "segment_index": float(center.segment_index),
            }
        )

    peaks.sort(key=lambda item: item["turn_deg"], reverse=True)
    if len(peaks) > max_peaks:
        peaks = peaks[:max_peaks]
    return peaks


def detect_turn_peaks(
    points: list[SamplePoint],
    min_angle_deg: float,
    min_separation: float,
    local_window: int,
) -> list[dict[str, float]]:
    """
    Detect turn peaks with arc-length separation filtering.

    This keeps one stable peak when multiple neighboring samples represent
    the same visual corner.
    """
    peaks = detect_local_turn_peaks(
        points,
        min_turn_deg=min_angle_deg,
        locality_window=local_window,
    )
    if min_separation <= 0.0 or len(peaks) <= 1:
        return peaks

    selected: list[dict[str, float]] = []
    for peak in peaks:
        s_value = peak["s"]
        if any(abs(s_value - item["s"]) < min_separation for item in selected):
            continue
        selected.append(peak)
    return selected
