
from app.versioning import calculate_hash, extract_sections, compare_versions


def test_hash_is_deterministic():
    assert calculate_hash("Battery life is 250 cycles.") == calculate_hash(
        "Battery life is 250 cycles."
    )


def test_hash_ignores_extra_whitespace():
    assert calculate_hash("Battery   life\nis 250 cycles.") == calculate_hash(
        "Battery life is 250 cycles."
    )


def test_extract_sections():
    pages = [
        {
            "page": 1,
            "text": (
                "1 Device Overview\n"
                "General device information.\n"
                "1.1 Intended Use\n"
                "For adult users."
            ),
            "has_text": True,
        }
    ]

    sections = extract_sections(pages)

    assert len(sections) == 2
    assert sections[0]["section_number"] == "1"
    assert sections[0]["title"] == "Device Overview"
    assert sections[1]["section_number"] == "1.1"


def test_compare_detects_modified_section():
    old_pages = [
        {
            "page": 1,
            "text": "1 Battery\nBattery life is 300 cycles.",
            "has_text": True,
        }
    ]
    new_pages = [
        {
            "page": 1,
            "text": "1 Battery\nBattery life is 250 cycles.",
            "has_text": True,
        }
    ]

    result = compare_versions(old_pages, new_pages)

    assert any(
        change["status"] == "modified"
        for change in result["changes"]
    )
