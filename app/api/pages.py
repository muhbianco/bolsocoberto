from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import csrf_ok, db_session, require_email_html
from app.core.config import settings
from app.core.exceptions import DomainError, NotFoundError, ValidationError
from app.models.job import JobStatus
from app.repositories.job_repository import JobRepository
from app.repositories.wp_index_repository import WpIndexRepository
from app.services.content_html import sanitize_html, to_plain_text, word_count
from app.services.fetch import parse_http_url
from app.services.internal_links import find_cannibals
from app.services.llm import CONTENT_TYPE_LABELS, ContentType, slugify
from app.services.similarity import compare
from app.services.wordpress import PostPayload, WordPressClient

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))

router = APIRouter(tags=["Editor"])

CATEGORIES = {"financas", "seguros"}


def _parse_urls(raw: str, *, required: bool) -> list[str]:
    seen: list[str] = []
    for line in (raw or "").splitlines():
        item = line.strip()
        if not item:
            continue
        parse_http_url(item)
        if item not in seen:
            seen.append(item)
    if not seen and required:
        raise ValidationError("Cole pelo menos uma URL.")
    if len(seen) > settings.fetch_max_urls:
        raise ValidationError(f"No máximo {settings.fetch_max_urls} URLs por pauta.")
    return seen


def _parse_content_type(raw: str) -> ContentType:
    try:
        return ContentType(raw)
    except ValueError:
        raise ValidationError("Tipo de conteúdo inválido.") from None


def _parse_tags(raw: str) -> list[str]:
    tags: list[str] = []
    for part in (raw or "").split(","):
        clean = part.strip()[:60]
        if clean and clean not in tags:
            tags.append(clean)
    return tags[:6]


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    email: str = Depends(require_email_html),
    session: AsyncSession = Depends(db_session),
) -> HTMLResponse:
    jobs = await JobRepository(session).list_recent()
    indexed = len(await WpIndexRepository(session).all_posts())
    return TEMPLATES.TemplateResponse(
        request,
        "jobs_list.html",
        {
            "email": email,
            "jobs": jobs,
            "indexed": indexed,
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
        {
            "email": email,
            "csrf": request.session.get("csrf", ""),
            "content_types": CONTENT_TYPE_LABELS,
            "selected_type": ContentType.EXPLICATIVO.value,
            "form": {},
            "cannibals": [],
        },
    )


@router.post("/jobs")
async def create_job(
    request: Request,
    urls: str = Form(default=""),
    angle: str = Form(default=""),
    topic: str = Form(default=""),
    content_type: str = Form(default=ContentType.EXPLICATIVO.value),
    update_target_post_id: str = Form(default=""),
    confirm_duplicate: str = Form(default=""),
    csrf: str = Form(...),
    email: str = Depends(require_email_html),
    session: AsyncSession = Depends(db_session),
):
    if not csrf_ok(request, csrf):
        raise DomainError("CSRF inválido.")
    kind = _parse_content_type(content_type)
    topic_clean = topic.strip()[:300]
    parsed = _parse_urls(urls, required=kind is not ContentType.GUIA)
    if kind is ContentType.GUIA and not parsed and not topic_clean:
        raise ValidationError("Guia evergreen precisa de um tema ou de pelo menos uma URL.")

    target_id = int(update_target_post_id) if update_target_post_id.strip().isdigit() else None

    if not confirm_duplicate and not target_id:
        posts = await WpIndexRepository(session).all_posts()
        cannibals = find_cannibals(posts, title=topic_clean, topic=angle.strip())
        if cannibals:
            return TEMPLATES.TemplateResponse(
                request,
                "jobs_new.html",
                {
                    "email": email,
                    "csrf": request.session.get("csrf", ""),
                    "content_types": CONTENT_TYPE_LABELS,
                    "selected_type": kind.value,
                    "form": {"urls": urls, "angle": angle, "topic": topic},
                    "cannibals": cannibals,
                },
            )

    job = await JobRepository(session).create(
        urls=parsed,
        angle=angle.strip()[:500] or None,
        topic=topic_clean or None,
        content_type=kind.value,
        update_target_post_id=target_id,
        created_by_email=email,
    )
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


_INTERACTIVE = {JobStatus.FAILED, JobStatus.NEEDS_REVIEW}


def _require_interactive(job) -> None:
    if job.status == JobStatus.APPLIED:
        raise DomainError("Este rascunho já foi aplicado no WordPress.")
    if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
        raise DomainError("Espere o processamento terminar.")
    if job.status not in _INTERACTIVE:
        raise DomainError("Este job não aceita essa ação agora.")


def _requeue(job) -> None:
    job.status = JobStatus.QUEUED
    job.error_message = None


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
            "blocking": job.blocking_reasons(
                similarity_threshold=settings.similarity_block_threshold
            )
            if (job.verification_json or {}).get("enforced", True)
            else [],
            "words": word_count(job.body_html or ""),
            "threshold": settings.similarity_block_threshold,
        },
    )


@router.get("/jobs/{job_id}/hero.jpg")
async def job_hero(
    job_id: str,
    email: str = Depends(require_email_html),
    session: AsyncSession = Depends(db_session),
) -> Response:
    del email
    job = await JobRepository(session).get(job_id)
    if job is None or not job.hero_image_bytes:
        raise NotFoundError("Sem capa gerada para este job.")
    return Response(
        content=job.hero_image_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post("/jobs/{job_id}/save")
async def save_job(
    job_id: str,
    request: Request,
    title: str = Form(...),
    seo_title: str = Form(default=""),
    focus_keyword: str = Form(default=""),
    slug: str = Form(...),
    category_slug: str = Form(...),
    excerpt: str = Form(default=""),
    tags: str = Form(default=""),
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
    if category_slug not in CATEGORIES:
        raise ValidationError("Categoria inválida.")

    job.title = title.strip()[:200]
    job.seo_title = seo_title.strip()[:70] or None
    job.focus_keyword = focus_keyword.strip()[:120] or None
    job.slug = slugify(slug.strip())[:80]
    job.category_slug = category_slug
    job.excerpt = excerpt.strip()[:158]
    job.tags_json = _parse_tags(tags)
    job.body_html = sanitize_html(body_html)
    job.status = JobStatus.NEEDS_REVIEW

    # Similaridade é determinística, então recalcular na edição dá retorno
    # imediato a quem está reescrevendo o trecho apontado.
    corpus = [
        (source.url, source.extracted_text or "")
        for source in job.sources
        if (source.extracted_text or "").strip()
    ]
    report = compare(to_plain_text(job.body_html), corpus)
    job.similarity_json = report.as_dict()
    job.similarity_max = report.max_containment

    await repo.save(job)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.post("/jobs/{job_id}/clear-issue")
async def clear_issue(
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
    payload = dict(job.verification_json or {})
    payload["issues"] = []
    payload["cleared_by_human"] = True
    job.verification_json = payload
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

    if (job.verification_json or {}).get("enforced", True):
        blocking = job.blocking_reasons(
            similarity_threshold=settings.similarity_block_threshold
        )
        if blocking:
            raise DomainError("Publicação bloqueada: " + " ".join(blocking))

    client = WordPressClient()

    if job.hero_image_bytes and not job.wp_media_id:
        job.wp_media_id = await client.upload_media(
            content=job.hero_image_bytes,
            filename=f"{job.slug or 'capa'}.jpg",
            alt_text=job.hero_image_alt or job.title,
        )
        await repo.save(job)

    post_id, link = await client.upsert_post(
        PostPayload(
            title=job.title,
            slug=job.slug or "rascunho",
            content=job.body_html,
            excerpt=job.excerpt or "",
            category_slug=job.category_slug or "financas",
            tags=list(job.tags_json or []),
            seo_title=job.seo_title or job.title,
            focus_keyword=job.focus_keyword or "",
            featured_media=job.wp_media_id,
            post_id=job.wp_post_id,
        )
    )
    job.wp_post_id = post_id
    job.wp_post_url = link[:500]
    job.status = JobStatus.APPLIED
    await repo.save(job)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.post("/jobs/{job_id}/continue")
async def continue_job(
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
    _require_interactive(job)
    if job.usable_source_count() < 1 and not (job.topic or "").strip():
        raise DomainError("Nenhuma fonte útil ainda. Cadastre outra URL.")
    _requeue(job)
    await repo.save(job)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.post("/jobs/{job_id}/urls")
async def add_job_urls(
    job_id: str,
    request: Request,
    urls: str = Form(...),
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
    _require_interactive(job)
    parsed = _parse_urls(urls, required=True)
    total = len({source.url for source in job.sources} | set(parsed))
    if total > settings.fetch_max_urls:
        raise ValidationError(
            f"No máximo {settings.fetch_max_urls} URLs por pauta ({len(job.sources)} já cadastradas)."
        )
    added = await repo.add_urls(job, parsed)
    if not added:
        raise ValidationError("Essas URLs já estão na pauta.")
    _requeue(job)
    await repo.save(job)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.post("/wp/sync")
async def sync_wp_index(
    request: Request,
    csrf: str = Form(...),
    email: str = Depends(require_email_html),
    session: AsyncSession = Depends(db_session),
) -> RedirectResponse:
    del email
    if not csrf_ok(request, csrf):
        raise DomainError("CSRF inválido.")
    posts = await WordPressClient().list_published()
    await WpIndexRepository(session).replace_all(posts)
    return RedirectResponse("/", status_code=303)
