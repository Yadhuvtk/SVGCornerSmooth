# SVGCornerSmooth

Advanced local-first toolkit for SVG sharp-corner detection, diagnostics, and production-safe corner rounding.

## Overview

SVGCornerSmooth analyzes real SVG vector geometry (`path`, `polyline`, `polygon`, `rect`, `circle`, `ellipse`) using `svgpathtools`, computes corner severity diagnostics, and can apply safe fillet rounding with radius profiles.

Highlights:
- Detection modes: `fast`, `accurate`, `preserve_shape`, `hybrid_advanced`
- Radius profiles: `fixed`, `vectorizer_legacy`, `adaptive`, `preserve_shape`, `aggressive`
- Safe rounding with shrink-on-failure validation
- Robust fillet solver fallback (`ok` / `shrunk` / `skipped`) with rejection reasons
- Cross-path adjacency-aware radius constraints for shared boundary endpoints
- Flask API with analyze/round/process routes
- API input guards (content-type, empty body, malformed SVG, 5 MB limit)
- Analyze-result cache (`X-Cache: HIT|MISS`) + `DELETE /api/cache`
- Gunicorn production entrypoint (`backend/wsgi.py`)
- Simplified React frontend: choose SVG, one-click finalize, download output
- Single-click pipeline runs: sharp-corner detection -> arc preview -> final rounding
- Animated optimization progress UI for production-style processing feedback

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
  sampling.py
  curvature.py
  tangents.py
  utils.py
  validate.py
  legacy_runtime.py

backend/
  __init__.py
  app.py
  config.py
  schemas.py
  wsgi.py

tests/
  fixtures/
    simple_rect.svg
    malformed.svg
  test_api.py
  test_adjacency.py
  test_parser.py
  test_tangents.py
  test_detect.py
  test_detect_advanced.py
  test_radius_profiles.py
  test_fillet.py
  test_legacy_runtime.py
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

### One-click (Windows)

```bat
run_all.bat
```

This launches backend and frontend together in two terminal windows.

### CLI

Compatibility entrypoint is preserved:

```bash
python detect_svg_corners.py input.svg
python detect_svg_corners.py input.svg output.svg --angle-threshold 35 --debug
python detect_svg_corners.py input.svg output.svg --apply-rounding --corner-radius 10 --radius-profile adaptive
python detect_svg_corners.py input.svg output.svg --export-mode diagnostics_overlay --detection-mode preserve_shape
python detect_svg_corners.py input.svg output.svg --detection-mode hybrid_advanced --debug
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

Production (Gunicorn):

```bash
make run-prod
```

Equivalent commands:

```bash
make run-dev
gunicorn backend.wsgi:app --workers 2 --timeout 120 --bind 127.0.0.1:5050 --log-level info
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

### `DELETE /api/cache`
Clears analyze cache entries.

Request guards:
- allowed content types: `image/svg+xml`, `multipart/form-data`, `application/json`
- empty input: `400 {"ok": false, "error": "empty_input"}`
- oversized input: `413 {"ok": false, "error": "file_too_large"}`
- malformed SVG parse failure: `422 {"ok": false, "error": "parse_error: ..."}`

Analyze responses include `X-Cache: MISS` for fresh compute and `X-Cache: HIT` for cached results.

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
- `hybrid_advanced`: fused tangent + local-turn + curvature detector for production corner finding

## Advanced Corner Detection

`hybrid_advanced` runs a 3-layer geometry-driven pipeline:

1. **Join tangent discontinuity**
   - robust start/end tangents with confidence
   - catches line-line, line-curve, curve-line, curve-curve sharp joins
2. **Local sampled turning-angle peaks**
   - adaptive arc-length sampling
   - catches sharp-looking local turns that endpoint-only logic can miss
3. **Localized curvature spikes**
   - curvature profiles on curves/arcs
   - emphasizes sharp spikes and suppresses broad smooth bends

All candidate evidence is merged spatially and fused with weighted scoring:

`final_corner_score = 0.25*tangent + 0.55*local_turn + 0.20*curvature`

The detector returns backward-compatible fields plus advanced diagnostics.

Example detected-corner payload:

```json
{
  "path_id": 0,
  "node_id": 12,
  "x": 120.41,
  "y": 56.03,
  "angle_deg": 97.4,
  "join_type": "corner",
  "source_type": "join",
  "tangent_angle_deg": 97.4,
  "local_turn_deg": 89.1,
  "curvature_peak": 0.3221,
  "tangent_discontinuity_score": 0.61,
  "local_turn_score": 0.49,
  "curvature_spike_score": 0.28,
  "endpoint_confidence": 0.93,
  "final_corner_score": 0.57,
  "confidence": 0.71,
  "detection_reason": "join_tangent_discontinuity,local_turn_peak"
}
```

### Radius profiles
- `fixed`: exact requested radius
- `vectorizer_legacy`: backward-compatible heuristic
- `adaptive`: balanced safe default
- `preserve_shape`: smaller radii on dense/tiny geometry
- `aggressive`: larger radii when risk is low

## Frontend workflow

1. Upload SVG
2. Click **Finalize SVG** (single click runs detect + arc preview + finalize round)
3. Watch optimization progress animation while processing
4. Optionally override per-corner radius values, use per-row **Reset** or **Reset all overrides**
5. Click **Finalize SVG** again to apply overrides
6. Download finalized SVG

Notes:
- Frontend is intentionally minimal for production flow.
- Advanced tuning remains available via CLI/API options.
- If backend is unreachable, a top-level offline state is shown: "Backend offline — make sure the Flask server is running on port 5050."

## Tests

```bash
py -m pytest -q
```

Current suite includes API integration, parser behavior, tangents, detection, radius profiles, fillet validation, adjacency handling, legacy runtime coverage, and round pipeline parse-validity.

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
