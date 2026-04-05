# SVGCornerSmooth

SVGCornerSmooth is a local-first toolkit for detecting sharp SVG corners and applying safe geometric rounding.

It includes:
- A Python geometry engine in `svg_corner_smooth/`
- A Flask backend API in `backend/`
- A React + Vite frontend in `frontend/`
- A compatibility CLI entrypoint `detect_svg_corners.py`

## What It Does

1. Detects sharp corners from geometry (not only SVG command letters).
2. Produces diagnostics and arc previews.
3. Applies fillet rounding with guardrails and fallback logic.
4. Returns rounded SVG output for export/download.

Supported SVG elements:
- `path`
- `polyline`
- `polygon`
- `rect`
- `circle`
- `ellipse`

## Main UI Flow

1. Upload SVG.
2. Click **Finalize SVG**.
3. Pipeline runs in order: `detect -> preview -> round`.
4. Download rounded SVG.

Legacy buttons are still available:
- Find Sharp Corners
- Add Arc Preview
- Finalize Round

## Prerequisites

- Python 3.10+
- Node.js 18+
- npm

## Install

From repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd frontend
npm install
cd ..
```

If `python` is not recognized on Windows, use `py` instead.

## Run Everything (Fastest on Windows)

From repo root:

```bat
run_all.bat
```

This starts:
- Backend: `http://127.0.0.1:5050`
- Frontend: `http://localhost:5173`

## Run Backend Only

From repo root:

```powershell
.\.venv\Scripts\Activate.ps1
python .\api_server.py
```

Backend defaults:
- Host: `127.0.0.1`
- Port: `5050`
- API revision in this repo: `6`

Quick health check (new terminal):

```powershell
Invoke-RestMethod http://127.0.0.1:5050/api/health
```

## Run Frontend Only

From repo root:

```powershell
cd frontend
npm run dev
```

Open:
- `http://localhost:5173`

Default dev proxy target is `http://127.0.0.1:5050`.

## Manual Run (Cross-Platform Summary)

Backend:

```bash
python api_server.py
```

Frontend:

```bash
cd frontend
npm run dev
```

## Backend Runtime Configuration

Environment variables:
- `SVG_BACKEND_HOST` default `127.0.0.1`
- `SVG_BACKEND_PORT` default `5050`
- `SVG_BACKEND_DEBUG` default `0`
- `SVG_MAX_UPLOAD_MB` optional
- `SVG_MAX_UPLOAD_BYTES` optional
- `SVG_CORS_ORIGIN` default `*`

PowerShell example:

```powershell
$env:SVG_BACKEND_PORT = "5051"
python .\api_server.py
```

CMD example:

```bat
set SVG_BACKEND_PORT=5051
python api_server.py
```

Bash example:

```bash
export SVG_BACKEND_PORT=5051
python api_server.py
```

## Frontend Runtime Configuration

Frontend environment variables:
- `VITE_PROXY_TARGET` default `http://127.0.0.1:5050` (Vite dev proxy target)
- `VITE_API_BASE` optional direct API base prefix for requests

Example:

```powershell
cd frontend
$env:VITE_PROXY_TARGET = "http://127.0.0.1:5051"
npm run dev
```

## API Overview

Base URL:
- `http://127.0.0.1:5050`

Endpoints:
- `GET /api/health`
- `GET /api/profiles`
- `POST /api/analyze`
- `POST /api/round`
- `POST /api/process` (compat route)
- `DELETE /api/cache`

Allowed content types:
- `multipart/form-data`
- `application/json`
- `image/svg+xml`

Important limits:
- Default max SVG upload: `5 MB`

## API Example Calls

Analyze:

```bash
curl -X POST http://127.0.0.1:5050/api/analyze \
  -F "file=@input.svg" \
  -F "detectionMode=strict_junction" \
  -F "radiusProfile=adaptive"
```

Round:

```bash
curl -X POST http://127.0.0.1:5050/api/round \
  -F "file=@input.svg" \
  -F "cornerRadius=12" \
  -F "radiusProfile=adaptive"
```

Clear analyze cache:

```bash
curl -X DELETE http://127.0.0.1:5050/api/cache
```

## Detection Modes

Supported:
- `fast`
- `accurate`
- `preserve_shape`
- `hybrid_advanced`
- `strict_junction`

## Radius Profiles

Supported:
- `fixed`
- `vectorizer_legacy`
- `adaptive`
- `preserve_shape`
- `aggressive`

Notes:
- Backend default `corner_radius`: `12.0`
- Backend default `radius_profile`: `adaptive`

## CLI Usage

Compatibility entrypoint:

```bash
python detect_svg_corners.py input.svg
python detect_svg_corners.py input.svg output.svg --angle-threshold 35 --debug
python detect_svg_corners.py input.svg output.svg --apply-rounding --corner-radius 12 --radius-profile adaptive
python detect_svg_corners.py input.svg output.svg --detection-mode strict_junction --apply-rounding --corner-radius 14
python detect_svg_corners.py input.svg output.svg --detection-mode hybrid_advanced --debug
```

Legacy live modes:

```bash
python detect_svg_corners.py input.svg --realtime
python detect_svg_corners.py input.svg --live-window
```

## Development

Run backend tests:

```bash
python -m pytest -q
```

Run frontend lint:

```bash
cd frontend
npm run lint
```

Make targets:

```bash
make run-dev
make run-prod
```

`run-prod` uses:

```bash
gunicorn backend.wsgi:app --workers 2 --timeout 120 --bind 127.0.0.1:5050 --log-level info
```

## Troubleshooting

## Backend unreachable in UI

- Start backend with `python api_server.py`.
- Confirm `http://127.0.0.1:5050/api/health` responds.
- Confirm frontend proxy points to the same host/port.

## Outdated backend warning in UI

If frontend shows:
- `Backend looks outdated. Restart backend to use latest corner detection.`

Then:
- Stop old backend process.
- Start backend again from this repo root with `python api_server.py`.
- Hard refresh browser.

## Stale analyze results

- Call `DELETE /api/cache`.
- Re-run analyze/preview/round.

## Port conflict on 5050

- Set `SVG_BACKEND_PORT` to another port before startup.
- Update `VITE_PROXY_TARGET` or `VITE_API_BASE` in frontend to match.

## Common Script References

- `run_all.bat`: start backend and frontend together (Windows).
- `api_server.py`: backend entrypoint.
- `detect_svg_corners.py`: CLI compatibility entrypoint.

## Project Structure

```text
SVGCornerSmooth/
  api_server.py
  detect_svg_corners.py
  run_all.bat
  requirements.txt
  Makefile
  README.md

  svg_corner_smooth/
    constants.py
    detect.py
    fillet.py
    radius_profiles.py
    rounder.py
    ...

  backend/
    app.py
    config.py
    schemas.py
    wsgi.py

  frontend/
    package.json
    vite.config.js
    src/
      components/
      hooks/
      lib/

  tests/
    fixtures/
    test_*.py
```

