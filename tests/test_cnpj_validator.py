"""Testes unitários para o módulo de validação de CNPJs, situação cadastral e anomalias (cnpj_validator.py)."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from cnpj_validator import (
    SITUACAO_ATIVA,
    SITUACAO_BAIXADA,
    SITUACAO_INAPTA,
    SITUACAO_NULA,
    SITUACAO_SUSPENSA,
    check_cnpj_anomalies,
    check_cnpj_status,
    formatar_cnpj_exibicao,
    limpar_cnpj,
    normalizar_situacao_cadastral,
    obter_cnpj_cache,
    obter_link_consulta_oficial,
    salvar_cnpj_cache,
    sincronizar_cnpjs_emendas_no_cache,
)
from database import inicializar_schema


def test_limpar_e_formatar_cnpj() -> None:
    """Verifica limpeza numérica, formatação padrão de 14 dígitos e geração de link oficial."""
    cnpj_bruto = " 83.456.123/0001-10 "
    limpo = limpar_cnpj(cnpj_bruto)
    assert limpo == "83456123000110"
    assert formatar_cnpj_exibicao(limpo) == "83.456.123/0001-10"

    link = obter_link_consulta_oficial(limpo)
    assert "83456123000110" in link
    assert "portaldatransparencia.gov.br" in link

    # Casos vazios ou incompletos
    assert limpar_cnpj("") == ""
    assert limpar_cnpj(None) == ""


def test_normalizar_situacao_cadastral() -> None:
    """Verifica padronização dos 5 status oficiais da Receita Federal (Ativa, Baixada, Inapta, Suspensa, Nula)."""
    assert normalizar_situacao_cadastral("ATIVA") == SITUACAO_ATIVA
    assert normalizar_situacao_cadastral("ativa") == SITUACAO_ATIVA
    assert normalizar_situacao_cadastral("BAIXADA") == SITUACAO_BAIXADA
    assert normalizar_situacao_cadastral("inapta") == SITUACAO_INAPTA
    assert normalizar_situacao_cadastral("SUSPENSA") == SITUACAO_SUSPENSA
    assert normalizar_situacao_cadastral("NULA") == SITUACAO_NULA
    assert normalizar_situacao_cadastral(None) == SITUACAO_ATIVA


def test_salvar_e_obter_cnpj_cache(tmp_path: Path) -> None:
    """Verifica inserção, atualização e consulta na tabela cnpj_cache do SQLite."""
    db_path = tmp_path / "test_cnpj.db"
    inicializar_schema(db_path)

    dados = {
        "cnpj": "83456123000110",
        "razao_social": "MedSul Hospitalar S.A.",
        "situacao_cadastral": "Ativa",
        "data_abertura": "2015-05-10",
        "natureza_juridica": "Sociedade Empresária Limitada",
        "natureza_juridica_codigo": "2062",
        "capital_social": 1500000.0,
        "cnae_principal": "8610-1/01 - Atividades de atendimento hospitalar",
    }
    salvar_cnpj_cache(dados, db_path=db_path)

    resgatado = obter_cnpj_cache("83456123000110", db_path=db_path)
    assert resgatado is not None
    assert resgatado["cnpj"] == "83456123000110"
    assert resgatado["razao_social"] == "MedSul Hospitalar S.A."
    assert resgatado["situacao_cadastral"] == "Ativa"
    assert resgatado["capital_social"] == 1500000.0

    # Atualização
    dados["situacao_cadastral"] = "Baixada"
    salvar_cnpj_cache(dados, db_path=db_path)
    atualizado = obter_cnpj_cache("83456123000110", db_path=db_path)
    assert atualizado["situacao_cadastral"] == "Baixada"


def test_check_cnpj_status_camada_1(tmp_path: Path) -> None:
    """1ª Camada: Verifica se check_cnpj_status identifica status válido e emite motivo para não-ativos."""
    db_path = tmp_path / "test_status.db"

    # CNPJ Inapto
    salvar_cnpj_cache(
        {
            "cnpj": "11222333000144",
            "razao_social": "Comércio Inapto Ltda",
            "situacao_cadastral": "Inapta",
        },
        db_path=db_path,
    )
    status_inapto = check_cnpj_status("11222333000144", db_path=db_path)
    assert status_inapto["status_valido"] is False
    assert status_inapto["situacao_cadastral"] == "Inapta"
    assert "omissão" in status_inapto["motivo_anomalia"].lower()

    # CNPJ Ativo
    salvar_cnpj_cache(
        {
            "cnpj": "22333444000155",
            "razao_social": "Empresa Regular Ltda",
            "situacao_cadastral": "Ativa",
        },
        db_path=db_path,
    )
    status_ativo = check_cnpj_status("22333444000155", db_path=db_path)
    assert status_ativo["status_valido"] is True
    assert status_ativo["situacao_cadastral"] == "Ativa"
    assert status_ativo["motivo_anomalia"] == ""


def test_anomalia_empresa_recem_criada(tmp_path: Path) -> None:
    """2ª Camada (Item 1): Detecta empresa aberta há menos de 180 dias da data da emenda."""
    db_path = tmp_path / "test_recem.db"
    salvar_cnpj_cache(
        {
            "cnpj": "33444555000166",
            "razao_social": "Nova Serviços Rápidos Ltda",
            "situacao_cadastral": "Ativa",
            "data_abertura": "2026-03-01",
        },
        db_path=db_path,
    )

    # Emenda em 2026-05-15 (75 dias após a abertura -> menos de 180 dias)
    resultado = check_cnpj_anomalies(
        "33444555000166",
        valor_emenda=250000.0,
        data_emenda="2026-05-15",
        db_path=db_path,
    )
    assert resultado["possui_anomalia"] is True
    assert any("Empresa Recém-Criada" in tag for tag in resultado["tags"])
    assert resultado["score_suspeita"] >= 70.0

    # Emenda em 2027-01-01 (> 180 dias -> não gera essa anomalia)
    resultado_antiga = check_cnpj_anomalies(
        "33444555000166",
        valor_emenda=250000.0,
        data_emenda="2027-01-01",
        db_path=db_path,
    )
    assert not any("Empresa Recém-Criada" in tag for tag in resultado_antiga["tags"])


def test_anomalia_empresario_individual_alto_valor_tcu(tmp_path: Path) -> None:
    """2ª Camada (Item 2): Sinaliza Empresário Individual (código 2135) recebendo > R$ 500.000 (apontamento do TCU)."""
    db_path = tmp_path / "test_ei.db"
    salvar_cnpj_cache(
        {
            "cnpj": "44555666000177",
            "razao_social": "José Silva ME",
            "situacao_cadastral": "Ativa",
            "natureza_juridica_codigo": "2135",
            "natureza_juridica": "Empresário (Individual)",
            "data_abertura": "2018-01-10",
        },
        db_path=db_path,
    )

    # Caso 1: EI recebendo R$ 850.000 (> R$ 500k) -> Sinaliza alerta vermelho
    res_alto = check_cnpj_anomalies("44555666000177", valor_emenda=850000.0, db_path=db_path)
    assert res_alto["possui_anomalia"] is True
    assert any("EI Recebendo Alto Valor" in tag for tag in res_alto["tags"])
    assert res_alto["score_suspeita"] >= 85.0

    # Caso 2: EI recebendo valor comum de R$ 150.000 (<= R$ 500k) -> Não sinaliza
    res_comum = check_cnpj_anomalies("44555666000177", valor_emenda=150000.0, db_path=db_path)
    assert not any("EI Recebendo Alto Valor" in tag for tag in res_comum["tags"])


def test_anomalia_cnae_incompativel_com_area(tmp_path: Path) -> None:
    """2ª Camada (Item 3): Detecta empresa de construção civil recebendo emenda temática de Saúde."""
    db_path = tmp_path / "test_cnae.db"
    salvar_cnpj_cache(
        {
            "cnpj": "55666777000188",
            "razao_social": "Construtora Exemplo Ltda",
            "situacao_cadastral": "Ativa",
            "cnae_principal": "4120-4/00 - Construção de edifícios",
            "data_abertura": "2016-01-10",
        },
        db_path=db_path,
    )

    # Área Saúde com CNAE de Construção Civil -> Incompatível
    res_incomp = check_cnpj_anomalies(
        "55666777000188",
        valor_emenda=200000.0,
        area="Saúde",
        db_path=db_path,
    )
    assert res_incomp["possui_anomalia"] is True
    assert any("CNAE Incompatível" in tag for tag in res_incomp["tags"])

    # Área Infraestrutura e Mobilidade com CNAE de Construção Civil -> Compatível
    res_comp = check_cnpj_anomalies(
        "55666777000188",
        valor_emenda=200000.0,
        area="Infraestrutura e Mobilidade",
        db_path=db_path,
    )
    assert not any("CNAE Incompatível" in tag for tag in res_comp["tags"])


def test_anomalia_capital_social_baixo(tmp_path: Path) -> None:
    """2ª Camada (Item 4): Sinaliza capital social < R$ 10.000 recebendo emenda >= R$ 200.000."""
    db_path = tmp_path / "test_cap.db"
    salvar_cnpj_cache(
        {
            "cnpj": "66777888000199",
            "razao_social": "Micro Consultoria ME",
            "situacao_cadastral": "Ativa",
            "capital_social": 2000.0,
            "data_abertura": "2017-01-10",
        },
        db_path=db_path,
    )

    res_baixo = check_cnpj_anomalies("66777888000199", valor_emenda=350000.0, db_path=db_path)
    assert res_baixo["possui_anomalia"] is True
    assert any("Capital Social Baixo" in tag for tag in res_baixo["tags"])


def test_sincronizar_cnpjs_emendas_no_cache(tmp_path: Path) -> None:
    """Verifica sincronização em lote de todos os CNPJs de emendas_clean para a tabela cnpj_cache."""
    db_path = tmp_path / "test_sync.db"
    inicializar_schema(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO emendas_clean (
                id_emenda, parlamentar, valor, municipio, municipio_normalizado,
                codigo_ibge, populacao, valor_per_capita, entidade_beneficiaria,
                area, data, ano_mes, fornecedor_nome, fornecedor_cnpj, uf_fornecedor,
                status_execucao, fonte_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "EM-TEST-01", "Deputado Teste", 100000.0, "Florianópolis", "FLORIANOPOLIS",
                "4205407", 500000, 0.2, "Hospital Alfa", "Saúde", "2026-05-10", "2026-05",
                "Hospital Alfa S.A.", "83456123000110", "SC", "Pago", "https://tcesc.tc.br",
            ),
        )
        conn.commit()

    total = sincronizar_cnpjs_emendas_no_cache(db_path)
    assert total == 1

    cached = obter_cnpj_cache("83456123000110", db_path)
    assert cached is not None
    assert cached["razao_social"] == "Hospital Alfa S.A."
    assert cached["situacao_cadastral"] == "Ativa"

