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
