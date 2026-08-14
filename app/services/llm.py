from __future__ import annotations

import json
import re
from typing import Any

import bleach
import httpx

from app.core.config import settings
from app.core.exceptions import DomainError
from app.core.logging import get_logger

logger = get_logger(__name__)

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

ALLOWED_TAGS = [
    "p",
    "h2",
    "h3",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "a",
    "blockquote",
    "br",
]
ALLOWED_ATTRS = {"a": ["href", "rel", "target"]}

_PROMPT = """Você é redator do portal Bolso Coberto (finanças e seguros, PT-BR).
Os trechos abaixo são FATOS extraídos de URLs de pauta. NÃO republicar, NÃO parafrasear o artigo original frase a frase, NÃO copiar título do portal.
Escreva um texto ORIGINAL na voz Bolso Coberto: direto, sem enrolação, sem tom de guru, sem conselho de investimento personalizado.
Só use fatos que estejam nos trechos. Se faltar dado, omita — não invente número, nome, data ou citação.
Citação curta (no máximo duas frases) só se for comentar, com a URL da fonte no href.
Inclua no final uma seção "Fontes" com lista de links.

Categoria: apenas "financas" ou "seguros".
Slug: minúsculas, hífen, sem acento, até 80 caracteres.

Responda SOMENTE JSON válido com as chaves:
title, slug, category, excerpt (meta description, até 155 caracteres), body_html, sources (array de objetos url e label).

Ângulo pedido pelo editor (pode estar vazio):
ANGLE_PLACEHOLDER

Fontes e fatos:
FACTS_PLACEHOLDER
"""


def sanitize_html(raw: str) -> str:
    return bleach.clean(
        raw or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=["http", "https"],
        strip=True,
    )


class GeminiDraft:
    def __init__(self) -> None:
        self.api_key = settings.gemini_api_key.get_secret_value().strip()
        self.model = settings.llm_model.strip() or "gemini-3.5-flash"

    async def write(
        self,
        *,
        facts: list[tuple[str, str]],
        angle: str | None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise DomainError("GEMINI_API_KEY não configurada.")
        blocks = []
        for url, text in facts:
            blocks.append(f"URL: {url}\nTRECHO:\n{text[:12000]}")
        prompt = _PROMPT.replace(
            "ANGLE_PLACEHOLDER", (angle or "").strip() or "(nenhum)"
        ).replace("FACTS_PLACEHOLDER", "\n\n".join(blocks))
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 4096,
                "responseMimeType": "application/json",
            },
        }
        url = _GEMINI_URL.format(model=self.model)
        timeout = httpx.Timeout(settings.llm_timeout_seconds, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url,
                    params={"key": self.api_key},
                    headers={"Content-Type": "application/json"},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            logger.exception("Falha de rede no Gemini")
            raise DomainError("LLM indisponível agora.") from exc
        if response.status_code >= 400:
            logger.error(
                "Gemini recusou",
                extra={"status": response.status_code, "body": (response.text or "")[:400]},
            )
            raise DomainError(_gemini_refusal_message(response))
        data = response.json()
        text = _first_text(data)
        parsed = _parse_json_object(text)
        category = str(parsed.get("category") or "").strip().lower()
        if category not in {"financas", "seguros"}:
            category = "financas"
        title = str(parsed.get("title") or "").strip()
        slug = _slugify(str(parsed.get("slug") or title))
        excerpt = str(parsed.get("excerpt") or "").strip()[:155]
        body = sanitize_html(str(parsed.get("body_html") or ""))
        sources_raw = parsed.get("sources") or []
        sources: list[dict[str, str]] = []
        if isinstance(sources_raw, list):
            for item in sources_raw:
                if not isinstance(item, dict):
                    continue
                href = str(item.get("url") or "").strip()
                label = str(item.get("label") or href).strip()[:200]
                if href.startswith("http"):
                    sources.append({"url": href[:2048], "label": label})
        if not title or not body:
            raise DomainError("LLM devolveu rascunho incompleto.")
        return {
            "title": title[:200],
            "slug": slug[:80],
            "category": category,
            "excerpt": excerpt,
            "body_html": body,
            "sources": sources,
        }


def _gemini_refusal_message(response: httpx.Response) -> str:
    body_text = response.text or ""
    reason = ""
    message = ""
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = str(error.get("message") or "")
            details = error.get("details") or []
            if isinstance(details, list):
                for item in details:
                    if isinstance(item, dict) and item.get("reason"):
                        reason = str(item["reason"])
                        break
    except ValueError:
        message = body_text[:200]
    if reason == "API_KEY_IP_ADDRESS_BLOCKED" or "IP address restriction" in message:
        return (
            "A chave Gemini está restrita por IP e esta VPS não está na lista. "
            "No Google Cloud → Credenciais da API key, inclua o IP público do host (62.238.104.94)."
        )
    if response.status_code == 403:
        return "Gemini recusou a chave (403)."
    if response.status_code == 404:
        return "Modelo Gemini não encontrado. Confira LLM_MODEL."
    return "LLM recusou a geração."


def _first_text(payload: dict[str, Any]) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
        return "".join(str(part.get("text") or "") for part in parts)
    except (KeyError, IndexError, TypeError) as exc:
        raise DomainError("Resposta do LLM sem texto.") from exc


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DomainError("LLM não devolveu JSON válido.") from exc
    if not isinstance(data, dict):
        raise DomainError("JSON do LLM não é objeto.")
    return data


def _slugify(value: str) -> str:
    normalized = value.lower().strip()
    translated = (
        normalized.replace("á", "a")
        .replace("à", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", translated).strip("-")
    return slug or "rascunho"
