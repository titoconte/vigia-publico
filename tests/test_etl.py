"""Testes unitários para a Fase 2 — Limpeza, cálculo per capita, agregações e banco de dados (ETL)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from collect_tce import executar_coleta_completa
from enrich_cnpj import CADASTRO_REFERENCIA_CNPJ, enriquecer_lote_cnpjs
from etl import (
    calcular_valor_per_capita,
    executar_etl,
    normalizar_municipio,
)


def test_normalizar_municipio_remove_acentos_e_padroniza_caixa() -> None:
    """Verifica se nomes de municípios têm acentos removidos e caixa padronizada em maiúsculas."""
    assert normalizar_municipio("  Florianópolis ") == "FLORIANOPOLIS"
    assert normalizar_municipio("São José") == "SAO JOSE"
    assert normalizar_municipio("Balneário Camboriú") == "BALNEARIO CAMBORIU"
    assert normalizar_municipio("Águas de Chapecó") == "AGUAS DE CHAPECO"


def test_calcular_valor_per_capita_exato_e_seguro() -> None:
    """Verifica o cálculo de valor_per_capita = valor_emenda / populacao e tratamento de população zero."""
    assert calcular_valor_per_capita(500000.0, 100000) == pytest.approx(5.0)
    assert calcular_valor_per_capita(3200000.0, 2656) == pytest.approx(3200000.0 / 2656)
    assert calcular_valor_per_capita(100000.0, 0) == 0.0
    assert calcular_valor_per_capita(100000.0, None) == 0.0


def test_executar_etl_gera_tabelas_limpas_agregados_e_indices(tmp_path: Path) -> None:
    """Verifica se o pipeline ETL gera emendas_clean e todas as tabelas agregadas no banco com índices."""
    raw_dir = tmp_path / "raw"
    enriched_dir = tmp_path / "enriched"
    clean_dir = tmp_path / "clean"
    db_path = tmp_path / "vigia_test.db"

    executar_coleta_completa(raw_dir=raw_dir, data_ref="20261110")
    enriquecer_lote_cnpjs(list(CADASTRO_REFERENCIA_CNPJ.keys()), output_dir=enriched_dir, usar_rede=False)

    resultado = executar_etl(
        raw_dir=raw_dir,
        enriched_dir=enriched_dir,
        clean_dir=clean_dir,
        db_path=db_path,
    )

    assert db_path.exists()
    assert len(resultado["emendas_clean"]) >= 20
    assert "valor_per_capita" in resultado["emendas_clean"].columns
    assert (resultado["emendas_clean"]["valor_per_capita"] > 0).all()

    with sqlite3.connect(db_path) as conn:
        tabelas = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {
            "emendas_clean",
            "agregados_parlamentar",
            "agregados_municipio",
            "agregados_fornecedor",
            "alertas",
            "alertas_feedback",
        }.issubset(tabelas)

        indices = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        assert any("parlamentar" in idx for idx in indices)
        assert any("municipio" in idx for idx in indices)
        assert any("cnpj" in idx for idx in indices)
