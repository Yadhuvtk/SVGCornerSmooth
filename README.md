# SVGCornerSmooth

SVGCornerSmooth is a local-first toolkit for finding sharp SVG corners and safely rounding them.

It includes:
- A Python geometry engine (`svg_corner_smooth/`)
- A Flask API backend (`backend/`)
- A React frontend (`frontend/`)
- A compatibility CLI (`detect_svg_corners.py`)

The main goal is practical production rounding on real SVGs (logos, glyph-like text outlines, exported artwork), including difficult tiny segments and curve-heavy paths.

## What This Project Does

1. Detects sharp corners from geometry (not just SVG command letters)
2. Shows corner diagnostics and arc preview
3. Applies fillet rounding with safety checks and fallback logic
4. Returns a clean rounded SVG for download

Supported SVG geometry inputs include:
- `path`
- `polyline`
- `polygon`
- `rect`
- `circle`
- `ellipse`

## Main Workflow (Simple UI)

Frontend flow is intentionally simple:
1. Choose SVG
2. Click **Finalize SVG**
3. Wait for pipeline stages: detect -> preview -> round
4. Download SVG

There is also a **Legacy** section with separate buttons:
- Find Sharp Corners
- Add Arc Preview
- Finalize Round

## Quick Start

## Prerequisites

- Python 3.10+
- Node.js 18+
- npm

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cd frontend
npm install
```

## Run (Recommended)

From repo root:

```bat
run_all.bat
```

This starts:
- Backend at `http://127.0.0.1:5050`
- Frontend at `http://localhost:5173`

## Run Manually

Backend:

```bash
python api_server.py
```

Frontend:

```bash
cd frontend
npm run dev
```

## Production Backend

`gunicorn` is included for production serving:

```bash
make run-prod
```

Equivalent command:

```bash
gunicorn backend.wsgi:app --workers 2 --timeout 120 --bind 127.0.0.1:5050 --log-level info
```

Dev make target:

```bash
make run-dev
```

## CLI Usage

Compatibility entrypoint:

```bash
python detect_svg_corners.py input.svg
python detect_svg_corners.py input.svg output.svg --angle-threshold 35 --debug
python detect_svg_corners.py input.svg output.svg --apply-rounding --corner-radius 12 --radius-profile adaptive
python detect_svg_corners.py input.svg output.svg --detection-mode strict_junction --apply-rounding --corner-radius 14
python detect_svg_corners.py input.svg output.svg --detection-mode hybrid_advanced --debug
```

Legacy realtime/live-window modes are preserved:

```bash
python detect_svg_corners.py input.svg --realtime
python detect_svg_corners.py input.svg --live-window
```

## Detection Modes

Available modes:
- `fast`
- `accurate`
- `preserve_shape`
- `hybrid_advanced`
- `strict_junction`

Practical guidance:
- Use `strict_junction` for strong visible join-corner detection on glyph-like shapes.
- Use `hybrid_advanced` when you want geometry-fusion detection (tangent + sampled turn + curvature evidence).
- Use `preserve_shape` when you want conservative behavior and fewer aggressive edits.

## Radius Profiles

Available profiles:
- `fixed`
- `vectorizer_legacy`
- `adaptive`
- `preserve_shape`
- `aggressive`

Practical guidance:
- `fixed`: direct radius value
- `adaptive`: safest general default
- `preserve_shape`: smaller radii in dense areas
- `aggressive`: larger rounding where possible

## API Overview

Base URL: `http://127.0.0.1:5050`

## Endpoints

- `GET /api/health`
- `GET /api/profiles`
- `POST /api/analyze`
- `POST /api/round`
- `POST /api/process` (compat route)
- `DELETE /api/cache`

## Response Contract

Top-level fields include:
- `ok`
- `api_revision`
- `summary`
- `corners`
- `rejected_corners`
- `diagnostics`
- `svg`
- `arc_preview`
- compatibility fields: `processedSvg`, `arcCircles`, `cornerCount`, `pathCount`, `updatedPathCount`

`summary` contains:
- `paths_found`
- `corners_found`
- `corners_rounded`
- `corners_skipped`
- `processing_ms`

## Input Validation and Limits

Backend guards:
- Max input size: `5 MB`
- Allowed content types: `multipart/form-data`, `image/svg+xml`, `application/json`
- Empty input -> `400 {"ok": false, "error": "empty_input"}`
- Oversized input -> `413 {"ok": false, "error": "file_too_large"}`
- Parse failure -> `422 {"ok": false, "error": "parse_error: ..."}`

## Analyze Cache

`/api/analyze` uses an in-process LRU cache.

- First request for an SVG/options pair: `X-Cache: MISS`
- Same SVG/options again: `X-Cache: HIT`
- Clear via `DELETE /api/cache`

Cache key includes SVG hash, relevant options, and API revision.

## Advanced Detection and Rounding Notes

The engine is designed for real exported artwork where corners are often messy.

Key robustness features include:
- Safe tangent normalization with degenerate guards
- Zero-length segment protection
- Shrink-on-failure fillet validation with minimum radius floor
- Curve-aware fillet fallback solver for difficult joins
- Legacy-compat fallback path for missing trim candidate matching
- Tiny-gap stitching and degenerate segment sanitization before and after rounding
- Adjacency constraints when endpoints are shared across paths

This reduces common failures where corners are detected but arcs were previously skipped.

## Frontend-Backend Compatibility

Frontend checks backend `api_revision` and warns if backend looks outdated.

If you see:
- `Backend looks outdated. Restart backend to use latest corner detection.`

Then stop old backend processes and restart from this repo root:

```bash
python api_server.py
```

Also hard refresh the browser.

## Troubleshooting

## 1) Frontend buttons do nothing or stale output

- Ensure backend is running on `127.0.0.1:5050`
- Call `DELETE /api/cache`
- Hard refresh frontend
- Re-upload SVG

## 2) Corners detected but Finalize Round looked wrong

Typical causes:
- Tiny duplicate nodes at visual corners
- Near-closed subpaths with micro endpoint gaps
- Over-trim conflicts between neighboring corners

Current pipeline includes cleanup and retry logic for these.

## 3) Backend connection error in UI

Start backend:

```bash
python api_server.py
```

## 4) Port conflicts on 5050

Set port env var before backend start:

```bash
set SVG_BACKEND_PORT=5051
python api_server.py
```

Then point frontend proxy/API base accordingly.

## Development

## Run tests

```bash
python -m pytest -q
```

## Important Scripts

- `run_all.bat`: start backend + frontend quickly
- `git_ai_push.bat`: stage all, commit message `AI`, push

## Project Structure

```text
SVGCornerSmooth/
  api_server.py
  detect_svg_corners.py
  run_all.bat
  git_ai_push.bat
  requirements.txt
  Makefile
  README.md

  svg_corner_smooth/
    __init__.py
    _legacy.py
    legacy_runtime.py
    curve_solver.py
    cli.py
    constants.py
    models.py
    parser.py
    tangents.py
    sampling.py
    curvature.py
    detect.py
    fillet.py
    radius_profiles.py
    diagnostics.py
    overlay.py
    rounder.py
    validate.py
    utils.py

  backend/
    app.py
    config.py
    schemas.py
    wsgi.py

  frontend/
    src/
      App.jsx
      components/
      hooks/
      lib/

  tests/
    fixtures/
    test_*.py
```

## Environment Variables

Backend:
- `SVG_BACKEND_HOST` (default `127.0.0.1`)
- `SVG_BACKEND_PORT` (default `5050`)
- `SVG_BACKEND_DEBUG` (`0`/`1`)
- `SVG_MAX_UPLOAD_MB`
- `SVG_MAX_UPLOAD_BYTES`
- `SVG_CORS_ORIGIN`

Frontend:
- `VITE_PROXY_TARGET` (dev proxy target)
- `VITE_API_BASE` (optional direct API base)

## Current Status

- Detection and rounding pipeline is production-focused for local workflows.
- API routes are tested.
- Frontend supports one-click finalize flow plus legacy controls.
- Readme is intended to be enough for onboarding without extra chat context.
