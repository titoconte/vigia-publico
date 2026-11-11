"""Testes unitários para a Fase 5 — Funções de carregamento, filtragem e perfis do Frontend Streamlit (app.py)."""

from __future__ import annotations

from pathlib import Path

from anomalies import executar_motor_anomalias
from app import (
    AVISO_ETICO_FRONTEND,
    carregar_dados_painel,
    filtrar_emendas_explorador,
    obter_dados_perfil_municipio,
    obter_dados_perfil_parlamentar,
    registrar_feedback_local,
)
from collect_tce import executar_coleta_completa
from enrich_cnpj import CADASTRO_REFERENCIA_CNPJ, enriquecer_lote_cnpjs
from etl import executar_etl


def _preparar_banco_frontend(tmp_path: Path) -> Path:
    """Cria e popula um banco SQLite temporário para validar as visões do Streamlit."""
    raw_dir = tmp_path / "raw"
    enriched_dir = tmp_path / "enriched"
    clean_dir = tmp_path / "clean"
    db_path = tmp_path / "vigia_frontend.db"

    executar_coleta_completa(raw_dir=raw_dir, data_ref="20261110")
    enriquecer_lote_cnpjs(list(CADASTRO_REFERENCIA_CNPJ.keys()), output_dir=enriched_dir, usar_rede=False)
    executar_etl(raw_dir=raw_dir, enriched_dir=enriched_dir, clean_dir=clean_dir, db_path=db_path)
    executar_motor_anomalias(db_path=db_path)
    return db_path


def test_aviso_etico_obrigatorio_presente() -> None:
    """Verifica se a frase ética exigida está presente no banner do frontend."""
    assert (
        "Esta ferramenta não substitui a verificação documental nem a apuração oficial."
        in AVISO_ETICO_FRONTEND
    )


def test_carregar_dados_painel_e_explorador(tmp_path: Path) -> None:
    """Verifica se as 4 tabelas base são carregadas e filtradas corretamente para as Páginas 1 e 2."""
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    assert not dados["alertas"].empty
    assert not dados["emendas"].empty
    assert not dados["parlamentares"].empty
    assert not dados["municipios"].empty

    df_filtrado = filtrar_emendas_explorador(
        dados["emendas"],
        parlamentar="Todos",
        municipio="Florianópolis",
        area="Saúde",
        valor_minimo=100000.0,
    )
    assert len(df_filtrado) >= 1
    assert (df_filtrado["municipio"] == "Florianópolis").all()


def test_perfis_parlamentar_e_municipio_e_feedback(tmp_path: Path) -> None:
    """Verifica os dados das Páginas 3 (Perfil do Parlamentar) e 4 (Perfil do Município) e o feedback."""
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)

    parlamentar_nome = str(dados["parlamentares"].iloc[0]["parlamentar"])
    perfil_parl = obter_dados_perfil_parlamentar(parlamentar_nome, db_path=db_path)
    assert perfil_parl["resumo"]["parlamentar"] == parlamentar_nome
    assert not perfil_parl["por_area"].empty

    perfil_mun = obter_dados_perfil_municipio("4218954", db_path=db_path)
    assert perfil_mun["resumo"]["municipio"] == "Urupema"
    assert perfil_mun["resumo"]["populacao"] == 2656
    assert len(perfil_mun["alertas"]) >= 1

    alerta_id = int(dados["alertas"].iloc[0]["id"])
    atualizado = registrar_feedback_local(
        alerta_id=alerta_id,
        avaliacao="util",
        comentario="Verificado pela reportagem",
        jornalista="Jornalista SC",
        db_path=db_path,
    )
    assert atualizado["util_count"] == 1
