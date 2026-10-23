import os
import pytesseract
from PIL import Image
import pymupdf
# Tesseract OCR executable
pytesseract.pytesseract.tesseract_cmd = (
    r"D:\tri9t-ct200-ai\tesseract.exe"
)

from pathlib import Path

import pymupdf

def extract_page_text_with_ocr(page, dpi=200):
    """
    Extract text from a PDF page using OCR.

    Args:
        page: A PyMuPDF page object.
        dpi: Rendering resolution for OCR.

    Returns:
        Extracted text as a string.
    """
    pix = page.get_pixmap(
        dpi=dpi,
        colorspace=pymupdf.csRGB,
        alpha=False,
    )

    image = Image.frombytes(
        "RGB",
        [pix.width, pix.height],
        pix.samples,
    )

    return pytesseract.image_to_string(
        image,
        lang="eng",
        config="--psm 3",
    ).strip()


def _extract_page_blocks(page) -> list[dict]:
    """Extract text blocks, lines, font metadata, and coordinates."""
    page_dict = page.get_text("dict", sort=True)
    extracted_blocks = []

    for block_index, block in enumerate(page_dict.get("blocks", [])):
        # Image blocks do not contain ordinary text lines.
        if block.get("type") != 0:
            continue

        block_lines = []
        block_text_parts = []
        all_font_sizes = []
        all_font_names = []
        all_flags = []

        for line in block.get("lines", []):
            spans = []
            line_text_parts = []

            for span in line.get("spans", []):
                span_text = span.get("text", "")

                if not span_text.strip():
                    continue

                font_size = span.get("size", 0)
                font_name = span.get("font", "")
                font_flags = span.get("flags", 0)

                spans.append({
                    "text": span_text,
                    "font": font_name,
                    "font_size": font_size,
                    "font_flags": font_flags,
                    "bbox": list(span.get("bbox", [])),
                })

                line_text_parts.append(span_text)
                all_font_sizes.append(font_size)
                all_font_names.append(font_name)
                all_flags.append(font_flags)

            line_text = "".join(line_text_parts).strip()

            if line_text:
                block_lines.append({
                    "text": line_text,
                    "bbox": list(line.get("bbox", [])),
                    "spans": spans,
                })
                block_text_parts.append(line_text)

        block_text = "\n".join(block_text_parts).strip()

        if not block_text:
            continue

        extracted_blocks.append({
            "block_index": block_index,
            "type": "text",
            "text": block_text,
            "bbox": list(block.get("bbox", [])),
            "lines": block_lines,
            "font_sizes": all_font_sizes,
            "font_names": sorted(set(all_font_names)),
            "font_flags": all_flags,
        })

    return extracted_blocks


import re


def _clean_table_cell(value) -> str:
    """Normalize whitespace and known punctuation artifacts in table cells."""
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\u00a0", " ")
    text = text.replace("\u200b", "")

    # Normalize line breaks and repeated whitespace.
    text = re.sub(r"\s+", " ", text)

    # Remove punctuation left at cell boundaries.
    text = text.strip(" \t\r\n,;")

    # Remove isolated commas caused by PDF cell extraction.
    text = re.sub(r"\s+,\s+", " ", text)
    text = re.sub(r"\s+,", ",", text)

    return text.strip(" \t\r\n,;")




def _extract_page_tables(page) -> list[dict]:
    """Detect tables and extract their rows, cells, and coordinates.

    Table detection is heuristic. A missing table in this result does not
    necessarily mean that the page contains no tables.
    """
    extracted_tables = []

    try:
        table_finder = page.find_tables()
        detected_tables = table_finder.tables

    except Exception as error:
        return [{
            "table_index": 0,
            "bbox": None,
            "rows": [],
            "row_count": 0,
            "column_count": 0,
            "warnings": [
                f"Table detection failed: "
                f"{type(error).__name__}: {error}"
            ],
        }]

    for table_index, table in enumerate(detected_tables):
        try:
            raw_rows = table.extract() or []
            rows = []

            for row in raw_rows:
                rows.append([
    _clean_table_cell(cell)
    for cell in row
])
                
            column_count = max(
                (len(row) for row in rows),
                default=0,
            )

            warnings = []

            if not rows:
                warnings.append(
                    "Detected table contains no extractable rows."
                )

            if rows and any(
                len(row) != column_count
                for row in rows
            ):
                warnings.append(
                    "Table rows have inconsistent column counts."
                )

            if rows and any(
                not any(cell.strip() for cell in row)
                for row in rows
            ):
                warnings.append(
                    "Table contains one or more empty rows."
                )

            extracted_tables.append({
                "table_index": table_index,
                "bbox": (
                    list(table.bbox)
                    if table.bbox
                    else None
                ),
                "rows": rows,
                "row_count": len(rows),
                "column_count": column_count,
                "warnings": warnings,
            })

        except Exception as error:
            extracted_tables.append({
                "table_index": table_index,
                "bbox": (
                    list(table.bbox)
                    if table.bbox
                    else None
                ),
                "rows": [],
                "row_count": 0,
                "column_count": 0,
                "warnings": [
                    f"Table extraction failed: "
                    f"{type(error).__name__}: {error}"
                ],
            })

    return extracted_tables


def _detect_page_warnings(
    text: str,
    image_count: int,
    blocks: list[dict],
) -> list[str]:
    """Identify pages that may need additional extraction or OCR review."""
    warnings = []

    if not text.strip():
        if image_count > 0:
            warnings.append(
                "No extractable text; page contains images and may need OCR."
            )
        else:
            warnings.append(
                "No extractable text found on this page."
            )

    elif len(text.strip()) < 40 and image_count > 0:
        warnings.append(
            "Very little extractable text on a page containing images; "
            "check whether OCR is needed."
        )

    if not blocks and image_count > 0:
        warnings.append(
            "Page appears image-based; verify text extraction."
        )

    return warnings



def extract_pdf(pdf_path: str) -> list[dict]:
    """Extract PDF text, layout, tables, and OCR text from scanned pages."""

    path = Path(pdf_path)

    if not path.exists():
        raise FileNotFoundError(
            f"PDF not found: {path.resolve()}"
        )

    if not path.is_file():
        raise ValueError(
            f"Expected a PDF file, got: {path.resolve()}"
        )

    pages = []

    try:
        with pymupdf.open(path) as document:
            if document.is_encrypted and not document.is_authenticated:
                raise ValueError(
                    f"PDF is password-protected and cannot be read: "
                    f"{path.name}"
                )

            for page_number, page in enumerate(document, start=1):
                # Extract ordinary PDF text and layout first.
                text = page.get_text("text", sort=True).strip()
                blocks = _extract_page_blocks(page)
                tables = _extract_page_tables(page)

                page_dict = page.get_text("dict")
                image_count = sum(
                    1
                    for block in page_dict.get("blocks", [])
                    if block.get("type") == 1
                )

                ocr_used = False
                ocr_error = None

                # Run OCR only when ordinary extraction gives little text.
                if len(text) < 40:
                    try:
                        ocr_text = extract_page_text_with_ocr(page)

                        if len(ocr_text.strip()) > len(text):
                            text = ocr_text.strip()
                            ocr_used = bool(text)

                            # Represent OCR output as a fallback text block.
                            if ocr_used:
                                blocks = [{
                                    "block_index": 0,
                                    "type": "text",
                                    "text": text,
                                    "bbox": list(page.rect),
                                    "lines": [],
                                    "font_sizes": [],
                                    "font_names": [],
                                    "font_flags": [],
                                    "source": "ocr",
                                }]

                    except Exception as error:
                        ocr_error = (
                            f"OCR failed: {type(error).__name__}: {error}"
                        )

                warnings = _detect_page_warnings(
                    text=text,
                    image_count=image_count,
                    blocks=blocks,
                )

                for table in tables:
                    for table_warning in table.get("warnings", []):
                        warnings.append(
                            f"Table {table['table_index']}: {table_warning}"
                        )

                if ocr_used:
                    warnings.append(
                        "OCR was used; verify extracted text for accuracy."
                    )

                if ocr_error:
                    warnings.append(ocr_error)

                pages.append({
                    "page": page_number,
                    "text": text,
                    "has_text": bool(text),
                    "blocks": blocks,
                    "tables": tables,
                    "image_count": image_count,
                    "warnings": warnings,
                    "needs_ocr": not bool(text.strip()),
                    "ocr_used": ocr_used,
                    "ocr_error": ocr_error,
                })

    except (
        pymupdf.FileDataError,
        pymupdf.FileNotFoundError,
    ) as error:
        raise ValueError(
            f"Unable to read PDF '{path.name}': {error}"
        ) from error

    return pages
