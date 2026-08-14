from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import trafilatura

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

USER_AGENT = (
    "BolsoCobertoBot/1.0 (+https://bolsocoberto.com.br/sobre; pauta editorial, nao scraper comercial)"
)
MAX_REDIRECTS = 3
BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata",
    }
)
BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)


class FetchError(Exception):
    def __init__(self, message: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    text: str
    http_status: int


def parse_http_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url or len(url) > 2048:
        raise FetchError("URL vazia ou longa demais.")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise FetchError("Só http/https.")
    if not parsed.hostname:
        raise FetchError("URL sem host.")
    if parsed.username or parsed.password:
        raise FetchError("URL com credencial não é aceita.")
    return url


def _is_blocked_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if address.is_private or address.is_loopback or address.is_link_local:
        return True
    if address.is_multicast or address.is_reserved or address.is_unspecified:
        return True
    return any(address in network for network in BLOCKED_NETWORKS)


def assert_public_host(hostname: str) -> None:
    host = hostname.strip().lower().rstrip(".")
    if not host or host in BLOCKED_HOSTS or host.endswith(".local"):
        raise FetchError("Host não permitido.")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_blocked_ip(literal):
            raise FetchError("IP privado/reservado não é permitido.")
        return
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError("Não resolveu o host.") from exc
    if not infos:
        raise FetchError("Não resolveu o host.")
    for info in infos:
        packed = info[4][0]
        ip = ipaddress.ip_address(packed)
        if _is_blocked_ip(ip):
            raise FetchError("Host resolve para rede privada.")


async def fetch_readable(url: str) -> FetchResult:
    current = parse_http_url(url)
    timeout = httpx.Timeout(settings.fetch_timeout_seconds, connect=8.0)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        max_redirects=0,
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            assert parsed.hostname is not None
            assert_public_host(parsed.hostname)
            try:
                response = await client.get(current)
            except httpx.HTTPError as exc:
                raise FetchError("Falha de rede ao baixar a URL.") from exc
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise FetchError("Redirect sem Location.", response.status_code)
                current = str(response.url.join(location))
                continue
            if response.status_code >= 400:
                raise FetchError(
                    f"HTTP {response.status_code} ao baixar a fonte.",
                    response.status_code,
                )
            content_type = (response.headers.get("content-type") or "").lower()
            if "html" not in content_type and "xml" not in content_type and "text/" not in content_type:
                raise FetchError("Resposta não é HTML/texto.", response.status_code)
            body = response.content[: settings.fetch_max_bytes + 1]
            if len(body) > settings.fetch_max_bytes:
                raise FetchError("Página maior que o limite.", response.status_code)
            extracted = trafilatura.extract(
                body.decode(response.encoding or "utf-8", errors="replace"),
                url=str(response.url),
                include_comments=False,
                include_tables=False,
                favor_precision=True,
            )
            text = (extracted or "").strip()
            if len(text) < 80:
                raise FetchError("Não deu para extrair texto útil (paywall, JS ou vazio).")
            return FetchResult(url=str(response.url), text=text[:80_000], http_status=response.status_code)
    raise FetchError("Muitos redirects.")
