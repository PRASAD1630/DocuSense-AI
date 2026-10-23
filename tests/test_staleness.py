
from app.versioning import calculate_hash
from app.staleness import check_staleness


def test_source_unchanged_is_not_stale():
    source = "Battery life is 300 cycles."
    source_hash = calculate_hash(source)

    result = check_staleness(
        source_text=source,
        stored_source_hash=source_hash,
        current_version="1",
        stored_version="1",
    )

    assert result["is_stale"] is False
    assert result["content_changed"] is False
    assert result["version_changed"] is False


def test_changed_source_is_stale():
    old_source = "Battery life is 300 cycles."
    new_source = "Battery life is 250 cycles."

    result = check_staleness(
        source_text=new_source,
        stored_source_hash=calculate_hash(old_source),
        current_version="2",
        stored_version="1",
    )

    assert result["is_stale"] is True
    assert result["content_changed"] is True
    assert result["version_changed"] is True


def test_version_change_is_stale_even_if_content_matches():
    source = "Battery life is 300 cycles."
    source_hash = calculate_hash(source)

    result = check_staleness(
        source_text=source,
        stored_source_hash=source_hash,
        current_version="2",
        stored_version="1",
    )

    assert result["is_stale"] is True
    assert result["content_changed"] is False
    assert result["version_changed"] is True
