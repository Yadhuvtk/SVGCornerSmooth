from svg_corner_smooth import _legacy
from svg_corner_smooth.fillet import FilletSettings, shrink_radius_until_valid, validate_fillet


def _legacy_corner(
    *,
    incoming: complex = complex(1.0, 0.0),
    outgoing: complex = complex(0.0, 1.0),
    prev_len: float = 80.0,
    next_len: float = 80.0,
) -> _legacy.CornerDetection:
    return _legacy.CornerDetection(
        path_id=0,
        node_id=4,
        x=0.0,
        y=0.0,
        angle_deg=90.0,
        incoming_dx=incoming.real,
        incoming_dy=incoming.imag,
        outgoing_dx=outgoing.real,
        outgoing_dy=outgoing.imag,
        prev_segment_length=prev_len,
        next_segment_length=next_len,
    )


def test_validate_fillet_success() -> None:
    result = validate_fillet(_legacy_corner(), radius=6.0, settings=FilletSettings())
    assert result.valid
    assert result.status in {'ok', 'shrunk'}
    assert result.radius > 0


def test_near_parallel_configuration_is_skipped_not_exception() -> None:
    # Near-parallel direction vectors are a common unstable solver case.
    corner = _legacy_corner(incoming=complex(1.0, 0.0), outgoing=complex(1.0, 1e-7), prev_len=120.0, next_len=120.0)
    result = validate_fillet(corner, radius=12.0, settings=FilletSettings())
    assert not result.valid
    assert result.status == 'skipped'


def test_solver_exception_is_captured_as_skipped(monkeypatch) -> None:
    corner = _legacy_corner()

    def _boom(*args, **kwargs):
        raise RuntimeError('no real intersection')

    monkeypatch.setattr(_legacy, 'compute_corner_arc_geometry', _boom)
    result = validate_fillet(corner, radius=12.0, settings=FilletSettings())
    assert result.status == 'skipped'
    assert 'solver_error' in result.reason


def test_shrink_loop_stops_at_hard_radius_floor() -> None:
    # Degenerate geometry keeps failing until floor is hit.
    corner = _legacy_corner(incoming=complex(1.0, 0.0), outgoing=complex(1.0, 0.0), prev_len=0.2, next_len=0.2)
    settings = FilletSettings(min_allowed_radius=0.5, max_radius_shrink_iterations=20)
    result = shrink_radius_until_valid(corner, initial_radius=8.0, settings=settings)
    assert not result.valid
    assert result.status == 'skipped'
    assert 'radius_too_small' in result.reason
