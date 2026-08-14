from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.content_html import to_plain_text

if TYPE_CHECKING:
    from app.models.job import WpPostIndex

# Link interno é o multiplicador mais barato de receita que existe: segura o
# leitor em mais páginas por sessão, o que multiplica impressão de anúncio, e
# ainda amarra o cluster temático para o Google.
MAX_LINKS = 6

PT_STOPWORDS = frozenset(
    """a ao aos as com como da das de do dos e em entre era essa esse esta este eu
    foi for fora ha isso isto ja la lhe mais mas me mesmo meu minha na nao nas nem no nos
    o os ou para pela pelas pelo pelos por qual quando que quem se sem seu sua suas seus
    so sobre tambem te tem ter teu tua um uma umas uns vai voce voces ate apos
    sao estao ser sera seria pode podem deve devem tudo todo toda todos todas
    """.split()
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_PARAGRAPH_RE = re.compile(r"(<p\b[^>]*>)(.*?)(</p>)", flags=re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True, slots=True)
class LinkSuggestion:
    wp_post_id: int
    title: str
    url: str
    phrase: str
    score: float

    def as_dict(self) -> dict[str, object]:
        return {
            "wp_post_id": self.wp_post_id,
            "title": self.title,
            "url": self.url,
            "phrase": self.phrase,
            "score": round(self.score, 3),
        }


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(char for char in folded if not unicodedata.combining(char))


def _fold_aligned(text: str) -> str:
    """Versão sem acento com o mesmo comprimento do original.

    A inserção de link usa os índices da busca para fatiar o HTML cru, então
    qualquer deslocamento de um caractere geraria markup quebrado.
    """
    output: list[str] = []
    for char in text or "":
        lowered = char.lower()
        if len(lowered) != 1:
            lowered = char
        decomposed = unicodedata.normalize("NFKD", lowered)
        base = "".join(part for part in decomposed if not unicodedata.combining(part))
        output.append(base[0] if base else lowered)
    return "".join(output)


def _tokens(text: str) -> list[str]:
    return [word for word in _WORD_RE.findall(_fold(text)) if word not in PT_STOPWORDS]


def _phrases(title: str) -> list[str]:
    """Trechos de 2 a 4 palavras do título alvo, dos mais longos aos mais curtos."""
    words = _WORD_RE.findall(_fold(title))
    candidates: list[str] = []
    for size in (4, 3, 2):
        for start in range(len(words) - size + 1):
            window = words[start : start + size]
            if window[0] in PT_STOPWORDS or window[-1] in PT_STOPWORDS:
                continue
            if all(word in PT_STOPWORDS for word in window):
                continue
            candidates.append(" ".join(window))
    return candidates


def score_candidates(
    posts: list[WpPostIndex],
    *,
    title: str,
    focus_keyword: str,
    body_html: str,
    category_slug: str | None,
    exclude_post_id: int | None = None,
) -> list[LinkSuggestion]:
    draft_text = _fold(f"{title} {focus_keyword} {to_plain_text(body_html)}")
    draft_tokens = set(_tokens(f"{title} {focus_keyword}"))
    suggestions: list[LinkSuggestion] = []

    for post in posts:
        if exclude_post_id is not None and post.wp_post_id == exclude_post_id:
            continue
        if not post.link:
            continue
        target_tokens = set(_tokens(post.title))
        if not target_tokens:
            continue
        overlap = len(draft_tokens & target_tokens) / len(target_tokens)

        phrase = ""
        for candidate in _phrases(post.title):
            if candidate and candidate in draft_text:
                phrase = candidate
                break
        if not phrase:
            continue

        score = overlap + len(phrase.split()) * 0.1
        if category_slug and post.category_slug == category_slug:
            score += 0.15
        suggestions.append(
            LinkSuggestion(
                wp_post_id=post.wp_post_id,
                title=post.title,
                url=post.link,
                phrase=phrase,
                score=score,
            )
        )

    suggestions.sort(key=lambda item: item.score, reverse=True)
    return suggestions


def inject_links(
    body_html: str,
    suggestions: list[LinkSuggestion],
    *,
    limit: int = MAX_LINKS,
) -> tuple[str, list[LinkSuggestion]]:
    """Insere o link no primeiro parágrafo em que a frase aparece.

    Parágrafo que já tem link é pulado, para não aninhar âncora nem empilhar
    saída no mesmo bloco.
    """
    applied: list[LinkSuggestion] = []
    used_urls: set[str] = set()
    result = body_html

    for suggestion in suggestions:
        if len(applied) >= limit:
            break
        if suggestion.url in used_urls:
            continue
        replaced = False

        def _handle(match: re.Match[str]) -> str:
            nonlocal replaced
            opening, inner, closing = match.group(1), match.group(2), match.group(3)
            if replaced or "<a" in inner.lower():
                return match.group(0)
            pattern = re.compile(
                r"\b" + r"\s+".join(re.escape(word) for word in suggestion.phrase.split()) + r"\b",
                flags=re.IGNORECASE,
            )
            # A frase é buscada na versão sem acento, então casa o texto visível
            # pela posição encontrada no fold, não pelo texto cru.
            folded_inner = _fold_aligned(inner)
            found = pattern.search(folded_inner)
            if not found or "<" in inner[found.start() : found.end()]:
                return match.group(0)
            anchor_text = inner[found.start() : found.end()]
            link = (
                f'<a href="{html.escape(suggestion.url, quote=True)}">{anchor_text}</a>'
            )
            replaced = True
            return f"{opening}{inner[: found.start()]}{link}{inner[found.end() :]}{closing}"

        candidate = _PARAGRAPH_RE.sub(_handle, result)
        if replaced:
            result = candidate
            used_urls.add(suggestion.url)
            applied.append(suggestion)

    return result, applied


def find_cannibals(
    posts: list[WpPostIndex],
    *,
    title: str,
    topic: str,
    limit: int = 3,
) -> list[WpPostIndex]:
    """Posts publicados que já cobrem o assunto.

    Atualizar um texto existente rende mais que publicar um quase igual, que
    divide autoridade entre duas URLs e ainda engorda a contagem de páginas finas.
    """
    reference = set(_tokens(f"{title} {topic}"))
    if not reference:
        return []
    scored: list[tuple[float, WpPostIndex]] = []
    for post in posts:
        target = set(_tokens(post.title))
        if not target:
            continue
        overlap = len(reference & target) / min(len(reference), len(target))
        if overlap >= 0.6:
            scored.append((overlap, post))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [post for _, post in scored[:limit]]
