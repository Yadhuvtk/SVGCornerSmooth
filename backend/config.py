"""Backend runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class BackendConfig:
    """Flask backend config loaded from environment."""

    max_upload_mb: int = 12
    cors_origin: str = "*"
    debug: bool = False

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @classmethod
    def from_env(cls) -> "BackendConfig":
        return cls(
            max_upload_mb=int(os.getenv("SVG_MAX_UPLOAD_MB", "12")),
            cors_origin=os.getenv("SVG_CORS_ORIGIN", "*"),
            debug=os.getenv("SVG_BACKEND_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"},
        )
