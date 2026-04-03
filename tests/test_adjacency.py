from svgpathtools import Path, parse_path

from svg_corner_smooth.parser import build_adjacency_graph
from svg_corner_smooth.rounder import process_svg
from svg_corner_smooth.validate import build_options


def test_shared_endpoint_paths_are_adjacent() -> None:
    paths = [
        parse_path('M 0,0 L 20,0 L 20,20 Z'),
        parse_path('M 20,20 L 40,20 L 40,40 Z'),
    ]

    graph = build_adjacency_graph(paths, tolerance=0.5)
    assert 1 in [neighbor for neighbor, _ in graph.adjacency[0]]
    assert 0 in [neighbor for neighbor, _ in graph.adjacency[1]]


def test_non_shared_paths_are_not_adjacent() -> None:
    paths = [
        parse_path('M 0,0 L 20,0 L 20,20 Z'),
        parse_path('M 80,80 L 100,80 L 100,100 Z'),
    ]

    graph = build_adjacency_graph(paths, tolerance=0.5)
    assert graph.adjacency[0] == []
    assert graph.adjacency[1] == []


def test_shared_corner_rounding_uses_same_radius() -> None:
    svg_text = '''
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
      <path d="M 0,0 L 60,0 L 60,60 Z" fill="none" stroke="black" />
      <path d="M 60,60 L 120,60 L 120,120 Z" fill="none" stroke="black" />
    </svg>
    '''

    options = build_options(
        angle_threshold=20,
        min_segment_length=0.1,
        corner_radius=12,
        radius_profile='fixed',
        detection_mode='accurate',
        apply_rounding=True,
        export_mode='apply_rounding',
    )

    result = process_svg(svg_text.encode('utf-8'), options)
    shared = [corner for corner in result.corners if abs(corner.x - 60.0) < 0.6 and abs(corner.y - 60.0) < 0.6]
    assert len(shared) >= 2
    radii = {round(corner.suggested_radius, 6) for corner in shared}
    assert len(radii) == 1
    assert any('constrained by adjacency' in note for corner in shared for note in corner.diagnostic_notes)
