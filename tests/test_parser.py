
from pathlib import Path

from app.parser import extract_pdf


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def test_original_manual_exists():
    assert (DATA_DIR / "ct200_manual.pdf").exists()


def test_updated_manual_exists():
    assert (DATA_DIR / "ct200_manual_v2.pdf").exists()


def test_original_manual_text_extraction():
    pdf_path = DATA_DIR / "ct200_manual.pdf"
    pages = extract_pdf(str(pdf_path))

    assert len(pages) == 6
    assert pages[0]["page"] == 1
    assert "CardioTrack CT-200" in pages[0]["text"]


def test_updated_manual_text_extraction():
    pdf_path = DATA_DIR / "ct200_manual_v2.pdf"
    pages = extract_pdf(str(pdf_path))

    assert len(pages) == 7
    assert pages[0]["page"] == 1
    assert "CardioTrack CT-200" in pages[0]["text"]


def test_extracted_pages_have_expected_fields():
    pages = extract_pdf(str(DATA_DIR / "ct200_manual.pdf"))

    for page in pages:
        assert "page" in page
        assert "text" in page
        assert "has_text" in page
        assert isinstance(page["text"], str)
        assert isinstance(page["has_text"], bool)
