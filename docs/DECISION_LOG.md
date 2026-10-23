# DocuSense AI
## Technical Decision Log

This document records key technical decisions made during the development of DocuSense AI, including the rationale, trade-offs, and known limitations.

### Decision 1: Use Python for the application

**Decision:** Implement the application in Python.

**Rationale:** Python provides suitable libraries for PDF processing, REST API development, database integration, automated testing, and LLM integration.

**Trade-off:** Dependency versions and compatibility must be managed carefully across Python environments.

### Decision 2: Use PyMuPDF for PDF extraction

**Decision:** Use PyMuPDF as the primary PDF extraction library.

**Rationale:** It supports text extraction, page-level blocks, document metadata, rendering, and table detection where supported.

**Trade-off:** Complex layouts, scanned documents, and visually arranged content may not produce a perfect semantic structure.

### Decision 3: Add Tesseract OCR as a fallback

**Decision:** Use Tesseract through pytesseract when normal text extraction returns insufficient content.

**Rationale:** Some technical manuals contain scanned pages or image-based text that cannot be extracted reliably through ordinary PDF text extraction.

**Trade-off:** OCR may introduce recognition errors, and the current fallback does not fully reconstruct tables from image-only pages. OCR availability and configuration also depend on the execution environment.

### Decision 4: Represent documents as hierarchical trees

**Decision:** Store document content as nodes with parent-child relationships.

**Rationale:** A hierarchy makes it easier to browse sections, retrieve specific content, pin selections, compare versions, and associate test cases with their source material.

**Trade-off:** Reconstructing the correct hierarchy from PDF layout and numbering conventions is imperfect and may require additional rules for unusual document formats.

### Decision 5: Use content hashes for change detection

**Decision:** Calculate hashes of source content and use them to support version comparison and staleness detection.

**Rationale:** Hashes provide an efficient way to identify exact content changes and preserve source-content traceability.

**Trade-off:** A hash alone cannot identify semantically equivalent content that has been reformatted or rewritten. It must be combined with node matching and other comparison logic.

### Decision 6: Use heuristic node matching across versions

**Decision:** Match sections across document versions using structural identifiers and content similarity.

**Rationale:** This supports comparison when the same section appears in multiple versions and allows the application to identify potentially modified content.

**Trade-off:** Sections that move, change numbering, split into multiple sections, or undergo major rewrites may not be matched reliably. Comparison results should be reviewed when matching confidence is uncertain.

### Decision 7: Use SQLite and SQLAlchemy for persistence

**Decision:** Use SQLite with SQLAlchemy models for document versions, document nodes, pinned selections, generation runs, and generated test cases.

**Rationale:** SQLite is simple to configure locally and is suitable for a prototype that needs persistent data without requiring a separate database server.

**Trade-off:** A server-based database may be more appropriate if the application needs concurrent workloads, multiple application instances, or larger-scale deployment.

### Decision 8: Pin document nodes to specific versions

**Decision:** Store selected document nodes together with their exact document version references.

**Rationale:** Test-case generation should use a defined source context. Pinning avoids silently substituting newer content for the content selected by the user.

**Trade-off:** A pinned selection may refer to an older version. The system therefore needs to evaluate source staleness when generated test cases are retrieved.

### Decision 9: Use a configured Groq-hosted language model

**Decision:** Integrate the Groq API for QA test-case generation.

**Rationale:** It provides access to a language model through an API without requiring the application to host the model locally.

**Trade-off:** Generation depends on network availability, API credentials, provider limits, model availability, and response quality. Credentials must be kept outside the source repository.

### Decision 10: Validate generated test cases

**Decision:** Require structured JSON output and validate the expected test-case count and structure before treating generation as successful.

**Rationale:** Structured output makes generated test cases easier to persist, retrieve, and use in downstream workflows.

**Trade-off:** Valid JSON does not guarantee technically correct, complete, or useful test cases. Human review remains necessary.

### Decision 11: Persist generation runs and source references

**Decision:** Store generation runs and test cases with references to their selected nodes, document versions, and source-content hashes.

**Rationale:** This maintains traceability between the generated QA artifact and the document content used to create it.

**Trade-off:** Additional metadata and persistence logic are required to keep references consistent.

### Decision 12: Make generation requests idempotent

**Decision:** Use a request key and request-content comparison to support duplicate-submission handling.

**Rationale:** Repeated requests with the same key and content should not unnecessarily create duplicate completed generation runs.

**Trade-off:** Clients must manage request keys consistently. Reusing a key with different content must be rejected to prevent ambiguity.

### Decision 13: Evaluate staleness during retrieval

**Decision:** Check generated test cases against the latest available corresponding source content when results are retrieved.

**Rationale:** Source content may change after test cases are generated. Retrieval-time checking helps surface test cases that may need review.

**Trade-off:** The quality of staleness results depends on cross-version node matching and source-content comparison. A stale flag is a review signal, not proof that a test case is invalid.

### Decision 14: Use FastAPI for the REST interface

**Decision:** Expose document operations and generation workflows through FastAPI endpoints.

**Rationale:** This provides a modular interface for ingestion, search, comparison, selection management, generation, and retrieval. Swagger UI also supports interactive API testing.

**Trade-off:** Input validation, error responses, API documentation, and database transaction behavior must be maintained as the application evolves.

### Decision 15: Use automated tests for core logic

**Decision:** Use pytest to test parsing, hierarchy reconstruction, versioning, and staleness behavior.

**Rationale:** Automated tests help catch regressions while individual modules and API behavior are developed.

**Trade-off:** Unit tests alone cannot cover all PDF layouts, external API failures, database deployment issues, or LLM response variations. Additional integration and edge-case testing is valuable.

### Summary

The overall design prioritizes source traceability, modularity, local reproducibility, and practical version-aware QA generation. The principal trade-offs are the limitations of PDF structure extraction, heuristic cross-version matching, external LLM dependence, and the need for human review of generated test cases.
