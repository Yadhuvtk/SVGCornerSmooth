# SVGCornerSmooth

Advanced local-first toolkit for SVG sharp-corner detection, diagnostics, and production-safe corner rounding.

## Overview

SVGCornerSmooth analyzes real SVG vector geometry (`path`, `polyline`, `polygon`, `rect`, `circle`, `ellipse`) using `svgpathtools`, computes corner severity diagnostics, and can apply safe fillet rounding with radius profiles.

Highlights:
- Detection modes: `fast`, `accurate`, `preserve_shape`
- Radius profiles: `fixed`, `vectorizer_legacy`, `adaptive`, `preserve_shape`, `aggressive`
- Safe rounding with shrink-on-failure validation
- Flask API with analyze/round/process routes
- React frontend with side-by-side preview, realtime parameter updates, diagnostics, and per-corner radius overrides

## Architecture

```text
svg_corner_smooth/
  __init__.py
  _legacy.py
  cli.py
  constants.py
  detect.py
  diagnostics.py
  fillet.py
  models.py
  overlay.py
  parser.py
  radius_profiles.py
  rounder.py
  tangents.py
  utils.py
  validate.py

backend/
  __init__.py
  app.py
  config.py
  schemas.py

tests/
  fixtures/
  test_parser.py
  test_tangents.py
  test_detect.py
  test_radius_profiles.py
  test_fillet.py
  test_rounder.py

frontend/
  src/
    components/
    hooks/
    lib/
    App.jsx
```

## Install (Windows / VS Code)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Frontend:

```bash
cd frontend
npm install
```

## Run

### CLI

Compatibility entrypoint is preserved:

```bash
python detect_svg_corners.py input.svg
python detect_svg_corners.py input.svg output.svg --angle-threshold 35 --debug
python detect_svg_corners.py input.svg output.svg --apply-rounding --corner-radius 10 --radius-profile adaptive
python detect_svg_corners.py input.svg output.svg --export-mode diagnostics_overlay --detection-mode preserve_shape
```

Legacy realtime/live window still works:

```bash
python detect_svg_corners.py input.svg --realtime
python detect_svg_corners.py input.svg --live-window
```

### Backend

Compatibility entrypoint is preserved:

```bash
python api_server.py
```

By default the backend listens on `http://127.0.0.1:5050` (override with `SVG_BACKEND_PORT`).

Or package app:

```bash
python -m flask --app backend.app:create_app run --port 5050
```

### Frontend

```bash
cd frontend
npm run dev
```

Dev proxy targets `http://127.0.0.1:5050` by default (override with `VITE_PROXY_TARGET`).

## API

### `GET /api/health`
Health and limits.

### `GET /api/profiles`
Available detection modes, radius profiles, export modes.

### `POST /api/analyze`
Analyze only. Returns corners + diagnostics + optional overlay SVG.

### `POST /api/round`
Apply rounding and return updated SVG.

### `POST /api/process`
Compatibility route for existing frontend behavior.

Common response shape:

```json
{
  "ok": true,
  "summary": {
    "paths_found": 1,
    "corners_found": 6,
    "corners_rounded": 4,
    "corners_skipped": 2,
    "processing_ms": 12.7
  },
  "corners": [],
  "rejected_corners": [],
  "diagnostics": {},
  "svg": "..."
}
```

## Modes and Profiles

### Detection modes
- `fast`: tangent-angle detection optimized for speed
- `accurate`: improved tangent sampling and severity scoring
- `preserve_shape`: conservative detection for logos/tiny detail

### Radius profiles
- `fixed`: exact requested radius
- `vectorizer_legacy`: backward-compatible heuristic
- `adaptive`: balanced safe default
- `preserve_shape`: smaller radii on dense/tiny geometry
- `aggressive`: larger radii when risk is low

## Frontend workflow

1. Upload SVG
2. Click **Find Sharp Corners**
3. Optionally click **Add Arc Preview**
4. Adjust parameters (live preview updates automatically)
5. Optionally set per-corner radius in table
6. Click **Finalize Round**
7. Download SVG / diagnostics JSON

## Tests

```bash
pytest -q
```

Test coverage includes parser behavior, tangents, detection, radius profiles, fillet validation, and round pipeline parse-validity.

## Screenshots

- `docs/screenshots/ui-analyze.png` (placeholder)
- `docs/screenshots/ui-round.png` (placeholder)

## Limitations / Known Issues

- Exact curve-trim intersection solving still relies on robust fallback in some complex self-intersections.
- For highly transformed nested arc-heavy artwork, transforms are baked into geometry and primitive tags may be converted to `<path>` after rounding.
- Legacy realtime window mode currently uses the compatibility engine.

## Roadmap

- stronger local self-intersection solver for curve-curve fillets
- optional undo stack and per-corner lock states in frontend
- batch processing mode for SVG folders
