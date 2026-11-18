"""Testes unitários para o módulo de auditoria de conformidade de contratos (contract_auditor.py)."""

from __future__ import annotations

from pathlib import Path

from anomalies import executar_motor_anomalias
from collect_tce import executar_coleta_completa
from contract_auditor import (
    auditar_contratos_emendas,
    avaliar_aderencia_objeto_area,
    normalizar_texto_contrato,
)
from dados_sc_loader import carregar_dados_abertos_sc
from enrich_cnpj import CADASTRO_REFERENCIA_CNPJ, enriquecer_lote_cnpjs
from etl import executar_etl


def _preparar_banco_contratos(tmp_path: Path) -> Path:
    """Prepara banco com emendas e contratos do SIGEF para teste de conformidade temática."""
    raw_dir = tmp_path / "raw"
    enriched_dir = tmp_path / "enriched"
    clean_dir = tmp_path / "clean"
    db_path = tmp_path / "vigia_contratos.db"

    executar_coleta_completa(raw_dir=raw_dir, data_ref="20261110")
    enriquecer_lote_cnpjs(list(CADASTRO_REFERENCIA_CNPJ.keys()), output_dir=enriched_dir, usar_rede=False)
    executar_etl(raw_dir=raw_dir, enriched_dir=enriched_dir, clean_dir=clean_dir, db_path=db_path)
    executar_motor_anomalias(db_path=db_path)

    carregar_dados_abertos_sc(
        db_path=db_path,
        enriched_dir=enriched_dir,
    )
    return db_path


def test_avaliar_aderencia_objeto_area() -> None:
    """Valida a detecção de consistência e inconsistência temática entre objeto contratual e área da emenda."""
    # Caso 1: Conforme (Saúde com ambulância/atendimento)
    res_conforme = avaliar_aderencia_objeto_area(
        objeto_contrato="Aquisição de ambulância de suporte básico e insumos hospitalares",
        area_emenda="Saúde",
    )
    assert res_conforme["status"] == "verde"
    assert "Objeto Conforme" in res_conforme["tag"]

    # Caso 2: Inconsistência manifesta (Saúde com pavimentação asfáltica)
    res_inconsistente = avaliar_aderencia_objeto_area(
        objeto_contrato="Execução de obras de pavimentação asfáltica e drenagem pluvial",
        area_emenda="Saúde",
    )
    assert res_inconsistente["status"] == "vermelho"
    assert "Inconsistência Temática" in res_inconsistente["tag"]

    # Caso 3: Objeto genérico
    res_generico = avaliar_aderencia_objeto_area(
        objeto_contrato="Prestação de serviços",
        area_emenda="Educação",
    )
    assert res_generico["status"] == "amarelo"


def test_auditar_contratos_emendas(tmp_path: Path) -> None:
    """Verifica a auditoria cruzada de contratos SIGEF vs emendas no banco SQLite."""
    db_path = _preparar_banco_contratos(tmp_path)
    resultado = auditar_contratos_emendas(db_path)

    assert "resumo" in resultado
    assert "auditorias" in resultado
    assert "df_agrupado" in resultado

    if resultado["resumo"]["total_cruzamentos"] > 0:
        aud = resultado["auditorias"][0]
        assert "numero_contrato" in aud
        assert "status_conformidade" in aud
        assert aud["status_conformidade"] in ("verde", "amarelo", "vermelho")
        assert "valor_contrato" in aud
        assert "objeto_contrato" in aud
