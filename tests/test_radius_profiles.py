from svg_corner_smooth.models import CornerSeverity
from svg_corner_smooth.radius_profiles import RadiusContext, compute_corner_radius


def _corner() -> CornerSeverity:
    return CornerSeverity(
        path_id=0,
        node_id=3,
        x=10.0,
        y=20.0,
        angle_deg=85.0,
        severity_score=0.7,
        local_scale=24.0,
        prev_segment_length=36.0,
        next_segment_length=30.0,
        curvature_hint=0.2,
        risk_score=0.25,
        join_type="corner",
    )


def test_radius_profiles_behave_reasonably() -> None:
    corner = _corner()
    context = RadiusContext(distance_to_prev_corner=40.0, distance_to_next_corner=50.0, collision_risk=0.15)

    requested = 12.0
    fixed = compute_corner_radius(corner, context, requested, profile="fixed")
    adaptive = compute_corner_radius(corner, context, requested, profile="adaptive")
    preserve = compute_corner_radius(corner, context, requested, profile="preserve_shape")
    aggressive = compute_corner_radius(corner, context, requested, profile="aggressive")
    legacy = compute_corner_radius(corner, context, requested, profile="vectorizer_legacy")

    assert fixed == requested
    assert preserve <= adaptive
    assert aggressive >= adaptive
    assert legacy > 0
