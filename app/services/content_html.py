from __future__ import annotations

import html as html_module
import re
from urllib.parse import urlparse

import bleach

ALLOWED_TAGS = [
    "p",
    "h2",
    "h3",
    "h4",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "a",
    "blockquote",
    "br",
    "hr",
    "small",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "caption",
    "figure",
    "figcaption",
    "img",
    "section",
    "div",
    "span",
]

_TAG_ATTRS: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "rel", "target", "title"}),
    "img": frozenset({"src", "alt", "width", "height", "loading", "decoding"}),
    "th": frozenset({"scope", "colspan", "rowspan"}),
    "td": frozenset({"colspan", "rowspan"}),
    "table": frozenset(),
    "section": frozenset(),
    "div": frozenset(),
    "span": frozenset(),
    "figure": frozenset(),
    "p": frozenset(),
    "caption": frozenset(),
}

# Só estas classes atravessam o sanitizador. Qualquer outra vira ruído removido,
# então o CSS do tema pode confiar no conjunto.
ALLOWED_CLASSES = frozenset(
    {
        "bc-takeaways",
        "bc-table-wrap",
        "bc-faq",
        "bc-faq-item",
        "bc-sources",
        "bc-primary-sources",
        "bc-note",
        "bc-updated",
        "bc-figure",
    }
)


def _attribute_allowed(tag: str, name: str, value: str) -> bool:
    if name == "class":
        parts = value.split()
        return bool(parts) and all(part in ALLOWED_CLASSES for part in parts)
    return name in _TAG_ATTRS.get(tag, frozenset())


def sanitize_html(raw: str) -> str:
    return bleach.clean(
        raw or "",
        tags=ALLOWED_TAGS,
        attributes=_attribute_allowed,
        protocols=["http", "https"],
        strip=True,
    )


def to_plain_text(raw: str) -> str:
    stripped = bleach.clean(raw or "", tags=[], attributes={}, strip=True)
    return html_module.unescape(stripped)


def word_count(raw: str) -> int:
    return len([token for token in to_plain_text(raw).split() if token.strip()])


def h2_count(raw: str) -> int:
    return len(re.findall(r"<h2\b", raw or "", flags=re.IGNORECASE))


_LINK_RE = re.compile(r'<a\s+([^>]*?)href="([^"]+)"([^>]*)>', flags=re.IGNORECASE)
_REL_RE = re.compile(r'\srel="[^"]*"', flags=re.IGNORECASE)
_TARGET_RE = re.compile(r'\starget="[^"]*"', flags=re.IGNORECASE)


def apply_link_policy(raw: str, *, site_host: str, nofollow_hosts: set[str]) -> str:
    """Reescreve o rel de cada link.

    Link interno fica limpo, fonte institucional fica dofollow (é sinal de
    autoridade que queremos passar) e veículo de imprensa vai nofollow.
    """

    def _replace(match: re.Match[str]) -> str:
        before, href, after = match.group(1), match.group(2), match.group(3)
        attrs = _REL_RE.sub("", f" {before.strip()} {after.strip()} ")
        attrs = _TARGET_RE.sub("", attrs).strip()
        host = (urlparse(href).hostname or "").lower().lstrip("www.")
        if host and host == site_host:
            rel = ""
        elif host in nofollow_hosts:
            rel = ' rel="nofollow noopener"'
        else:
            rel = ' rel="noopener"'
        extra = f" {attrs}" if attrs else ""
        return f'<a href="{href}"{rel}{extra}>'

    return _LINK_RE.sub(_replace, raw or "")


def registrable_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def insert_after_first_paragraph(body: str, block: str) -> str:
    """Coloca o bloco logo depois da abertura, que é onde o leitor ainda está."""
    if not block:
        return body
    match = re.search(r"</p>", body or "", flags=re.IGNORECASE)
    if not match:
        return f"{block}{body}"
    cut = match.end()
    return f"{body[:cut]}{block}{body[cut:]}"
