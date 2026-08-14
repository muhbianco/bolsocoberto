from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import JSON, MEDIUMBLOB, MEDIUMTEXT
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
    content_type: Mapped[str] = mapped_column(String(20), nullable=False, default="explicativo")
    source_urls: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    topic: Mapped[str | None] = mapped_column(String(300), nullable=True)
    angle: Mapped[str | None] = mapped_column(String(500), nullable=True)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    seo_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    focus_keyword: Mapped[str | None] = mapped_column(String(120), nullable=True)
    slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category_slug: Mapped[str | None] = mapped_column(String(50), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(MEDIUMTEXT, nullable=True)

    tags_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    takeaways_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    faq_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    sources_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    primary_sources_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    internal_links_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    fact_ledger_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    macro_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    verification_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    similarity_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    similarity_max: Mapped[float | None] = mapped_column(Float, nullable=True)

    hero_image_bytes: Mapped[bytes | None] = mapped_column(MEDIUMBLOB, nullable=True)
    hero_image_alt: Mapped[str | None] = mapped_column(String(300), nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    wp_post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wp_media_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wp_post_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    update_target_post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

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

    def verification_issues(self) -> list[dict[str, Any]]:
        payload = self.verification_json or {}
        issues = payload.get("issues")
        return issues if isinstance(issues, list) else []

    def blocking_reasons(self, *, similarity_threshold: float) -> list[str]:
        """Motivos que impedem publicar. Não é aviso, é trava."""
        reasons: list[str] = []
        issues = self.verification_issues()
        if issues:
            reasons.append(
                f"{len(issues)} afirmação(ões) sem lastro na trilha de fatos. "
                "Corrija o corpo ou remova o trecho."
            )
        if self.similarity_max is not None and self.similarity_max > similarity_threshold:
            reasons.append(
                f"Similaridade de {self.similarity_max:.0%} com uma das fontes, "
                f"acima do limite de {similarity_threshold:.0%}. Reescreva os trechos apontados."
            )
        return reasons


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


class WpPostIndex(TimestampMixin, Base):
    """Espelho local dos posts publicados.

    Serve para sugerir link interno e para barrar canibalização antes de criar
    mais um texto sobre um assunto que o site já cobre.
    """

    __tablename__ = "editor_wp_index"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    wp_post_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    link: Mapped[str] = mapped_column(String(500), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_slug: Mapped[str | None] = mapped_column(String(50), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
