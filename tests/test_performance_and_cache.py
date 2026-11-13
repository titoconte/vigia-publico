"""Testes unitários de performance, caching inteligente e configurações do Streamlit."""

from __future__ import annotations

import os
from pathlib import Path
import time

import pandas as pd
import pytest

from anomalies import executar_motor_anomalias
from app import (
    carregar_dados_painel,
    carregar_mapa_macrorregioes_sc,
    limpar_cache_aplicacao,
    obter_dados_perfil_municipio,
    obter_dados_perfil_parlamentar,
)
from cnpj_validator import (
    _MEM_CACHE_CNPJ,
    check_cnpj_status,
    limpar_mem_cache_cnpj,
    obter_cnpj_cache,
    salvar_cnpj_cache,
)
from collect_tce import executar_coleta_completa
from database import conectar_banco
from enrich_cnpj import CADASTRO_REFERENCIA_CNPJ, enriquecer_lote_cnpjs
from etl import executar_etl
from fund_tracker import check_fund_usage


def _preparar_banco_performance(tmp_path: Path) -> Path:
    """Cria e popula um banco SQLite temporário isolado para testes de performance e cache."""
    raw_dir = tmp_path / "raw"
    enriched_dir = tmp_path / "enriched"
    clean_dir = tmp_path / "clean"
    db_path = tmp_path / "vigia_perf.db"

    executar_coleta_completa(raw_dir=raw_dir, data_ref="20261110")
    enriquecer_lote_cnpjs(list(CADASTRO_REFERENCIA_CNPJ.keys()), output_dir=enriched_dir, usar_rede=False)
    executar_etl(raw_dir=raw_dir, enriched_dir=enriched_dir, clean_dir=clean_dir, db_path=db_path)
    executar_motor_anomalias(db_path=db_path)
    return db_path


def test_config_toml_performance_settings() -> None:
    """Verifica se o arquivo .streamlit/config.toml possui todas as diretivas de alta performance ativas."""
    config_file = Path(".streamlit/config.toml")
    assert config_file.exists(), ".streamlit/config.toml deve existir na raiz do projeto."
    conteudo = config_file.read_text(encoding="utf-8")

    assert "fastReruns = true" in conteudo, "fastReruns deve estar ativado para evitar fila de reruns."
    assert "enableStaticServing = true" in conteudo, "enableStaticServing deve estar ativado para assets estáticos."
    assert "gatherUsageStats = false" in conteudo, "gatherUsageStats deve ser desativado para eliminar requisições desnecessárias."
    assert 'toolbarMode = "minimal"' in conteudo, "toolbarMode deve ser minimal para leveza na interface."


def test_mem_cache_cnpj_e_limpeza(tmp_path: Path) -> None:
    """Verifica se o cache em memória de CNPJ funciona e é zerado por limpar_mem_cache_cnpj."""
    db_path = _preparar_banco_performance(tmp_path)
    limpar_mem_cache_cnpj()
    assert len(_MEM_CACHE_CNPJ) == 0

    # Consulta um CNPJ conhecido da base de teste
    cnpj_teste = "00000000000191"
    dados_mock = {
        "cnpj": cnpj_teste,
        "razao_social": "BANCO DO BRASIL S/A",
        "situacao_cadastral": "Ativa",
    }
    salvar_cnpj_cache(dados_mock, db_path=db_path)

    # Verifica se entrou no cache em memória
    chave = (str(db_path.resolve()), cnpj_teste)
    assert chave in _MEM_CACHE_CNPJ
    assert _MEM_CACHE_CNPJ[chave]["razao_social"] == "BANCO DO BRASIL S/A"

    # Segunda busca deve vir instantânea da memória
    retorno = obter_cnpj_cache(cnpj_teste, db_path=db_path)
    assert retorno is not None
    assert retorno["razao_social"] == "BANCO DO BRASIL S/A"

    # Testa a limpeza
    limpar_mem_cache_cnpj()
    assert len(_MEM_CACHE_CNPJ) == 0


def test_carregar_dados_painel_e_limpeza_cache(tmp_path: Path) -> None:
    """Verifica se carregar_dados_painel mantém a consistência dos DataFrames e se limpar_cache_aplicacao opera sem erro."""
    db_path = _preparar_banco_performance(tmp_path)
    limpar_cache_aplicacao()

    # 1. Primeira carga
    dados1 = carregar_dados_painel(db_path=db_path)
    assert not dados1["emendas"].empty
    assert not dados1["alertas"].empty
    qtd_emendas1 = len(dados1["emendas"])

    # 2. Segunda carga (com cache do Streamlit)
    dados2 = carregar_dados_painel(db_path=db_path)
    assert len(dados2["emendas"]) == qtd_emendas1

    # 3. Limpeza do cache
    limpar_cache_aplicacao()
    dados3 = carregar_dados_painel(db_path=db_path)
    assert len(dados3["emendas"]) == qtd_emendas1


def test_perfis_parlamentar_e_municipio_cache(tmp_path: Path) -> None:
    """Verifica se obter_dados_perfil_parlamentar e obter_dados_perfil_municipio retornam estruturas válidas com cache."""
    db_path = _preparar_banco_performance(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)

    # Perfil Parlamentar
    parl_nome = str(dados["parlamentares"].iloc[0]["parlamentar"])
    p1 = obter_dados_perfil_parlamentar(parl_nome, db_path=db_path)
    p2 = obter_dados_perfil_parlamentar(parl_nome, db_path=db_path)
    assert p1["resumo"]["parlamentar"] == p2["resumo"]["parlamentar"]
    assert len(p1["emendas"]) == len(p2["emendas"])

    # Perfil Município
    cod_mun = str(dados["municipios"].iloc[0]["codigo_ibge"])
    m1 = obter_dados_perfil_municipio(cod_mun, db_path=db_path)
    m2 = obter_dados_perfil_municipio(cod_mun, db_path=db_path)
    assert m1["resumo"]["codigo_ibge"] == m2["resumo"]["codigo_ibge"]
    assert len(m1["emendas"]) == len(m2["emendas"])


def test_check_fund_usage_cache(tmp_path: Path) -> None:
    """Verifica se check_fund_usage opera com alta velocidade e consistência de dados em chamadas subsequentes."""
    db_path = _preparar_banco_performance(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    cod_mun = str(dados["municipios"].iloc[0]["codigo_ibge"])

    # Primeira execução
    t0 = time.perf_counter()
    r1 = check_fund_usage(cod_mun, db_path=db_path)
    t1 = time.perf_counter()
    duracao_primeira = t1 - t0

    # Segunda execução (deve aproveitar cache)
    t0 = time.perf_counter()
    r2 = check_fund_usage(cod_mun, db_path=db_path)
    t1 = time.perf_counter()
    duracao_segunda = t1 - t0

    assert r1["municipio"] == r2["municipio"]
    assert r1["score_conformidade"] == r2["score_conformidade"]
    assert len(r1["emendas_analisadas"]) == len(r2["emendas_analisadas"])
    # Segunda chamada deve ser rápida
    assert duracao_segunda <= duracao_primeira or duracao_segunda < 0.1


def test_carregar_mapa_macrorregioes_cache() -> None:
    """Valida o carregamento com cache do mapa de macrorregiões de Santa Catarina."""
    mapa = carregar_mapa_macrorregioes_sc()
    assert isinstance(mapa, dict)
    if mapa:
        # Florianópolis
        assert "4205407" in mapa
        assert "Grande Florianópolis" in mapa["4205407"]
