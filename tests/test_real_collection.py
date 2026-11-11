"""Testes unitários (TDD) para a integração de coleta real de dados públicos de Santa Catarina."""

from __future__ import annotations

from pathlib import Path

import httpx
import pandas as pd
import pytest

from collect_tce import (
    coletar_dados_abertos_sc,
    coletar_emendas_tce_sc,
    coletar_populacao_ibge,
    extrair_cnpj_e_nome_credor,
    limpar_area_subacao,
    obter_partido_parlamentar_sc,
    resolver_usar_rede,
)


def test_resolver_usar_rede_respeita_parametro_env_e_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica a prioridade de resolução do modo de rede (explícito > env > pytest offline > produção real)."""
    assert resolver_usar_rede(True) is True
    assert resolver_usar_rede(False) is False

    monkeypatch.setenv("VIGIA_USAR_REDE", "1")
    assert resolver_usar_rede(None) is True

    monkeypatch.setenv("VIGIA_USAR_REDE", "false")
    assert resolver_usar_rede(None) is False

    monkeypatch.delenv("VIGIA_USAR_REDE", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_algo.py::test_x")
    assert resolver_usar_rede(None) is False

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert resolver_usar_rede(None) is True


def test_coletar_populacao_ibge_api_real_extrai_municipios_sem_sufixo_sc(tmp_path: Path) -> None:
    """Verifica se a coleta real do IBGE extrai código, nome sem '- SC' e população estimada."""
    payload_ibge = [
        {
            "id": "9324",
            "variavel": "População residente estimada",
            "resultados": [
                {
                    "series": [
                        {
                            "localidade": {"id": "4200051", "nome": "Abdon Batista - SC"},
                            "serie": {"2026": "2628"},
                        },
                        {
                            "localidade": {"id": "4205407", "nome": "Florianópolis - SC"},
                            "serie": {"2026": "587486"},
                        },
                    ]
                }
            ],
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        """Simula resposta oficial da API de Agregados 6579 do IBGE."""
        assert "agregados/6579" in str(request.url)
        return httpx.Response(200, json=payload_ibge)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    caminho = coletar_populacao_ibge(output_dir=tmp_path, usar_api_ibge=True, client=client)

    df = pd.read_csv(caminho, dtype={"codigo_ibge": str})
    abdon = df[df["codigo_ibge"] == "4200051"].iloc[0]
    assert abdon["municipio"] == "Abdon Batista"
    assert int(abdon["populacao"]) == 2628

    floripa = df[df["codigo_ibge"] == "4205407"].iloc[0]
    assert floripa["municipio"] == "Florianópolis"
    assert int(floripa["populacao"]) == 587486


def test_coletar_dados_abertos_sc_api_real_despesas_e_ckan_transferencias(tmp_path: Path) -> None:
    """Verifica o download real de despesas estaduais (latin-1) e streaming limitado de transferências CKAN."""
    csv_despesas_latin1 = (
        "cdunidadegestora;nmunidadegestora;vlempenhado;vlliquidado;vlpago\n"
        '480091;"Fundo Estadual de Saúde";1500000,50;1200000,00;1000000,00\n'
    ).encode("latin-1")

    ckan_meta = {
        "success": True,
        "result": {
            "resources": [
                {
                    "format": "CSV",
                    "name": "Transferencias-SC.csv",
                    "url": "https://dados.sc.gov.br/download/transferencias.csv",
                }
            ]
        },
    }
    csv_transf_latin1 = (
        "nuanoexercicio;nmmunicipiocredor;nmcredor;nuidentificacao;vlpago\n"
        '2026;TUBARAO;"ASSOCIACAO HOSPITALAR DE TUBARAO";83706929000168;250000,00\n'
        '2026;CHAPECO;"FUNDO MUNICIPAL DE SAUDE";83021808000182;400000,00\n'
        '2026;JOINVILLE;"LINHA EXTRA QUE DEVE SER CORTADA";83169623000110;90000,00\n'
    ).encode("latin-1")

    def handler(request: httpx.Request) -> httpx.Response:
        """Simula respostas das APIs de Despesa do Portal da Transparência SC e CKAN Dados Abertos SC."""
        url = str(request.url)
        if "despesa/exportcsv" in url:
            return httpx.Response(200, content=csv_despesas_latin1)
        if "package_show" in url:
            return httpx.Response(200, json=ckan_meta)
        if "download/transferencias.csv" in url:
            return httpx.Response(200, content=csv_transf_latin1)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    caminhos = coletar_dados_abertos_sc(output_dir=tmp_path, usar_rede=True, max_linhas=2, client=client)

    df_desp = pd.read_csv(caminhos["despesas"])
    assert len(df_desp) == 1
    assert "Fundo Estadual de Saúde" in str(df_desp.iloc[0].to_dict())

    df_transf = pd.read_csv(caminhos["transferencias"])
    assert len(df_transf) == 2
    assert "TUBARAO" in str(df_transf.iloc[0].to_dict())


def test_parsers_credor_area_e_partido_emendas_sc() -> None:
    """Verifica extração de CNPJ/credor, limpeza da área da subação e mapeamento de partido da ALESC."""
    cnpj, nome = extrair_cnpj_e_nome_credor("83.006.650/0001-71  FUNDACAO HOSPITALAR ALEX KRIESER")
    assert cnpj == "83006650000171"
    assert nome == "FUNDACAO HOSPITALAR ALEX KRIESER"

    assert limpar_area_subacao("Emendas parlamentares impositivas da Saúde") == "Saúde"
    assert (
        limpar_area_subacao("Emendas parlamentares impositivas da Infraestrutura e Mobilidade")
        == "Infraestrutura e Mobilidade"
    )
    assert obter_partido_parlamentar_sc("JULIO CESAR GARCIA") == "PSD"
    assert obter_partido_parlamentar_sc("BANCADA DO OESTE") == "Bancada Regional"


def test_coletar_emendas_tce_sc_api_real_portal_transparencia_e_cache(tmp_path: Path) -> None:
    """Verifica coleta real de emendas (exportcsv + extratoemenda + cache JSON) com as 14 colunas exigidas."""
    csv_indice = (
        "ano;numero;parlamentar_bancada;modalidade;liberado_execucao;situacao;valor;empenhado;liquidado;pago\n"
        '2026;2026EP000001;"NEODI SARETTA";"Transferência Especial";Sim;Ativo;100000;100000;100000;100000\n'
        '2026;2026EP001979;"JULIO CESAR GARCIA";"Convênio";Sim;Ativo;350000;350000;0;0\n'
    ).encode("latin-1")

    extratos = {
        "2026EP000001": {
            "emenda": {
                "emendaIdentificacao": {
                    "nuano": "2026",
                    "nuemendaparlamentar": "2026EP000001",
                    "nmparlamentar": "NEODI SARETTA",
                    "identificacaocredor": "78.511.052/0001-10  MUNICIPIO DE ABDON BATISTA",
                    "nmlocalidade": "Abdon Batista",
                    "nmsubacao": "Emendas parlamentares impositivas da Agricultura",
                    "vlemendaparlamentar": "100000",
                },
                "emendaEmpenho": [{"dtlancamento": "2026-06-26 00:00:00"}],
                "emendaLiquidacao": [{"dtlancamento": "2026-06-26 00:00:00"}],
                "emendaPagamento": [{"dtlancamento": "2026-06-30 00:00:00"}],
            }
        },
        "2026EP001979": {
            "emenda": {
                "emendaIdentificacao": {
                    "nuano": "2026",
                    "nuemendaparlamentar": "2026EP001979",
                    "nmparlamentar": "JULIO CESAR GARCIA",
                    "identificacaocredor": "83.006.650/0001-71  FUNDACAO HOSPITALAR ALEX KRIESER",
                    "nmlocalidade": "Florianópolis",
                    "nmsubacao": "Emendas parlamentares impositivas da Saúde",
                    "vlemendaparlamentar": "350000",
                },
                "emendaEmpenho": [{"dtlancamento": "2026-05-14 00:00:00"}],
                "emendaLiquidacao": [],
                "emendaPagamento": [],
            }
        },
    }

    chamadas_extrato: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Simula endpoints de exportcsv e extratoemenda do Portal da Transparência SC."""
        url = str(request.url)
        if "emendaparlamentar/exportcsv" in url:
            return httpx.Response(200, content=csv_indice)
        if "emendaparlamentar/extratoemenda" in url:
            for codigo, payload in extratos.items():
                if codigo in url:
                    chamadas_extrato.append(codigo)
                    return httpx.Response(200, json=payload)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    caminho = coletar_emendas_tce_sc(
        output_dir=tmp_path,
        data_ref="20261111",
        usar_rede=True,
        max_emendas=10,
        client=client,
    )

    assert caminho.exists()
    assert len(chamadas_extrato) == 2

    df = pd.read_csv(caminho, dtype={"fornecedor_cnpj": str, "codigo_ibge": str})
    assert len(df) == 2
    row_convenio = df[df["id_emenda"] == "2026EP001979"].iloc[0]
    assert row_convenio["fornecedor_cnpj"] == "83006650000171"
    assert row_convenio["fornecedor_nome"] == "FUNDACAO HOSPITALAR ALEX KRIESER"
    assert row_convenio["area"] == "Saúde"
    assert row_convenio["partido"] == "PSD"
    assert row_convenio["status_execucao"] == "Empenhado"
    assert row_convenio["data"] == "2026-05-14"
    assert "2026EP001979" in row_convenio["fonte_url"]

    # Segunda chamada deve reutilizar o cache de extratos em disco sem novas requisições de extrato
    coletar_emendas_tce_sc(
        output_dir=tmp_path,
        data_ref="20261111",
        usar_rede=True,
        max_emendas=10,
        client=client,
    )
    assert len(chamadas_extrato) == 2

