import io
from pathlib import Path

import pytest

from backend.app import create_app
from backend.config import BackendConfig


FIXTURE_DIR = Path(__file__).resolve().parent / 'fixtures'


@pytest.fixture()
def backend_cfg() -> BackendConfig:
    return BackendConfig(max_svg_bytes=64 * 1024, cors_origin='*', debug=False)


@pytest.fixture()
def app(backend_cfg: BackendConfig):
    flask_app = create_app(backend_cfg)
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def simple_svg_bytes() -> bytes:
    return (FIXTURE_DIR / 'simple_rect.svg').read_bytes()


@pytest.fixture()
def malformed_svg_text() -> str:
    return (FIXTURE_DIR / 'malformed.svg').read_text(encoding='utf-8')


def _assert_top_level_shape(payload: dict):
    assert 'ok' in payload
    assert 'summary' in payload or payload.get('ok') is False
    if payload.get('ok'):
        for key in ('corners', 'rejected_corners', 'diagnostics', 'svg'):
            assert key in payload


def test_health_returns_200(client):
    response = client.get('/api/health')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['ok'] is True


def test_profiles_returns_detection_modes_and_radius_profiles(client):
    response = client.get('/api/profiles')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['ok'] is True
    assert 'detection_modes' in payload
    assert 'radius_profiles' in payload


def test_analyze_with_valid_svg_returns_corners(client, simple_svg_bytes):
    response = client.post(
        '/api/analyze',
        data={'file': (io.BytesIO(simple_svg_bytes), 'simple_rect.svg')},
        content_type='multipart/form-data',
    )
    assert response.status_code == 200
    payload = response.get_json()
    _assert_top_level_shape(payload)
    assert payload['ok'] is True
    assert isinstance(payload['corners'], list)
    assert payload['summary']['paths_found'] >= 1


def test_analyze_with_empty_body_returns_400(client):
    response = client.post('/api/analyze', json={})
    assert response.status_code == 400
    payload = response.get_json()
    assert payload['ok'] is False
    assert payload['error'] == 'empty_input'


def test_analyze_with_oversized_body_returns_413(client, backend_cfg):
    oversized = ('<svg xmlns="http://www.w3.org/2000/svg">' + (' ' * backend_cfg.MAX_SVG_BYTES) + '</svg>').encode('utf-8')
    response = client.post('/api/analyze', data=oversized, content_type='image/svg+xml')
    assert response.status_code == 413
    payload = response.get_json()
    assert payload['ok'] is False
    assert payload['error'] == 'file_too_large'


def test_analyze_with_malformed_svg_returns_422(client, malformed_svg_text):
    response = client.post('/api/analyze', data=malformed_svg_text, content_type='image/svg+xml')
    assert response.status_code == 422
    payload = response.get_json()
    assert payload['ok'] is False
    assert 'parse_error' in payload['error']


def test_round_with_valid_svg_and_params_returns_svg_string(client, simple_svg_bytes):
    response = client.post(
        '/api/round',
        data={
            'file': (io.BytesIO(simple_svg_bytes), 'simple_rect.svg'),
            'cornerRadius': '6',
            'radiusProfile': 'fixed',
            'detectionMode': 'accurate',
        },
        content_type='multipart/form-data',
    )
    assert response.status_code == 200
    payload = response.get_json()
    _assert_top_level_shape(payload)
    assert payload['ok'] is True
    assert isinstance(payload['svg'], str)


def test_round_skipped_corners_appear_in_rejected_corners(client, simple_svg_bytes):
    response = client.post(
        '/api/round',
        data={
            'file': (io.BytesIO(simple_svg_bytes), 'simple_rect.svg'),
            'cornerRadius': '1',
            'minAllowedRadius': '50',
            'radiusProfile': 'fixed',
        },
        content_type='multipart/form-data',
    )
    assert response.status_code == 200
    payload = response.get_json()
    _assert_top_level_shape(payload)
    assert payload['ok'] is True
    assert isinstance(payload['rejected_corners'], list)
    assert len(payload['rejected_corners']) >= 1


def test_process_compat_route_returns_same_shape_as_analyze(client, simple_svg_bytes):
    analyze_response = client.post(
        '/api/analyze',
        data={'file': (io.BytesIO(simple_svg_bytes), 'simple_rect.svg')},
        content_type='multipart/form-data',
    )
    process_response = client.post(
        '/api/process',
        data={'file': (io.BytesIO(simple_svg_bytes), 'simple_rect.svg')},
        content_type='multipart/form-data',
    )

    assert analyze_response.status_code == 200
    assert process_response.status_code == 200

    analyze_payload = analyze_response.get_json()
    process_payload = process_response.get_json()

    for key in ('ok', 'summary', 'corners', 'rejected_corners', 'diagnostics', 'svg'):
        assert key in analyze_payload
        assert key in process_payload


def test_analyze_cache_header_and_clear_route(client, simple_svg_bytes):
    first = client.post(
        '/api/analyze',
        data={'file': (io.BytesIO(simple_svg_bytes), 'simple_rect.svg')},
        content_type='multipart/form-data',
    )
    second = client.post(
        '/api/analyze',
        data={'file': (io.BytesIO(simple_svg_bytes), 'simple_rect.svg')},
        content_type='multipart/form-data',
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers.get('X-Cache') == 'MISS'
    assert second.headers.get('X-Cache') == 'HIT'

    cleared = client.delete('/api/cache')
    assert cleared.status_code == 200
    payload = cleared.get_json()
    assert payload['ok'] is True
