"""Flask application for SVG corner analysis and rounding."""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request

from svg_corner_smooth.constants import SUPPORTED_DETECTION_MODES, SUPPORTED_EXPORT_MODES, SUPPORTED_RADIUS_PROFILES
from svg_corner_smooth.diagnostics import corner_to_dict, diagnostics_to_dict, rejected_to_dict, summary_to_dict
from svg_corner_smooth.rounder import analyze_svg, process_svg, round_svg
from svg_corner_smooth.validate import validate_processing_options, validate_svg_bytes

from .config import BackendConfig
from .schemas import parse_options_from_mapping


def _build_response(result: Any) -> dict[str, Any]:
    summary = summary_to_dict(result.summary)
    corners_payload = [corner_to_dict(corner) for corner in result.corners]
    rejected_payload = [rejected_to_dict(item) for item in result.diagnostics.rejected_corners]
    diagnostics_payload = diagnostics_to_dict(result.diagnostics)

    # Keep compatibility fields used by previous frontend versions.
    response = {
        "ok": True,
        "summary": summary,
        "corners": corners_payload,
        "rejected_corners": rejected_payload,
        "diagnostics": diagnostics_payload,
        "svg": result.svg_text,
        "arc_preview": result.arc_preview,
        "cornerCount": len(corners_payload),
        "pathCount": summary["paths_found"],
        "updatedPathCount": summary["corners_rounded"],
        "processedSvg": result.svg_text,
        "mode": diagnostics_payload["export_mode"],
        "radiusProfile": diagnostics_payload["radius_profile"],
        "arcCircles": result.arc_preview,
    }
    return response


def _extract_svg_bytes() -> bytes:
    if "file" in request.files:
        upload = request.files["file"]
        return upload.read()

    payload = request.get_json(silent=True) or {}
    svg_text = payload.get("svg")
    if isinstance(svg_text, str) and svg_text.strip():
        return svg_text.encode("utf-8")

    raise ValueError("Missing SVG input. Send multipart field 'file' or JSON {svg: ...}")


def create_app(config: BackendConfig | None = None) -> Flask:
    """Application factory."""
    cfg = config or BackendConfig.from_env()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = cfg.max_upload_bytes

    @app.after_request
    def add_cors_headers(response):  # type: ignore[no-untyped-def]
        response.headers["Access-Control-Allow-Origin"] = cfg.cors_origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        return response

    @app.get("/api/health")
    def health() -> Any:
        return jsonify({"ok": True, "max_upload_mb": cfg.max_upload_mb})

    @app.get("/api/profiles")
    def profiles() -> Any:
        return jsonify(
            {
                "ok": True,
                "detection_modes": list(SUPPORTED_DETECTION_MODES),
                "radius_profiles": list(SUPPORTED_RADIUS_PROFILES),
                "export_modes": list(SUPPORTED_EXPORT_MODES),
            }
        )

    @app.route("/api/process", methods=["OPTIONS"])
    @app.route("/api/analyze", methods=["OPTIONS"])
    @app.route("/api/round", methods=["OPTIONS"])
    def options_preflight() -> Any:
        return ("", 204)

    @app.post("/api/analyze")
    def analyze_route() -> Any:
        try:
            svg_bytes = _extract_svg_bytes()
            validate_svg_bytes(svg_bytes, cfg.max_upload_bytes)

            data = request.form if request.form else (request.get_json(silent=True) or {})
            options = parse_options_from_mapping(data)
            options.apply_rounding = False
            if options.export_mode == "apply_rounding":
                options.export_mode = "diagnostics_overlay"

            validate_processing_options(options)
            result = analyze_svg(svg_bytes, options)
            return jsonify(_build_response(result))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Unexpected server failure: {exc}"}), 500

    @app.post("/api/round")
    def round_route() -> Any:
        try:
            svg_bytes = _extract_svg_bytes()
            validate_svg_bytes(svg_bytes, cfg.max_upload_bytes)

            data = request.form if request.form else (request.get_json(silent=True) or {})
            options = parse_options_from_mapping(data)
            options.apply_rounding = True
            options.export_mode = "apply_rounding"

            validate_processing_options(options)
            result = round_svg(svg_bytes, options)
            return jsonify(_build_response(result))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Unexpected server failure: {exc}"}), 500

    @app.post("/api/process")
    def process_route() -> Any:
        """Compatibility route preserving existing frontend contract."""
        try:
            svg_bytes = _extract_svg_bytes()
            validate_svg_bytes(svg_bytes, cfg.max_upload_bytes)

            data = request.form if request.form else (request.get_json(silent=True) or {})
            options = parse_options_from_mapping(data)
            validate_processing_options(options)

            result = process_svg(svg_bytes, options)
            return jsonify(_build_response(result))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Unexpected server failure: {exc}"}), 500

    return app
