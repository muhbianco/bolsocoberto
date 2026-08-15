from __future__ import annotations

import asyncio
import unicodedata

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import DomainError
from app.core.logging import get_logger
from app.models.job import FetchStatus, JobStatus
from app.repositories.job_repository import JobRepository
from app.repositories.wp_index_repository import WpIndexRepository
from app.services.content_html import (
    apply_link_policy,
    insert_after_first_paragraph,
    registrable_host,
    sanitize_html,
    to_plain_text,
)
from app.services.enrich import (
    fetch_macro_snapshot,
    hero_fields,
    render_fixed_income_table,
    render_macro_context,
    snapshot_facts,
)
from app.services.fetch import FetchError, fetch_readable, parse_http_url
from app.services.image import build_hero
from app.services.internal_links import inject_links, score_candidates
from app.services.llm import ContentType, EditorialLLM
from app.services.similarity import compare
from app.services.sources import (
    collect_press_sources,
    collect_primary_sources,
    is_institutional,
    render_faq,
    render_sources_block,
    render_takeaways,
    render_trust_links,
)

logger = get_logger(__name__)

# Só faz sentido pendurar tabela de renda fixa em pauta que fala de juros.
_ENRICH_TERMS = (
    "cdi",
    "selic",
    "renda fixa",
    "cdb",
    "poupanca",
    "juro",
    "investiment",
    "tesouro",
    "ipca",
    "inflacao",
    "dolar",
    "copom",
    "lci",
    "lca",
    "financiament",
    "emprestim",
)

# Recorte mais estreito, usado só para decidir a capa: são os termos que nomeiam
# o indicador estampado no cartão.
_HERO_TERMS = (
    "selic",
    "cdi",
    "ipca",
    "juro",
    "inflacao",
    "poupanca",
    "copom",
    "renda fixa",
    "tesouro",
    "dolar",
)


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(char for char in folded if not unicodedata.combining(char))


class JobRunner:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = JobRepository(session)
        self.index_repo = WpIndexRepository(session)
        self.llm = EditorialLLM()

    async def run(self, job_id: str) -> None:
        job = await self.repo.get(job_id)
        if job is None:
            return
        try:
            await self._pipeline(job)
        except DomainError as exc:
            job.status = JobStatus.FAILED
            job.error_message = exc.message
            await self.repo.save(job)
        except Exception as exc:
            logger.exception("Falha inesperada na pauta", extra={"job_id": job.id})
            job.status = JobStatus.FAILED
            job.error_message = f"Falha inesperada na redação ({type(exc).__name__})."
            await self.repo.save(job)

    async def _pipeline(self, job) -> None:
        content_type = _content_type(job.content_type)
        facts, fetch_errors = await self._gather_sources(job)
        topic = (job.topic or "").strip()

        if not facts and not topic:
            job.status = JobStatus.FAILED
            job.error_message = (
                "Nenhuma fonte rendeu texto útil. " + " | ".join(fetch_errors)
            )[:1500]
            await self.repo.save(job)
            return

        snapshot = await fetch_macro_snapshot()
        macro_facts = snapshot_facts(snapshot)

        ledger: list[dict[str, str]] = []
        if facts:
            ledger = await self.llm.extract_facts(facts)

        draft = await self.llm.write(
            ledger=ledger,
            macro_facts=macro_facts,
            angle=job.angle,
            topic=topic,
            content_type=content_type,
        )

        input_urls = [source.url for source in job.sources]
        body = await self._assemble_body(
            draft=draft,
            ledger=ledger,
            input_urls=input_urls,
            snapshot=snapshot,
            job=job,
        )

        verification = await self.llm.verify(
            body_html=body,
            ledger=ledger,
            macro_facts=macro_facts,
        )
        # Notícia tem lastro obrigatório. Guia evergreen escreve conhecimento
        # estável de domínio, então a checagem vira aviso e não trava.
        verification["enforced"] = bool(facts)

        similarity = compare(to_plain_text(body), facts)

        job.title = draft["title"]
        job.seo_title = draft["seo_title"]
        job.focus_keyword = draft["focus_keyword"]
        job.slug = draft["slug"]
        job.category_slug = draft["category"]
        job.excerpt = draft["excerpt"]
        job.body_html = body
        job.tags_json = draft["tags"]
        job.takeaways_json = draft["takeaways"]
        job.faq_json = draft["faq"]
        job.fact_ledger_json = ledger
        job.macro_json = snapshot.as_dict()
        job.verification_json = verification
        job.similarity_json = similarity.as_dict()
        job.similarity_max = similarity.max_containment
        job.status = JobStatus.NEEDS_REVIEW
        job.error_message = (
            "Algumas URLs falharam: " + " | ".join(fetch_errors)[:1400]
            if fetch_errors
            else None
        )

        if settings.hero_image_enabled:
            await self._attach_hero(job, draft, snapshot)

        await self.repo.save(job)

    async def _gather_sources(self, job) -> tuple[list[tuple[str, str]], list[str]]:
        facts: list[tuple[str, str]] = []
        errors: list[str] = []
        for source in job.sources:
            if source.fetch_status == FetchStatus.OK and (source.extracted_text or "").strip():
                facts.append((source.url, source.extracted_text or ""))
                continue
            if source.fetch_status == FetchStatus.FAILED:
                errors.append(f"{source.url}: {source.error_message or 'falhou'}")
                continue
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
        return facts, errors

    async def _assemble_body(
        self,
        *,
        draft: dict,
        ledger: list[dict[str, str]],
        input_urls: list[str],
        snapshot,
        job,
    ) -> str:
        body = draft["body_html"]
        body = insert_after_first_paragraph(body, render_takeaways(draft["takeaways"]))

        haystack = _fold(
            draft["title"] + draft["focus_keyword"] + " ".join(f.get("claim", "") for f in ledger)
        )
        if draft["category"] == "financas" and any(term in haystack for term in _ENRICH_TERMS):
            body += render_macro_context(snapshot)
            body += render_fixed_income_table(snapshot)

        body += render_faq(draft["faq"])
        body += render_trust_links(site_url=settings.wp_base_url)

        primary = collect_primary_sources(ledger, input_urls)
        press = collect_press_sources(input_urls)
        job.primary_sources_json = [
            {"label": ref.label, "url": ref.url} for ref in primary
        ]
        job.sources_json = [{"label": ref.label, "url": ref.url} for ref in press]
        body += render_sources_block(primary, press)

        body, applied = await self._link_internally(body, draft, job)
        job.internal_links_json = [item.as_dict() for item in applied]

        # Sanitiza antes para o modelo de aspas ficar normalizado, aplica a
        # política de rel sobre isso, e sanitiza de novo porque a saída final é
        # o que vai para o site.
        body = sanitize_html(body)
        nofollow_hosts = {
            registrable_host(url) for url in input_urls if not is_institutional(url)
        }
        body = apply_link_policy(
            body,
            site_host=registrable_host(settings.wp_base_url),
            nofollow_hosts={host for host in nofollow_hosts if host},
        )
        return sanitize_html(body)

    async def _link_internally(self, body: str, draft: dict, job):
        try:
            posts = await self.index_repo.all_posts()
        except Exception:
            logger.exception("Índice do WordPress indisponível")
            return body, []
        if not posts:
            return body, []
        suggestions = score_candidates(
            posts,
            title=draft["title"],
            focus_keyword=draft["focus_keyword"],
            body_html=body,
            category_slug=draft["category"],
            exclude_post_id=job.wp_post_id,
        )
        return inject_links(body, suggestions)

    async def _attach_hero(self, job, draft: dict, snapshot) -> None:
        fields = hero_fields(snapshot) if _hero_shows_indicator(draft) else None
        # Pillow é CPU puro; rodar no loop travaria o worker inteiro.
        hero = await asyncio.to_thread(
            build_hero,
            category=draft["category"],
            headline=draft["title"],
            fields=fields,
        )
        if hero is None:
            return
        job.hero_image_bytes = hero.data
        job.hero_image_alt = hero.alt


def _hero_shows_indicator(draft: dict) -> bool:
    """A capa de dados estampa Selic ou IPCA, então só cabe quando a pauta é
    sobre juro ou inflação. Antes bastava ser da editoria de finanças, e toda
    matéria saía com o mesmo gráfico da Selic. O teste é no título e na palavra
    -chave, não no ledger: um fato solto citando "empréstimo" não faz da pauta
    uma matéria de juro."""
    if draft["category"] != "financas":
        return False
    haystack = _fold(f"{draft['title']} {draft['focus_keyword']}")
    return any(term in haystack for term in _HERO_TERMS)


def _content_type(raw: str | None) -> ContentType:
    try:
        return ContentType(raw or "")
    except ValueError:
        return ContentType.EXPLICATIVO
