"""Flask application for SVG corner analysis and rounding."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import Any

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from svg_corner_smooth.constants import SUPPORTED_DETECTION_MODES, SUPPORTED_EXPORT_MODES, SUPPORTED_RADIUS_PROFILES
from svg_corner_smooth.diagnostics import corner_to_dict, diagnostics_to_dict, rejected_to_dict, summary_to_dict
from svg_corner_smooth.parser import parse_svg_document
from svg_corner_smooth.rounder import analyze_svg, process_svg, round_svg
from svg_corner_smooth.validate import validate_processing_options, validate_svg_bytes

from .config import BackendConfig
from .schemas import parse_options_from_mapping

_ALLOWED_CONTENT_TYPES = ("multipart/form-data", "application/json", "image/svg+xml")
_ANALYZE_CACHE_MAX = 32
_ANALYZE_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()


class ApiError(Exception):
    """Structured API error with HTTP status."""

    def __init__(self, error: str, status_code: int) -> None:
        super().__init__(error)
        self.error = error
        self.status_code = status_code


def _build_response(result: Any, api_revision: int) -> dict[str, Any]:
    summary = summary_to_dict(result.summary)
    corners_payload = [corner_to_dict(corner) for corner in result.corners]
    rejected_payload = [rejected_to_dict(item) for item in result.diagnostics.rejected_corners]
    diagnostics_payload = diagnostics_to_dict(result.diagnostics)

    # Keep compatibility fields used by previous frontend versions.
    response = {
        "ok": True,
        "api_revision": int(api_revision),
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
        "adjacency": result.adjacency,
    }
    return response


def _error_response(error: str, status_code: int, api_revision: int | None = None) -> tuple[Response, int]:
    payload: dict[str, Any] = {"ok": False, "error": error}
    if api_revision is not None:
        payload["api_revision"] = int(api_revision)
    return jsonify(payload), status_code


def _ensure_supported_content_type() -> None:
    content_type = (request.content_type or "").lower()
    if any(content_type.startswith(prefix) for prefix in _ALLOWED_CONTENT_TYPES):
        return
    raise ApiError("unsupported_content_type", 415)


def _extract_svg_bytes() -> bytes:
    if "file" in request.files:
        upload = request.files["file"]
        return upload.read()

    content_type = (request.content_type or "").lower()
    if content_type.startswith("image/svg+xml"):
        return request.get_data(cache=False) or b""

    payload = request.get_json(silent=True) or {}
    svg_text = payload.get("svg")
    if isinstance(svg_text, str):
        return svg_text.encode("utf-8")

    return b""


def _validate_svg_payload(svg_bytes: bytes, cfg: BackendConfig) -> None:
    if len(svg_bytes) == 0:
        raise ApiError("empty_input", 400)
    if len(svg_bytes) > cfg.MAX_SVG_BYTES:
        raise ApiError("file_too_large", 413)

    try:
        validate_svg_bytes(svg_bytes, cfg.MAX_SVG_BYTES)
        # strict=True ensures malformed path data raises instead of being silently skipped.
        parse_svg_document(svg_bytes, strict=True)
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(f"parse_error: {exc}", 422) from exc


def _analyze_cache_get(key: str) -> dict[str, Any] | None:
    payload = _ANALYZE_CACHE.get(key)
    if payload is None:
        return None
    _ANALYZE_CACHE.move_to_end(key)
    return payload


def _analyze_cache_put(key: str, payload: dict[str, Any]) -> None:
    _ANALYZE_CACHE[key] = payload
    _ANALYZE_CACHE.move_to_end(key)
    while len(_ANALYZE_CACHE) > _ANALYZE_CACHE_MAX:
        _ANALYZE_CACHE.popitem(last=False)


def _normalize_analyze_options(options: Any) -> dict[str, Any]:
    """Normalize analyze options that can affect response payload."""
    return {
        "angle_threshold": round(float(options.angle_threshold), 6),
        "samples_per_curve": int(options.samples_per_curve),
        "min_segment_length": round(float(options.min_segment_length), 6),
        "detection_mode": str(options.detection_mode),
        "corner_radius": round(float(options.corner_radius), 6),
        "radius_profile": str(options.radius_profile),
        "export_mode": str(options.export_mode),
        "marker_radius": round(float(options.marker_radius), 6),
    }


def _cache_key_for_analyze(svg_bytes: bytes, options: Any, api_revision: int) -> str:
    svg_hash = hashlib.sha256(svg_bytes).hexdigest()
    normalized = _normalize_analyze_options(options)
    payload = {
        "api_revision": int(api_revision),
        "svg_sha256": svg_hash,
        "options": normalized,
    }
    cache_material = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(cache_material).hexdigest()


def create_app(config: BackendConfig | None = None) -> Flask:
    """Application factory."""
    cfg = config or BackendConfig.from_env()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = cfg.MAX_SVG_BYTES
    _ANALYZE_CACHE.clear()

    @app.after_request
    def add_cors_headers(response):  # type: ignore[no-untyped-def]
        response.headers["Access-Control-Allow-Origin"] = cfg.cors_origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
        return response

    @app.get("/api/health")
    def health() -> Any:
        return jsonify({"ok": True, "api_revision": cfg.API_REVISION, "max_upload_mb": round(cfg.max_upload_mb, 3)})

    @app.get("/api/profiles")
    def profiles() -> Any:
        return jsonify(
            {
                "ok": True,
                "api_revision": cfg.API_REVISION,
                "detection_modes": list(SUPPORTED_DETECTION_MODES),
                "radius_profiles": list(SUPPORTED_RADIUS_PROFILES),
                "export_modes": list(SUPPORTED_EXPORT_MODES),
            }
        )

    @app.route("/api/process", methods=["OPTIONS"])
    @app.route("/api/analyze", methods=["OPTIONS"])
    @app.route("/api/round", methods=["OPTIONS"])
    @app.route("/api/cache", methods=["OPTIONS"])
    def options_preflight() -> Any:
        return ("", 204)

    @app.delete("/api/cache")
    def clear_cache_route() -> Any:
        entries_removed = len(_ANALYZE_CACHE)
        _ANALYZE_CACHE.clear()
        return jsonify(
            {
                "ok": True,
                "error": None,
                "api_revision": cfg.API_REVISION,
                "cleared": True,
                "entries_removed": entries_removed,
            }
        )

    @app.post("/api/analyze")
    def analyze_route() -> Any:
        try:
            _ensure_supported_content_type()
            svg_bytes = _extract_svg_bytes()
            _validate_svg_payload(svg_bytes, cfg)

            data = request.form if request.form else (request.get_json(silent=True) or {})
            options = parse_options_from_mapping(data)
            options.apply_rounding = False
            if options.export_mode == "apply_rounding":
                options.export_mode = "diagnostics_overlay"

            validate_processing_options(options)

            cache_key = _cache_key_for_analyze(svg_bytes, options, cfg.API_REVISION)
            cached_payload = _analyze_cache_get(cache_key)
            if cached_payload is not None:
                response = jsonify(cached_payload)
                response.headers["X-Cache"] = "HIT"
                return response

            result = analyze_svg(svg_bytes, options)
            payload = _build_response(result, api_revision=cfg.API_REVISION)
            _analyze_cache_put(cache_key, payload)
            response = jsonify(payload)
            response.headers["X-Cache"] = "MISS"
            return response
        except ApiError as exc:
            return _error_response(exc.error, exc.status_code, api_revision=cfg.API_REVISION)
        except RequestEntityTooLarge:
            return _error_response("file_too_large", 413, api_revision=cfg.API_REVISION)
        except ValueError as exc:
            return _error_response(str(exc), 400, api_revision=cfg.API_REVISION)
        except Exception as exc:
            return _error_response(f"Unexpected server failure: {exc}", 500, api_revision=cfg.API_REVISION)

    @app.post("/api/round")
    def round_route() -> Any:
        try:
            _ensure_supported_content_type()
            svg_bytes = _extract_svg_bytes()
            _validate_svg_payload(svg_bytes, cfg)

            data = request.form if request.form else (request.get_json(silent=True) or {})
            options = parse_options_from_mapping(data)
            options.apply_rounding = True
            options.export_mode = "apply_rounding"

            validate_processing_options(options)
            result = round_svg(svg_bytes, options)
            return jsonify(_build_response(result, api_revision=cfg.API_REVISION))
        except ApiError as exc:
            return _error_response(exc.error, exc.status_code, api_revision=cfg.API_REVISION)
        except RequestEntityTooLarge:
            return _error_response("file_too_large", 413, api_revision=cfg.API_REVISION)
        except ValueError as exc:
            return _error_response(str(exc), 400, api_revision=cfg.API_REVISION)
        except Exception as exc:
            return _error_response(f"Unexpected server failure: {exc}", 500, api_revision=cfg.API_REVISION)

    @app.post("/api/process")
    def process_route() -> Any:
        """Compatibility route preserving existing frontend contract."""
        try:
            _ensure_supported_content_type()
            svg_bytes = _extract_svg_bytes()
            _validate_svg_payload(svg_bytes, cfg)

            data = request.form if request.form else (request.get_json(silent=True) or {})
            options = parse_options_from_mapping(data)
            validate_processing_options(options)

            result = process_svg(svg_bytes, options)
            return jsonify(_build_response(result, api_revision=cfg.API_REVISION))
        except ApiError as exc:
            return _error_response(exc.error, exc.status_code, api_revision=cfg.API_REVISION)
        except RequestEntityTooLarge:
            return _error_response("file_too_large", 413, api_revision=cfg.API_REVISION)
        except ValueError as exc:
            return _error_response(str(exc), 400, api_revision=cfg.API_REVISION)
        except Exception as exc:
            return _error_response(f"Unexpected server failure: {exc}", 500, api_revision=cfg.API_REVISION)

    return app
