from pathlib import Path

from svg_corner_smooth.parser import parse_svg_document


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def test_parser_supports_primitives_and_transforms() -> None:
    doc = parse_svg_document(str(FIXTURE_DIR / "simple_polyline.svg"))
    assert len(doc.entries) == 2

    tags = {entry.source_tag for entry in doc.entries}
    assert "polyline" in tags
    assert "rect" in tags

    first_path = doc.entries[0].path
    start = first_path[0].start
    assert abs(start.real - 10.0) < 1e-6
    assert abs(start.imag - 5.0) < 1e-6


def test_parser_strips_generated_overlay_groups() -> None:
    svg_text = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <path d="M 10,10 L 90,10 L 90,90 L 10,90 Z" />
      <g id="detected-corners-overlay">
        <circle cx="10" cy="10" r="3" />
      </g>
      <g id="diagnostics-overlay">
        <text x="12" y="8">debug</text>
      </g>
    </svg>
    """
    doc = parse_svg_document(svg_text)

    assert len(doc.entries) == 1
    assert doc.entries[0].source_tag == "path"
