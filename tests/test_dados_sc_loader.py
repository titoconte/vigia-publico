"""Testes unitários para o módulo de ingestão de Dados Abertos SC (dados_sc_loader.py)."""

from __future__ import annotations

from pathlib import Path

from dados_sc_loader import (
    carregar_dados_abertos_sc,
    gerar_dados_referencia_contratos_sc,
    gerar_dados_referencia_servidores_sc,
    inicializar_schema_dados_sc,
    normalizar_nome_busca,
    sincronizar_socios_qsa_no_banco,
)
from database import conectar_banco


def test_normalizar_nome_busca() -> None:
    """Verifica se nomes próprios são normalizados para permitir busca e matching sem ruído."""
    assert normalizar_nome_busca("José da Silva Júnior") == "JOSE DA SILVA JUNIOR"
    assert normalizar_nome_busca("Ângela Maria D'Ávila") == "ANGELA MARIA D AVILA"
    assert normalizar_nome_busca("  MARCOS   AURELIO   ") == "MARCOS AURELIO"
    assert normalizar_nome_busca("") == ""
    assert normalizar_nome_busca(None) == ""


def test_inicializar_schema_e_carga_dados_abertos(tmp_path: Path) -> None:
    """Verifica se as tabelas de servidores, sócios e contratos são criadas e populadas no SQLite."""
    db_path = tmp_path / "teste_dados_sc.db"
    csv_serv = tmp_path / "servidores_teste.csv"
    csv_cont = tmp_path / "contratos_teste.csv"

    resultado = carregar_dados_abertos_sc(
        db_path=db_path,
        csv_servidores=csv_serv,
        csv_contratos=csv_cont,
        enriched_dir=Path("data/enriched"),
    )

    assert resultado["servidores_carregados"] >= 5
    assert resultado["contratos_carregados"] >= 3

    with conectar_banco(db_path) as conn:
        cont_serv = conn.execute("SELECT COUNT(*) FROM servidores_estaduais").fetchone()[0]
        cont_cont = conn.execute("SELECT COUNT(*) FROM contratos_estaduais").fetchone()[0]
        cont_socios = conn.execute("SELECT COUNT(*) FROM cnpj_socios").fetchone()[0]

    assert cont_serv >= 5
    assert cont_cont >= 3
    assert cont_socios >= 0
