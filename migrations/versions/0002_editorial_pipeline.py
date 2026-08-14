"""Pipeline editorial: trilha de fatos, verificação, SEO e índice do WordPress.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL_OPTS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}

def _new_columns() -> list[sa.Column]:
    """Objetos Column novos a cada chamada: o Alembic os liga à tabela, então
    reaproveitar instâncias entre upgrade e downgrade quebra."""
    return [
        sa.Column(
            "content_type",
            sa.String(length=20),
            nullable=False,
            server_default="explicativo",
        ),
        sa.Column("topic", sa.String(length=300), nullable=True),
        sa.Column("seo_title", sa.String(length=255), nullable=True),
        sa.Column("focus_keyword", sa.String(length=120), nullable=True),
        sa.Column("tags_json", mysql.JSON(), nullable=True),
        sa.Column("takeaways_json", mysql.JSON(), nullable=True),
        sa.Column("faq_json", mysql.JSON(), nullable=True),
        sa.Column("primary_sources_json", mysql.JSON(), nullable=True),
        sa.Column("internal_links_json", mysql.JSON(), nullable=True),
        sa.Column("fact_ledger_json", mysql.JSON(), nullable=True),
        sa.Column("macro_json", mysql.JSON(), nullable=True),
        sa.Column("verification_json", mysql.JSON(), nullable=True),
        sa.Column("similarity_json", mysql.JSON(), nullable=True),
        sa.Column("similarity_max", sa.Float(), nullable=True),
        sa.Column("hero_image_bytes", mysql.MEDIUMBLOB(), nullable=True),
        sa.Column("hero_image_alt", sa.String(length=300), nullable=True),
        sa.Column("wp_media_id", sa.Integer(), nullable=True),
        sa.Column("wp_post_url", sa.String(length=500), nullable=True),
        sa.Column("update_target_post_id", sa.Integer(), nullable=True),
    ]


def _datetime() -> mysql.DATETIME:
    return mysql.DATETIME(fsp=6)


def upgrade() -> None:
    for column in _new_columns():
        op.add_column("editor_jobs", column)

    op.create_table(
        "editor_wp_index",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("wp_post_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("link", sa.String(length=500), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("category_slug", sa.String(length=50), nullable=True),
        sa.Column("published_at", _datetime(), nullable=True),
        sa.Column("synced_at", _datetime(), nullable=True),
        sa.Column("created_at", _datetime(), nullable=False),
        sa.Column("updated_at", _datetime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_editor_wp_index")),
        sa.UniqueConstraint("wp_post_id", name=op.f("uq_editor_wp_index_wp_post_id")),
        **MYSQL_OPTS,
    )


def downgrade() -> None:
    op.drop_table("editor_wp_index")
    for column in reversed(_new_columns()):
        op.drop_column("editor_jobs", column.name)
