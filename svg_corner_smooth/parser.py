"""SVG parsing utilities with support for path and primitive shape elements."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Iterable, Optional

from svgpathtools import Path, parse_path

from .models import ParsedPathEntry, ParsedSvgDocument
from .utils import matrix_multiply, parse_transform, transform_path


_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def extract_namespace(tag: str) -> str:
    """Extract namespace URI from tag format '{namespace}name'."""
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return ""


def svg_tag(namespace: str, local_name: str) -> str:
    """Build namespaced tag if namespace is present."""
    if namespace:
        return f"{{{namespace}}}{local_name}"
    return local_name


def _parse_points(points_attr: str) -> list[tuple[float, float]]:
    values = [part for part in points_attr.replace(",", " ").split() if part]
    numbers = [float(value) for value in values]
    output: list[tuple[float, float]] = []
    for index in range(0, len(numbers) - 1, 2):
        output.append((numbers[index], numbers[index + 1]))
    return output


def _rect_to_path_d(element: ET.Element) -> Optional[str]:
    x = float(element.get("x", "0"))
    y = float(element.get("y", "0"))
    width = float(element.get("width", "0"))
    height = float(element.get("height", "0"))
    if width <= 0 or height <= 0:
        return None

    rx = float(element.get("rx", "0") or 0)
    ry = float(element.get("ry", "0") or 0)
    if rx <= 0 and ry <= 0:
        return f"M {x},{y} L {x + width},{y} L {x + width},{y + height} L {x},{y + height} Z"

    if rx <= 0:
        rx = ry
    if ry <= 0:
        ry = rx
    rx = min(rx, width / 2.0)
    ry = min(ry, height / 2.0)

    return (
        f"M {x + rx},{y} "
        f"L {x + width - rx},{y} "
        f"A {rx},{ry} 0 0 1 {x + width},{y + ry} "
        f"L {x + width},{y + height - ry} "
        f"A {rx},{ry} 0 0 1 {x + width - rx},{y + height} "
        f"L {x + rx},{y + height} "
        f"A {rx},{ry} 0 0 1 {x},{y + height - ry} "
        f"L {x},{y + ry} "
        f"A {rx},{ry} 0 0 1 {x + rx},{y} Z"
    )


def _circle_to_path_d(element: ET.Element) -> Optional[str]:
    cx = float(element.get("cx", "0"))
    cy = float(element.get("cy", "0"))
    radius = float(element.get("r", "0"))
    if radius <= 0:
        return None
    return (
        f"M {cx - radius},{cy} "
        f"A {radius},{radius} 0 1 0 {cx + radius},{cy} "
        f"A {radius},{radius} 0 1 0 {cx - radius},{cy} Z"
    )


def _ellipse_to_path_d(element: ET.Element) -> Optional[str]:
    cx = float(element.get("cx", "0"))
    cy = float(element.get("cy", "0"))
    rx = float(element.get("rx", "0"))
    ry = float(element.get("ry", "0"))
    if rx <= 0 or ry <= 0:
        return None
    return (
        f"M {cx - rx},{cy} "
        f"A {rx},{ry} 0 1 0 {cx + rx},{cy} "
        f"A {rx},{ry} 0 1 0 {cx - rx},{cy} Z"
    )


def element_to_path_data(element: ET.Element, local_tag: str) -> Optional[str]:
    """Convert supported SVG element types into path data."""
    if local_tag == "path":
        return element.get("d")

    if local_tag == "polyline":
        points = _parse_points(element.get("points", ""))
        if len(points) < 2:
            return None
        head = f"M {points[0][0]},{points[0][1]}"
        tail = " ".join(f"L {x},{y}" for x, y in points[1:])
        return f"{head} {tail}"

    if local_tag == "polygon":
        points = _parse_points(element.get("points", ""))
        if len(points) < 3:
            return None
        head = f"M {points[0][0]},{points[0][1]}"
        tail = " ".join(f"L {x},{y}" for x, y in points[1:])
        return f"{head} {tail} Z"

    if local_tag == "rect":
        return _rect_to_path_d(element)

    if local_tag == "circle":
        return _circle_to_path_d(element)

    if local_tag == "ellipse":
        return _ellipse_to_path_d(element)

    return None


def _iter_supported_elements(
    root: ET.Element,
    inherited_matrix: tuple[float, float, float, float, float, float] = _IDENTITY,
) -> Iterable[tuple[ET.Element, str, tuple[float, float, float, float, float, float]]]:
    """
    Walk SVG nodes recursively and yield supported geometry elements with
    accumulated transform matrix (including parent groups).
    """
    own_matrix = matrix_multiply(inherited_matrix, parse_transform(root.get("transform")))
    tag = root.tag
    if isinstance(tag, str):
        local = tag.split("}", 1)[-1]
        if local in {"path", "polyline", "polygon", "rect", "circle", "ellipse"}:
            yield root, local, own_matrix

    for child in list(root):
        yield from _iter_supported_elements(child, own_matrix)


def parse_svg_document(source: str | bytes | ET.ElementTree, debug: bool = False) -> ParsedSvgDocument:
    """Parse SVG XML source and return normalized path entries."""
    if isinstance(source, ET.ElementTree):
        tree = source
    elif isinstance(source, bytes):
        root = ET.fromstring(source)
        tree = ET.ElementTree(root)
    elif isinstance(source, str) and os.path.exists(source):
        tree = ET.parse(source)
    else:
        root = ET.fromstring(source)  # type: ignore[arg-type]
        tree = ET.ElementTree(root)

    root = tree.getroot()
    namespace = extract_namespace(root.tag)
    if namespace:
        ET.register_namespace("", namespace)

    entries: list[ParsedPathEntry] = []
    path_id = 0
    for element, local_tag, matrix in _iter_supported_elements(root):
        path_data = element_to_path_data(element, local_tag=local_tag)
        if not path_data:
            continue
        try:
            path = parse_path(path_data)
        except Exception:
            if debug:
                print(f"[debug] Could not parse {local_tag} element path data.")
            continue

        if matrix != _IDENTITY:
            path = transform_path(path, matrix)

        entries.append(
            ParsedPathEntry(
                path_id=path_id,
                source_tag=local_tag,
                element=element,
                path=path,
            )
        )
        path_id += 1

    return ParsedSvgDocument(tree=tree, root=root, namespace=namespace, entries=entries)


def write_path_back_to_element(entry: ParsedPathEntry, new_path: Path, namespace: str) -> None:
    """Write path data back to source element, converting primitive to <path> if needed."""
    element = entry.element
    if entry.source_tag != "path":
        element.tag = svg_tag(namespace, "path")
        # Remove primitive geometry attributes that no longer apply.
        for attr_name in ("x", "y", "width", "height", "rx", "ry", "r", "cx", "cy", "points"):
            if attr_name in element.attrib:
                del element.attrib[attr_name]

    element.set("d", new_path.d())
    # Transform has already been baked into the path geometry.
    if "transform" in element.attrib:
        del element.attrib["transform"]
