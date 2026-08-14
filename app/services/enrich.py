from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Séries do SGS/Banco Central. API pública, sem chave.
SERIE_SELIC_META = 432
SERIE_CDI_ANUALIZADO = 4390
SERIE_IPCA_MENSAL = 433
SERIE_DOLAR_VENDA = 1

_SGS_PATH = "/dados/serie/bcdata.sgs.{code}/dados/ultimos/{count}?formato=json"

# Tabela regressiva de IR em renda fixa (Lei 11.033/2004).
IR_ATE_180 = 0.225
IR_181_360 = 0.20
IR_361_720 = 0.175
IR_ACIMA_720 = 0.15

# Poupança rende 0,5% a.m. + TR enquanto a Selic meta passa de 8,5% a.a.
POUPANCA_TETO_SELIC = 8.5
POUPANCA_MENSAL = 0.005

VALORES_SIMULACAO = (1_000.0, 10_000.0, 100_000.0)


@dataclass(frozen=True, slots=True)
class SeriePonto:
    data: date
    valor: float


@dataclass(frozen=True, slots=True)
class MacroSnapshot:
    selic: float | None = None
    selic_data: date | None = None
    selic_serie: tuple[float, ...] = ()
    cdi: float | None = None
    cdi_data: date | None = None
    ipca_12m: float | None = None
    ipca_data: date | None = None
    ipca_serie: tuple[float, ...] = ()
    dolar: float | None = None
    dolar_data: date | None = None

    @property
    def is_empty(self) -> bool:
        return self.selic is None and self.cdi is None and self.ipca_12m is None

    def as_dict(self) -> dict[str, object]:
        return {
            "selic": self.selic,
            "selic_data": self.selic_data.isoformat() if self.selic_data else None,
            "selic_serie": list(self.selic_serie),
            "cdi": self.cdi,
            "cdi_data": self.cdi_data.isoformat() if self.cdi_data else None,
            "ipca_12m": self.ipca_12m,
            "ipca_data": self.ipca_data.isoformat() if self.ipca_data else None,
            "ipca_serie": list(self.ipca_serie),
            "dolar": self.dolar,
            "dolar_data": self.dolar_data.isoformat() if self.dolar_data else None,
        }


def _parse_points(payload: object) -> list[SeriePonto]:
    if not isinstance(payload, list):
        return []
    points: list[SeriePonto] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        raw_date = str(item.get("data") or "")
        raw_value = str(item.get("valor") or "").replace(",", ".")
        try:
            parsed_date = datetime.strptime(raw_date, "%d/%m/%Y").date()
            parsed_value = float(raw_value)
        except ValueError:
            continue
        points.append(SeriePonto(data=parsed_date, valor=parsed_value))
    return points


async def _fetch_series(client: httpx.AsyncClient, code: int, count: int) -> list[SeriePonto]:
    path = _SGS_PATH.format(code=code, count=count)
    try:
        response = await client.get(f"{settings.bcb_api_base.rstrip('/')}{path}")
    except httpx.HTTPError:
        logger.warning("SGS indisponível", extra={"serie": code})
        return []
    if response.status_code >= 400:
        logger.warning(
            "SGS recusou",
            extra={"serie": code, "status": response.status_code},
        )
        return []
    try:
        return _parse_points(response.json())
    except ValueError:
        return []


async def fetch_macro_snapshot() -> MacroSnapshot:
    """Puxa os indicadores do BCB. Falha de rede nunca derruba a pauta."""
    timeout = httpx.Timeout(settings.bcb_timeout_seconds, connect=5.0)
    headers = {"User-Agent": "BolsoCobertoEditor/1.0", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            selic = await _fetch_series(client, SERIE_SELIC_META, 12)
            cdi = await _fetch_series(client, SERIE_CDI_ANUALIZADO, 1)
            ipca = await _fetch_series(client, SERIE_IPCA_MENSAL, 12)
            dolar = await _fetch_series(client, SERIE_DOLAR_VENDA, 1)
    except Exception:
        logger.exception("Falha ao montar snapshot macro")
        return MacroSnapshot()

    ipca_12m: float | None = None
    ipca_data: date | None = None
    if len(ipca) == 12:
        acumulado = 1.0
        for point in ipca:
            acumulado *= 1 + point.valor / 100
        ipca_12m = (acumulado - 1) * 100
        ipca_data = ipca[-1].data

    return MacroSnapshot(
        selic=selic[-1].valor if selic else None,
        selic_data=selic[-1].data if selic else None,
        selic_serie=tuple(point.valor for point in selic),
        cdi=cdi[-1].valor if cdi else None,
        cdi_data=cdi[-1].data if cdi else None,
        ipca_12m=ipca_12m,
        ipca_data=ipca_data,
        ipca_serie=tuple(point.valor for point in ipca),
        dolar=dolar[-1].valor if dolar else None,
        dolar_data=dolar[-1].data if dolar else None,
    )


def _br_number(value: float, decimals: int = 2) -> str:
    formatted = f"{value:,.{decimals}f}"
    return formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _br_money(value: float) -> str:
    return f"R$ {_br_number(value)}"


def _br_percent(value: float, decimals: int = 2) -> str:
    return f"{_br_number(value, decimals)}%"


def _br_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "-"


def poupanca_anual(selic: float) -> float:
    """Regra da poupança pós-2012, com TR tratada como zero.

    Acima do teto rende 0,5% ao mês; abaixo dele, 70% da Selic meta.
    """
    if selic > POUPANCA_TETO_SELIC:
        return ((1 + POUPANCA_MENSAL) ** 12 - 1) * 100
    return selic * 0.70


def render_fixed_income_table(snapshot: MacroSnapshot) -> str:
    """Tabela de rendimento em 12 meses, calculada aqui e não pedida ao modelo.

    Números determinísticos não alucinam e nenhuma das fontes de pauta publica
    esse recorte, o que é exatamente o valor original que o Google cobra.
    """
    if snapshot.cdi is None and snapshot.selic is None:
        return ""
    cdi = snapshot.cdi if snapshot.cdi is not None else snapshot.selic
    selic = snapshot.selic if snapshot.selic is not None else cdi
    assert cdi is not None and selic is not None

    cdb_bruto = cdi / 100
    lci_taxa = cdi * 0.90 / 100
    poupanca_taxa = poupanca_anual(selic) / 100

    linhas: list[str] = []
    for principal in VALORES_SIMULACAO:
        cdb_liquido = principal * cdb_bruto * (1 - IR_361_720)
        lci_liquido = principal * lci_taxa
        poupanca_liquido = principal * poupanca_taxa
        linhas.append(
            "<tr>"
            f"<th scope=\"row\">{_br_money(principal)}</th>"
            f"<td>{_br_money(cdb_liquido)}</td>"
            f"<td>{_br_money(lci_liquido)}</td>"
            f"<td>{_br_money(poupanca_liquido)}</td>"
            "</tr>"
        )

    referencia = _br_date(snapshot.cdi_data or snapshot.selic_data)
    return (
        '<div class="bc-table-wrap">'
        "<table>"
        f"<caption>Quanto rende em 12 meses com CDI a {_br_percent(cdi)} ao ano "
        f"(referência de {referencia}). Cálculo do Bolso Coberto.</caption>"
        "<thead><tr>"
        '<th scope="col">Valor aplicado</th>'
        '<th scope="col">CDB 100% do CDI (líquido de IR)</th>'
        '<th scope="col">LCI/LCA 90% do CDI (isento)</th>'
        '<th scope="col">Poupança</th>'
        "</tr></thead>"
        f"<tbody>{''.join(linhas)}</tbody>"
        "</table>"
        '<p class="bc-note"><small>Rendimento no primeiro ano, sem aportes. '
        f"CDB considera IR de {_br_percent(IR_361_720 * 100, 1)} para aplicações acima de 360 dias. "
        "LCI/LCA são isentas de IR para pessoa física. "
        "Poupança segue a regra de 0,5% ao mês mais TR enquanto a Selic supera 8,5% ao ano. "
        "Rentabilidade passada não garante resultado futuro.</small></p>"
        "</div>"
    )


def render_macro_context(snapshot: MacroSnapshot) -> str:
    if snapshot.is_empty:
        return ""
    itens: list[str] = []
    if snapshot.selic is not None:
        itens.append(
            f"<li>Selic meta em <strong>{_br_percent(snapshot.selic)} ao ano</strong> "
            f"({_br_date(snapshot.selic_data)})</li>"
        )
    if snapshot.cdi is not None:
        itens.append(
            f"<li>CDI anualizado em <strong>{_br_percent(snapshot.cdi)}</strong> "
            f"({_br_date(snapshot.cdi_data)})</li>"
        )
    if snapshot.ipca_12m is not None:
        itens.append(
            f"<li>IPCA acumulado em 12 meses: <strong>{_br_percent(snapshot.ipca_12m)}</strong> "
            f"({_br_date(snapshot.ipca_data)})</li>"
        )
    if snapshot.dolar is not None:
        itens.append(
            f"<li>Dólar comercial a <strong>{_br_money(snapshot.dolar)}</strong> "
            f"({_br_date(snapshot.dolar_data)})</li>"
        )
    if snapshot.selic is not None and snapshot.ipca_12m is not None:
        juro_real = ((1 + snapshot.selic / 100) / (1 + snapshot.ipca_12m / 100) - 1) * 100
        itens.append(f"<li>Juro real da Selic: <strong>{_br_percent(juro_real)} ao ano</strong></li>")
    if not itens:
        return ""
    return (
        '<div class="bc-note">'
        "<p><strong>Os números do dia, direto do Banco Central</strong></p>"
        f"<ul>{''.join(itens)}</ul>"
        "</div>"
    )


def hero_fields(snapshot: MacroSnapshot) -> dict[str, object] | None:
    """Dados para a capa. Um gráfico do indicador é relevante e específico,
    ao contrário de foto de banco de imagem, que o Discover trata como genérica."""
    if snapshot.selic is not None and len(snapshot.selic_serie) >= 3:
        return {
            "label": "Selic meta",
            "value": f"{_br_percent(snapshot.selic)} ao ano",
            "reference": f"Banco Central · {_br_date(snapshot.selic_data)}",
            "series": list(snapshot.selic_serie),
        }
    if snapshot.ipca_12m is not None and len(snapshot.ipca_serie) >= 3:
        return {
            "label": "IPCA em 12 meses",
            "value": _br_percent(snapshot.ipca_12m),
            "reference": f"IBGE · {_br_date(snapshot.ipca_data)}",
            "series": list(snapshot.ipca_serie),
        }
    return None


def snapshot_facts(snapshot: MacroSnapshot) -> list[str]:
    """Fatos oficiais entregues ao redator junto com o ledger das pautas."""
    if snapshot.is_empty:
        return []
    facts: list[str] = []
    if snapshot.selic is not None:
        facts.append(
            f"Selic meta: {_br_percent(snapshot.selic)} ao ano em {_br_date(snapshot.selic_data)} "
            "(Banco Central, série SGS 432)."
        )
    if snapshot.cdi is not None:
        facts.append(
            f"CDI anualizado: {_br_percent(snapshot.cdi)} em {_br_date(snapshot.cdi_data)} "
            "(Banco Central, série SGS 4390)."
        )
    if snapshot.ipca_12m is not None:
        facts.append(
            f"IPCA acumulado em 12 meses: {_br_percent(snapshot.ipca_12m)} até "
            f"{_br_date(snapshot.ipca_data)} (IBGE via SGS 433)."
        )
    if snapshot.dolar is not None:
        facts.append(
            f"Dólar comercial (venda): {_br_money(snapshot.dolar)} em {_br_date(snapshot.dolar_data)} "
            "(Banco Central, série SGS 1)."
        )
    return facts
