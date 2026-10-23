
from app.structure import build_document_tree, flatten_tree


def make_heading(text, y=30, font_size=14):
    return {
        "text": text,
        "bbox": [50, y, 350, y + 20],
        "max_font_size": font_size,
        "lines": [
            {
                "spans": [
                    {"text": text, "size": font_size}
                ]
            }
        ],
    }


def make_table(rows, y=70, table_index=0):
    return {
        "table_index": table_index,
        "bbox": [50, y, 400, y + 60],
        "rows": rows,
        "row_count": len(rows),
        "column_count": max((len(row) for row in rows), default=0),
        "warnings": [],
    }


def test_nested_section_uses_correct_parent():
    pages = [
        {
            "page": 1,
            "blocks": [
                make_heading("1 Device Overview", 20),
                make_heading("1.1 Intended Use", 50),
                make_heading("1.1.1 Clinical Use", 80),
            ],
            "tables": [],
        }
    ]

    document = build_document_tree(pages, version="v1")
    nodes = flatten_tree(document["root"])
    sections = {node.get("numbering"): node for node in nodes}

    assert sections["1.1"]["parent_id"] == sections["1"]["id"]
    assert sections["1.1.1"]["parent_id"] == sections["1.1"]["id"]


def test_missing_parent_is_flagged():
    pages = [
        {
            "page": 1,
            "blocks": [
                make_heading("2.1.1.1 Battery Life Under Typical Use")
            ],
            "tables": [],
        }
    ]

    document = build_document_tree(pages, version="v1")
    nodes = flatten_tree(document["root"])

    section = next(
        node for node in nodes
        if node.get("numbering") == "2.1.1.1"
    )

    assert section["parent_id"] == document["root"]["id"]
    assert any("Missing expected parent" in warning for warning in section["warnings"])


def test_duplicate_headings_have_distinct_ids():
    pages = [
        {
            "page": 1,
            "blocks": [
                make_heading("1 Error Codes", 20),
                make_heading("2 Error Codes", 50),
            ],
            "tables": [],
        }
    ]

    document = build_document_tree(pages, version="v1")
    nodes = flatten_tree(document["root"])
    sections = [node for node in nodes if node["type"] == "section"]

    assert len(sections) == 2
    assert sections[0]["id"] != sections[1]["id"]


def test_source_reading_order_is_preserved():
    pages = [
        {
            "page": 1,
            "blocks": [
                make_heading("3 Device Operation", 20),
                make_heading("3.4 Auto Shutoff", 50),
                make_heading("3.3 Result Display and Classification", 80),
            ],
            "tables": [],
        }
    ]

    document = build_document_tree(pages, version="v1")
    nodes = flatten_tree(document["root"])
    sections = [
        node for node in nodes
        if node["type"] == "section"
        and node.get("numbering", "").startswith("3.")
    ]

    assert [node["numbering"] for node in sections] == ["3.4", "3.3"]


def test_content_hash_is_present():
    pages = [
        {
            "page": 1,
            "blocks": [make_heading("1 Device Overview")],
            "tables": [],
        }
    ]

    document = build_document_tree(pages, version="v1")
    nodes = flatten_tree(document["root"])

    assert all(
        isinstance(node["content_hash"], str)
        and len(node["content_hash"]) == 64
        for node in nodes
    )


def test_parent_child_relationships_are_consistent():
    pages = [
        {
            "page": 1,
            "blocks": [
                make_heading("1 Device Overview", 20),
                make_heading("1.1 Intended Use", 50),
            ],
            "tables": [],
        }
    ]

    document = build_document_tree(pages, version="v1")
    nodes = flatten_tree(document["root"])

    for parent in nodes:
        for child in parent["children"]:
            assert child["parent_id"] == parent["id"]


def test_table_nodes_are_preserved_in_tree():
    pages = [
        {
            "page": 1,
            "blocks": [make_heading("2 General Specifications", 30)],
            "tables": [
                make_table(
                    [
                        ["Parameter", "Value"],
                        ["Pressure range", "0-299 mmHg"],
                    ],
                    y=70,
                )
            ],
        }
    ]

    document = build_document_tree(pages, version="v1")
    nodes = flatten_tree(document["root"])
    tables = [node for node in nodes if node["type"] == "table"]

    assert len(tables) == 1
    assert tables[0]["rows"] == [
        ["Parameter", "Value"],
        ["Pressure range", "0-299 mmHg"],
    ]


def test_table_is_attached_to_current_section():
    pages = [
        {
            "page": 1,
            "blocks": [make_heading("2 General Specifications", 30)],
            "tables": [
                make_table([["Parameter", "Value"]], y=70)
            ],
        }
    ]

    document = build_document_tree(pages, version="v1")
    nodes = flatten_tree(document["root"])

    section = next(
        node for node in nodes
        if node.get("numbering") == "2"
    )
    table = next(
        node for node in nodes
        if node["type"] == "table"
    )

    assert table["parent_id"] == section["id"]
    assert table in section["children"]


def test_table_nodes_have_content_hashes():
    pages = [
        {
            "page": 1,
            "blocks": [make_heading("2 General Specifications", 30)],
            "tables": [
                make_table([["Parameter", "Value"]], y=70)
            ],
        }
    ]

    document = build_document_tree(pages, version="v1")
    nodes = flatten_tree(document["root"])
    table = next(node for node in nodes if node["type"] == "table")

    assert isinstance(table["content_hash"], str)
    assert len(table["content_hash"]) == 64
