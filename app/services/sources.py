from __future__ import annotations

import html
from dataclasses import dataclass

from app.services.content_html import registrable_host

# Domínios cujo link é ativo institucional: passar autoridade para eles é ganho
# de SEO, não vazamento. Sufixos cobrem o resto do setor público.
INSTITUTIONAL_SUFFIXES = (
    ".gov.br",
    ".leg.br",
    ".jus.br",
    ".edu.br",
    ".gov",
)

INSTITUTIONAL_HOSTS = frozenset(
    {
        "b3.com.br",
        "anbima.com.br",
        "cnseg.org.br",
        "febraban.org.br",
        "abecip.org.br",
        "fgv.br",
        "fipe.org.br",
        "idec.org.br",
        "serasaexperian.com.br",
        "imf.org",
        "worldbank.org",
        "oecd.org",
        "bis.org",
    }
)

# Nome de exibição do veículo. A citação usa o nome da casa, nunca a manchete.
PRESS_NAMES = {
    "infomoney.com.br": "InfoMoney",
    "valor.globo.com": "Valor Econômico",
    "valorinveste.globo.com": "Valor Investe",
    "g1.globo.com": "g1",
    "oglobo.globo.com": "O Globo",
    "folha.uol.com.br": "Folha de S.Paulo",
    "estadao.com.br": "Estadão",
    "einvestidor.estadao.com.br": "E-Investidor",
    "cnnbrasil.com.br": "CNN Brasil",
    "exame.com": "Exame",
    "seudinheiro.com": "Seu Dinheiro",
    "moneytimes.com.br": "Money Times",
    "investnews.com.br": "InvestNews",
    "agenciabrasil.ebc.com.br": "Agência Brasil",
    "poder360.com.br": "Poder360",
    "gazetadopovo.com.br": "Gazeta do Povo",
    "istoedinheiro.com.br": "IstoÉ Dinheiro",
    "veja.abril.com.br": "Veja",
    "uol.com.br": "UOL",
    "terra.com.br": "Terra",
    "reuters.com": "Reuters",
    "bloomberglinea.com.br": "Bloomberg Línea",
    "bloomberg.com": "Bloomberg",
    "ft.com": "Financial Times",
    "cnbc.com": "CNBC",
    "sindiseguro.com.br": "Sindiseguro",
    "revistaapolice.com.br": "Revista Apólice",
    "cqcs.com.br": "CQCS",
}


@dataclass(frozen=True, slots=True)
class SourceRef:
    label: str
    url: str


def is_institutional(url: str) -> bool:
    host = registrable_host(url)
    if not host:
        return False
    if host in INSTITUTIONAL_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in INSTITUTIONAL_SUFFIXES)


def press_display_name(url: str) -> str:
    host = registrable_host(url)
    if not host:
        return ""
    if host in PRESS_NAMES:
        return PRESS_NAMES[host]
    label = host.split(".")[0]
    return label.capitalize()


def collect_primary_sources(
    ledger: list[dict[str, str]],
    input_urls: list[str],
) -> list[SourceRef]:
    """Fonte primária é o órgão que produziu o dado, não o veículo que noticiou.

    Sai daqui a lista que vai visível e dofollow no rodapé do artigo.
    """
    refs: list[SourceRef] = []
    seen: set[str] = set()

    for fact in ledger:
        label = (fact.get("primary_source") or "").strip()
        url = (fact.get("primary_source_url") or "").strip()
        if not label:
            continue
        key = url.lower() or label.lower()
        if key in seen:
            continue
        seen.add(key)
        refs.append(SourceRef(label=label[:200], url=url))

    for url in input_urls:
        if not is_institutional(url):
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        refs.append(SourceRef(label=press_display_name(url) or url, url=url))

    return refs[:10]


def collect_press_sources(input_urls: list[str]) -> list[SourceRef]:
    """Um veículo por domínio. Dois links para a mesma casa entregam o método."""
    refs: list[SourceRef] = []
    seen_hosts: set[str] = set()
    for url in input_urls:
        if is_institutional(url):
            continue
        host = registrable_host(url)
        if not host or host in seen_hosts:
            continue
        seen_hosts.add(host)
        refs.append(SourceRef(label=press_display_name(url), url=url))
    return refs[:6]


def _join_names(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} e {names[-1]}"


def render_sources_block(
    primary: list[SourceRef],
    press: list[SourceRef],
) -> str:
    """Monta o rodapé de fontes em código, não no modelo.

    Duas camadas com papéis diferentes: referência institucional em lista
    visível e com link ativo, e apuração de imprensa em uma linha, nofollow e
    sem repetir a manchete de quem publicou primeiro.
    """
    parts: list[str] = []

    if primary:
        itens: list[str] = []
        for ref in primary:
            label = html.escape(ref.label)
            if ref.url:
                itens.append(
                    f'<li><a href="{html.escape(ref.url, quote=True)}" rel="noopener">{label}</a></li>'
                )
            else:
                itens.append(f"<li>{label}</li>")
        parts.append(
            '<section class="bc-primary-sources">'
            "<h2>Dados e referências</h2>"
            f"<ul>{''.join(itens)}</ul>"
            "</section>"
        )

    if press:
        links = [
            f'<a href="{html.escape(ref.url, quote=True)}" rel="nofollow noopener">'
            f"{html.escape(ref.label)}</a>"
            for ref in press
        ]
        parts.append(
            '<p class="bc-sources"><small>Apuração a partir de material publicado por '
            f"{_join_names(links)}. O texto acima é original do Bolso Coberto."
            "</small></p>"
        )

    return "".join(parts)


def render_trust_links(*, site_url: str) -> str:
    """Link interno para as páginas de confiança — sinal de E-E-A-T em YMYL.

    Com corpus pequeno o linker automático não acha âncora entre matérias;
    estas duas URLs sempre existem depois da higiene e não canibalizam pauta.
    """
    base = (site_url or "").rstrip("/")
    if not base:
        return ""
    editorial = html.escape(f"{base}/politica-editorial/", quote=True)
    sobre = html.escape(f"{base}/sobre/", quote=True)
    return (
        '<p class="bc-note bc-trust-links">Este texto segue a '
        f'<a href="{editorial}">política editorial</a> do '
        f'<a href="{sobre}">Bolso Coberto</a>: dado conferido na fonte e '
        "revisão humana antes de publicar.</p>"
    )


def render_takeaways(takeaways: list[str]) -> str:
    if not takeaways:
        return ""
    itens = "".join(f"<li>{html.escape(item)}</li>" for item in takeaways)
    return (
        '<div class="bc-takeaways">'
        "<p><strong>O que muda no seu bolso</strong></p>"
        f"<ul>{itens}</ul>"
        "</div>"
    )


def render_faq(faq: list[dict[str, str]]) -> str:
    if not faq:
        return ""
    blocos = "".join(
        f'<div class="bc-faq-item"><h3>{html.escape(item["question"])}</h3>'
        f"<p>{html.escape(item['answer'])}</p></div>"
        for item in faq
    )
    return f'<section class="bc-faq"><h2>Perguntas frequentes</h2>{blocos}</section>'
