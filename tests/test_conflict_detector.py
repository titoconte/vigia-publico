"""Testes unitários para o módulo de detecção de Conflito de Interesses (conflict_detector.py)."""

from __future__ import annotations

from pathlib import Path

from anomalies import executar_motor_anomalias
from collect_tce import executar_coleta_completa
from conflict_detector import (
    checar_conflito_direto_pasta,
    detectar_conflitos_servidores,
)
from dados_sc_loader import carregar_dados_abertos_sc
from enrich_cnpj import CADASTRO_REFERENCIA_CNPJ, enriquecer_lote_cnpjs
from etl import executar_etl


def _preparar_banco_conflitos(tmp_path: Path) -> Path:
    """Prepara banco populado com emendas, CNPJs enriquecidos, servidores e sócios QSA."""
    raw_dir = tmp_path / "raw"
    enriched_dir = tmp_path / "enriched"
    clean_dir = tmp_path / "clean"
    db_path = tmp_path / "vigia_conflito.db"

    executar_coleta_completa(raw_dir=raw_dir, data_ref="20261110")
    enriquecer_lote_cnpjs(list(CADASTRO_REFERENCIA_CNPJ.keys()), output_dir=enriched_dir, usar_rede=False)
    executar_etl(raw_dir=raw_dir, enriched_dir=enriched_dir, clean_dir=clean_dir, db_path=db_path)
    executar_motor_anomalias(db_path=db_path)

    # Carrega dados abertos de servidores e contratos
    carregar_dados_abertos_sc(
        db_path=db_path,
        enriched_dir=enriched_dir,
    )
    return db_path


def test_checar_conflito_direto_pasta() -> None:
    """Valida o mapeamento de órgãos de lotação do servidor com a área temática da emenda."""
    assert checar_conflito_direto_pasta("Secretaria de Estado da Saúde (SES)", "Saúde") is True
    assert checar_conflito_direto_pasta("Fundo Estadual de Saúde", "Saúde") is True
    assert checar_conflito_direto_pasta("Secretaria de Estado da Educação (SED)", "Educação") is True
    assert checar_conflito_direto_pasta("Secretaria de Estado da Saúde (SES)", "Educação") is False
    assert checar_conflito_direto_pasta("Secretaria de Estado da Fazenda", "Saúde") is False


def test_detectar_conflitos_servidores(tmp_path: Path) -> None:
    """Verifica a identificação e classificação de servidores públicos sócios de fornecedores."""
    db_path = _preparar_banco_conflitos(tmp_path)
    resultado = detectar_conflitos_servidores(db_path)

    assert "resumo" in resultado
    assert "casos_detalhados" in resultado
    assert "df_agrupado" in resultado

    # Se houver cruzamentos identificados
    if resultado["resumo"]["total_casos"] > 0:
        caso = resultado["casos_detalhados"][0]
        assert "servidor_nome" in caso
        assert "fornecedor_cnpj" in caso
        assert "severidade" in caso
        assert caso["severidade"] in ("vermelho", "amarelo")
        assert "emendas_relacionadas" in caso
