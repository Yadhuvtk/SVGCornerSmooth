"""Backend runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

MAX_SVG_BYTES = 5 * 1024 * 1024  # 5 MB
API_REVISION = 3


@dataclass
class BackendConfig:
    """Flask backend config loaded from environment."""

    max_svg_bytes: int = MAX_SVG_BYTES
    api_revision: int = API_REVISION
    cors_origin: str = "*"
    debug: bool = False

    @property
    def MAX_SVG_BYTES(self) -> int:
        return int(self.max_svg_bytes)

    @property
    def API_REVISION(self) -> int:
        return int(self.api_revision)

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_svg_bytes)

    @property
    def max_upload_mb(self) -> float:
        return float(self.max_svg_bytes) / (1024.0 * 1024.0)

    @classmethod
    def from_env(cls) -> "BackendConfig":
        raw_mb = os.getenv("SVG_MAX_UPLOAD_MB")
        if raw_mb is not None and raw_mb.strip():
            max_svg_bytes = int(float(raw_mb) * 1024 * 1024)
        else:
            max_svg_bytes = int(os.getenv("SVG_MAX_UPLOAD_BYTES", str(MAX_SVG_BYTES)))
        return cls(
            max_svg_bytes=max_svg_bytes,
            cors_origin=os.getenv("SVG_CORS_ORIGIN", "*"),
            debug=os.getenv("SVG_BACKEND_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"},
        )
