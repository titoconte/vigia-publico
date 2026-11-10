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
from enrich_cnpj import enriquecer_cnpj, enriquecer_lote_cnpjs, limpar_cnpj


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
