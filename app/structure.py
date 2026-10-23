
import hashlib
import json
import re
from typing import Any


NUMBERED_HEADING_PATTERN = re.compile(
    r"^\s*(\d+(?:\.\d+)*)(?:\.)?\s+(.+?)\s*$"
)


def _normalize_text(text: Any) -> str:
    """Normalize text for hashing and comparisons."""
    if text is None:
        return ""

    text = str(text)
    text = text.replace("\u00a0", " ")
    text = text.replace("\u200b", "")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _content_hash(text: str) -> str:
    """Return a SHA-256 hash for normalized text."""
    normalized = _normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _heading_level(numbering: str) -> int:
    """Calculate the level of a numbered heading."""
    return numbering.count(".") + 1


def _expected_parent_number(numbering: str):
    """Return the expected parent section number."""
    if not numbering or "." not in numbering:
        return None

    return numbering.rsplit(".", 1)[0]


def _get_block_text(block: dict) -> str:
    """Read text from common block representations."""
    text = block.get("text", "")

    if text:
        return _normalize_text(text)

    parts = []

    for line in block.get("lines", []):
        for span in line.get("spans", []):
            span_text = span.get("text", "")
            if span_text:
                parts.append(str(span_text))

    return _normalize_text(" ".join(parts))


def _get_font_size(block: dict) -> float:
    """Return the largest available font size for a block."""
    candidates = []

    for key in ("max_font_size", "font_size", "size"):
        value = block.get(key)
        if isinstance(value, (int, float)):
            candidates.append(float(value))

    for line in block.get("lines", []):
        for span in line.get("spans", []):
            value = span.get("size")
            if isinstance(value, (int, float)):
                candidates.append(float(value))

    return max(candidates, default=0.0)


def _is_heading(block: dict) -> bool:
    """Identify numbered section headings."""
    text = _get_block_text(block)

    if not text or len(text) > 180:
        return False

    match = NUMBERED_HEADING_PATTERN.match(text)
    if not match:
        return False

    numbering, title = match.groups()

    if not title.strip():
        return False

    # Numbered headings are recognized using their numbering pattern.
    # Font size provides additional evidence but is not mandatory because
    # synthetic test blocks and some PDFs may lack font metadata.
    if len(title.split()) > 25:
        return False

    if _get_font_size(block) >= 11:
        return True

    # Permit numbered headings with missing font metadata.
    return True


def _make_node_id(
    version: str,
    numbering: str,
    title: str,
    occurrence: int = 1,
) -> str:
    """Create a stable ID within a document version."""
    safe_numbering = numbering.replace(".", "-") if numbering else "un"
    title_hash = _content_hash(title)[:10]

    return (
        f"{version}:section:{safe_numbering}:"
        f"{title_hash}:{occurrence}"
    )


def _get_bbox_y(bbox) -> float:
    """Get the top vertical coordinate of a bounding box."""
    if not bbox or len(bbox) < 2:
        return 0.0

    try:
        return float(bbox[1])
    except (TypeError, ValueError):
        return 0.0


def _point_inside_bbox(point, bbox) -> bool:
    """Check whether a point lies inside a bounding box."""
    if not bbox or len(bbox) < 4:
        return False

    try:
        x0, y0, x1, y1 = map(float, bbox[:4])
        x, y = point
    except (TypeError, ValueError):
        return False

    return x0 <= x <= x1 and y0 <= y <= y1


def _block_is_inside_table(block: dict, tables: list) -> bool:
    """Determine whether a text block belongs to a detected table."""
    bbox = block.get("bbox")

    if not bbox or len(bbox) < 4:
        return False

    try:
        x0, y0, x1, y1 = map(float, bbox[:4])
    except (TypeError, ValueError):
        return False

    center = ((x0 + x1) / 2, (y0 + y1) / 2)

    for table in tables:
        if _point_inside_bbox(center, table.get("bbox")):
            return True

    return False


def _table_body_text(rows: list) -> str:
    """Create a readable text representation of table rows."""
    row_strings = []

    for row in rows or []:
        cells = [_normalize_text(cell) for cell in row]
        row_strings.append(" | ".join(cells))

    return "\n".join(row_strings)


def _make_table_node(
    table: dict,
    page_number: int,
    version: str,
    parent: dict,
) -> dict:
    """Convert an extracted table into a tree node."""
    rows = table.get("rows", [])
    table_index = table.get("table_index", 0)
    table_text = _table_body_text(rows)
    table_hash = _content_hash(table_text)

    return {
        "id": (
            f"{version}:table:page-{page_number}:"
            f"{table_index}:{table_hash[:12]}"
        ),
        "heading": f"Table {table_index + 1}",
        "numbering": None,
        "level": parent["level"] + 1,
        "type": "table",
        "body_text": table_text,
        "rows": rows,
        "row_count": table.get("row_count", len(rows)),
        "column_count": table.get(
            "column_count",
            max((len(row) for row in rows), default=0),
        ),
        "page_numbers": [page_number],
        "source_blocks": [
            {
                "page": page_number,
                "table_index": table_index,
                "bbox": table.get("bbox"),
            }
        ],
        "content_hash": table_hash,
        "parent_id": parent["id"],
        "children": [],
        "warnings": list(table.get("warnings", [])),
    }


def build_document_tree(
    pages: list,
    document_title: str = None,
    version: str = "v1",
) -> dict:
    """
    Build a hierarchical document tree from extracted PDF pages.

    Tables are inserted into the active section based on their vertical
    position relative to text blocks. Numbered sections are attached to
    their expected parent when available. Missing parents are reported
    rather than invented.
    """
    root = {
        "id": f"{version}:document",
        "heading": document_title or "Document",
        "numbering": None,
        "level": 0,
        "type": "document",
        "body_text": "",
        "page_numbers": [],
        "source_blocks": [],
        "content_hash": "",
        "parent_id": None,
        "children": [],
        "warnings": [],
    }

    all_nodes = [root]
    section_by_number = {}
    heading_occurrences = {}
    current_node = root

    for page_data in pages:
        page_number = page_data.get("page", 1)
        blocks = page_data.get("blocks", [])
        tables = page_data.get("tables", [])

        root["page_numbers"].append(page_number)

        # Combine text blocks and tables into reading-order events.
        events = []

        for block_index, block in enumerate(blocks):
            events.append(
                (
                    _get_bbox_y(block.get("bbox")),
                    1,
                    block_index,
                    "block",
                    block,
                )
            )

        for table_index, table in enumerate(tables):
            events.append(
                (
                    _get_bbox_y(table.get("bbox")),
                    0,
                    table_index,
                    "table",
                    table,
                )
            )

        events.sort(key=lambda item: (item[0], item[1], item[2]))

        for _, _, _, event_type, item in events:
            if event_type == "table":
                table_node = _make_table_node(
                    table=item,
                    page_number=page_number,
                    version=version,
                    parent=current_node,
                )

                current_node["children"].append(table_node)
                all_nodes.append(table_node)
                continue

            block = item

            # Avoid adding table text to the section body when PyMuPDF
            # has also returned the same text as ordinary text blocks.
            if _block_is_inside_table(block, tables):
                continue

            text = _get_block_text(block)
            if not text:
                continue

            source_block = {
                "page": page_number,
                "text": text,
                "bbox": block.get("bbox"),
            }

            if _is_heading(block):
                match = NUMBERED_HEADING_PATTERN.match(text)
                numbering, title = match.groups()

                numbering = numbering.rstrip(".")
                title = title.strip()
                level = _heading_level(numbering)

                occurrence_key = (numbering, title)
                heading_occurrences[occurrence_key] = (
                    heading_occurrences.get(occurrence_key, 0) + 1
                )

                occurrence = heading_occurrences[occurrence_key]

                node = {
                    "id": _make_node_id(
                        version,
                        numbering,
                        title,
                        occurrence,
                    ),
                    "heading": title,
                    "numbering": numbering,
                    "level": level,
                    "type": "section",
                    "body_text": "",
                    "page_numbers": [page_number],
                    "source_blocks": [source_block],
                    "content_hash": "",
                    "parent_id": None,
                    "children": [],
                    "warnings": [],
                }

                expected_parent = _expected_parent_number(numbering)

                if expected_parent is None:
                    parent = root
                else:
                    parent = section_by_number.get(expected_parent)

                    if parent is None:
                        parent = root
                        warning = (
                            f"Missing expected parent section "
                            f"{expected_parent} for section {numbering}; "
                            f"attached to document root."
                        )
                        node["warnings"].append(warning)
                        root["warnings"].append(warning)

                node["parent_id"] = parent["id"]
                parent["children"].append(node)

                all_nodes.append(node)
                section_by_number[numbering] = node
                current_node = node

            else:
                if current_node["body_text"]:
                    current_node["body_text"] += "\n"

                current_node["body_text"] += text
                current_node["source_blocks"].append(source_block)

                if page_number not in current_node["page_numbers"]:
                    current_node["page_numbers"].append(page_number)

    def finalize(node: dict) -> str:
        """Calculate a content hash that includes child content."""
        child_hashes = []

        for child in node["children"]:
            child_hashes.append(finalize(child))

        payload = {
            "heading": node.get("heading", ""),
            "numbering": node.get("numbering"),
            "type": node.get("type"),
            "body_text": _normalize_text(node.get("body_text", "")),
        }

        if node.get("type") == "table":
            payload["rows"] = node.get("rows", [])

        payload["children"] = child_hashes

        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        )

        node["content_hash"] = hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest()

        return node["content_hash"]

    finalize(root)

    return {
        "document_id": root["id"],
        "version": version,
        "root": root,
        "node_count": count_nodes(root),
    }


def count_nodes(root: dict) -> int:
    """Count a tree node and all its descendants."""
    count = 1

    for child in root.get("children", []):
        count += count_nodes(child)

    return count


def flatten_tree(root: dict) -> list:
    """
    Return nodes in depth-first reading order.

    The original node dictionaries are returned, so parent-child
    relationships remain accessible to callers and tests.
    """
    nodes = []

    def visit(node):
        nodes.append(node)

        for child in node.get("children", []):
            visit(child)

    visit(root)
    return nodes


def print_tree(node: dict, indent: int = 0) -> None:
    """Print a readable document tree."""
    prefix = "  " * indent
    print(f"{prefix}- {node['heading']} [{node['type']}]")

    if node["type"] == "table":
        print(
            f"{prefix}  Rows: {node.get('row_count', 0)}, "
            f"Columns: {node.get('column_count', 0)}"
        )

    for warning in node.get("warnings", []):
        print(f"{prefix}  WARNING: {warning}")

    for child in node.get("children", []):
        print_tree(child, indent + 1)


if __name__ == "__main__":
    from pathlib import Path
    from app.parser import extract_pdf

    pdf_files = [
        ("data/ct200_manual.pdf", "v1"),
        ("data/ct200_manual_v2.pdf", "v2"),
    ]

    for pdf_path, version in pdf_files:
        path = Path(pdf_path)

        if not path.exists():
            print(f"File not found: {path}")
            continue

        pages = extract_pdf(str(path))
        document = build_document_tree(
            pages,
            document_title=path.stem.replace("_", " "),
            version=version,
        )

        print("\n" + "=" * 65)
        print(f"File: {path.name}")
        print(f"Version: {version}")
        print(f"Pages: {len(pages)}")
        print(f"Total nodes: {document['node_count']}")
        print_tree(document["root"])
