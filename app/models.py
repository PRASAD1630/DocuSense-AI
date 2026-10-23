
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentVersion(Base):
    """One immutable ingested version of a source document."""

    __tablename__ = "document_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_name: Mapped[str] = mapped_column(String(255), index=True)
    version_label: Mapped[str] = mapped_column(String(100), index=True)
    source_filename: Mapped[str] = mapped_column(String(500))
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )

    nodes: Mapped[list["DocumentNode"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="DocumentNode.ordinal",
    )

    __table_args__ = (
        UniqueConstraint(
            "document_name",
            "version_label",
            name="uq_document_version_label",
        ),
    )


class DocumentNode(Base):
    """A document heading, paragraph, table, figure, or other content node."""

    __tablename__ = "document_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        index=True,
    )

    # Stable logical identity across document versions, when matched.
    logical_id: Mapped[str] = mapped_column(String(255), index=True)

    # Identifier from the tree builder, unique within a version.
    node_key: Mapped[str] = mapped_column(String(500), index=True)

    title: Mapped[str] = mapped_column(String(1000), default="")
    node_type: Mapped[str] = mapped_column(String(50), default="section")
    level: Mapped[int] = mapped_column(Integer, default=0)
    section_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )

    body_text: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)

    version: Mapped["DocumentVersion"] = relationship(
        back_populates="nodes"
    )

    parent: Mapped["DocumentNode | None"] = relationship(
        back_populates="children",
        remote_side="DocumentNode.id",
        foreign_keys=[parent_id],
    )

    children: Mapped[list["DocumentNode"]] = relationship(
        back_populates="parent",
        foreign_keys=[parent_id],
        order_by="DocumentNode.ordinal",
    )

    __table_args__ = (
        UniqueConstraint(
            "version_id",
            "node_key",
            name="uq_node_key_per_version",
        ),
        Index(
            "ix_node_version_logical",
            "version_id",
            "logical_id",
        ),
    )


class PinnedSelection(Base):
    """A named selection of exact node/version pairs."""

    __tablename__ = "pinned_selections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )

    items: Mapped[list["SelectionItem"]] = relationship(
        back_populates="selection",
        cascade="all, delete-orphan",
        order_by="SelectionItem.ordinal",
    )


class SelectionItem(Base):
    """One exact node and version included in a pinned selection."""

    __tablename__ = "selection_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    selection_id: Mapped[int] = mapped_column(
        ForeignKey("pinned_selections.id", ondelete="CASCADE"),
        index=True,
    )
    node_id: Mapped[int] = mapped_column(
        ForeignKey("document_nodes.id", ondelete="RESTRICT"),
        index=True,
    )
    version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"),
        index=True,
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    ordinal: Mapped[int] = mapped_column(Integer, default=0)

    selection: Mapped["PinnedSelection"] = relationship(
        back_populates="items"
    )
    node: Mapped["DocumentNode"] = relationship()
    version: Mapped["DocumentVersion"] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "selection_id",
            "node_id",
            "version_id",
            name="uq_selection_node_version",
        ),
    )


class GenerationRun(Base):
    """Tracks a generation request, including failures and duplicate submissions."""

    __tablename__ = "generation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    request_key: Mapped[str] = mapped_column(
        String(255), unique=True, index=True
    )
    selection_id: Mapped[int] = mapped_column(
        ForeignKey("pinned_selections.id", ondelete="RESTRICT"),
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(50), default="pending", index=True
    )
    provider: Mapped[str] = mapped_column(String(100), default="unknown")
    model_name: Mapped[str] = mapped_column(String(255), default="unknown")
    prompt_version: Mapped[str] = mapped_column(String(100), default="v1")
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    response_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    selection: Mapped["PinnedSelection"] = relationship()
    test_cases: Mapped[list["GeneratedTestCase"]] = relationship(
        back_populates="generation_run",
        cascade="all, delete-orphan",
    )


class GeneratedTestCase(Base):
    """A validated test case linked to its exact source node and version."""

    __tablename__ = "generated_test_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    generation_run_id: Mapped[int] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="CASCADE"),
        index=True,
    )
    selection_item_id: Mapped[int] = mapped_column(
        ForeignKey("selection_items.id", ondelete="RESTRICT"),
        index=True,
    )

    node_id: Mapped[int] = mapped_column(
        ForeignKey("document_nodes.id", ondelete="RESTRICT"),
        index=True,
    )
    version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"),
        index=True,
    )

    test_type: Mapped[str] = mapped_column(String(100), default="functional")
    title: Mapped[str] = mapped_column(String(500))
    steps: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_result: Mapped[str] = mapped_column(Text)
    source_content_hash: Mapped[str] = mapped_column(String(64), index=True)
    structured_output: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )

    # Updated when staleness is checked; retrieval should still recalculate it.
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    staleness_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    generation_run: Mapped["GenerationRun"] = relationship(
        back_populates="test_cases"
    )
    selection_item: Mapped["SelectionItem"] = relationship()
    node: Mapped["DocumentNode"] = relationship()
    version: Mapped["DocumentVersion"] = relationship()
