from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from enum import StrEnum
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import DomainError
from app.core.logging import get_logger
from app.services.content_html import sanitize_html

logger = get_logger(__name__)

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

MAX_SOURCE_CHARS = 12_000
EXTRACT_MAX_OUTPUT_TOKENS = 16_384
# Teto da API generateContent para Gemini 3.5 Flash. Env acima disso não aumenta nada.
GEMINI_MAX_OUTPUT_TOKENS = 65_536
_MAX_TOKENS_MESSAGE = (
    "A resposta do LLM foi cortada no limite de tokens. "
    "O Gemini 3.5 Flash reserva parte do orçamento para raciocínio interno; "
    "reduza o número de fontes ou tente de novo."
)


class ContentType(StrEnum):
    NOTICIA = "noticia"
    EXPLICATIVO = "explicativo"
    GUIA = "guia"


CONTENT_TYPE_LABELS = {
    ContentType.NOTICIA: "Notícia curta",
    ContentType.EXPLICATIVO: "Explicativo (notícia como gancho)",
    ContentType.GUIA: "Guia evergreen",
}

_OUTLINES: dict[ContentType, str] = {
    ContentType.NOTICIA: """Alvo: 600 a 900 palavras.
1. Abertura de duas ou três frases com o fato principal e o número que importa.
2. <h2> O que aconteceu — o fato em contexto, com os dados do ledger.
3. <h2> O que muda no seu bolso — nomeie pelo menos três segmentos concretos de
   quem vive de salário e o efeito em reais por mês ou por ano, com a premissa
   da conta escrita. Se a conta não sair dos fatos, diga isso em vez de estimar.
4. <h2> O que acompanha daqui — o próximo fato a observar, sem inventar prazo.
   Não escreva seção de perguntas frequentes: o FAQ estruturado entra depois.""",
    ContentType.EXPLICATIVO: """Alvo: 1100 a 1600 palavras. Este é o formato principal do site.
A notícia é o gancho, não o produto. O leitor chega pelo fato e fica pela explicação.
1. Abertura de três a quatro frases: o que aconteceu e por que ele deveria se importar.
2. <h2> O que de fato mudou — os dados do ledger, com período e fonte de cada número.
3. <h2> Por que isso aconteceu — o mecanismo econômico, explicado sem jargão.
4. <h2> Quem sente no bolso — pelo menos três segmentos concretos de quem vive de
   salário (quem financia imóvel, quem paga aluguel, quem tem dívida no cartão,
   quem recebe piso, quem tem reserva no CDB). Efeito em reais, premissa explícita.
5. <h2> Os números de hoje — aqui entram os blocos de dados calculados.
6. <h2> O que fazer com essa informação — orientação geral e honesta, nunca
   recomendação personalizada, e diga também quando a resposta é "não fazer nada".
Não escreva seção de perguntas frequentes: o FAQ estruturado entra depois.""",
    ContentType.GUIA: """Alvo: 1800 a 2500 palavras. Conteúdo perene, é o que sustenta a receita.
1. Abertura que responde a pergunta principal em até 60 palavras, direto,
   porque é esse trecho que vira resposta destacada e citação em resposta de IA.
2. <h2> O que é e como funciona.
3. <h2> Quanto custa (ou quanto rende) na prática — com números, e o que isso muda
   no bolso de pelo menos três segmentos concretos de quem vive de salário.
4. <h2> Comparativo — tabela comparando as opções reais do mercado brasileiro.
5. <h2> Passo a passo — lista ordenada, acionável.
6. <h2> Erros que custam caro — 4 a 6 erros comuns e o prejuízo de cada um.
Não escreva seção de perguntas frequentes: o FAQ estruturado entra depois."""
}

_EXTRACT_PROMPT = """Você extrai fatos verificáveis de reportagens para a redação do Bolso Coberto.

Para CADA informação factual relevante do material abaixo, devolva uma entrada com:
- claim: a afirmação em uma frase curta e neutra, em PT-BR
- value: o número exato como apareceu, ou "" se não houver número
- unit: a unidade do número (%, R$, pontos, milhões, pontos-base) ou ""
- period: a que data ou período o dado se refere (ex.: "junho de 2026") ou ""
- entity: quem produziu ou anunciou o dado (IBGE, Copom, Susep, uma empresa) ou ""
- primary_source: o nome da fonte ORIGINAL do dado, nunca o veículo que noticiou.
  Se o texto diz "segundo o IBGE, o varejo cresceu 0,5%", primary_source é
  "IBGE - Pesquisa Mensal de Comércio", e não o nome do jornal.
- primary_source_url: URL oficial da fonte primária se o texto citar uma; caso
  contrário "". Não invente URL.
- source_url: a URL do material de onde você tirou o fato

Regras:
- Só extraia o que está EXPLÍCITO. Não deduza, não complete, não arredonde.
- Ignore opinião de colunista, projeção sem autor identificado, publicidade e
  chamadas para outras matérias.
- Uma entrada por fato. Não junte dois números na mesma entrada.
- Se o mesmo fato aparece em mais de uma fonte, registre uma vez e separe as URLs
  por espaço em source_url.
- Preserve o número exatamente como publicado, sem converter unidade.

Responda SOMENTE JSON válido: {"facts": [...]}

MATERIAL:
FACTS_PLACEHOLDER
"""

_WRITE_PROMPT = """Você é redator do Bolso Coberto, portal brasileiro de finanças pessoais e seguros.

Você NÃO recebeu o texto das reportagens, apenas a lista de fatos apurados. Escreva
a partir dela. Isso é proposital: o resultado precisa ser um texto nosso, e não a
versão reescrita do texto de outro veículo.

VOZ
Direto e claro, frases curtas. Fale com o leitor por "você".
Sem tom de guru, sem "descubra o segredo", sem "no mundo de hoje", sem emoji.
Explique todo jargão na primeira vez que ele aparecer.
Nunca dê recomendação personalizada de investimento nem de apólice.

REGRA DE FATO — inegociável
Todo número, percentual, valor, data, nome próprio e citação do seu texto precisa
sair da LISTA DE FATOS. Se um dado que você gostaria de usar não está lá, escreva
sem ele. Não invente, não estime, não escreva "cerca de" para disfarçar ausência.
Ao usar um dado, deixe claro o período e de quem ele é.

PAUTA
TOPIC_PLACEHOLDER

ESTRUTURA
OUTLINE_PLACEHOLDER

VALOR PRÓPRIO — é o que nos separa da fonte
- Traduza cada número em consequência concreta e específica para o leitor.
- Quando o dado permitir uma conta simples e verificável, mostre a conta.
- Prefira exemplos com valores redondos e realistas para o Brasil.
- Se houver contradição entre fontes, aponte a contradição em vez de escolher uma.

REGRA DO BOLSO — é o que a marca promete
Todo texto precisa nomear pelo menos três segmentos concretos de quem vive de
salário (quem financia imóvel, quem paga aluguel, quem tem dívida no cartão,
quem recebe piso ou salário mínimo, quem tem reserva no CDB) e dizer o efeito
em reais por mês ou por ano sempre que a conta sair dos fatos apurados. Quando
a conta não for possível, diga isso em vez de estimar. A premissa de cada conta
precisa aparecer escrita ("para quem tem R$ 10 mil aplicados"): é honesto, e o
checador trata número hipotético marcado como exemplo, não como afirmação sem
lastro.

ÂNGULO PEDIDO PELO EDITOR
ANGLE_PLACEHOLDER

DADOS OFICIAIS JÁ VERIFICADOS (use à vontade, vêm do Banco Central e do IBGE)
MACRO_PLACEHOLDER

LISTA DE FATOS APURADOS
LEDGER_PLACEHOLDER

HTML PERMITIDO no body_html
p, h2, h3, h4, ul, ol, li, strong, em, a, blockquote, table, thead, tbody, tr, th,
td, caption, small.
Não escreva <h1>: o tema do site já publica o título.
Não escreva a seção de fontes nem lista de links de veículos: ela é montada
automaticamente depois, fora do seu texto.
Não insira imagens.

RESPONDA SOMENTE JSON VÁLIDO com exatamente estas chaves:
{
  "title": "H1 do artigo, até 70 caracteres, promete apenas o que o texto entrega",
  "seo_title": "título para a página de resultados, até 60 caracteres, palavra-chave no começo",
  "focus_keyword": "a busca principal que este texto atende, 2 a 5 palavras",
  "slug": "minusculas-com-hifen-sem-acento-ate-80-caracteres",
  "category": "financas ou seguros",
  "tags": ["3 a 6 temas ou entidades, em minúsculas"],
  "excerpt": "meta description entre 140 e 155 caracteres, contendo a palavra-chave",
  "takeaways": ["3 a 5 itens no formato 'Quem <segmento>: <efeito, com valor e período>'"],
  "pocket_line": "efeito principal no bolso, até 90 caracteres, sem jargão, para a capa",
  "body_html": "o artigo completo em HTML",
  "faq": [{"question": "...", "answer": "..."}],
  "image_alt": "descrição objetiva para a imagem de capa, até 120 caracteres"
}
"""

_VERIFY_PROMPT = """Você é o checador de fatos da redação do Bolso Coberto.

Compare o RASCUNHO com a LISTA DE FATOS. Para cada número, percentual, valor em
reais, data, nome próprio e citação que aparece no rascunho, classifique:
- "unsupported": não existe na lista de fatos
- "distorted": existe na lista, mas o rascunho mudou o valor, o período, a unidade
  ou a quem o dado pertence

Não reporte:
- números de contas explicativas genéricas (ex.: "divida por 12", "são 30 dias")
- valores hipotéticos claramente marcados como exemplo
- os blocos identificados como cálculo do Bolso Coberto
- dados que constam na lista de fatos oficiais do Banco Central e do IBGE

Responda SOMENTE JSON válido:
{"issues": [{"excerpt": "trecho literal do rascunho", "kind": "unsupported ou distorted", "why": "explicação em uma frase"}],
 "verdict": "ok ou revisar"}

LISTA DE FATOS
LEDGER_PLACEHOLDER

FATOS OFICIAIS
MACRO_PLACEHOLDER

RASCUNHO
DRAFT_PLACEHOLDER
"""

_STRING_SCHEMA = {"type": "string"}
_WRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": _STRING_SCHEMA,
        "seo_title": _STRING_SCHEMA,
        "focus_keyword": _STRING_SCHEMA,
        "slug": _STRING_SCHEMA,
        "category": _STRING_SCHEMA,
        "tags": {"type": "array", "items": _STRING_SCHEMA},
        "excerpt": _STRING_SCHEMA,
        "takeaways": {"type": "array", "items": _STRING_SCHEMA},
        "pocket_line": _STRING_SCHEMA,
        "body_html": _STRING_SCHEMA,
        "faq": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": _STRING_SCHEMA,
                    "answer": _STRING_SCHEMA,
                },
                "required": ["question", "answer"],
            },
        },
        "image_alt": _STRING_SCHEMA,
    },
    "required": ["title", "body_html"],
}
_VERIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "excerpt": _STRING_SCHEMA,
                    "kind": _STRING_SCHEMA,
                    "why": _STRING_SCHEMA,
                },
                "required": ["excerpt", "kind", "why"],
            },
        },
        "verdict": _STRING_SCHEMA,
    },
    "required": ["issues", "verdict"],
}


class EditorialLLM:
    """Pipeline editorial em três passagens.

    A separação existe por um motivo concreto: o redator só recebe a trilha de
    fatos, nunca a prosa da fonte, então parafrasear frase a frase deixa de ser
    possível por construção em vez de por instrução.
    """

    def __init__(self) -> None:
        self.api_key = settings.gemini_api_key.get_secret_value().strip()
        self.model = settings.llm_model.strip() or "gemini-3.5-flash"

    async def _generate(
        self,
        prompt: str,
        *,
        temperature: float,
        max_output_tokens: int,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise DomainError("GEMINI_API_KEY não configurada.")
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": _generation_config(
                self.model,
                temperature,
                max_output_tokens,
                response_schema=response_schema,
            ),
        }
        url = _GEMINI_URL.format(model=self.model)
        timeout = httpx.Timeout(
            connect=10.0,
            write=30.0,
            pool=10.0,
            read=settings.llm_timeout_seconds,
        )
        response: httpx.Response | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        url,
                        params={"key": self.api_key},
                        headers={"Content-Type": "application/json"},
                        json=payload,
                    )
                break
            except httpx.TimeoutException as exc:
                logger.warning(
                    "Gemini estourou o tempo",
                    extra={"attempt": attempt + 1},
                )
                if attempt == 1:
                    raise DomainError(_network_error_message(exc)) from exc
                await asyncio.sleep(1.5)
            except httpx.HTTPError as exc:
                logger.exception("Falha de rede no Gemini")
                raise DomainError(_network_error_message(exc)) from exc
        if response is None:
            raise DomainError("LLM indisponível agora.")
        if response.status_code >= 400:
            logger.error(
                "Gemini recusou",
                extra={"status": response.status_code, "body": (response.text or "")[:400]},
            )
            raise DomainError(_gemini_refusal_message(response))
        return _parse_generate_response(response.json())

    async def extract_facts(self, sources: list[tuple[str, str]]) -> list[dict[str, str]]:
        blocks = [
            f"URL: {url}\nTEXTO:\n{text[:MAX_SOURCE_CHARS]}" for url, text in sources
        ]
        parsed = await self._generate(
            _EXTRACT_PROMPT.replace("FACTS_PLACEHOLDER", "\n\n---\n\n".join(blocks)),
            temperature=0.1,
            max_output_tokens=EXTRACT_MAX_OUTPUT_TOKENS,
        )
        raw_facts = parsed.get("facts")
        if not isinstance(raw_facts, list):
            raise DomainError("Extração de fatos não devolveu lista.")
        facts: list[dict[str, str]] = []
        for item in raw_facts:
            if not isinstance(item, dict):
                continue
            claim = str(item.get("claim") or "").strip()
            if not claim:
                continue
            facts.append(
                {
                    "claim": claim[:400],
                    "value": str(item.get("value") or "").strip()[:80],
                    "unit": str(item.get("unit") or "").strip()[:40],
                    "period": str(item.get("period") or "").strip()[:80],
                    "entity": str(item.get("entity") or "").strip()[:120],
                    "primary_source": str(item.get("primary_source") or "").strip()[:200],
                    "primary_source_url": _http_or_blank(item.get("primary_source_url")),
                    "source_url": str(item.get("source_url") or "").strip()[:600],
                }
            )
        if not facts:
            raise DomainError("Nenhum fato verificável foi extraído das fontes.")
        return facts

    async def write(
        self,
        *,
        ledger: list[dict[str, str]],
        macro_facts: list[str],
        angle: str | None,
        topic: str | None,
        content_type: ContentType,
    ) -> dict[str, Any]:
        default_topic = (
            "Escreva a partir dos fatos apurados abaixo."
            if ledger
            else "(sem tema definido)"
        )
        prompt = (
            _WRITE_PROMPT.replace("OUTLINE_PLACEHOLDER", _OUTLINES[content_type])
            .replace("TOPIC_PLACEHOLDER", (topic or "").strip() or default_topic)
            .replace("ANGLE_PLACEHOLDER", (angle or "").strip() or "(nenhum, use seu julgamento)")
            .replace("MACRO_PLACEHOLDER", _render_macro(macro_facts))
            .replace("LEDGER_PLACEHOLDER", _render_ledger(ledger))
        )
        parsed = await self._generate(
            prompt,
            temperature=0.5,
            max_output_tokens=settings.llm_max_output_tokens,
            response_schema=_WRITE_SCHEMA,
        )
        return _normalize_draft(parsed)

    async def verify(
        self,
        *,
        body_html: str,
        ledger: list[dict[str, str]],
        macro_facts: list[str],
    ) -> dict[str, Any]:
        prompt = (
            _VERIFY_PROMPT.replace("LEDGER_PLACEHOLDER", _render_ledger(ledger))
            .replace("MACRO_PLACEHOLDER", _render_macro(macro_facts))
            .replace("DRAFT_PLACEHOLDER", body_html[:40_000])
        )
        try:
            parsed = await self._generate(
                prompt,
                temperature=0.0,
                max_output_tokens=8192,
                response_schema=_VERIFY_SCHEMA,
            )
        except DomainError as exc:
            logger.warning("Verificação do LLM falhou", extra={"error": exc.message})
            return {"issues": [], "verdict": "revisar", "parse_failed": True}
        raw_issues = parsed.get("issues")
        issues: list[dict[str, str]] = []
        if isinstance(raw_issues, list):
            for item in raw_issues:
                if not isinstance(item, dict):
                    continue
                excerpt = str(item.get("excerpt") or "").strip()
                if not excerpt:
                    continue
                kind = str(item.get("kind") or "").strip().lower()
                issues.append(
                    {
                        "excerpt": excerpt[:300],
                        "kind": kind if kind in {"unsupported", "distorted"} else "unsupported",
                        "why": str(item.get("why") or "").strip()[:300],
                    }
                )
        verdict = "revisar" if issues else "ok"
        return {"issues": issues, "verdict": verdict, "parse_failed": False}


def _render_ledger(ledger: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for index, fact in enumerate(ledger, start=1):
        parts = [f"[{index}] {fact.get('claim', '')}"]
        value = fact.get("value") or ""
        unit = fact.get("unit") or ""
        if value:
            parts.append(f"valor={value}{(' ' + unit) if unit else ''}")
        if fact.get("period"):
            parts.append(f"período={fact['period']}")
        if fact.get("entity"):
            parts.append(f"quem={fact['entity']}")
        if fact.get("primary_source"):
            parts.append(f"fonte primária={fact['primary_source']}")
        lines.append(" | ".join(parts))
    return "\n".join(lines) if lines else "(vazio)"


def _render_macro(macro_facts: list[str]) -> str:
    return "\n".join(f"- {fact}" for fact in macro_facts) if macro_facts else "(nenhum)"


def _http_or_blank(value: Any) -> str:
    text = str(value or "").strip()
    return text[:2048] if text.startswith("http") else ""


def _normalize_draft(parsed: dict[str, Any]) -> dict[str, Any]:
    title = str(parsed.get("title") or "").strip()
    body = sanitize_html(str(parsed.get("body_html") or ""))
    if not title or not body:
        raise DomainError("LLM devolveu rascunho incompleto.")

    category = str(parsed.get("category") or "").strip().lower()
    if category not in {"financas", "seguros"}:
        category = "financas"

    seo_title = str(parsed.get("seo_title") or title).strip()[:70]
    excerpt = str(parsed.get("excerpt") or "").strip()[:158]

    return {
        "title": title[:200],
        "seo_title": seo_title,
        "focus_keyword": str(parsed.get("focus_keyword") or "").strip()[:120],
        "slug": slugify(str(parsed.get("slug") or title))[:80],
        "category": category,
        "tags": _string_list(parsed.get("tags"), limit=6, max_len=60),
        "excerpt": excerpt,
        "takeaways": _string_list(parsed.get("takeaways"), limit=5, max_len=220),
        "pocket_line": str(parsed.get("pocket_line") or "").strip()[:90],
        "body_html": body,
        "faq": _faq_list(parsed.get("faq")),
        "image_alt": str(parsed.get("image_alt") or title).strip()[:120],
    }


def _string_list(raw: Any, *, limit: int, max_len: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    items: list[str] = []
    for entry in raw:
        text = str(entry or "").strip()
        if text:
            items.append(text[:max_len])
        if len(items) >= limit:
            break
    return items


def _faq_list(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    items: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question") or "").strip()
        answer = str(entry.get("answer") or "").strip()
        if question and answer:
            items.append({"question": question[:300], "answer": answer[:1200]})
        if len(items) >= 6:
            break
    return items


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
    if response.status_code == 429:
        return "Cota do Gemini estourada. Tente de novo em alguns minutos."
    return "LLM recusou a geração."


def _network_error_message(exc: BaseException) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return (
            "O Gemini demorou demais nesta passagem. "
            "Tente de novo; se persistir, use menos fontes."
        )
    return "LLM indisponível agora."


def _generation_config(
    model: str,
    temperature: float,
    max_output_tokens: int,
    response_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": cap_output_tokens(max_output_tokens),
        "responseMimeType": "application/json",
        "thinkingConfig": _thinking_config(model),
    }
    if response_schema:
        config["responseSchema"] = response_schema
    return config


def cap_output_tokens(requested: int) -> int:
    return max(256, min(int(requested), GEMINI_MAX_OUTPUT_TOKENS))


def _thinking_config(model: str) -> dict[str, Any]:
    name = (model or "").strip().lower()
    # 2.5 não aceita thinkingLevel; budget 0 desliga o raciocínio.
    if name.startswith("gemini-2."):
        return {"thinkingBudget": 0}
    # 3.x Flash default é medium e esses tokens entram em maxOutputTokens.
    return {"thinkingLevel": "minimal"}


def _finish_reason(payload: dict[str, Any]) -> str:
    try:
        return str(payload["candidates"][0].get("finishReason") or "")
    except (KeyError, IndexError, TypeError):
        return ""


def _usage_counts(payload: dict[str, Any]) -> dict[str, int]:
    meta = payload.get("usageMetadata")
    if not isinstance(meta, dict):
        return {}
    counts: dict[str, int] = {}
    for key in (
        "promptTokenCount",
        "candidatesTokenCount",
        "thoughtsTokenCount",
        "totalTokenCount",
    ):
        value = meta.get(key)
        if isinstance(value, int):
            counts[key] = value
    return counts


def _parse_generate_response(payload: dict[str, Any]) -> dict[str, Any]:
    reason = _finish_reason(payload)
    usage = _usage_counts(payload)
    if usage:
        logger.info("Gemini usage", extra={"finish": reason, **usage})
    if reason == "SAFETY":
        raise DomainError("O filtro de segurança do Gemini bloqueou esta pauta.")
    text = _first_text(payload)
    if not text.strip():
        if reason == "MAX_TOKENS":
            raise DomainError(_MAX_TOKENS_MESSAGE)
        raise DomainError("Resposta do LLM sem texto.")
    try:
        parsed = _parse_json_object(text)
    except DomainError:
        if reason == "MAX_TOKENS":
            raise DomainError(_MAX_TOKENS_MESSAGE) from None
        raise
    if reason == "MAX_TOKENS":
        logger.warning(
            "Gemini cortou no limite, mas o JSON fechou",
            extra={"finish": reason, **usage},
        )
    return parsed


def _first_text(payload: dict[str, Any]) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return ""
    chunks: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("thought"):
            continue
        chunks.append(str(part.get("text") or ""))
    return "".join(chunks)


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    sliced = _json_object_slice(text)
    if sliced and sliced != text:
        candidates.append(sliced)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(data, dict):
            return data
        last_error = DomainError("JSON do LLM não é objeto.")
    logger.warning(
        "Gemini JSON inválido",
        extra={"chars": len(text), "preview": text[:240]},
    )
    if isinstance(last_error, DomainError):
        raise last_error
    raise DomainError("LLM não devolveu JSON válido.") from last_error


def _json_object_slice(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def slugify(value: str) -> str:
    folded = unicodedata.normalize("NFKD", (value or "").lower().strip())
    ascii_only = "".join(char for char in folded if not unicodedata.combining(char))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    return slug or "rascunho"
