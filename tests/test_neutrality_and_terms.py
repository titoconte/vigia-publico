"""Testes para garantir a remoção dos termos de apuração jornalística e a conformidade ética."""

from __future__ import annotations

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_disclaimer_etico_sem_termos_jornalisticos() -> None:
    """Verifica que o aviso ético padrão utiliza verificação documental sem menção a apuração jornalística."""
    frase_obrigatoria = "Esta ferramenta não substitui a verificação documental nem a apuração oficial."

    from app import AVISO_ETICO_FRONTEND
    from main import AVISO_ETICO_API
    from anomalies import NOTA_ETICA_PADRAO

    assert frase_obrigatoria in AVISO_ETICO_FRONTEND
    assert frase_obrigatoria in AVISO_ETICO_API
    assert "verificação e análise documental" in NOTA_ETICA_PADRAO
    assert "jornalística" not in NOTA_ETICA_PADRAO.lower()


def test_arquivos_principais_nao_contem_apuracao_jornalistica() -> None:
    """Garante que termos de apuração jornalística foram removidos de app, main, scheduler, telegram_bot e anomalies."""
    arquivos = [
        ROOT_DIR / "anomalies.py",
        ROOT_DIR / "app.py",
        ROOT_DIR / "main.py",
        ROOT_DIR / "scheduler.py",
        ROOT_DIR / "telegram_bot.py",
    ]

    termos_proibidos = [
        "apuração jornalística",
        "apuracao jornalistica",
        "verificação jornalística",
        "verificacao jornalistica",
        "jornalistas cadastrados",
        "avaliações de jornalistas",
        "feedback de jornalistas",
    ]

    for arq in arquivos:
        assert arq.exists(), f"Arquivo não encontrado: {arq}"
        conteudo = arq.read_text(encoding="utf-8").lower()
        for termo in termos_proibidos:
            assert termo not in conteudo, f"Termo proibido '{termo}' encontrado no arquivo {arq.name}"
