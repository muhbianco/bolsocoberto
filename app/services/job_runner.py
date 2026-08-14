from __future__ import annotations

from app.core.exceptions import DomainError
from app.core.logging import get_logger
from app.models.job import FetchStatus, JobStatus
from app.repositories.job_repository import JobRepository
from app.services.fetch import FetchError, fetch_readable, parse_http_url
from app.services.llm import GeminiDraft

logger = get_logger(__name__)


class JobRunner:
    def __init__(self, repo: JobRepository) -> None:
        self.repo = repo
        self.llm = GeminiDraft()

    async def run(self, job_id: str) -> None:
        job = await self.repo.get(job_id)
        if job is None:
            return
        facts: list[tuple[str, str]] = []
        errors: list[str] = []
        for source in job.sources:
            try:
                parse_http_url(source.url)
                result = await fetch_readable(source.url)
            except FetchError as exc:
                source.fetch_status = FetchStatus.FAILED
                source.http_status = exc.http_status
                source.error_message = str(exc)
                errors.append(f"{source.url}: {exc}")
                continue
            source.fetch_status = FetchStatus.OK
            source.http_status = result.http_status
            source.extracted_text = result.text
            source.error_message = None
            facts.append((result.url, result.text))

        if not facts:
            job.status = JobStatus.FAILED
            job.error_message = "Nenhuma fonte rendeu texto útil. " + " | ".join(errors)[:1500]
            await self.repo.save(job)
            return

        try:
            draft = await self.llm.write(facts=facts, angle=job.angle)
        except DomainError as exc:
            job.status = JobStatus.FAILED
            job.error_message = exc.message
            await self.repo.save(job)
            return
        except Exception:
            logger.exception("Falha inesperada no LLM", extra={"job_id": job.id})
            job.status = JobStatus.FAILED
            job.error_message = "Falha inesperada na redação."
            await self.repo.save(job)
            return

        job.title = draft["title"]
        job.slug = draft["slug"]
        job.category_slug = draft["category"]
        job.excerpt = draft["excerpt"]
        job.body_html = draft["body_html"]
        job.sources_json = draft["sources"]
        job.status = JobStatus.NEEDS_REVIEW
        if errors:
            job.error_message = "Algumas URLs falharam: " + " | ".join(errors)[:1500]
        else:
            job.error_message = None
        await self.repo.save(job)
