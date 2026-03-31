#!/usr/bin/env python3
# pip install svgpathtools
"""Compatibility CLI shim for SVGCornerSmooth.

This entrypoint keeps legacy command usage working while delegating to the
refactored package CLI implementation.
"""

from svg_corner_smooth.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

# Example usage:
#   python detect_svg_corners.py input.svg
#   python detect_svg_corners.py input.svg output.svg --angle-threshold 35 --debug
#   python detect_svg_corners.py input.svg output.svg --angle-threshold 35 --debug --export-mode diagnostics_overlay
