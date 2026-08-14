from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.database import SessionFactory, dispose_engine
from app.core.logging import configure_logging, get_logger
from app.models.job import JobStatus
from app.repositories.job_repository import JobRepository
from app.services.job_runner import JobRunner

logger = get_logger(__name__)


async def process_one() -> bool:
    async with SessionFactory() as session:
        job = await JobRepository(session).claim_next()
        if job is None:
            return False
        job_id = job.id
        await session.commit()

    async with SessionFactory() as session:
        try:
            await JobRunner(session).run(job_id)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Worker falhou no job", extra={"job_id": job_id})
            async with SessionFactory() as fail_session:
                repo = JobRepository(fail_session)
                failed = await repo.get(job_id)
                if failed is not None and failed.status == JobStatus.RUNNING:
                    failed.status = JobStatus.FAILED
                    failed.error_message = "Falha inesperada no worker."
                    await repo.save(failed)
                    await fail_session.commit()
    return True


async def main() -> None:
    configure_logging(settings.log_level)
    logger.info("Worker de pauta iniciado")
    try:
        while True:
            try:
                processed = await process_one()
            except Exception:
                logger.exception("Loop do worker")
                processed = False
            if not processed:
                await asyncio.sleep(settings.worker_poll_seconds)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
