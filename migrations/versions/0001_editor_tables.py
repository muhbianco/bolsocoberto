"""Tabelas do editor (prefixo editor_).

Revision ID: 0001
Revises:
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def _datetime() -> mysql.DATETIME:
    return mysql.DATETIME(fsp=6)


def upgrade() -> None:
    op.create_table(
        "editor_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_urls", mysql.JSON(), nullable=False),
        sa.Column("angle", sa.String(length=500), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("slug", sa.String(length=200), nullable=True),
        sa.Column("category_slug", sa.String(length=50), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("body_html", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column("sources_json", mysql.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("wp_post_id", sa.Integer(), nullable=True),
        sa.Column("created_by_email", sa.String(length=255), nullable=False),
        sa.Column("claimed_at", _datetime(), nullable=True),
        sa.Column("created_at", _datetime(), nullable=False),
        sa.Column("updated_at", _datetime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_editor_jobs")),
        **MYSQL_OPTS,
    )
    op.create_index(op.f("ix_editor_jobs_status"), "editor_jobs", ["status"], unique=False)

    op.create_table(
        "editor_job_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("fetch_status", sa.String(length=20), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("extracted_text", mysql.MEDIUMTEXT(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", _datetime(), nullable=False),
        sa.Column("updated_at", _datetime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["editor_jobs.id"],
            name="fk_editor_job_sources_job_id_editor_jobs",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_editor_job_sources")),
        **MYSQL_OPTS,
    )
    op.create_index(
        op.f("ix_editor_job_sources_job_id"),
        "editor_job_sources",
        ["job_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_editor_job_sources_job_id"), table_name="editor_job_sources")
    op.drop_table("editor_job_sources")
    op.drop_index(op.f("ix_editor_jobs_status"), table_name="editor_jobs")
    op.drop_table("editor_jobs")
