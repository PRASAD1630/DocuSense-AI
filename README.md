# TRI9T CT200 — Version-Aware Document Intelligence & QA Test Generation

## Overview

This project implements a document intelligence and QA test generation system for CT200 technical manuals. It processes PDF documents, reconstructs their hierarchical structure, manages document versions, identifies content changes, and generates structured QA test cases using a Large Language Model (LLM).

Generated test cases remain linked to their original document nodes and versions. The system checks whether their source content has changed when the test cases are retrieved, helping users identify potentially outdated tests.

## Key Features

- **PDF ingestion:** Extract text, page blocks, and available table information from PDF manuals.
- **Hierarchical document reconstruction:** Represent document content using nodes, sections, parent-child relationships, and page references.
- **Content hashing:** Calculate hashes to support content integrity checks and change detection.
- **Version management:** Store multiple versions of a document.
- **Version comparison:** Identify potentially added or modified sections across document revisions.
- **Document browsing:** Retrieve document trees, top-level sections, and individual nodes.
- **Search:** Search document content and retrieve relevant nodes.
- **Pinned selections:** Save specific node and version combinations for repeatable QA generation.
- **LLM-based QA generation:** Generate structured test cases using the configured Groq model.
- **Response validation:** Validate generated test case structures before storing results.
- **Duplicate request protection:** Use request keys and request hashes to prevent duplicate completed generation requests.
- **Staleness detection:** Compare stored source content with the latest corresponding node when generated test cases are retrieved.
- **Automated testing:** Use pytest to validate key project components.
- **OCR fallback:** Attempt OCR when a PDF page contains insufficient extractable text.

## Technology Stack

| Component | Technology |
|---|---|
| Programming language | Python |
| API framework | FastAPI |
| Database | SQLite |
| ORM | SQLAlchemy |
| PDF processing | PyMuPDF |
| OCR | Tesseract OCR, pytesseract |
| LLM provider | Groq API |
| Configuration | python-dotenv |
| Testing | pytest |
| API documentation | FastAPI Swagger UI |
| Optional interface | Streamlit |

## Project Structure

```text
tri9t-ct200-ai/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── parser.py
│   ├── structure.py
│   ├── versioning.py
│   ├── staleness.py
│   ├── generation.py
│   ├── check_changes.py
│   └── streamlit_app.py
├── data/
│   ├── ct200_manual.pdf
│   ├── ct200_manual_v2.pdf
│   └── tri9t.db
├── docs/
│   ├── APPROACH.md
│   └── DECISION_LOG.md
├── tests/
│   ├── test_parser.py
│   ├── test_staleness.py
│   ├── test_structure.py
│   └── test_versioning.py
├── outputs/
├── .env
├── .gitignore
├── requirements.txt
├── pytest.ini
└── README.md
```

*Note: The listed files represent the intended project layout. Keep only files and directories that actually exist in your final repository.*

## Prerequisites

Before running the project, ensure you have:

- Python 3.10 or a compatible Python version supported by the installed dependencies.
- pip.
- Tesseract OCR installed and accessible if OCR functionality is required.
- A Groq API key for LLM-based test generation.
- The CT200 PDF files used for ingestion and version comparison.

## Installation

### 1. Clone or open the project

```powershell
git clone <your-repository-url>
cd tri9t-ct200-ai
```

If you already have the project locally, open PowerShell in the project root instead.

### 2. Create a virtual environment

```powershell
python -m venv .venv
```

Activate it on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
```

Replace `your_groq_api_key` with your own key. Never commit the actual API key to Git or include it in the submission archive.

### 5. Configure Tesseract OCR

If Tesseract is not available on your system PATH, configure its executable location in the parser according to your local installation.

For example:

```python
pytesseract.pytesseract.tesseract_cmd = r"C:\Path\To\tesseract.exe"
```

Use the actual path on your computer.

## Running the Application

Start the FastAPI server from the project root:

```powershell
uvicorn app.main:app --reload
```

The API will generally be available at:

- **Base URL:** `http://127.0.0.1:8000`
- **Interactive Swagger documentation:** `http://127.0.0.1:8000/docs`
- **OpenAPI schema:** `http://127.0.0.1:8000/openapi.json`

Use the Swagger interface to inspect request schemas, submit API requests, and view responses.

## API Capabilities

The API provides endpoints for the following workflows. Refer to `/docs` for the exact HTTP methods, request payloads, and response schemas implemented in the current code.

| Capability | Purpose |
|---|---|
| Health check | Check API availability |
| Document ingestion | Process a PDF and store a document version |
| List documents | Browse ingested document versions |
| Document tree | Retrieve the hierarchical representation of a version |
| Section browsing | Retrieve top-level sections |
| Node retrieval | Retrieve an individual document node |
| Search | Find matching document nodes |
| Version comparison | Compare two ingested versions |
| Selection creation | Pin nodes to specific document versions |
| Selection retrieval | Retrieve saved selections and their items |
| Test generation | Generate QA test cases for a selection |
| Generation-run retrieval | Retrieve generation run status and metadata |
| Generated test case retrieval | Retrieve generated test cases and their staleness information |

## Typical Workflow

### Step 1: Ingest document versions

Ingest the original CT200 manual and its revised version through the document ingestion endpoint.

The system extracts content, builds a hierarchical representation, calculates hashes, and stores the resulting document version and nodes.

### Step 2: Browse and search

Use document tree, section browsing, node retrieval, and search endpoints to locate the relevant content.

### Step 3: Compare versions

Compare the original and revised document versions to identify sections that may have changed.

Review the comparison output carefully because structural changes and similar section headings can affect node matching.

### Step 4: Create a pinned selection

Create a selection containing the specific node and version pairs that should be used for QA generation.

This preserves the source context of the generation request.

### Step 5: Generate QA test cases

Submit the selection to the generation endpoint.

The configured Groq model generates structured test cases. The application validates the output and stores successful results with their source references and hashes.

### Step 6: Retrieve generated test cases

Retrieve the generation run and its test cases using the generation run ID.

Review the generated test cases, source references, and staleness information.

### Step 7: Review staleness

The retrieval workflow compares the stored source content hash with the content hash of the latest corresponding node.

- If the corresponding source content has changed, the test case can be marked stale.
- If the source content remains unchanged, a version change alone should not mark the test case stale.
- If the system cannot reliably match the source node, the result should be treated conservatively and reviewed.

## Versioning and Staleness Design

### Content hashes

Content hashes provide a compact way to identify changes in stored source content. They are associated with document nodes and copied into generated test case records to preserve source provenance.

### Version-pinned selections

Each selection item records the node and version used for generation. This makes it possible to identify the exact source context behind generated test cases.

### Retrieval-time validation

Staleness is checked when generated test cases are retrieved. This allows the application to identify potential changes that occurred after generation.

Staleness is not the same as generation failure: a test case can be generated successfully and later become stale if its source content changes.

## LLM Generation and Validation

The generation workflow uses the configured Groq model to produce structured QA test cases.

The workflow includes:

1. Loading the selected source content.
2. Constructing the generation prompt.
3. Requesting structured output from the model.
4. Validating the response structure and required fields.
5. Checking the expected test case count.
6. Persisting successful generation results and source references.
7. Recording generation status and handling failures.

LLM-generated test cases are suggestions and should be reviewed for technical accuracy before being used in a real testing environment.

## Running Tests

From the project root, with the virtual environment activated, run:

```powershell
python -m pytest -q
```

To run an individual test module:

```powershell
python -m pytest tests/test_parser.py -v
python -m pytest tests/test_structure.py -v
python -m pytest tests/test_versioning.py -v
python -m pytest tests/test_staleness.py -v
```

The test suite covers the parser, document structure, versioning, and staleness utilities. API integration behavior should also be checked through Swagger or automated API tests where available.

## Limitations

- PDF extraction quality depends on document layout and formatting.
- OCR output may contain recognition errors and requires verification.
- Reconstructing tables, lists, and complex layouts can be imperfect.
- Cross-version matching relies on structural identifiers and similarity signals, so some matches may require review.
- Staleness accuracy depends on identifying the correct corresponding source node and comparing consistent content hashes.
- LLM-generated test cases may contain incomplete or incorrect assumptions.
- Groq-based generation requires a valid API key, network connectivity, and an available model.
- SQLite is appropriate for local development and small-scale use; larger deployments may require a different database and additional operational controls.

## Security Notes

- Never commit `.env` or API credentials.
- Keep local virtual environments and Python cache files out of version control.
- Avoid exposing the development server publicly without appropriate security controls.
- Review generated test cases before using them for device validation or safety-critical testing.
- Include only permitted PDF files and data in the final submission.

## Future Improvements

Potential improvements include:

- More robust cross-version node identity matching.
- Improved OCR quality checks and extraction confidence reporting.
- More comprehensive automated API integration tests.
- Additional document layout and table reconstruction support.
- Improved test case traceability and impact analysis.
- Production-oriented database configuration, authentication, and logging.

## Conclusion

This project demonstrates a workflow for transforming technical manuals into structured, versioned content and generating traceable QA test cases from selected document nodes. By combining document parsing, persistence, version comparison, LLM output validation, and retrieval-time staleness checks, it provides a foundation for maintaining QA coverage as technical documentation evolves.