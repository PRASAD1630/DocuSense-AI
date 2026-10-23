
from app.parser import extract_pdf
from app.versioning import extract_sections, compare_versions


OLD_PDF = "data/ct200_manual.pdf"
NEW_PDF = "data/ct200_manual_v2.pdf"


def main():
    old_pages = extract_pdf(OLD_PDF)
    new_pages = extract_pdf(NEW_PDF)

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

    result = compare_versions(old_pages, new_pages)

    print("\nDOCUMENT VERSION COMPARISON")
    print("=" * 70)
    print("Original sections:", len(old_sections))
    print("Updated sections:", len(new_sections))

    for change in result["changes"]:
        number = change["section_number"]
        status = change["status"]

        print("\n" + "-" * 70)
        print(f"Section: {number}")
        print(f"Title: {change['title']}")
        print(f"Status: {status}")

        if number in old_by_number:
            print("\nORIGINAL CONTENT:")
            print(old_by_number[number]["content"])

        if number in new_by_number:
            print("\nUPDATED CONTENT:")
            print(new_by_number[number]["content"])


if __name__ == "__main__":
    main()
