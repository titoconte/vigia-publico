"""Fase 6 — Agendador semanal (segunda-feira 8h) de Coleta -> ETL -> Anomalias e envio de e-mail HTML."""

from __future__ import annotations

from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import html
import os
from pathlib import Path
import smtplib
from typing import Any

import pandas as pd

from anomalies import executar_motor_anomalias
from collect_tce import DEFAULT_RAW_DIR, executar_coleta_completa
from database import DEFAULT_DB_PATH
from enrich_cnpj import DEFAULT_ENRICHED_DIR, enriquecer_lote_cnpjs
from etl import DEFAULT_CLEAN_DIR, executar_etl

DEFAULT_RELATORIO_HTML = Path("data/clean/relatorio_semanal_top10.html")


def gerar_relatorio_html_top10(alertas: list[dict[str, Any]]) -> str:
    """Gera o relatório em HTML com os Top 10 alertas da semana e aviso ético obrigatório."""
    top10 = alertas[:10]
    data_geracao = datetime.now().strftime("%d/%m/%Y %H:%M")

    linhas_html: list[str] = []
    for idx, item in enumerate(top10, start=1):
        linhas_html.append(
            f"""
            <tr>
                <td style="padding:8px;border:1px solid #cbd5e1;text-align:center;">{idx}</td>
                <td style="padding:8px;border:1px solid #cbd5e1;text-align:center;"><strong>{float(item['pontuacao']):.1f}</strong></td>
                <td style="padding:8px;border:1px solid #cbd5e1;">{html.escape(str(item['tipo']))}</td>
                <td style="padding:8px;border:1px solid #cbd5e1;">{html.escape(str(item['parlamentar']))}</td>
                <td style="padding:8px;border:1px solid #cbd5e1;">{html.escape(str(item.get('municipio') or '-'))}</td>
                <td style="padding:8px;border:1px solid #cbd5e1;text-align:right;">R$ {float(item['valor']):,.2f}</td>
                <td style="padding:8px;border:1px solid #cbd5e1;">{html.escape(str(item['justificativa']))}</td>
                <td style="padding:8px;border:1px solid #cbd5e1;"><a href="{html.escape(str(item['fonte_url']))}">Fonte TCE/SC</a></td>
            </tr>
            """
        )

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8" />
    <title>Vigia Público SC — Top 10 Alertas da Semana</title>
</head>
<body style="font-family:Arial,sans-serif;color:#1e293b;line-height:1.5;margin:24px;">
    <h2>🔍 Vigia Público SC — Top 10 Alertas da Semana ({data_geracao})</h2>
    <p style="background:#fef3c7;border-left:4px solid #f59e0b;padding:12px;">
        <strong>Aviso Ético e Legal:</strong> Esta ferramenta não substitui a verificação jornalística nem a apuração oficial.
        Os alertas apontam padrões estatísticos e cadastrais que merecem verificação, não constituindo prova de irregularidade.
    </p>
    <table style="border-collapse:collapse;width:100%;font-size:14px;">
        <thead>
            <tr style="background:#f1f5f9;">
                <th style="padding:8px;border:1px solid #cbd5e1;">#</th>
                <th style="padding:8px;border:1px solid #cbd5e1;">Pts</th>
                <th style="padding:8px;border:1px solid #cbd5e1;">Regra / Padrão</th>
                <th style="padding:8px;border:1px solid #cbd5e1;">Parlamentar</th>
                <th style="padding:8px;border:1px solid #cbd5e1;">Município</th>
                <th style="padding:8px;border:1px solid #cbd5e1;">Valor (R$)</th>
                <th style="padding:8px;border:1px solid #cbd5e1;">Justificativa</th>
                <th style="padding:8px;border:1px solid #cbd5e1;">Fonte</th>
            </tr>
        </thead>
        <tbody>
            {''.join(linhas_html)}
        </tbody>
    </table>
</body>
</html>"""


def enviar_relatorio_por_email(
    conteudo_html: str,
    destinatarios: list[str] | None = None,
) -> bool:
    """Envia o relatório HTML semanal por e-mail via SMTP para a lista de jornalistas cadastrados."""
    lista_emails = destinatarios or [
        e.strip() for e in os.getenv("ALERT_RECIPIENTS", "").split(",") if e.strip()
    ]
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASSWORD", "").strip()
    remetente = os.getenv("SMTP_FROM", smtp_user or "alertas@vigiapublico.org.br")

    if not lista_emails or not smtp_host or not smtp_user or not smtp_pass:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Vigia Público SC — Resumo Semanal: Top 10 Alertas para Apuração"
    msg["From"] = remetente
    msg["To"] = ", ".join(lista_emails)
    msg.attach(MIMEText(conteudo_html, "html", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as servidor:
        servidor.starttls()
        servidor.login(smtp_user, smtp_pass)
        servidor.sendmail(remetente, lista_emails, msg.as_string())
    return True


def executar_ciclo_semanal(
    *,
    raw_dir: Path | str = DEFAULT_RAW_DIR,
    enriched_dir: Path | str = DEFAULT_ENRICHED_DIR,
    clean_dir: Path | str = DEFAULT_CLEAN_DIR,
    db_path: Path | str = DEFAULT_DB_PATH,
    relatorio_html_path: Path | str = DEFAULT_RELATORIO_HTML,
    enviar_email: bool = True,
    usar_rede: bool | None = None,
) -> dict[str, Any]:
    """Executa o pipeline semanal completo (Coleta -> ETL -> Motor de Anomalias -> Relatório Top 10 HTML -> E-mail)."""
    res_coleta = executar_coleta_completa(raw_dir=raw_dir, usar_rede=usar_rede)
    df_emendas = pd.read_csv(res_coleta["emendas_csv"], dtype={"fornecedor_cnpj": str})
    cnpjs = df_emendas["fornecedor_cnpj"].dropna().astype(str).unique().tolist()
    enriquecer_lote_cnpjs(cnpjs, output_dir=enriched_dir, usar_rede=usar_rede)
    executar_etl(
        raw_dir=raw_dir,
        enriched_dir=enriched_dir,
        clean_dir=clean_dir,
        db_path=db_path,
        usar_rede=usar_rede,
    )
    alertas = executar_motor_anomalias(db_path=db_path)

    top_10 = alertas[:10]
    html_relatorio = gerar_relatorio_html_top10(top_10)
    caminho_html = Path(relatorio_html_path)
    caminho_html.parent.mkdir(parents=True, exist_ok=True)
    caminho_html.write_text(html_relatorio, encoding="utf-8")

    email_enviado = False
    if enviar_email:
        try:
            email_enviado = enviar_relatorio_por_email(html_relatorio)
        except Exception:
            email_enviado = False

    return {
        "total_alertas": len(alertas),
        "top_10_alertas": top_10,
        "relatorio_html_path": str(caminho_html),
        "email_enviado": email_enviado,
    }


def iniciar_agendador_semanal() -> None:
    """Inicia o agendador APScheduler configurado para rodar toda segunda-feira às 08h00."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(
        executar_ciclo_semanal,
        trigger="cron",
        day_of_week="mon",
        hour=8,
        minute=0,
        id="ciclo_semanal_vigia_publico_sc",
        replace_existing=True,
    )
    print("Agendador iniciado: execução programada para toda segunda-feira às 08:00.")
    scheduler.start()


if __name__ == "__main__":
    res = executar_ciclo_semanal(enviar_email=False)
    print(f"Ciclo semanal executado: {res['total_alertas']} alertas | Relatório salvo em {res['relatorio_html_path']}")
