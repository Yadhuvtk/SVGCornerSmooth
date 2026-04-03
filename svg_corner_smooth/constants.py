"""Project-wide constants and defaults."""

from __future__ import annotations

DEFAULT_ANGLE_THRESHOLD = 45.0
DEFAULT_SAMPLES_PER_CURVE = 25
DEFAULT_MARKER_RADIUS = 3.0
DEFAULT_MIN_SEGMENT_LENGTH = 1.0
DEFAULT_CORNER_RADIUS = 12.0
DEFAULT_RADIUS_PROFILE = "adaptive"
DEFAULT_DETECTION_MODE = "accurate"
DEFAULT_EXPORT_MODE = "markers_only"

EPSILON = 1e-12
CONTINUITY_TOLERANCE = 1e-9
MIN_FILLET_RADIUS = 0.5  # px

SUPPORTED_RADIUS_PROFILES = (
    "fixed",
    "vectorizer_legacy",
    "adaptive",
    "preserve_shape",
    "aggressive",
)

SUPPORTED_DETECTION_MODES = (
    "fast",
    "accurate",
    "preserve_shape",
    "hybrid_advanced",
)

SUPPORTED_EXPORT_MODES = (
    "markers_only",
    "preview_arcs",
    "apply_rounding",
    "diagnostics_overlay",
)
