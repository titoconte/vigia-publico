"""Fase 6 (Item 2) — Bot do Telegram para envio de resumos semanais e consulta via /alertas e /parlamentar."""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from database import DEFAULT_DB_PATH, conectar_banco
from main import garantir_dados_iniciais


def formatar_resumo_top_alertas_texto(
    db_path: Path | str = DEFAULT_DB_PATH,
    limite: int = 10,
) -> str:
    """Formata o resumo em texto dos principais alertas para envio no Telegram."""
    caminho = garantir_dados_iniciais(db_path)
    with conectar_banco(caminho) as conn:
        linhas = conn.execute(
            "SELECT * FROM alertas ORDER BY pontuacao DESC, valor DESC LIMIT ?",
            (limite,),
        ).fetchall()

    partes = [
        "🔍 *Vigia Público SC — Top Alertas para Apuração*",
        "⚠️ _Esta ferramenta não substitui a verificação jornalística nem a apuração oficial._\n",
    ]
    for idx, row in enumerate(linhas, start=1):
        partes.append(
            f"{idx}. *[{float(row['pontuacao']):.1f} pts] {row['tipo']}*\n"
            f"   👤 {row['parlamentar']} | 📍 {row['municipio']}\n"
            f"   💰 R$ {float(row['valor']):,.2f} | 🏢 {row['beneficiario']}\n"
            f"   🔗 Fonte: {row['fonte_url']}\n"
        )
    return "\n".join(partes)


def consultar_parlamentar_texto(
    termo_nome: str,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> str:
    """Busca o perfil resumido e os alertas de um parlamentar a partir do comando /parlamentar <nome>."""
    caminho = garantir_dados_iniciais(db_path)
    termo = termo_nome.strip().lower()
    if not termo:
        return "Uso: `/parlamentar <nome do parlamentar>`"

    with conectar_banco(caminho) as conn:
        parl = conn.execute(
            "SELECT * FROM agregados_parlamentar WHERE LOWER(parlamentar) LIKE ? ORDER BY total_emendas DESC",
            (f"%{termo}%",),
        ).fetchone()
        if not parl:
            return f"Nenhum parlamentar encontrado para o termo '{termo_nome}'."

        nome_exato = str(parl["parlamentar"])
        alertas = conn.execute(
            "SELECT * FROM alertas WHERE parlamentar = ? ORDER BY pontuacao DESC LIMIT 5",
            (nome_exato,),
        ).fetchall()

    linhas = [
        f"🏛️ *Perfil do Parlamentar: {nome_exato}* ({parl['partido']})",
        f"💰 Total em emendas: R$ {float(parl['total_emendas']):,.2f}",
        f"📊 Quantidade de emendas: {int(parl['quantidade_emendas'])}",
        f"🏥 Área principal: {parl['principal_area']}",
        f"🏢 Principal fornecedor: {parl['principal_fornecedor']} ({float(parl['percentual_maior_fornecedor']):.1f}%)\n",
        "🚨 *Padrões / Alertas associados:*",
    ]
    if alertas:
        for a in alertas:
            linhas.append(f"- [{float(a['pontuacao']):.1f} pts] {a['tipo']}: {a['justificativa']}")
    else:
        linhas.append("- Nenhum alerta estatístico associado.")
    linhas.append("\n⚠️ _Esta ferramenta não substitui a verificação jornalística nem a apuração oficial._")
    return "\n".join(linhas)


def processar_comando_telegram(
    mensagem: str,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> str:
    """Interpreta comandos do bot (/start, /alertas, /parlamentar <nome>) e retorna a resposta textual."""
    texto = (mensagem or "").strip()
    if texto.startswith("/alertas"):
        return formatar_resumo_top_alertas_texto(db_path=db_path, limite=10)
    if texto.startswith("/parlamentar"):
        argumento = texto.replace("/parlamentar", "", 1).strip()
        return consultar_parlamentar_texto(argumento, db_path=db_path)
    return (
        "👋 Bem-vindo ao *Vigia Público SC*!\n"
        "Comandos disponíveis:\n"
        "• `/alertas` — Lista os Top 10 alertas da semana\n"
        "• `/parlamentar <nome>` — Exibe totais e alertas de um parlamentar"
    )


def enviar_resumo_telegram(
    db_path: Path | str = DEFAULT_DB_PATH,
    bot_token: str | None = None,
    chat_ids: list[str] | None = None,
) -> int:
    """Envia o resumo semanal de alertas via API HTTP do Telegram Bot para os jornalistas cadastrados."""
    token = (bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
    destinos = chat_ids or [
        c.strip() for c in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()
    ]
    if not token or not destinos:
        return 0

    texto = formatar_resumo_top_alertas_texto(db_path=db_path, limite=10)
    enviados = 0
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chat_id in destinos:
        try:
            resp = httpx.post(
                url,
                json={"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"},
                timeout=15.0,
            )
            if resp.status_code == 200:
                enviados += 1
        except Exception:
            continue
    return enviados


if __name__ == "__main__":
    print(processar_comando_telegram("/alertas"))
