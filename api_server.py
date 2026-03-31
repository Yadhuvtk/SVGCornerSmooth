#!/usr/bin/env python3
"""Compatibility server shim for SVGCornerSmooth Flask backend."""

from __future__ import annotations

import os

from backend.app import create_app


app = create_app()


if __name__ == "__main__":
    host = os.getenv("SVG_BACKEND_HOST", "127.0.0.1")
    port = int(os.getenv("SVG_BACKEND_PORT", "5000"))
    debug = os.getenv("SVG_BACKEND_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}
    app.run(host=host, port=port, debug=debug)
