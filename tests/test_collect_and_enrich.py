"""Testes unitários para a Fase 1 — Coleta de dados (TCE/SC, IBGE, Dados Abertos SC e Receita Federal/CNPJ)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from collect_tce import (
    coletar_dados_abertos_sc,
    coletar_emendas_tce_sc,
    coletar_populacao_ibge,
    executar_coleta_completa,
)
from enrich_cnpj import enriquecer_cnpj, enriquecer_lote_cnpjs, limpar_cnpj, sanear_cnpjs_fallback


def test_coletar_emendas_tce_sc_cria_csv_com_colunas_obrigatorias(tmp_path: Path) -> None:
    """Verifica se a coleta do TCE/SC gera o CSV datado com todas as colunas mínimas exigidas."""
    caminho_csv = coletar_emendas_tce_sc(output_dir=tmp_path, data_ref="20261110")
    assert caminho_csv.exists()
    assert caminho_csv.name == "emendas_20261110.csv"

    df = pd.read_csv(caminho_csv, dtype={"fornecedor_cnpj": str, "codigo_ibge": str})
    colunas_esperadas = {
        "id_emenda",
        "parlamentar",
        "partido",
        "valor",
        "municipio",
        "codigo_ibge",
        "entidade_beneficiaria",
        "area",
        "data",
        "fornecedor_nome",
        "fornecedor_cnpj",
        "uf_fornecedor",
        "status_execucao",
        "fonte_url",
    }
    assert colunas_esperadas.issubset(set(df.columns))
    assert len(df) >= 20
    assert (df["valor"] > 0).all()


def test_coletar_populacao_ibge_cria_csv_valido(tmp_path: Path) -> None:
    """Verifica se a coleta populacional do IBGE gera populacao_ibge.csv com código IBGE, município e população."""
    caminho_ibge = coletar_populacao_ibge(output_dir=tmp_path)
    assert caminho_ibge.exists()
    assert caminho_ibge.name == "populacao_ibge.csv"

    df = pd.read_csv(caminho_ibge, dtype={"codigo_ibge": str})
    assert {"codigo_ibge", "municipio", "populacao"}.issubset(set(df.columns))
    assert len(df) >= 20
    assert (df["populacao"] > 0).all()
    assert "Florianópolis" in df["municipio"].values or "FLORIANOPOLIS" in df["municipio"].str.upper().values


def test_coletar_dados_abertos_sc_cria_despesas_e_transferencias(tmp_path: Path) -> None:
    """Verifica se a coleta complementar de Dados Abertos SC salva despesas_sc.csv e transferencias_sc.csv."""
    caminhos = coletar_dados_abertos_sc(output_dir=tmp_path)
    assert caminhos["despesas"].exists()
    assert caminhos["transferencias"].exists()
    assert caminhos["despesas"].name == "despesas_sc.csv"
    assert caminhos["transferencias"].name == "transferencias_sc.csv"


def test_enriquecer_cnpj_salva_json_com_campos_obrigatorios(tmp_path: Path) -> None:
    """Verifica se o enriquecimento de CNPJ retorna e salva data de abertura, capital social, CNAE e sócios."""
    cnpj_formatado = "12.345.678/0001-90"
    assert limpar_cnpj(cnpj_formatado) == "12345678000190"

    dados = enriquecer_cnpj(cnpj_formatado, output_dir=tmp_path, usar_rede=False)
    arquivo_json = tmp_path / "cnpj_12345678000190.json"
    assert arquivo_json.exists()

    conteudo = json.loads(arquivo_json.read_text(encoding="utf-8"))
    for campo in ("cnpj", "razao_social", "data_abertura", "capital_social", "cnae_principal", "uf", "socios"):
        assert campo in conteudo
        assert campo in dados
    assert isinstance(conteudo["socios"], list)


def test_executar_coleta_completa_e_lote_cnpjs(tmp_path: Path) -> None:
    """Verifica a orquestração completa da Fase 1 (raw + enriched)."""
    raw_dir = tmp_path / "raw"
    enriched_dir = tmp_path / "enriched"
    resumo = executar_coleta_completa(raw_dir=raw_dir, data_ref="20261110")
    assert Path(resumo["emendas_csv"]).exists()
    assert Path(resumo["populacao_csv"]).exists()

    df_emendas = pd.read_csv(resumo["emendas_csv"], dtype={"fornecedor_cnpj": str})
    cnpjs = df_emendas["fornecedor_cnpj"].dropna().unique().tolist()
    resultados = enriquecer_lote_cnpjs(cnpjs, output_dir=enriched_dir, usar_rede=False)
    assert len(resultados) == len(cnpjs)


def test_enriquecer_cnpj_api_extrai_cnae_formatado_secundarios_e_natureza(tmp_path: Path) -> None:
    """Verifica extração completa de CNAE principal formatado, CNAEs secundários e natureza jurídica na BrasilAPI."""
    import httpx

    payload = {
        "cnpj": "00058956000144",
        "razao_social": "ASSOCIACAO DE MORADORES DE BARRAGEM SUL",
        "nome_fantasia": "AMBS",
        "descricao_situacao_cadastral": "ATIVA",
        "data_inicio_atividade": "1994-05-10",
        "capital_social": 0.0,
        "codigo_natureza_juridica": 3999,
        "natureza_juridica": "Associação Privada",
        "cnae_fiscal": 9430800,
        "cnae_fiscal_descricao": "Atividades de associações de defesa de direitos sociais",
        "cnaes_secundarios": [
            {
                "codigo": 9493600,
                "descricao": "Atividades de organizações associativas ligadas à cultura e à arte",
            },
            {"codigo": 0, "descricao": ""},
        ],
        "uf": "SC",
        "municipio": "ITUPORANGA",
        "qsa": [{"nome_socio": "JOAO DA SILVA"}],
    }

    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))
    dados = enriquecer_cnpj(
        "00.058.956/0001-44",
        output_dir=tmp_path,
        usar_rede=True,
        client=client,
    )
    assert dados["cnae_principal"] == "9430-8/00 - Atividades de associações de defesa de direitos sociais"
    assert dados["cnaes_secundarios"] == [
        "9493-6/00 - Atividades de organizações associativas ligadas à cultura e à arte"
    ]
    assert dados["natureza_juridica_codigo"] == "3999"
    assert dados["natureza_juridica"] == "Associação Privada"
    assert dados["situacao_cadastral"] == "Ativa"


def test_enriquecer_cnpj_fallback_municipal_aplica_8411(tmp_path: Path) -> None:
    """Verifica que o fallback offline/404 aplica CNAE 8411-6/00 quando o favorecido é ente municipal."""
    dados = enriquecer_cnpj(
        "01566621000108",
        output_dir=tmp_path,
        usar_rede=False,
        nome_fallback="MUNICIPIO DE FLOR DO SERTAO",
    )
    assert dados["cnae_principal"] == "8411-6/00 - Administração pública em geral"
    assert dados["natureza_juridica_codigo"] == "1244"
    assert dados["cnaes_secundarios"] == []


def test_sanear_cnpjs_fallback_atualiza_json_cache_e_emendas_clean(tmp_path: Path) -> None:
    """Valida o saneamento de CNPJs legados (4789-0/99) via BrasilAPI e regra 8411-6/00 para municípios."""
    import sqlite3
    import httpx
    from cnpj_validator import limpar_mem_cache_cnpj, obter_cnaes_cnpj, salvar_cnpj_cache
    from database import inicializar_schema

    limpar_mem_cache_cnpj()
    db_path = tmp_path / "saneamento.db"
    enriched_dir = tmp_path / "enriched"
    enriched_dir.mkdir(parents=True, exist_ok=True)
    inicializar_schema(db_path)

    # Grava registros legados com fallback genérico 4789-0/99
    for cnpj_k, nome_k in [
        ("00058956000144", "ASSOC DE MORAD DE BARRAGEM SUL - ITUPORANGA"),
        ("01566620000155", "MUNICIPIO DE TIGRINHOS"),
    ]:
        legado = {
            "cnpj": cnpj_k,
            "razao_social": f"Fornecedor Cadastrado {cnpj_k[-4:]}",
            "data_abertura": "2019-06-01",
            "capital_social": 150000.0,
            "cnae_principal": "4789-0/99 - Comércio e serviços gerais",
            "uf": "SC",
            "municipio": "Florianópolis",
            "socios": [],
        }
        (enriched_dir / f"cnpj_{cnpj_k}.json").write_text(json.dumps(legado), encoding="utf-8")
        salvar_cnpj_cache({**legado, "razao_social": nome_k}, db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO emendas_clean (
                id_emenda, parlamentar, valor, municipio, municipio_normalizado,
                codigo_ibge, populacao, valor_per_capita, entidade_beneficiaria,
                area, data, ano_mes, fornecedor_nome, fornecedor_cnpj, uf_fornecedor,
                cnae_fornecedor, status_execucao, fonte_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "EM-S1", "Dep A", 100000.0, "Ituporanga", "ITUPORANGA", "4208500", 26000, 3.84,
                    "ASSOC DE MORAD DE BARRAGEM SUL - ITUPORANGA", "Assistência Social", "2026-05-01", "2026-05",
                    "ASSOC DE MORAD DE BARRAGEM SUL - ITUPORANGA", "00058956000144", "SC",
                    "4789-0/99 - Comércio e serviços gerais", "Pago", "https://tcesc.tc.br",
                ),
                (
                    "EM-S2", "Dep B", 250000.0, "Tigrinhos", "TIGRINHOS", "4217956", 2329, 107.34,
                    "MUNICIPIO DE TIGRINHOS", "Infraestrutura e Mobilidade", "2026-05-02", "2026-05",
                    "MUNICIPIO DE TIGRINHOS", "01566620000155", "SC",
                    "4789-0/99 - Comércio e serviços gerais", "Pago", "https://tcesc.tc.br",
                ),
            ],
        )
        conn.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        """Retorna dados reais para a associação e 404 para o município para testar ambos os caminhos."""
        if "00058956000144" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "cnpj": "00058956000144",
                    "razao_social": "ASSOCIACAO DE MORADORES DE BARRAGEM SUL",
                    "descricao_situacao_cadastral": "ATIVA",
                    "codigo_natureza_juridica": 3999,
                    "natureza_juridica": "Associação Privada",
                    "cnae_fiscal": 9430800,
                    "cnae_fiscal_descricao": "Atividades de associações de defesa de direitos sociais",
                    "cnaes_secundarios": [
                        {"codigo": 9493600, "descricao": "Atividades de organizações associativas ligadas à cultura e à arte"}
                    ],
                    "uf": "SC",
                    "municipio": "ITUPORANGA",
                },
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    resumo = sanear_cnpjs_fallback(
        db_path=db_path,
        enriched_dir=enriched_dir,
        usar_rede=True,
        client=client,
    )
    assert resumo["atualizados"] == 2

    info_assoc = obter_cnaes_cnpj("00058956000144", db_path=db_path)
    assert info_assoc["grupo_cnpj"] == "Outro CNPJ"
    assert info_assoc["cnae_principal"] == "9430-8/00 - Atividades de associações de defesa de direitos sociais"
    assert len(info_assoc["cnaes_secundarios"]) == 1

    info_mun = obter_cnaes_cnpj("01566620000155", db_path=db_path)
    assert info_mun["grupo_cnpj"] == "CNPJ de Município"
    assert info_mun["cnae_principal"] == "8411-6/00 - Administração pública em geral"

    with sqlite3.connect(db_path) as conn:
        cnaes_emendas = dict(conn.execute("SELECT fornecedor_cnpj, cnae_fornecedor FROM emendas_clean").fetchall())
    assert cnaes_emendas["00058956000144"].startswith("9430-8/00")
    assert cnaes_emendas["01566620000155"] == "8411-6/00 - Administração pública em geral"

