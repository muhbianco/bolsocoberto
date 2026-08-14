from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import enrich, similarity
from app.services.content_html import (
    apply_link_policy,
    insert_after_first_paragraph,
    sanitize_html,
)
from app.services.internal_links import LinkSuggestion, find_cannibals, inject_links
from app.services.sources import (
    collect_press_sources,
    collect_primary_sources,
    is_institutional,
    render_sources_block,
)

FONTE = (
    "O IBGE informou nesta quinta-feira que as vendas no varejo brasileiro "
    "cresceram 0,5% em junho na comparacao mensal, encerrando o segundo "
    "trimestre com desempenho acima do esperado pelo mercado financeiro."
)


class TestSimilaridade:
    def test_texto_colado_e_reprovado(self) -> None:
        colado = FONTE[: int(len(FONTE) * 0.8)]
        report = similarity.compare(colado, [("https://veiculo.example/x", FONTE)])
        assert report.max_containment > 0.8
        assert report.longest_run_words >= 20
        assert report.worst_url == "https://veiculo.example/x"

    def test_texto_proprio_passa(self) -> None:
        proprio = (
            "Quem depende de credito rotativo sente primeiro. O varejo avancou meio "
            "ponto percentual, e isso muda a conta de quem parcela compras no cartao "
            "todo mes, porque demanda aquecida sustenta juro alto por mais tempo."
        )
        report = similarity.compare(proprio, [("u", FONTE)])
        assert report.max_containment < 0.05

    def test_sem_fonte_ou_texto_curto_nao_quebra(self) -> None:
        assert similarity.compare("qualquer coisa", []).max_containment == 0.0
        assert similarity.compare("oi", [("u", FONTE)]).max_containment == 0.0


class TestLinkInterno:
    def test_insere_um_link_e_pula_paragrafo_com_ancora(self) -> None:
        corpo = (
            "<p>A Selic subiu e muda o custo do seguro de vida de quem contratou agora.</p>"
            "<p>Ja existe <a href='/x'>um link</a> e tambem seguro de vida aqui.</p>"
        )
        sugestao = LinkSuggestion(
            wp_post_id=7,
            title="Seguro de vida vale a pena",
            url="https://bolsocoberto.com.br/seguro-de-vida",
            phrase="seguro de vida",
            score=1.0,
        )
        resultado, aplicados = inject_links(corpo, [sugestao])
        assert resultado.count("bolsocoberto.com.br/seguro-de-vida") == 1
        assert "<a href='/x'>um link</a>" in resultado
        assert len(aplicados) == 1

    def test_frase_sem_acento_casa_texto_acentuado_sem_corromper(self) -> None:
        corpo = "<p>O financiamento imobiliário ficou mais caro este mês.</p>"
        sugestao = LinkSuggestion(
            wp_post_id=9,
            title="Financiamento imobiliario passo a passo",
            url="https://bolsocoberto.com.br/fin",
            phrase="financiamento imobiliario",
            score=1.0,
        )
        resultado, aplicados = inject_links(corpo, [sugestao])
        assert len(aplicados) == 1
        assert "financiamento imobiliário</a>" in resultado
        assert "ficou mais caro este mês." in resultado

    def test_detecta_canibalizacao(self) -> None:
        posts = [
            SimpleNamespace(
                wp_post_id=1,
                title="Seguro de vida vale a pena em 2026",
                link="https://bolsocoberto.com.br/a",
                category_slug="seguros",
            ),
            SimpleNamespace(
                wp_post_id=2,
                title="Como declarar criptomoeda no imposto de renda",
                link="https://bolsocoberto.com.br/b",
                category_slug="financas",
            ),
        ]
        encontrados = find_cannibals(posts, title="seguro de vida vale a pena", topic="")
        assert [post.wp_post_id for post in encontrados] == [1]


class TestPoliticaDeFontes:
    def test_classifica_institucional_por_sufixo_e_lista(self) -> None:
        assert is_institutional("https://www.ibge.gov.br/estatisticas/pmc")
        assert is_institutional("https://www.b3.com.br/indices")
        assert not is_institutional("https://www.infomoney.com.br/mercados/di-sobe")

    def test_um_link_por_veiculo_e_sem_manchete(self) -> None:
        urls = [
            "https://www.infomoney.com.br/mercados/di-sobe-hoje",
            "https://www.infomoney.com.br/mercados/di-sobe-de-novo",
            "https://valor.globo.com/financas/noticia",
        ]
        press = collect_press_sources(urls)
        assert [ref.label for ref in press] == ["InfoMoney", "Valor Econômico"]

        bloco = render_sources_block([], press)
        assert 'rel="nofollow noopener"' in bloco
        assert "di-sobe-de-novo" not in bloco
        assert "Apuração a partir de material publicado por" in bloco

    def test_fonte_primaria_vem_do_ledger(self) -> None:
        ledger = [
            {
                "claim": "Varejo cresceu 0,5% em junho",
                "primary_source": "IBGE - Pesquisa Mensal de Comércio",
                "primary_source_url": "https://www.ibge.gov.br/pmc",
            }
        ]
        primary = collect_primary_sources(ledger, ["https://www.infomoney.com.br/x"])
        assert primary[0].label.startswith("IBGE")

        bloco = render_sources_block(primary, [])
        assert "Dados e referências" in bloco
        # Fonte institucional passa autoridade de propósito: nada de nofollow.
        assert "nofollow" not in bloco


class TestHtml:
    def test_sanitizador_aceita_tabela_e_recusa_script(self) -> None:
        cru = (
            '<table><tr><th scope="col">a</th><td>b</td></tr></table>'
            '<script>alert(1)</script><p onclick="x()">oi</p>'
        )
        limpo = sanitize_html(cru)
        assert "<table>" in limpo and "<th scope=" in limpo
        assert "script" not in limpo and "onclick" not in limpo

    def test_sanitizador_filtra_classe_fora_da_allowlist(self) -> None:
        limpo = sanitize_html('<div class="bc-takeaways">a</div><div class="hack">b</div>')
        assert 'class="bc-takeaways"' in limpo
        assert 'class="hack"' not in limpo

    def test_politica_de_link_separa_interno_veiculo_e_institucional(self) -> None:
        corpo = (
            '<p><a href="https://bolsocoberto.com.br/x">interno</a> '
            '<a href="https://www.infomoney.com.br/y">veiculo</a> '
            '<a href="https://www.bcb.gov.br/z">orgao</a></p>'
        )
        resultado = apply_link_policy(
            corpo,
            site_host="bolsocoberto.com.br",
            nofollow_hosts={"infomoney.com.br"},
        )
        assert '<a href="https://bolsocoberto.com.br/x">' in resultado
        assert '<a href="https://www.infomoney.com.br/y" rel="nofollow noopener">' in resultado
        assert '<a href="https://www.bcb.gov.br/z" rel="noopener">' in resultado

    def test_bloco_entra_depois_da_abertura(self) -> None:
        assert (
            insert_after_first_paragraph("<p>um</p><p>dois</p>", "<div>X</div>")
            == "<p>um</p><div>X</div><p>dois</p>"
        )
        assert insert_after_first_paragraph("<p>a</p>", "") == "<p>a</p>"


class TestCalculoFinanceiro:
    @pytest.fixture
    def snapshot(self) -> enrich.MacroSnapshot:
        return enrich.MacroSnapshot(
            selic=15.0,
            selic_data=date(2026, 8, 14),
            selic_serie=(13.0, 14.0, 14.75, 15.0),
            cdi=14.9,
            cdi_data=date(2026, 8, 14),
            ipca_12m=4.5,
            ipca_data=date(2026, 7, 31),
        )

    def test_regra_da_poupanca(self) -> None:
        assert enrich.poupanca_anual(15.0) == pytest.approx(6.1678, abs=0.001)
        assert enrich.poupanca_anual(8.0) == pytest.approx(5.6)

    def test_tabela_de_renda_fixa_bate_na_mao(self, snapshot: enrich.MacroSnapshot) -> None:
        tabela = enrich.render_fixed_income_table(snapshot)
        # 100.000 x 14,9% x (1 - 17,5% de IR) = 12.292,50
        assert "R$ 12.292,50" in tabela
        # 100.000 x 14,9% x 90%, isento de IR = 13.410,00
        assert "R$ 13.410,00" in tabela
        assert 'class="bc-table-wrap"' in tabela

    def test_sem_dado_nao_inventa_bloco(self) -> None:
        vazio = enrich.MacroSnapshot()
        assert enrich.render_fixed_income_table(vazio) == ""
        assert enrich.render_macro_context(vazio) == ""
        assert enrich.snapshot_facts(vazio) == []

    def test_capa_prefere_serie_da_selic(self, snapshot: enrich.MacroSnapshot) -> None:
        campos = enrich.hero_fields(snapshot)
        assert campos is not None
        assert campos["label"] == "Selic meta"
        assert len(campos["series"]) == 4
