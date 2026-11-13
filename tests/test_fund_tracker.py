"""Testes unitários para o módulo de fluxo de recursos, rastreabilidade e integração TCE/SC (fund_tracker.py)."""

from __future__ import annotations

from pathlib import Path

from fund_tracker import (
    avaliar_objeto_plano_trabalho,
    avaliar_prestacao_contas_esfinge,
    avaliar_ritmo_execucao,
    check_fund_usage,
    gerar_link_transparencia_municipio,
    normalizar_texto_simples,
)


def test_normalizar_texto_e_link_transparencia() -> None:
    """Verifica remoção de acentos e geração de links de transparência para municípios catarinenses."""
    assert normalizar_texto_simples("Florianópolis") == "florianopolis"
    assert normalizar_texto_simples("São José") == "sao jose"
    assert normalizar_texto_simples(None) == ""

    link_florianopolis = gerar_link_transparencia_municipio("Florianópolis")
    assert "florianopolis" in link_florianopolis
    assert "transparencia" in link_florianopolis


def test_avaliar_objeto_plano_trabalho() -> None:
    """Sinal 1: Verifica compatibilidade semântica do plano de trabalho com a área temática da emenda."""
    # Objeto compatível com Saúde
    res_saude = avaliar_objeto_plano_trabalho(area="Saúde", objeto_texto="Reforma de clínica hospitalar municipal")
    assert res_saude["status"] == "verde"
    assert "Compatível" in res_saude["tag"]

    # Objeto sem termos de Saúde
    res_sem_termo = avaliar_objeto_plano_trabalho(area="Saúde", objeto_texto="Aquisição de material de pavimentação asfáltica")
    assert res_sem_termo["status"] == "amarelo"

    # Sem texto de objeto
    res_vazio = avaliar_objeto_plano_trabalho(area="Educação", objeto_texto="")
    assert res_vazio["status"] == "amarelo"
    assert res_vazio["exige_cautelar_tce"] is True


def test_avaliar_prestacao_contas_esfinge() -> None:
    """Sinal 2: Verifica tramitação orçamentária para monitoramento no e-Sfinge do TCE/SC."""
    res_pago = avaliar_prestacao_contas_esfinge(status_execucao="Pago")
    assert res_pago["status"] == "verde"
    assert "e-Sfinge" in res_pago["tag"]

    res_empenhado = avaliar_prestacao_contas_esfinge(status_execucao="Empenhado")
    assert res_empenhado["status"] == "amarelo"
    assert "Execução" in res_empenhado["tag"]


def test_avaliar_ritmo_execucao() -> None:
    """Sinal 3: Verifica ritmo de execução financeira frente a prazos decorridos."""
    res_pago = avaliar_ritmo_execucao(status_execucao="Pago", valor=500000.0)
    assert res_pago["status"] == "verde"
    assert "Concluído" in res_pago["tag"]

    # Aprovado há mais de 1 ano sem empenho
    res_lento = avaliar_ritmo_execucao(status_execucao="Aprovado", valor=500000.0, data_emenda="2024-01-10")
    assert res_lento["status"] == "amarelo"
    assert "Lenta" in res_lento["tag"]


def test_check_fund_usage_municipio_real() -> None:
    """Verifica a consolidação da rastreabilidade para um município da base (ex: Florianópolis)."""
    resultado = check_fund_usage("4205407", db_path="data/vigia_publico.db")
    assert resultado["municipio"] == "Florianópolis"
    assert resultado["codigo_ibge"] == "4205407"
    assert resultado["quantidade_emendas"] > 0
    assert len(resultado["emendas_analisadas"]) > 0
    assert "links_oficiais" in resultado
    assert "tce_fluxo_recursos" in resultado["links_oficiais"]
    assert "portal_transparencia_municipio" in resultado["links_oficiais"]
    assert 0.0 <= resultado["score_conformidade"] <= 100.0

    # Verifica primeira emenda da lista
    primeira = resultado["emendas_analisadas"][0]
    assert "id_emenda" in primeira
    assert "estagio_fluxo" in primeira
    assert len(primeira["sinais"]) == 5

    # Garante neutralidade (sem termos de desvio/crime)
    for sinal in primeira["sinais"]:
        desc = sinal["descricao"].lower()
        for termo in ("desvio", "corrupção", "fraude", "crime", "roubo"):
            assert termo not in desc

