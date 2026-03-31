from svg_corner_smooth import _legacy
from svg_corner_smooth.fillet import FilletSettings, shrink_radius_until_valid, validate_fillet


def _legacy_corner() -> _legacy.CornerDetection:
    return _legacy.CornerDetection(
        path_id=0,
        node_id=4,
        x=0.0,
        y=0.0,
        angle_deg=90.0,
        incoming_dx=1.0,
        incoming_dy=0.0,
        outgoing_dx=0.0,
        outgoing_dy=1.0,
        prev_segment_length=80.0,
        next_segment_length=80.0,
    )


def test_validate_fillet_success() -> None:
    result = validate_fillet(_legacy_corner(), radius=6.0, settings=FilletSettings())
    assert result.valid
    assert result.radius > 0


def test_shrink_rejects_below_minimum() -> None:
    settings = FilletSettings(min_allowed_radius=5.0, max_radius_shrink_iterations=2)
    result = shrink_radius_until_valid(_legacy_corner(), initial_radius=1.0, settings=settings)
    assert not result.valid
    assert result.reason in {"radius_below_min", "radius_shrunk_below_min"}
