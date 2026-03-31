#!/usr/bin/env python3
"""Local API server for SVG corner detection + rounding."""

from __future__ import annotations

import io
import json
import traceback
import xml.etree.ElementTree as ET
from typing import Any

from flask import Flask, jsonify, request

import detect_svg_corners as dsc


app = Flask(__name__)


def parse_bool(value: str | None, default: bool = False) -> bool:
    """Parse a truthy/falsey form value."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_float(value: str | None, default: float) -> float:
    """Parse float safely."""
    if value is None or value == "":
        return default
    return float(value)


def parse_int(value: str | None, default: int) -> int:
    """Parse int safely."""
    if value is None or value == "":
        return default
    return int(value)


@app.after_request
def add_cors_headers(response):  # type: ignore[no-untyped-def]
    """Allow requests from local frontend dev server."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


@app.get("/api/health")
def health() -> Any:
    """Simple health endpoint."""
    return jsonify({"ok": True})


@app.route("/api/process", methods=["OPTIONS"])
def process_options() -> Any:
    """Preflight support."""
    return ("", 204)


@app.post("/api/process")
def process_svg() -> Any:
    """Process uploaded SVG and return corners + processed SVG output."""
    try:
        if "file" not in request.files:
            return jsonify({"error": "Missing file field 'file'."}), 400

        upload = request.files["file"]
        file_bytes = upload.read()
        if not file_bytes:
            return jsonify({"error": "Uploaded file is empty."}), 400

        angle_threshold = parse_float(request.form.get("angleThreshold"), 45.0)
        samples_per_curve = parse_int(request.form.get("samplesPerCurve"), 25)
        marker_radius = parse_float(request.form.get("markerRadius"), 3.0)
        min_segment_length = parse_float(request.form.get("minSegmentLength"), 1.0)
        corner_radius = parse_float(request.form.get("cornerRadius"), 0.0)
        radius_profile = (request.form.get("radiusProfile") or "fixed").strip().lower()
        apply_rounding = parse_bool(request.form.get("applyRounding"), False)
        preview_arcs = parse_bool(request.form.get("previewArcs"), False)
        debug = parse_bool(request.form.get("debug"), False)

        # Per-corner radius overrides (JSON string: {"pathId:nodeId": radius, ...})
        per_corner_radii: dict[str, float] | None = None
        overrides_raw = request.form.get("cornerRadiusOverridesJson")
        if overrides_raw:
            try:
                raw = json.loads(overrides_raw)
                per_corner_radii = {str(k): float(v) for k, v in raw.items() if float(v) > 0}
            except (json.JSONDecodeError, ValueError):
                per_corner_radii = None

        if radius_profile not in {"fixed", "vectorizer"}:
            radius_profile = "fixed"

        # Reuse existing argument validation to stay consistent with CLI behavior.
        validation_args = type(
            "ValidationArgs",
            (),
            {
                "angle_threshold": angle_threshold,
                "samples_per_curve": samples_per_curve,
                "marker_radius": marker_radius,
                "corner_radius": corner_radius,
                "min_segment_length": min_segment_length,
                "apply_rounding": apply_rounding,
            },
        )()
        # Skip apply_rounding radius check for preview mode (radius may be 0 initially)
        if not preview_arcs:
            dsc.validate_args(validation_args)

        try:
            root = ET.fromstring(file_bytes)
        except ET.ParseError as exc:
            return jsonify({"error": f"Invalid SVG/XML: {exc}"}), 400

        tree = ET.ElementTree(root)
        namespace = dsc.extract_namespace(root.tag)
        if namespace:
            ET.register_namespace("", namespace)

        parsed_paths = dsc.parse_svg_paths(root, namespace=namespace, debug=debug)
        if not parsed_paths:
            return jsonify({"error": "No valid <path> elements found in uploaded SVG."}), 400

        all_corners: list[dsc.CornerDetection] = []
        for path_id, parsed_path in parsed_paths:
            path_corners = dsc.detect_corners_in_path(
                path=parsed_path,
                path_id=path_id,
                angle_threshold=angle_threshold,
                samples_per_curve=samples_per_curve,
                min_segment_length=min_segment_length,
                debug=debug,
            )
            all_corners.extend(path_corners)
        all_corners.sort(key=lambda item: (item.path_id, item.node_id))

        updated_paths = 0
        arc_circles: list[dict] = []

        if preview_arcs:
            # Preview mode: draw full inscribed circles + arcs so the user can inspect and adjust.
            arc_circles = dsc.append_arc_preview_circles(
                root=root,
                namespace=namespace,
                corners=all_corners,
                corner_radius=corner_radius,
                radius_profile=radius_profile,
                per_corner_radii=per_corner_radii,
                debug=debug,
            )
        elif apply_rounding and (corner_radius > 0.0 or per_corner_radii):
            updated_paths = dsc.apply_rounding_to_svg_paths(
                root=root,
                namespace=namespace,
                parsed_paths=parsed_paths,
                corners=all_corners,
                corner_radius=corner_radius,
                radius_profile=radius_profile,
                samples_per_curve=samples_per_curve,
                debug=debug,
                per_corner_radii=per_corner_radii,
            )
            # Show animated markers over the rounded paths.
            dsc.append_corner_markers(
                root=root,
                namespace=namespace,
                corners=all_corners,
                marker_radius=marker_radius,
                corner_radius=0.0,
                radius_profile=radius_profile,
                debug=debug,
            )
        else:
            # Marker-only mode: animated sonar-ping dots at each corner.
            dsc.append_corner_markers(
                root=root,
                namespace=namespace,
                corners=all_corners,
                marker_radius=marker_radius,
                corner_radius=0.0,
                radius_profile=radius_profile,
                debug=debug,
            )

        output_buffer = io.BytesIO()
        tree.write(output_buffer, encoding="utf-8", xml_declaration=True)
        output_svg = output_buffer.getvalue().decode("utf-8")

        corners_payload = [
            {
                "path_id": corner.path_id,
                "node_id": corner.node_id,
                "x": round(corner.x, 4),
                "y": round(corner.y, 4),
                "angle_deg": round(corner.angle_deg, 2),
                "prev_segment_length": round(corner.prev_segment_length, 4),
                "next_segment_length": round(corner.next_segment_length, 4),
            }
            for corner in all_corners
        ]

        mode = "preview_arcs" if preview_arcs else ("rounded" if apply_rounding else "marked")
        return jsonify(
            {
                "corners": corners_payload,
                "cornerCount": len(all_corners),
                "pathCount": len(parsed_paths),
                "updatedPathCount": updated_paths,
                "processedSvg": output_svg,
                "mode": mode,
                "radiusProfile": radius_profile,
                "arcCircles": arc_circles,
            }
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - defensive guard
        return (
            jsonify(
                {
                    "error": f"Unexpected server error: {exc}",
                    "traceback": traceback.format_exc(),
                }
            ),
            500,
        )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
