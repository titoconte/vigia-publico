"""Testes unitários para a Fase 6 — Agendador semanal (scheduler.py) e Bot do Telegram (telegram_bot.py)."""

from __future__ import annotations

from pathlib import Path

from scheduler import (
    executar_ciclo_semanal,
    gerar_relatorio_html_top10,
)
from telegram_bot import (
    processar_comando_telegram,
    formatar_resumo_top_alertas_texto,
)


def test_executar_ciclo_semanal_e_gerar_html_top10(tmp_path: Path) -> None:
    """Verifica se o ciclo semanal executa Coleta -> ETL -> Anomalias e gera HTML com Top 10 alertas."""
    db_path = tmp_path / "vigia_sched.db"
    raw_dir = tmp_path / "raw"
    enriched_dir = tmp_path / "enriched"
    clean_dir = tmp_path / "clean"
    html_out = tmp_path / "relatorio_semanal.html"

    resumo = executar_ciclo_semanal(
        raw_dir=raw_dir,
        enriched_dir=enriched_dir,
        clean_dir=clean_dir,
        db_path=db_path,
        relatorio_html_path=html_out,
        enviar_email=False,
    )
    assert html_out.exists()
    assert len(resumo["top_10_alertas"]) == 10

    html = gerar_relatorio_html_top10(resumo["top_10_alertas"])
    assert "<html" in html.lower()
    assert "top 10 alertas" in html.lower()
    assert "esta ferramenta não substitui a verificação documental" in html.lower()


def test_comandos_telegram_alertas_e_parlamentar(tmp_path: Path) -> None:
    """Verifica se o bot do Telegram responde aos comandos /alertas e /parlamentar <nome>."""
    db_path = tmp_path / "vigia_bot.db"
    executar_ciclo_semanal(
        raw_dir=tmp_path / "raw",
        enriched_dir=tmp_path / "enriched",
        clean_dir=tmp_path / "clean",
        db_path=db_path,
        relatorio_html_path=tmp_path / "relatorio.html",
        enviar_email=False,
    )

    resp_alertas = processar_comando_telegram("/alertas", db_path=db_path)
    assert "Top Alertas" in resp_alertas
    assert "verificação documental" in resp_alertas

    resp_parl = processar_comando_telegram("/parlamentar Júlio Garcia", db_path=db_path)
    assert "Júlio Garcia" in resp_parl
    assert "R$" in resp_parl

    resp_nao_encontrado = processar_comando_telegram("/parlamentar Inexistente XYZ", db_path=db_path)
    assert "Nenhum parlamentar encontrado" in resp_nao_encontrado

    texto_resumo = formatar_resumo_top_alertas_texto(db_path=db_path, limite=5)
    assert "Vigia Público SC" in texto_resumo
