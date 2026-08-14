from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import JSON, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UtcDateTime, new_uuid


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    APPLIED = "applied"
    FAILED = "failed"


class FetchStatus(StrEnum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"


class EditorJob(TimestampMixin, Base):
    __tablename__ = "editor_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    angle: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_slug: Mapped[str | None] = mapped_column(String(50), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    sources_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    wp_post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_email: Mapped[str] = mapped_column(String(255), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    sources: Mapped[list[EditorJobSource]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="EditorJobSource.id",
    )

    def usable_source_count(self) -> int:
        return sum(
            1
            for source in self.sources
            if source.fetch_status == FetchStatus.OK and (source.extracted_text or "").strip()
        )


class EditorJobSource(TimestampMixin, Base):
    __tablename__ = "editor_job_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("editor_jobs.id", name="fk_editor_job_sources_job_id_editor_jobs"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    fetch_status: Mapped[str] = mapped_column(String(20), nullable=False, default=FetchStatus.PENDING)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[EditorJob] = relationship(back_populates="sources")
