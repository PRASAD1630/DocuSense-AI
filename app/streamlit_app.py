
import csv
import io
import json
import tempfile

from pathlib import Path

import streamlit as st

from app.parser import extract_pdf
from app.versioning import compare_versions


# --------------------------------------------------
# PAGE CONFIGURATION
# --------------------------------------------------

st.set_page_config(
    page_title="Tri9T Document Comparison",
    page_icon="📄",
    layout="wide",
)

st.title("CT-200 Document Version Comparison")

st.caption(
    "Compare document versions, inspect section-level changes, "
    "and export structured JSON and CSV reports."
)


# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------

if "comparison_report" not in st.session_state:
    st.session_state["comparison_report"] = None


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def save_uploaded_pdf(uploaded_file, destination: Path) -> Path:
    """Save an uploaded PDF to a temporary path."""
    destination.write_bytes(uploaded_file.getvalue())
    return destination


def build_comparison_report(
    original_file,
    updated_file,
    original_pages,
    updated_pages,
    result,
) -> dict:
    """Build a report containing comparison results and summary counts."""
    changes = result.get("changes", [])

    added = [
        change for change in changes
        if change.get("status") == "added"
    ]

    modified = [
        change for change in changes
        if change.get("status") == "modified"
    ]

    removed = [
        change for change in changes
        if change.get("status") == "removed"
    ]

    return {
        "project": "Tri9T CT-200 Document Version Comparison",
        "original_document": original_file.name,
        "updated_document": updated_file.name,
        "original_pages": len(original_pages),
        "updated_pages": len(updated_pages),
        **result,
        "summary": {
            "added_sections": len(added),
            "modified_sections": len(modified),
            "removed_sections": len(removed),
            "total_changes": len(changes),
            "high_priority_changes": sum(
                1 for change in changes
                if change.get("review_priority") == "HIGH"
            ),
        },
    }


def create_csv_report(report: dict) -> str:
    """Convert section-level comparison results to CSV."""
    csv_buffer = io.StringIO()

    csv_columns = [
        "section_number",
        "title",
        "status",
        "review_priority",
        "similarity",
        "numeric_changes",
        "error_code_changes",
        "review_flags",
        "old_content",
        "new_content",
    ]

    writer = csv.DictWriter(
        csv_buffer,
        fieldnames=csv_columns,
        extrasaction="ignore",
    )

    writer.writeheader()

    for change in report.get("changes", []):
        row = {
            key: change.get(key, "")
            for key in csv_columns
        }

        # Convert nested data structures into CSV-compatible strings.
        for key in (
            "numeric_changes",
            "error_code_changes",
            "review_flags",
        ):
            row[key] = json.dumps(
                change.get(key, {}),
                ensure_ascii=False,
            )

        writer.writerow(row)

    return csv_buffer.getvalue()


# --------------------------------------------------
# PDF UPLOAD SECTION
# --------------------------------------------------

col1, col2 = st.columns(2)

with col1:
    original_file = st.file_uploader(
        "Upload original PDF",
        type=["pdf"],
        key="original_pdf",
        help="Select the original version of the document.",
    )

with col2:
    updated_file = st.file_uploader(
        "Upload updated PDF",
        type=["pdf"],
        key="updated_pdf",
        help="Select the updated version of the document.",
    )


# --------------------------------------------------
# DOCUMENT COMPARISON
# --------------------------------------------------

if st.button("Compare documents", type="primary"):

    if original_file is None or updated_file is None:
        st.warning("Please upload both PDF documents.")

    elif original_file.name == updated_file.name:
        st.warning(
            "Both uploaded files have the same filename. "
            "If these are different versions, rename one file "
            "so the reports are easier to identify."
        )

    else:
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                original_path = save_uploaded_pdf(
                    original_file,
                    temp_path / "original.pdf",
                )

                updated_path = save_uploaded_pdf(
                    updated_file,
                    temp_path / "updated.pdf",
                )

                with st.spinner(
                    "Extracting and comparing document versions..."
                ):
                    original_pages = extract_pdf(str(original_path))
                    updated_pages = extract_pdf(str(updated_path))

                    if not original_pages or not updated_pages:
                        raise ValueError(
                            "One or both PDFs contain no extractable pages."
                        )

                    result = compare_versions(
                        original_pages,
                        updated_pages,
                    )

                report = build_comparison_report(
                    original_file,
                    updated_file,
                    original_pages,
                    updated_pages,
                    result,
                )

                st.session_state["comparison_report"] = report

            st.success("Document comparison completed successfully.")

        except Exception as exc:
            st.session_state["comparison_report"] = None

            st.error(
                f"Comparison failed: {exc}"
            )

            st.info(
                "Verify that both files are valid PDFs and that "
                "their text can be extracted. Scanned PDFs may "
                "require OCR support."
            )


# --------------------------------------------------
# DISPLAY RESULTS
# --------------------------------------------------

report = st.session_state.get("comparison_report")

if report is None:

    st.info(
        "Upload the original and updated PDFs, then click "
        "'Compare documents' to view the results."
    )

else:
    summary = report["summary"]
    changes = report.get("changes", [])

    # ----------------------------------------------
    # SUMMARY METRICS
    # ----------------------------------------------

    st.subheader("Comparison summary")

    metric1, metric2, metric3, metric4 = st.columns(4)

    metric1.metric(
        "Original sections",
        report["old_section_count"],
    )

    metric2.metric(
        "Updated sections",
        report["new_section_count"],
    )

    metric3.metric(
        "Modified sections",
        summary["modified_sections"],
    )

    metric4.metric(
        "Added / removed",
        f"{summary['added_sections']} / "
        f"{summary['removed_sections']}",
    )

    st.metric(
        "High-priority changes",
        summary["high_priority_changes"],
    )

    st.divider()

    # ----------------------------------------------
    # PRIORITY FILTER
    # ----------------------------------------------

    st.subheader("Detected changes")

    selected_priority = st.selectbox(
        "Filter by review priority",
        ["ALL", "HIGH", "MEDIUM", "LOW"],
        key="priority_filter",
    )

    filtered_changes = changes

    if selected_priority != "ALL":
        filtered_changes = [
            change for change in changes
            if change.get("review_priority", "LOW")
            == selected_priority
        ]

    if not filtered_changes:

        st.info("No changes match the selected priority.")

    else:

        # ------------------------------------------
        # INDIVIDUAL SECTION DETAILS
        # ------------------------------------------

        for change in filtered_changes:

            heading = (
                f"{change.get('status', 'unknown').upper()} — "
                f"{change.get('section_number', 'N/A')} — "
                f"{change.get('title', 'Untitled')}"
            )

            with st.expander(heading):

                st.write(
                    "**Review priority:**",
                    change.get("review_priority", "Not assigned"),
                )

                st.write(
                    "**Status:**",
                    change.get("status", "unknown").upper(),
                )

                if "similarity" in change:
                    similarity = max(
                        0.0,
                        min(1.0, float(change["similarity"])),
                    )

                    st.progress(similarity)

                    st.caption(
                        f"Text similarity: {similarity:.1%}"
                    )

                review_flags = change.get("review_flags", [])

                st.markdown("**Review flags**")

                if review_flags:
                    for flag in review_flags:
                        st.write(f"- {flag}")
                else:
                    st.write("No review flags detected.")

                # Original and updated content side by side.
                old_col, new_col = st.columns(2)

                with old_col:
                    st.markdown("**Original content**")

                    old_content = change.get("old_content")

                    st.text(
                        old_content
                        if old_content
                        else "No original content"
                    )

                with new_col:
                    st.markdown("**Updated content**")

                    new_content = change.get("new_content")

                    st.text(
                        new_content
                        if new_content
                        else "No updated content"
                    )

                # Numeric differences.
                st.markdown("**Numeric changes**")

                st.json(
                    change.get("numeric_changes", {})
                )

                # Error-code differences.
                st.markdown("**Error-code changes**")

                st.json(
                    change.get("error_code_changes", {})
                )

                # Word-level differences.
                word_changes = (
                    change.get("diff", {}).get("word_changes", [])
                )

                if word_changes:
                    st.markdown("**Word-level differences**")
                    st.json(word_changes)

                # Hash information.
                with st.expander("View content hashes"):
                    st.write("Original hash:")
                    st.code(
                        change.get("old_hash") or "Not available"
                    )

                    st.write("Updated hash:")
                    st.code(
                        change.get("new_hash") or "Not available"
                    )

    # --------------------------------------------------
    # REPORT DOWNLOADS
    # --------------------------------------------------

    st.divider()
    st.subheader("Export comparison report")

    json_data = json.dumps(
        report,
        indent=2,
        ensure_ascii=False,
    )

    csv_data = create_csv_report(report)

    download_col1, download_col2 = st.columns(2)

    with download_col1:
        st.download_button(
            label="Download JSON report",
            data=json_data,
            file_name="comparison_report.json",
            mime="application/json",
            key="download_json_report",
            use_container_width=True,
        )

    with download_col2:
        st.download_button(
            label="Download CSV report",
            data=csv_data,
            file_name="comparison_report.csv",
            mime="text/csv",
            key="download_csv_report",
            use_container_width=True,
        )

    st.caption(
        "Review priorities are heuristic indicators for directing "
        "human review, not definitive safety assessments."
    )
