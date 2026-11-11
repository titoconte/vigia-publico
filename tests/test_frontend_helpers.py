"""Testes unitários para a Fase 5 — Funções de carregamento, filtragem e perfis do Frontend Streamlit (app.py)."""

from __future__ import annotations

from pathlib import Path

from anomalies import executar_motor_anomalias
from app import (
    AVISO_ETICO_FRONTEND,
    calcular_valor_por_populacao_filtrada,
    carregar_dados_painel,
    eh_bancada_regional,
    filtrar_emendas_explorador,
    obter_dados_perfil_municipio,
    obter_dados_perfil_parlamentar,
    obter_totais_por_ano,
    obter_totais_por_parlamentar,
    obter_totais_por_partido,
    registrar_feedback_local,
    separar_autores_por_tipo,
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


def test_eh_bancada_regional_e_separacao_autores() -> None:
    """Verifica se bancadas regionais são diferenciadas por iniciar estritamente com 'BANCADA '."""
    assert eh_bancada_regional("BANCADA DA SERRA") is True
    assert eh_bancada_regional("Bancada do Vale do Itajai") is True
    assert eh_bancada_regional("bancada do oeste") is True
    assert eh_bancada_regional("BANCADA") is False
    assert eh_bancada_regional("BANCADA_TESTE") is False
    assert eh_bancada_regional("Dep. Paulinha") is False
    assert eh_bancada_regional("Luciane Carminatti") is False
    assert eh_bancada_regional("") is False
    assert eh_bancada_regional(None) is False

    autores = [
        "BANCADA DA SERRA",
        "Dep. Paulinha",
        "BANCADA DO NORTE",
        "Ivan Naatz",
        "BANCADA DO SUL",
    ]
    separados = separar_autores_por_tipo(autores)
    assert len(separados["bancadas"]) == 3
    assert len(separados["parlamentares"]) == 2
    assert "BANCADA DA SERRA" in separados["bancadas"]
    assert "Dep. Paulinha" in separados["parlamentares"]


def test_histogramas_partido_parlamentar_ano(tmp_path: Path) -> None:
    """Verifica o cálculo correto dos histogramas por partido, por parlamentar e por ano para o Perfil Parlamentar."""
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    df_emendas = dados["emendas"]

    totais_partido = obter_totais_por_partido(df_emendas)
    assert not totais_partido.empty
    assert totais_partido.sum() == df_emendas["valor"].sum()
    assert "PSD" in totais_partido.index or "PL" in totais_partido.index or "MDB" in totais_partido.index

    totais_bancadas = obter_totais_por_parlamentar(df_emendas, tipo_autor="Bancadas")
    totais_individuais = obter_totais_por_parlamentar(df_emendas, tipo_autor="Parlamentares")
    totais_todos = obter_totais_por_parlamentar(df_emendas, tipo_autor="Todos")

    assert not totais_bancadas.empty
    assert not totais_individuais.empty
    assert len(totais_bancadas) + len(totais_individuais) == len(totais_todos)
    assert all("BANCADA" in str(nome).upper() for nome in totais_bancadas.index)
    assert all("BANCADA" not in str(nome).upper() for nome in totais_individuais.index)

    totais_ano = obter_totais_por_ano(df_emendas)
    assert not totais_ano.empty
    assert "2026" in totais_ano.index
    assert totais_ano["2026"] == df_emendas["valor"].sum()


def test_filtrar_emendas_por_tipo_autor(tmp_path: Path) -> None:
    """Verifica a filtragem de emendas separando parlamentares individuais de bancadas regionais."""
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    df_emendas = dados["emendas"]

    df_bancadas = filtrar_emendas_explorador(df_emendas, tipo_autor="Bancada Regional")
    df_individuais = filtrar_emendas_explorador(df_emendas, tipo_autor="Parlamentar Individual")
    df_todos = filtrar_emendas_explorador(df_emendas, tipo_autor="Todos")

    assert len(df_bancadas) > 0
    assert len(df_individuais) > 0
    assert len(df_bancadas) + len(df_individuais) == len(df_todos)
    assert df_bancadas["parlamentar"].apply(eh_bancada_regional).all()
    assert (~df_individuais["parlamentar"].apply(eh_bancada_regional)).all()


def test_calcular_valor_por_populacao_filtrada(tmp_path: Path) -> None:
    """Verifica o cálculo da razão valor total / população total dos municípios contemplados no Explorador."""
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    df_emendas = dados["emendas"]

    # Caso geral com base completa
    resumo_geral = calcular_valor_por_populacao_filtrada(df_emendas)
    assert resumo_geral["total_valor"] == df_emendas["valor"].sum()
    assert resumo_geral["populacao_total"] > 0
    assert resumo_geral["valor_por_habitante"] > 0
    esperado = round(resumo_geral["total_valor"] / resumo_geral["populacao_total"], 2)
    assert resumo_geral["valor_por_habitante"] == esperado

    # Caso filtrado por um município específico (Florianópolis)
    df_floripa = df_emendas[df_emendas["municipio"] == "Florianópolis"]
    resumo_floripa = calcular_valor_por_populacao_filtrada(df_floripa)
    assert resumo_floripa["total_valor"] == df_floripa["valor"].sum()
    assert resumo_floripa["populacao_total"] == 537211  # População IBGE de Florianópolis
    assert resumo_floripa["valor_por_habitante"] == round(df_floripa["valor"].sum() / 537211, 2)

    # Caso DataFrame vazio
    resumo_vazio = calcular_valor_por_populacao_filtrada(df_emendas.iloc[0:0])
    assert resumo_vazio["total_valor"] == 0.0
    assert resumo_vazio["populacao_total"] == 0
    assert resumo_vazio["valor_por_habitante"] == 0.0
