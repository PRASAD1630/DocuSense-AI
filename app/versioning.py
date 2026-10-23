
import hashlib
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher, unified_diff


# Match numeric values, optionally followed by a technical unit.
NUMBER_PATTERN = re.compile(
    r"(?<!\w)[+-]?\d+(?:\.\d+)?"
    r"(?:\s*(?:mmHg|mm|cm|kg|mg|g|ml|mL|"
    r"seconds?|secs?|minutes?|mins?|hours?|"
    r"cycles?|%|°C|V|mA))?",
    re.IGNORECASE,
)

# Match error codes such as E1, E3, E6.
ERROR_CODE_PATTERN = re.compile(r"\bE\d+\b", re.IGNORECASE)


def normalize_text(text: str) -> str:
    """Normalize Unicode characters and whitespace."""
    text = unicodedata.normalize("NFKC", text)
    return " ".join(text.split())


def calculate_hash(text: str) -> str:
    """Return a deterministic SHA-256 hash of normalized text."""
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract_sections(pages: list[dict]) -> list[dict]:
    """
    Extract numbered sections from PDF pages.

    Supports headings such as:
        1 Device Overview
        1.1 Intended Use
        5. Data Management
        2.1.1.1 Battery Life Under Typical Use
    """
    full_text = "\n".join(page["text"] for page in pages)
    full_text = unicodedata.normalize("NFKC", full_text)
    lines = full_text.splitlines()

    heading_pattern = re.compile(
        r"^\s*(\d+(?:\.\d+)*)(?:\.)?\s+(.+?)\s*$"
    )

    sections = []
    current_section = None

    def save_current_section():
        if current_section is None:
            return

        content = "\n".join(current_section["content_lines"]).strip()

        sections.append({
            "section_number": current_section["section_number"],
            "title": current_section["title"],
            "content": content,
            "content_hash": calculate_hash(content),
        })

    for line in lines:
        normalized_line = unicodedata.normalize("NFKC", line).strip()
        match = heading_pattern.match(normalized_line)

        if match:
            save_current_section()
            current_section = {
                "section_number": match.group(1),
                "title": match.group(2).strip(),
                "content_lines": [],
            }
        elif current_section is not None:
            current_section["content_lines"].append(normalized_line)

    save_current_section()
    return sections


def get_text_diff(old_text: str, new_text: str) -> dict:
    """
    Compare normalized words to reduce noise from PDF line wrapping.
    Also retain a line-based diff for readable context.
    """
    old_normalized = normalize_text(old_text)
    new_normalized = normalize_text(new_text)

    old_words = old_normalized.split()
    new_words = new_normalized.split()

    matcher = SequenceMatcher(
        None, old_words, new_words, autojunk=False
    )

    word_changes = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        word_changes.append({
            "operation": tag,
            "old_text": " ".join(old_words[i1:i2]),
            "new_text": " ".join(new_words[j1:j2]),
        })

    line_diff = list(unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        fromfile="original",
        tofile="updated",
        lineterm="",
    ))

    removed_lines = [
        line[1:] for line in line_diff
        if line.startswith("-") and not line.startswith("---")
    ]

    added_lines = [
        line[1:] for line in line_diff
        if line.startswith("+") and not line.startswith("+++")
    ]

    return {
        "diff": line_diff,
        "removed_lines": removed_lines,
        "added_lines": added_lines,
        "word_changes": word_changes,
    }


def extract_numeric_values(text: str) -> list[str]:
    """Extract numeric values and adjacent units from text."""
    return [
        normalize_text(match.group(0))
        for match in NUMBER_PATTERN.finditer(text)
    ]


def extract_error_codes(text: str) -> list[str]:
    """Extract error codes such as E1, E3, and E6."""
    return [
        code.upper()
        for code in ERROR_CODE_PATTERN.findall(text)
    ]


def compare_occurrences(
    old_values: list[str],
    new_values: list[str],
) -> dict:
    """Compare value occurrences without losing duplicates."""
    old_counter = Counter(old_values)
    new_counter = Counter(new_values)

    removed = list((old_counter - new_counter).elements())
    added = list((new_counter - old_counter).elements())

    return {
        "removed": removed,
        "added": added,
    }


def compare_error_code_changes(
    old_text: str,
    new_text: str,
) -> dict:
    """
    Compare unique error codes and retain occurrence counts.

    The added and removed lists contain each distinct code once.
    Occurrence dictionaries show how often each code appears.
    """
    old_codes = Counter(extract_error_codes(old_text))
    new_codes = Counter(extract_error_codes(new_text))

    return {
        "removed": sorted(set(old_codes) - set(new_codes)),
        "added": sorted(set(new_codes) - set(old_codes)),
        "old_occurrences": dict(sorted(old_codes.items())),
        "new_occurrences": dict(sorted(new_codes.items())),
    }


def detect_sensitive_changes(
    old_text: str,
    new_text: str,
) -> list[str]:
    """
    Return review indicators for numeric values, error codes,
    and selected technical terms.

    These are heuristics, not a definitive safety assessment.
    """
    flags = []

    numeric_changes = compare_occurrences(
        extract_numeric_values(old_text),
        extract_numeric_values(new_text),
    )

    if numeric_changes["removed"] or numeric_changes["added"]:
        flags.append("numeric_values")

    code_changes = compare_error_code_changes(old_text, new_text)

    if code_changes["removed"] or code_changes["added"]:
        flags.append("error_codes")

    keywords = (
        "battery", "pressure", "alarm", "error", "safety",
        "threshold", "deflation", "inflation", "limit",
        "warning", "failure", "temperature",
    )

    old_lower = normalize_text(old_text).lower()
    new_lower = normalize_text(new_text).lower()

    changed_keywords = [
        word for word in keywords
        if (word in old_lower) != (word in new_lower)
    ]

    if changed_keywords:
        flags.append("technical_terms: " + ", ".join(changed_keywords))

    return flags

def classify_review_priority(review_flags: list[str]) -> str:
    """Assign a review priority using detected change indicators.

    This is a heuristic for prioritizing human review, not a
    definitive assessment of device safety or change severity.
    """
    if "numeric_values" in review_flags or "error_codes" in review_flags:
        return "HIGH"

    if any(flag.startswith("technical_terms:") for flag in review_flags):
        return "MEDIUM"

    return "LOW"


def compare_versions(
    old_pages: list[dict],
    new_pages: list[dict],
) -> dict:
    """Compare document sections and provide detailed change information."""
    old_sections = extract_sections(old_pages)
    new_sections = extract_sections(new_pages)

    old_by_number = {
        section["section_number"]: section
        for section in old_sections
    }

    new_by_number = {
        section["section_number"]: section
        for section in new_sections
    }

    changes = []

    # Detect added and modified sections.
    for number, new_section in new_by_number.items():
        old_section = old_by_number.get(number)

        if old_section is None:
            old_content = ""
            new_content = new_section["content"]
            status = "added"

        elif old_section["content_hash"] != new_section["content_hash"]:
            old_content = old_section["content"]
            new_content = new_section["content"]
            status = "modified"

        else:
            continue

        change = {
            "section_number": number,
            "title": new_section["title"],
            "status": status,
            "old_hash": (
                old_section["content_hash"]
                if old_section else None
            ),
            "new_hash": new_section["content_hash"],
            "old_content": old_content if old_section else None,
            "new_content": new_content,
            "diff": get_text_diff(old_content, new_content),
            "numeric_changes": compare_occurrences(
                extract_numeric_values(old_content),
                extract_numeric_values(new_content),
            ),
            "error_code_changes": compare_error_code_changes(
                old_content or "",
                new_content or "",
            ),
            "review_flags": detect_sensitive_changes(
                old_content, new_content
            ),
        }

        if status == "modified":
            change["similarity"] = round(
                SequenceMatcher(
                    None,
                    normalize_text(old_content),
                    normalize_text(new_content),
                    autojunk=False,
                ).ratio(),
                3,
            )

        changes.append(change)

    # Detect removed sections.
    for number, old_section in old_by_number.items():
        if number in new_by_number:
            continue

        old_content = old_section["content"]

        changes.append({
            "section_number": number,
            "title": old_section["title"],
            "status": "removed",
            "old_hash": old_section["content_hash"],
            "new_hash": None,
            "old_content": old_content,
            "new_content": None,
            "diff": get_text_diff(old_content, ""),
            "numeric_changes": compare_occurrences(
                extract_numeric_values(old_content),
                [],
            ),
            "error_code_changes": compare_error_code_changes(
                old_content,
                "",
            ),
            "review_flags": detect_sensitive_changes(
                old_content, ""
            ),
        })

    
    # Assign a review priority to every detected change.
    for change in changes:
        change["review_priority"] = classify_review_priority(
            change.get("review_flags", [])
        )

    return {
        "old_section_count": len(old_sections),
        "new_section_count": len(new_sections),
        "changes": changes,
    }

