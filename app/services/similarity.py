from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

SHINGLE_SIZE = 8

_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_SPACE_RE = re.compile(r"\s+")


def _normalize_tokens(text: str) -> list[str]:
    lowered = (text or "").lower()
    folded = unicodedata.normalize("NFKD", lowered)
    ascii_only = "".join(char for char in folded if not unicodedata.combining(char))
    cleaned = _PUNCT_RE.sub(" ", ascii_only)
    return _SPACE_RE.sub(" ", cleaned).strip().split()


def _digest(tokens: list[str], start: int) -> bytes:
    joined = " ".join(tokens[start : start + SHINGLE_SIZE])
    return hashlib.blake2b(joined.encode("utf-8"), digest_size=8).digest()


def _shingles(tokens: list[str]) -> set[bytes]:
    if len(tokens) < SHINGLE_SIZE:
        return set()
    return {_digest(tokens, index) for index in range(len(tokens) - SHINGLE_SIZE + 1)}


@dataclass(frozen=True, slots=True)
class SimilarityReport:
    max_containment: float = 0.0
    worst_url: str = ""
    longest_run_words: int = 0
    longest_run_text: str = ""
    per_source: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "max_containment": round(self.max_containment, 4),
            "worst_url": self.worst_url,
            "longest_run_words": self.longest_run_words,
            "longest_run_text": self.longest_run_text,
            "per_source": {url: round(value, 4) for url, value in self.per_source.items()},
        }


def compare(draft_text: str, sources: list[tuple[str, str]]) -> SimilarityReport:
    """Mede quanto do rascunho é texto colado das fontes.

    A métrica é contenção de 8-gramas: fração dos 8-gramas do rascunho que
    também existem em alguma fonte. Diferente de similaridade simétrica, ela não
    se dilui quando a fonte é muito maior que o texto novo.
    """
    draft_tokens = _normalize_tokens(draft_text)
    draft_shingles = _shingles(draft_tokens)
    if not draft_shingles or not sources:
        return SimilarityReport()

    per_source: dict[str, float] = {}
    best_containment = 0.0
    best_url = ""
    best_run = 0
    best_run_start = 0

    for url, source_text in sources:
        source_shingles = _shingles(_normalize_tokens(source_text))
        if not source_shingles:
            per_source[url] = 0.0
            continue
        hits = [
            index
            for index in range(len(draft_tokens) - SHINGLE_SIZE + 1)
            if _digest(draft_tokens, index) in source_shingles
        ]
        containment = len(hits) / len(draft_shingles)
        per_source[url] = containment
        if containment > best_containment:
            best_containment = containment
            best_url = url

        run = 0
        previous = -2
        for index in hits:
            run = run + 1 if index == previous + 1 else 1
            previous = index
            if run > best_run:
                best_run = run
                best_run_start = index - run + 1

    longest_words = best_run + SHINGLE_SIZE - 1 if best_run else 0
    longest_text = (
        " ".join(draft_tokens[best_run_start : best_run_start + longest_words])
        if longest_words
        else ""
    )
    return SimilarityReport(
        max_containment=best_containment,
        worst_url=best_url,
        longest_run_words=longest_words,
        longest_run_text=longest_text[:400],
        per_source=per_source,
    )
