"""Command-line interface for SVG corner detection and corner rounding."""

from __future__ import annotations

import argparse
import json
import os
import sys
from types import SimpleNamespace

from . import legacy_runtime as _legacy
from .diagnostics import print_corner_table
from .rounder import process_svg
from .validate import build_options, validate_processing_options


def _parse_overrides(raw: str | None) -> dict[str, float] | None:
    if not raw:
        return None
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("--corner-overrides-json must be a JSON object")
    out: dict[str, float] = {}
    for key, value in payload.items():
        radius = float(value)
        if radius > 0.0:
            out[str(key)] = radius
    return out or None


def build_cli_parser() -> argparse.ArgumentParser:
    """Create parser for local CLI usage."""
    parser = argparse.ArgumentParser(
        description="Analyze SVG corners and optionally apply safe corner rounding.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python detect_svg_corners.py input.svg\n"
            "  python detect_svg_corners.py input.svg output.svg --angle-threshold 35 --debug\n"
            "  python detect_svg_corners.py input.svg output.svg --apply-rounding --corner-radius 12 --radius-profile adaptive\n"
            "  python detect_svg_corners.py input.svg output.svg --export-mode diagnostics_overlay --detection-mode preserve_shape"
        ),
    )
    parser.add_argument("input_svg", help="Path to input SVG file")
    parser.add_argument("output_svg", nargs="?", default=None, help="Optional output SVG path")

    parser.add_argument("--angle-threshold", type=float, default=45.0)
    parser.add_argument("--samples-per-curve", type=int, default=25)
    parser.add_argument("--marker-radius", type=float, default=3.0)
    parser.add_argument("--min-segment-length", type=float, default=1.0)
    parser.add_argument("--corner-radius", type=float, default=12.0)
    parser.add_argument(
        "--radius-profile",
        default="adaptive",
        choices=("fixed", "vectorizer", "vectorizer_legacy", "adaptive", "preserve_shape", "aggressive"),
    )
    parser.add_argument(
        "--detection-mode",
        default="accurate",
        choices=("fast", "accurate", "preserve_shape", "hybrid_advanced"),
    )
    parser.add_argument(
        "--export-mode",
        default="markers_only",
        choices=("markers_only", "preview_arcs", "apply_rounding", "diagnostics_overlay"),
    )

    parser.add_argument("--apply-rounding", action="store_true", help="Compatibility flag for rounded output mode")
    parser.add_argument("--preview-arcs", action="store_true", help="Compatibility flag for arc preview mode")
    parser.add_argument("--diagnostics-overlay", action="store_true", help="Shortcut for diagnostics overlay mode")

    parser.add_argument("--corner-overrides-json", default=None, help="JSON map like {'0:12': 6.5}")
    parser.add_argument("--max-radius-shrink-iterations", type=int, default=10)
    parser.add_argument("--min-allowed-radius", type=float, default=0.5)
    parser.add_argument("--intersection-safety-margin", type=float, default=0.01)
    parser.add_argument("--no-skip-invalid-corners", action="store_true")
    parser.add_argument("--no-exact-curve-trim", action="store_true")

    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--realtime", action="store_true", help="Legacy realtime stream mode")
    parser.add_argument("--live-window", action="store_true", help="Legacy Tk live-window mode")
    return parser


def _run_legacy(args: argparse.Namespace) -> int:
    """Use legacy engine for streaming/live-window compatibility."""
    radius_profile = args.radius_profile
    if radius_profile not in {"fixed", "vectorizer"}:
        radius_profile = "vectorizer" if radius_profile == "vectorizer_legacy" else "fixed"

    legacy_args = SimpleNamespace(
        input_svg=args.input_svg,
        output_svg=args.output_svg,
        angle_threshold=args.angle_threshold,
        samples_per_curve=args.samples_per_curve,
        marker_radius=args.marker_radius,
        corner_radius=args.corner_radius,
        radius_profile=radius_profile,
        apply_rounding=args.apply_rounding,
        min_segment_length=args.min_segment_length,
        debug=args.debug,
        realtime=args.realtime,
        live_window=args.live_window,
    )
    return _legacy.run_detection(legacy_args)


def run_cli(args: argparse.Namespace) -> int:
    """Execute CLI pipeline."""
    if not os.path.exists(args.input_svg):
        raise FileNotFoundError(f"Input file not found: {args.input_svg}")

    # Preserve old realtime/live-window behavior through the legacy implementation.
    if args.realtime or args.live_window:
        return _run_legacy(args)

    with open(args.input_svg, "rb") as handle:
        svg_bytes = handle.read()

    export_mode = args.export_mode
    if args.preview_arcs:
        export_mode = "preview_arcs"
    if args.diagnostics_overlay:
        export_mode = "diagnostics_overlay"
    if args.apply_rounding:
        export_mode = "apply_rounding"

    options = build_options(
        angle_threshold=args.angle_threshold,
        samples_per_curve=args.samples_per_curve,
        marker_radius=args.marker_radius,
        min_segment_length=args.min_segment_length,
        corner_radius=args.corner_radius,
        radius_profile=args.radius_profile,
        detection_mode=args.detection_mode,
        export_mode=export_mode,
        apply_rounding=args.apply_rounding or export_mode == "apply_rounding",
        preview_arcs=export_mode == "preview_arcs",
        debug=args.debug,
        max_radius_shrink_iterations=args.max_radius_shrink_iterations,
        min_allowed_radius=args.min_allowed_radius,
        skip_invalid_corners=not args.no_skip_invalid_corners,
        exact_curve_trim=not args.no_exact_curve_trim,
        intersection_safety_margin=args.intersection_safety_margin,
        per_corner_radii=_parse_overrides(args.corner_overrides_json),
    )
    validate_processing_options(options)

    result = process_svg(svg_bytes, options)
    print_corner_table(result.corners)

    if args.output_svg:
        with open(args.output_svg, "w", encoding="utf-8") as handle:
            handle.write(result.svg_text)
        print(f"\nWrote SVG: {args.output_svg}")

    return 0


def main() -> int:
    """Program entry point."""
    parser = build_cli_parser()
    args = parser.parse_args()
    try:
        return run_cli(args)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: unexpected failure: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
