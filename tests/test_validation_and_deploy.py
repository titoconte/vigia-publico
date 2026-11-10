"""Testes de validação das Fases 7 e 8 — Documentação, ética, feedback.md, CI/CD e arquivos de deploy."""

from __future__ import annotations

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_arquivos_documentacao_e_deploy_existem() -> None:
    """Verifica a existência e conteúdo mínimo do README.md, feedback.md, LICENSE, CI e configs de deploy."""
    readme = ROOT_DIR / "README.md"
    feedback = ROOT_DIR / "feedback.md"
    licenca = ROOT_DIR / "LICENSE"
    ci_workflow = ROOT_DIR / ".github" / "workflows" / "ci.yml"
    railway = ROOT_DIR / "railway.json"
    render = ROOT_DIR / "render.yaml"
    changelog = ROOT_DIR / "CHANGELOG.md"

    assert readme.exists()
    assert feedback.exists()
    assert licenca.exists()
    assert ci_workflow.exists()
    assert railway.exists()
    assert render.exists()
    assert changelog.exists()

    texto_readme = readme.read_text(encoding="utf-8")
    assert "Vigia Público SC" in texto_readme
    assert "Como Rodar Localmente" in texto_readme
    assert "Como Contribuir" in texto_readme
    assert "Limitações Éticas" in texto_readme
    assert "Esta ferramenta não substitui a verificação jornalística nem a apuração oficial." in texto_readme

    texto_feedback = feedback.read_text(encoding="utf-8")
    assert "Verificação Manual de 5 Alertas" in texto_feedback
    assert "Feedback de Jornalistas" in texto_feedback
