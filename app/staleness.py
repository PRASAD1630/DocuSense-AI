
from app.versioning import calculate_hash


def check_staleness(
    source_text: str,
    stored_source_hash: str,
    current_version: str,
    stored_version: str,
) -> dict:
    """
    Check whether a generated QA item is still current.

    The stored hash represents the source text used when the
    QA item was generated.
    """
    current_hash = calculate_hash(source_text)
    content_changed = current_hash != stored_source_hash
    version_changed = current_version != stored_version

    return {
        "is_stale": content_changed or version_changed,
        "content_changed": content_changed,
        "version_changed": version_changed,
        "stored_version": stored_version,
        "current_version": current_version,
        "stored_source_hash": stored_source_hash,
        "current_source_hash": current_hash,
    }
