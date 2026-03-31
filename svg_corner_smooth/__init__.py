"""SVG corner smoothing toolkit package."""

from .constants import SUPPORTED_DETECTION_MODES, SUPPORTED_EXPORT_MODES, SUPPORTED_RADIUS_PROFILES
from .models import CornerSeverity, DiagnosticsReport, ProcessingOptions, ProcessingResult
from .rounder import analyze_svg, process_svg, round_svg

__all__ = [
    "CornerSeverity",
    "DiagnosticsReport",
    "ProcessingOptions",
    "ProcessingResult",
    "SUPPORTED_DETECTION_MODES",
    "SUPPORTED_EXPORT_MODES",
    "SUPPORTED_RADIUS_PROFILES",
    "analyze_svg",
    "process_svg",
    "round_svg",
]
