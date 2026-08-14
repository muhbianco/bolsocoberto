from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import csrf_ok, db_session, require_email_html
from app.core.config import settings
from app.core.exceptions import DomainError, NotFoundError, ValidationError
from app.models.job import JobStatus
from app.repositories.job_repository import JobRepository
from app.services.fetch import parse_http_url
from app.services.llm import sanitize_html
from app.services.wordpress import WordPressClient

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))

router = APIRouter(tags=["Editor"])


def _parse_urls(raw: str) -> list[str]:
    seen: list[str] = []
    for line in (raw or "").splitlines():
        item = line.strip()
        if not item:
            continue
        parse_http_url(item)
        if item not in seen:
            seen.append(item)
    if not seen:
        raise ValidationError("Cole pelo menos uma URL.")
    if len(seen) > settings.fetch_max_urls:
        raise ValidationError(f"No máximo {settings.fetch_max_urls} URLs por pauta.")
    return seen


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    email: str = Depends(require_email_html),
    session: AsyncSession = Depends(db_session),
) -> HTMLResponse:
    jobs = await JobRepository(session).list_recent()
    return TEMPLATES.TemplateResponse(
        request,
        "jobs_list.html",
        {
            "email": email,
            "jobs": jobs,
            "csrf": request.session.get("csrf", ""),
        },
    )


@router.get("/jobs/new", response_class=HTMLResponse)
async def new_job_form(
    request: Request,
    email: str = Depends(require_email_html),
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request,
        "jobs_new.html",
        {"email": email, "csrf": request.session.get("csrf", "")},
    )


@router.post("/jobs")
async def create_job(
    request: Request,
    urls: str = Form(...),
    angle: str = Form(default=""),
    csrf: str = Form(...),
    email: str = Depends(require_email_html),
    session: AsyncSession = Depends(db_session),
) -> RedirectResponse:
    if not csrf_ok(request, csrf):
        raise DomainError("CSRF inválido.")
    parsed = _parse_urls(urls)
    angle_clean = angle.strip()[:500] or None
    job = await JobRepository(session).create(
        urls=parsed,
        angle=angle_clean,
        created_by_email=email,
    )
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def view_job(
    job_id: str,
    request: Request,
    email: str = Depends(require_email_html),
    session: AsyncSession = Depends(db_session),
) -> HTMLResponse:
    job = await JobRepository(session).get(job_id)
    if job is None:
        raise NotFoundError("Job não encontrado.")
    return TEMPLATES.TemplateResponse(
        request,
        "viewer.html",
        {
            "email": email,
            "job": job,
            "csrf": request.session.get("csrf", ""),
            "JobStatus": JobStatus,
        },
    )


@router.post("/jobs/{job_id}/save")
async def save_job(
    job_id: str,
    request: Request,
    title: str = Form(...),
    slug: str = Form(...),
    category_slug: str = Form(...),
    excerpt: str = Form(default=""),
    body_html: str = Form(...),
    csrf: str = Form(...),
    email: str = Depends(require_email_html),
    session: AsyncSession = Depends(db_session),
) -> RedirectResponse:
    del email
    if not csrf_ok(request, csrf):
        raise DomainError("CSRF inválido.")
    repo = JobRepository(session)
    job = await repo.get(job_id)
    if job is None:
        raise NotFoundError("Job não encontrado.")
    if job.status not in {JobStatus.NEEDS_REVIEW, JobStatus.FAILED}:
        raise DomainError("Este job não pode ser editado agora.")
    if category_slug not in {"financas", "seguros"}:
        raise ValidationError("Categoria inválida.")
    job.title = title.strip()[:200]
    job.slug = slug.strip()[:80]
    job.category_slug = category_slug
    job.excerpt = excerpt.strip()[:155]
    job.body_html = sanitize_html(body_html)
    job.status = JobStatus.NEEDS_REVIEW
    await repo.save(job)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.post("/jobs/{job_id}/apply")
async def apply_job(
    job_id: str,
    request: Request,
    csrf: str = Form(...),
    email: str = Depends(require_email_html),
    session: AsyncSession = Depends(db_session),
) -> RedirectResponse:
    del email
    if not csrf_ok(request, csrf):
        raise DomainError("CSRF inválido.")
    repo = JobRepository(session)
    job = await repo.get(job_id)
    if job is None:
        raise NotFoundError("Job não encontrado.")
    if job.status != JobStatus.NEEDS_REVIEW:
        raise DomainError("Só aplica rascunho depois da revisão.")
    if not job.title or not job.body_html:
        raise DomainError("Título e corpo são obrigatórios.")
    post_id = await WordPressClient().create_draft(
        title=job.title,
        slug=job.slug or "rascunho",
        content=job.body_html,
        excerpt=job.excerpt or "",
        category_slug=job.category_slug or "financas",
    )
    job.wp_post_id = post_id
    job.status = JobStatus.APPLIED
    await repo.save(job)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)
