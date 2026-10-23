
import hashlib
import json
from pathlib import Path
from typing import Any
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from app.generation import generate_for_selection, GenerationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.models import (
    DocumentNode,
    DocumentVersion,
    GeneratedTestCase,
    GenerationRun,
    PinnedSelection,
    SelectionItem,
)
from app.parser import extract_pdf
from app.structure import build_document_tree
from app.versioning import compare_versions, normalize_text


# ---------------------------------------------------------
# PATHS AND CONFIGURATION
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"

ORIGINAL_PDF = DATA_DIR / "ct200_manual.pdf"
UPDATED_PDF = DATA_DIR / "ct200_manual_v2.pdf"
REPORT_PATH = OUTPUT_DIR / "comparison_report.json"


# ---------------------------------------------------------
# FASTAPI APPLICATION
# ---------------------------------------------------------

app = FastAPI(
    title="TRI9T CT-200 Document Intelligence API",
    description=(
        "PDF ingestion, hierarchical document reconstruction, "
        "document version comparison, browsing, and search."
    ),
    version="1.1.0",
)


# ---------------------------------------------------------
# REQUEST SCHEMAS
# ---------------------------------------------------------

class IngestRequest(BaseModel):
    document_name: str = Field(
        default="CT-200 Manual",
        min_length=1,
        max_length=200,
    )
    version_label: str = Field(
        min_length=1,
        max_length=100,
    )
    pdf_path: str = Field(min_length=1)



    
class SelectionItemRequest(BaseModel):
    node_id: int = Field(gt=0)
    version_id: int = Field(gt=0)


class CreateSelectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    items: list[SelectionItemRequest] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_items(self):
        pairs = [
            (item.node_id, item.version_id)
            for item in self.items
        ]

        if len(pairs) != len(set(pairs)):
            raise ValueError(
                "Duplicate node/version pairs are not allowed."
            )

        return self



class GenerateTestCasesRequest(BaseModel):
    """Request to generate QA cases for a saved pinned selection."""

    selection_id: int = Field(gt=0)
    request_key: str = Field(min_length=1, max_length=255)
    count_per_node: int = Field(default=3, ge=3, le=5)


# ---------------------------------------------------------
# GENERAL HELPERS
# ---------------------------------------------------------

def _sha256(text: str) -> str:
    """Return a stable SHA-256 hash of normalized text."""
    return hashlib.sha256(
        normalize_text(text).encode("utf-8")
    ).hexdigest()


def _node_value(
    node: Any,
    key: str,
    default: Any = None,
) -> Any:
    """Read a value from a dictionary or an object."""
    if isinstance(node, dict):
        return node.get(key, default)

    return getattr(node, key, default)


def _resolve_version_pdf(version: DocumentVersion) -> Path:
    """Resolve the original PDF path recorded during ingestion."""
    metadata = version.metadata_json or {}

    recorded_path = metadata.get("absolute_source_path")

    if recorded_path:
        candidate = Path(recorded_path)
        if candidate.is_file():
            return candidate

    candidate = DATA_DIR / version.source_filename

    if candidate.is_file():
        return candidate

    raise HTTPException(
        status_code=404,
        detail=(
            f"Source PDF for version '{version.version_label}' "
            "could not be found."
        ),
    )


def _serialize_node(
    node: DocumentNode,
    include_children: bool = False,
) -> dict:
    """Convert a database node into a JSON-serializable dictionary."""

    result = {
        "id": node.id,
        "version_id": node.version_id,
        "logical_id": node.logical_id,
        "node_key": node.node_key,
        "title": node.title,
        "node_type": node.node_type,
        "section_number": node.section_number,
        "level": node.level,
        "body_text": node.body_text,
        "content_hash": node.content_hash,
        "parent_id": node.parent_id,
        "ordinal": node.ordinal,
        "page_number": node.page_number,
        "source_metadata": node.source_metadata or {},
        "warnings": node.warnings or [],
    }

    if include_children:
        result["children"] = [
            _serialize_node(child, include_children=True)
            for child in sorted(
                node.children,
                key=lambda item: item.ordinal,
            )
        ]

    return result


# ---------------------------------------------------------
# HIERARCHICAL TREE -> DATABASE
# ---------------------------------------------------------

def _tree_to_database(
    db: Session,
    version: DocumentVersion,
    tree: Any,
) -> int:
    """
    Persist the complete document tree.

    build_document_tree() returns a wrapper dictionary similar to:

    {
        "document_id": "...",
        "version": "v1",
        "root": {...},
        "node_count": 30
    }

    This function unwraps the root and recursively saves every
    nested section, paragraph, table, and other supported node.
    """

    if isinstance(tree, dict) and isinstance(tree.get("root"), dict):
        root = tree["root"]
    else:
        root = tree

    if not isinstance(root, dict):
        raise ValueError(
            "The document tree does not contain a valid root node."
        )

    records: list[tuple[DocumentNode, str | None]] = []
    source_to_record: dict[str, DocumentNode] = {}

    def visit(
        node: dict,
        parent_source_id: str | None = None,
    ) -> None:
        if not isinstance(node, dict):
            return

        source_id = str(
            node.get("id") or f"node-{len(records)}"
        )

        body = str(node.get("body_text") or "")
        title = str(
            node.get("heading")
            or node.get("title")
            or "Untitled"
        )

        section_number = node.get("numbering")
        node_type = str(node.get("type") or "section")

        level_value = node.get("level", 0)

        try:
            level = int(level_value)
        except (TypeError, ValueError):
            level = 0

        page_numbers = node.get("page_numbers") or []

        page_number = (
            page_numbers[0]
            if isinstance(page_numbers, list) and page_numbers
            else None
        )

        # Preserve extracted content and metadata, including tables.
        metadata = {
            "source_id": source_id,
            "source_blocks": node.get("source_blocks", []),
            "page_numbers": page_numbers,
            "rows": node.get("rows", []),
            "row_count": node.get("row_count"),
            "column_count": node.get("column_count"),
            "bbox": node.get("bbox"),
        }

        content_hash = str(
            node.get("content_hash") or _sha256(body)
        )

        # Preliminary logical identity:
        # numbered sections use their section number;
        # unnumbered nodes use their type and title.
        #
        # This is a useful first-pass mapping, not a guarantee
        # of perfect semantic identity across document versions.
        if section_number:
            logical_id = f"section:{section_number}"
        else:
            logical_id = (
                f"{node_type}:{_sha256(title)[:20]}"
            )

        record = DocumentNode(
            version_id=version.id,
            logical_id=logical_id,
            node_key=source_id,
            title=title,
            node_type=node_type,
            section_number=(
                str(section_number)
                if section_number is not None
                else None
            ),
            level=level,
            body_text=body,
            content_hash=content_hash,
            parent_id=None,
            ordinal=len(records),
            page_number=page_number,
            source_metadata=metadata,
            warnings=node.get("warnings", []) or [],
        )

        records.append((record, parent_source_id))
        source_to_record[source_id] = record

        children = node.get("children") or []

        if isinstance(children, list):
            for child in children:
                visit(child, source_id)

    visit(root)

    if not records:
        raise ValueError(
            "No document nodes were produced from the parsed PDF."
        )

    # Add all nodes first so each record receives a database ID.
    db.add_all([record for record, _ in records])
    db.flush()

    # Set parent IDs after all records have database IDs.
    for record, parent_source_id in records:
        if parent_source_id is None:
            continue

        parent_record = source_to_record.get(parent_source_id)

        if parent_record is not None:
            record.parent_id = parent_record.id

    db.flush()

    return len(records)


# ---------------------------------------------------------
# APPLICATION STARTUP
# ---------------------------------------------------------

@app.on_event("startup")
def startup() -> None:
    """Create database tables if they do not exist."""
    init_db()


# ---------------------------------------------------------
# BASIC ENDPOINTS
# ---------------------------------------------------------

@app.get("/")
def root():
    return {
        "project": "TRI9T CT-200 Document Intelligence",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "TRI9T CT-200 Document Intelligence API",
    }


# ---------------------------------------------------------
# DOCUMENT INGESTION
# ---------------------------------------------------------

@app.post("/documents/ingest")
def ingest_document(
    request: IngestRequest,
    db: Session = Depends(get_db),
):
    """
    Extract PDF content, reconstruct the document hierarchy,
    and save all nodes into the database.

    If a previous ingestion for the same version label contains
    only one node, it is treated as an incomplete ingestion and
    rebuilt. A complete existing ingestion is left unchanged.
    """

    pdf_path = Path(request.pdf_path).expanduser().resolve()

    if not pdf_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"PDF file not found: {pdf_path}",
        )

    if pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(
            status_code=422,
            detail="The supplied file must be a PDF.",
        )

    try:
        pages = extract_pdf(str(pdf_path))
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"PDF extraction failed: {exc}",
        ) from exc

    if not pages:
        raise HTTPException(
            status_code=422,
            detail="The PDF parser did not return any pages.",
        )

    source_text = "\n".join(
        page.get("text", "") for page in pages
    )
    source_hash = _sha256(source_text)

    existing = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_name == request.document_name,
            DocumentVersion.version_label == request.version_label,
        )
    )

    if existing is not None:
        if existing.source_hash != source_hash:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This document/version label already exists "
                    "with different source content. Use a new "
                    "version label."
                ),
            )

        existing_node_count = len(existing.nodes)

        # Return immediately if the version appears completely
        # ingested. A one-node record is considered incomplete
        # for this project because the manuals contain many nodes.
        if existing_node_count > 1:
            return {
                "message": "This document version is already ingested",
                "version_id": existing.id,
                "document_name": existing.document_name,
                "version_label": existing.version_label,
                "page_count": existing.page_count,
                "node_count": existing_node_count,
                "source_hash": existing.source_hash,
                "ocr_implemented": False,
            }

        # Remove an incomplete previous ingestion before rebuilding.
        try:
            for old_node in list(existing.nodes):
                db.delete(old_node)

            db.flush()
            db.delete(existing)
            db.flush()
        except Exception as exc:
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail=(
                    "Could not remove the incomplete previous "
                    f"ingestion: {exc}"
                ),
            ) from exc

    try:
        tree = build_document_tree(
            pages,
            document_title=request.document_name,
            version=request.version_label,
        )

        version = DocumentVersion(
            document_name=request.document_name,
            version_label=request.version_label,
            source_filename=pdf_path.name,
            source_hash=source_hash,
            page_count=len(pages),
            metadata_json={
                "absolute_source_path": str(pdf_path),
                "extraction_method": (
                    "PyMuPDF text and table extraction"
                ),
                "ocr_implemented": False,
                "pages_needing_ocr": [
                    page.get("page")
                    for page in pages
                    if page.get("needs_ocr")
                ],
            },
        )

        db.add(version)
        db.flush()

        node_count = _tree_to_database(
            db=db,
            version=version,
            tree=tree,
        )

        db.commit()
        db.refresh(version)

    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Document ingestion failed: {exc}",
        ) from exc

    return {
        "message": "Document ingested successfully",
        "version_id": version.id,
        "document_name": version.document_name,
        "version_label": version.version_label,
        "page_count": version.page_count,
        "node_count": node_count,
        "source_hash": version.source_hash,
        "ocr_implemented": False,
        "note": (
            "OCR is not implemented. Pages that may need OCR "
            "are flagged by the parser."
        ),
    }


# ---------------------------------------------------------
# LIST DOCUMENT VERSIONS
# ---------------------------------------------------------

@app.get("/documents")
def list_documents(
    db: Session = Depends(get_db),
):
    versions = db.scalars(
        select(DocumentVersion).order_by(DocumentVersion.id)
    ).all()

    results = []

    for version in versions:
        results.append(
            {
                "version_id": version.id,
                "document_name": version.document_name,
                "version_label": version.version_label,
                "source_filename": version.source_filename,
                "source_hash": version.source_hash,
                "page_count": version.page_count,
                "node_count": len(version.nodes),
                "created_at": (
                    version.created_at.isoformat()
                    if version.created_at
                    else None
                ),
            }
        )

    return results


# ---------------------------------------------------------
# GET COMPLETE DOCUMENT TREE
# ---------------------------------------------------------

@app.get("/documents/{version_id}/tree")
def get_document_tree(
    version_id: int,
    db: Session = Depends(get_db),
):
    version = db.get(DocumentVersion, version_id)

    if version is None:
        raise HTTPException(
            status_code=404,
            detail="Document version not found",
        )

    roots = db.scalars(
        select(DocumentNode)
        .where(
            DocumentNode.version_id == version_id,
            DocumentNode.parent_id.is_(None),
        )
        .order_by(DocumentNode.ordinal)
    ).all()

    return {
        "version_id": version.id,
        "document_name": version.document_name,
        "version_label": version.version_label,
        "page_count": version.page_count,
        "node_count": len(version.nodes),
        "tree": [
            _serialize_node(node, include_children=True)
            for node in roots
        ],
    }


# ---------------------------------------------------------
# LIST TOP-LEVEL SECTIONS
# ---------------------------------------------------------

@app.get("/documents/{version_id}/sections")
def list_top_level_sections(
    version_id: int,
    db: Session = Depends(get_db),
):
    version = db.get(DocumentVersion, version_id)

    if version is None:
        raise HTTPException(
            status_code=404,
            detail="Document version not found",
        )

    # Only return first-level sections, excluding the document root.
    nodes = db.scalars(
        select(DocumentNode)
        .where(
            DocumentNode.version_id == version_id,
            DocumentNode.parent_id.is_not(None),
            DocumentNode.level <= 1,
            DocumentNode.node_type != "document",
        )
        .order_by(DocumentNode.ordinal)
    ).all()

    return {
        "version_id": version.id,
        "version_label": version.version_label,
        "count": len(nodes),
        "sections": [
            _serialize_node(node)
            for node in nodes
        ],
    }


# ---------------------------------------------------------
# GET NODE BY DATABASE ID
# ---------------------------------------------------------

@app.get("/nodes/{node_id}")
def get_node(
    node_id: int,
    db: Session = Depends(get_db),
):
    node = db.get(DocumentNode, node_id)

    if node is None:
        raise HTTPException(
            status_code=404,
            detail="Node not found",
        )

    return _serialize_node(
        node,
        include_children=True,
    )


# ---------------------------------------------------------
# SEARCH DOCUMENT NODES
# ---------------------------------------------------------

@app.get("/search")
def search_nodes(
    q: str = Query(min_length=1, max_length=500),
    version_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    search_term = q.strip()

    if not search_term:
        raise HTTPException(
            status_code=422,
            detail="Search query cannot be blank.",
        )

    query = select(DocumentNode).where(
        (
            DocumentNode.title.ilike(f"%{search_term}%")
        )
        |
        (
            DocumentNode.body_text.ilike(f"%{search_term}%")
        )
    )

    if version_id is not None:
        query = query.where(
            DocumentNode.version_id == version_id
        )

    nodes = db.scalars(
        query.order_by(DocumentNode.ordinal).limit(limit)
    ).all()

    return {
        "query": search_term,
        "version_id": version_id,
        "count": len(nodes),
        "results": [
            _serialize_node(node)
            for node in nodes
        ],
    }


# ---------------------------------------------------------
# COMPARE TWO DOCUMENT VERSIONS
# ---------------------------------------------------------

@app.get("/compare")
def compare_documents(
    old_version_id: int,
    new_version_id: int,
    db: Session = Depends(get_db),
):
    old_version = db.get(
        DocumentVersion,
        old_version_id,
    )
    new_version = db.get(
        DocumentVersion,
        new_version_id,
    )

    if old_version is None or new_version is None:
        raise HTTPException(
            status_code=404,
            detail="One or both document versions were not found.",
        )

    if old_version.document_name != new_version.document_name:
        raise HTTPException(
            status_code=400,
            detail=(
                "The versions belong to different documents "
                "and cannot be compared as versions of the same manual."
            ),
        )

    old_pdf_path = _resolve_version_pdf(old_version)
    new_pdf_path = _resolve_version_pdf(new_version)

    try:
        old_pages = extract_pdf(str(old_pdf_path))
        new_pages = extract_pdf(str(new_pdf_path))

        result = compare_versions(
            old_pages,
            new_pages,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Version comparison failed: {exc}",
        ) from exc

    return {
        "document_name": old_version.document_name,
        "old_version": {
            "version_id": old_version.id,
            "version_label": old_version.version_label,
            "page_count": old_version.page_count,
        },
        "new_version": {
            "version_id": new_version.id,
            "version_label": new_version.version_label,
            "page_count": new_version.page_count,
        },
        "comparison": result,
        "limitations": [
            (
                "Section numbering and text similarity are "
                "used as matching signals."
            ),
            (
                "The comparison does not guarantee perfect "
                "semantic identity matching."
            ),
            (
                "OCR is not implemented in this ingestion pipeline."
            ),
        ],
    }


# ---------------------------------------------------------
# COMMAND-LINE COMPARISON REPORT
# ---------------------------------------------------------

def run_cli_comparison():
    """Compare the supplied v1 and v2 PDFs and save a JSON report."""

    for pdf_path in (ORIGINAL_PDF, UPDATED_PDF):
        if not pdf_path.exists():
            print(f"ERROR: PDF not found: {pdf_path}")
            return

    try:
        original_pages = extract_pdf(str(ORIGINAL_PDF))
        updated_pages = extract_pdf(str(UPDATED_PDF))

        result = compare_versions(
            original_pages,
            updated_pages,
        )

        OUTPUT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        report = {
            "project": (
                "TRI9T CT-200 Document Version Comparison"
            ),
            "original_document": ORIGINAL_PDF.name,
            "updated_document": UPDATED_PDF.name,
            "original_pages": len(original_pages),
            "updated_pages": len(updated_pages),
            **result,
        }

        with REPORT_PATH.open(
            "w",
            encoding="utf-8",
        ) as report_file:
            json.dump(
                report,
                report_file,
                indent=4,
                ensure_ascii=False,
            )

        print(
            f"Comparison report saved to: {REPORT_PATH}"
        )

    except Exception as exc:
        print(f"ERROR: Comparison failed: {exc}")


# ---------------------------------------------------------
# VERSION-PINNED SELECTIONS
# ---------------------------------------------------------

def _serialize_selection(selection: PinnedSelection) -> dict:
    """Serialize a selection and its exact version-pinned items."""
    return {
        "selection_id": selection.id,
        "name": selection.name,
        "description": selection.description,
        "created_at": (
            selection.created_at.isoformat()
            if selection.created_at
            else None
        ),
        "items": [
            {
                "selection_item_id": item.id,
                "node_id": item.node_id,
                "version_id": item.version_id,
                "version_label": item.version.version_label,
                "document_name": item.version.document_name,
                "node_title": item.node.title,
                "node_type": item.node.node_type,
                "content_hash": item.content_hash,
            }
            for item in selection.items
        ],
    }


@app.post("/selections", status_code=201)
def create_selection(
    request: CreateSelectionRequest,
    db: Session = Depends(get_db),
):
    """Create a named selection of exact node/version pairs."""

    selection = PinnedSelection(
        name=request.name.strip(),
        description=request.description.strip(),
    )

    if not selection.name:
        raise HTTPException(
            status_code=422,
            detail="Selection name cannot be blank.",
        )

    # Validate every node/version pair before saving anything.
    validated_items = []

    for requested_item in request.items:
        node = db.get(DocumentNode, requested_item.node_id)
        version = db.get(DocumentVersion, requested_item.version_id)

        if node is None:
            raise HTTPException(
                status_code=404,
                detail=f"Node {requested_item.node_id} not found.",
            )

        if version is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Document version {requested_item.version_id} "
                    "not found."
                ),
            )

        if node.version_id != version.id:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Node {node.id} belongs to version "
                    f"{node.version_id}, not version {version.id}."
                ),
            )

        validated_items.append((node, version))

    try:
        db.add(selection)
        db.flush()

        for ordinal, (node, version) in enumerate(validated_items):
            db.add(
                SelectionItem(
                    selection_id=selection.id,
                    node_id=node.id,
                    version_id=version.id,
                    content_hash=node.content_hash,
                    ordinal=ordinal,
                )
            )

        db.commit()
        db.refresh(selection)

        return _serialize_selection(selection)

    except Exception:
        db.rollback()
        raise


@app.get("/selections")
def list_selections(
    db: Session = Depends(get_db),
):
    """List saved selections."""
    selections = db.scalars(
        select(PinnedSelection).order_by(PinnedSelection.id)
    ).all()

    return {
        "count": len(selections),
        "selections": [
            _serialize_selection(selection)
            for selection in selections
        ],
    }


@app.get("/selections/{selection_id}")
def get_selection(
    selection_id: int,
    db: Session = Depends(get_db),
):
    """Retrieve a saved selection with its pinned versions."""
    selection = db.get(PinnedSelection, selection_id)

    if selection is None:
        raise HTTPException(
            status_code=404,
            detail="Selection not found.",
        )

    return _serialize_selection(selection)


# ---------------------------------------------------------
# GROQ-POWERED QA TEST-CASE GENERATION
# ---------------------------------------------------------

@app.post("/generate")
def generate_test_cases(
    request: GenerateTestCasesRequest,
    db: Session = Depends(get_db),
):
    """Generate and persist QA cases for a version-pinned selection."""
    try:
        return generate_for_selection(
            db=db,
            selection_id=request.selection_id,
            request_key=request.request_key.strip(),
            count_per_node=request.count_per_node,
        )
    except GenerationError as exc:
        message = str(exc)
        lower_message = message.lower()

        if "not found" in lower_message:
            status_code = 404
        elif (
            "request_key" in lower_message
            or "already" in lower_message
            or "different request" in lower_message
        ):
            status_code = 409
        elif "missing" in lower_message or "unsupported llm_provider" in lower_message:
            status_code = 503
        else:
            status_code = 400

        raise HTTPException(status_code=status_code, detail=message) from exc


# ---------------------------------------------------------
# GENERATED TEST-CASE RETRIEVAL AND RETRIEVAL-TIME STALENESS
# ---------------------------------------------------------

def _check_test_case_staleness(
    db: Session,
    test_case: GeneratedTestCase,
) -> dict[str, Any]:
    """Compare the test case's pinned source with its latest counterpart.

    A newer document version does not automatically make a test case stale.
    It is marked stale when the matched logical node's content has changed.
    If a corresponding node cannot be found, the result is conservatively
    marked stale because its impact cannot be verified safely.
    """
    original_node = db.get(DocumentNode, test_case.node_id)
    original_version = db.get(DocumentVersion, test_case.version_id)

    if original_node is None or original_version is None:
        reason = "The original source node or version could not be found."
        test_case.is_stale = True
        test_case.staleness_reason = reason
        return {
            "is_stale": True,
            "staleness_status": "unavailable",
            "content_changed": None,
            "version_changed": None,
            "stored_version_id": test_case.version_id,
            "stored_version_label": (
                original_version.version_label if original_version else None
            ),
            "current_version_id": None,
            "current_version_label": None,
            "current_node_id": None,
            "staleness_reason": reason,
        }

    latest_version = db.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_name == original_version.document_name)
        .order_by(DocumentVersion.created_at.desc(), DocumentVersion.id.desc())
        .limit(1)
    ).first()

    if latest_version is None:
        reason = "No document version is available for comparison."
        test_case.is_stale = True
        test_case.staleness_reason = reason
        return {
            "is_stale": True,
            "staleness_status": "unavailable",
            "content_changed": None,
            "version_changed": None,
            "stored_version_id": original_version.id,
            "stored_version_label": original_version.version_label,
            "current_version_id": None,
            "current_version_label": None,
            "current_node_id": None,
            "staleness_reason": reason,
        }

    latest_node = db.scalars(
        select(DocumentNode)
        .where(
            DocumentNode.version_id == latest_version.id,
            DocumentNode.logical_id == original_node.logical_id,
        )
        .order_by(DocumentNode.ordinal, DocumentNode.id)
        .limit(1)
    ).first()

    version_changed = latest_version.id != test_case.version_id

    if latest_node is None:
        reason = (
            "No matching logical node was found in the latest version; "
            "staleness cannot be ruled out."
        )
        test_case.is_stale = True
        test_case.staleness_reason = reason
        return {
            "is_stale": True,
            "staleness_status": "unmatched",
            "content_changed": None,
            "version_changed": version_changed,
            "stored_version_id": original_version.id,
            "stored_version_label": original_version.version_label,
            "current_version_id": latest_version.id,
            "current_version_label": latest_version.version_label,
            "current_node_id": None,
            "staleness_reason": reason,
        }

    content_changed = latest_node.content_hash != test_case.source_content_hash
    is_stale = content_changed
    if content_changed:
        reason = "The corresponding source node's content changed in the latest version."
        status = "stale"
    elif version_changed:
        reason = "The document version changed, but the matched source content is unchanged."
        status = "current_content_version_changed"
    else:
        reason = "The source content matches the version used for generation."
        status = "current"

    # Keep the stored summary fields current, but recalculate this on every read.
    test_case.is_stale = is_stale
    test_case.staleness_reason = reason

    return {
        "is_stale": is_stale,
        "staleness_status": status,
        "content_changed": content_changed,
        "version_changed": version_changed,
        "stored_version_id": original_version.id,
        "stored_version_label": original_version.version_label,
        "current_version_id": latest_version.id,
        "current_version_label": latest_version.version_label,
        "current_node_id": latest_node.id,
        "staleness_reason": reason,
    }


def _serialize_generated_test_case(
    db: Session,
    test_case: GeneratedTestCase,
) -> dict[str, Any]:
    staleness = _check_test_case_staleness(db, test_case)
    return {
        "test_case_id": test_case.id,
        "generation_run_id": test_case.generation_run_id,
        "selection_item_id": test_case.selection_item_id,
        "node_id": test_case.node_id,
        "version_id": test_case.version_id,
        "test_type": test_case.test_type,
        "title": test_case.title,
        "steps": test_case.steps,
        "expected_result": test_case.expected_result,
        "source_content_hash": test_case.source_content_hash,
        "created_at": test_case.created_at.isoformat() if test_case.created_at else None,
        "staleness": staleness,
    }


def _get_generation_run_or_404(db: Session, run_id: int) -> GenerationRun:
    run = db.get(GenerationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Generation run not found.")
    return run


@app.get("/generation-runs/{run_id}")
def get_generation_run(
    run_id: int,
    db: Session = Depends(get_db),
):
    """Retrieve a generation run and dynamically recheck its test cases."""
    run = _get_generation_run_or_404(db, run_id)
    cases = db.scalars(
        select(GeneratedTestCase)
        .where(GeneratedTestCase.generation_run_id == run.id)
        .order_by(GeneratedTestCase.id)
    ).all()

    response = {
        "generation_run_id": run.id,
        "request_key": run.request_key,
        "selection_id": run.selection_id,
        "status": run.status,
        "provider": run.provider,
        "model_name": run.model_name,
        "prompt_version": run.prompt_version,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error_message": run.error_message,
        "test_case_count": len(cases),
        "test_cases": [
            _serialize_generated_test_case(db, case) for case in cases
        ],
    }
    db.commit()
    return response


@app.get("/generation-runs/{run_id}/test-cases")
def get_generation_run_test_cases(
    run_id: int,
    db: Session = Depends(get_db),
):
    """Retrieve saved test cases with retrieval-time staleness information."""
    run = _get_generation_run_or_404(db, run_id)
    cases = db.scalars(
        select(GeneratedTestCase)
        .where(GeneratedTestCase.generation_run_id == run.id)
        .order_by(GeneratedTestCase.id)
    ).all()

    response_cases = [
        _serialize_generated_test_case(db, case) for case in cases
    ]
    db.commit()
    return {
        "generation_run_id": run.id,
        "selection_id": run.selection_id,
        "status": run.status,
        "count": len(response_cases),
        "stale_count": sum(
            1 for case in response_cases if case["staleness"]["is_stale"]
        ),
        "test_cases": response_cases,
    }

if __name__ == "__main__":
    run_cli_comparison()
