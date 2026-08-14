from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.logging import get_logger

logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    config = Config(str(BASE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BASE_DIR / "migrations"))
    config.attributes["configure_logger"] = False
    return config


def _upgrade_to_head() -> None:
    command.upgrade(_alembic_config(), "head")


async def run_migrations() -> None:
    await asyncio.to_thread(_upgrade_to_head)
    logger.info("Migrations aplicadas até head")
