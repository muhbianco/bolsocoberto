from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import utcnow
from app.models.job import EditorJob, EditorJobSource, FetchStatus, JobStatus


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        urls: list[str],
        angle: str | None,
        created_by_email: str,
        content_type: str,
        topic: str | None = None,
        update_target_post_id: int | None = None,
    ) -> EditorJob:
        job = EditorJob(
            status=JobStatus.QUEUED,
            content_type=content_type,
            source_urls=urls,
            topic=topic,
            angle=angle,
            update_target_post_id=update_target_post_id,
            wp_post_id=update_target_post_id,
            created_by_email=created_by_email,
            sources=[
                EditorJobSource(url=url, fetch_status=FetchStatus.PENDING) for url in urls
            ],
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: str) -> EditorJob | None:
        result = await self.session.execute(
            select(EditorJob)
            .options(selectinload(EditorJob.sources))
            .where(EditorJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_recent(self, *, limit: int = 50) -> list[EditorJob]:
        result = await self.session.execute(
            select(EditorJob).order_by(EditorJob.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def claim_next(self) -> EditorJob | None:
        result = await self.session.execute(
            select(EditorJob)
            .where(EditorJob.status == JobStatus.QUEUED)
            .order_by(EditorJob.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = result.scalar_one_or_none()
        if job is None:
            return None
        job.status = JobStatus.RUNNING
        job.claimed_at = utcnow()
        await self.session.flush()
        loaded = await self.get(job.id)
        return loaded

    async def save(self, job: EditorJob) -> None:
        await self.session.flush()

    async def add_urls(self, job: EditorJob, urls: list[str]) -> list[str]:
        existing = {source.url for source in job.sources}
        added: list[str] = []
        for url in urls:
            if url in existing:
                continue
            job.sources.append(
                EditorJobSource(url=url, fetch_status=FetchStatus.PENDING)
            )
            existing.add(url)
            added.append(url)
        if added:
            job.source_urls = list(job.source_urls) + added
        await self.session.flush()
        return added
