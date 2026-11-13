"""Testes unitários para o módulo de autenticação e proteção por senha (auth.py)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from auth import (
    DEFAULT_PASSWORD,
    DEFAULT_USERNAME,
    calcular_hash_senha,
    fazer_login,
    fazer_logout,
    obter_credenciais_configuradas,
    renderizar_tela_login,
    usuario_esta_autenticado,
    verificar_credenciais,
)


def test_calcular_hash_senha() -> None:
    """Verifica se o hash SHA-256 é calculado de forma determinística e não reversível."""
    hash1 = calcular_hash_senha("segredo123")
    hash2 = calcular_hash_senha("segredo123")
    hash3 = calcular_hash_senha("outro_segredo")

    assert hash1 == hash2
    assert hash1 != hash3
    assert len(hash1) == 64


def test_obter_credenciais_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica se as variáveis de ambiente VIGIA_ADMIN_USERNAME e VIGIA_ADMIN_PASSWORD são lidas."""
    monkeypatch.setenv("VIGIA_ADMIN_USERNAME", "jornalista_sc")
    monkeypatch.setenv("VIGIA_ADMIN_PASSWORD", "chave_ultra_secreta")

    creds = obter_credenciais_configuradas()
    assert creds["username"] == "jornalista_sc"
    assert creds["password"] == "chave_ultra_secreta"


def test_verificar_credenciais(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica a validação de credenciais válidas e rejeição de incorretas com mitigação de timing attack."""
    monkeypatch.setenv("VIGIA_ADMIN_USERNAME", "auditor")
    monkeypatch.setenv("VIGIA_ADMIN_PASSWORD", "senha_forte_2026")

    # Sucesso (inclusive case-insensitive no usuário e com limpeza de aspas/espaços acidentais)
    assert verificar_credenciais("auditor", "senha_forte_2026") is True
    assert verificar_credenciais("AUDITOR", "senha_forte_2026") is True
    assert verificar_credenciais("auditor", ' "senha_forte_2026" ') is True

    # Falhas
    assert verificar_credenciais("auditor", "senha_completamente_incorreta") is False
    assert verificar_credenciais("usuario_inexistente_xyz", "senha_completamente_incorreta") is False
    assert verificar_credenciais("", "") is False
    assert verificar_credenciais("auditor", "") is False


def test_ciclo_login_logout() -> None:
    """Verifica a alteração correta do session_state durante o login e logout."""
    mock_st = MagicMock()
    mock_st.session_state = {}

    assert usuario_esta_autenticado(mock_st) is False

    # Login
    fazer_login(mock_st, "investigador")
    assert usuario_esta_autenticado(mock_st) is True
    assert mock_st.session_state["usuario_logado"] == "investigador"

    # Logout
    fazer_logout(mock_st)
    assert usuario_esta_autenticado(mock_st) is False
    assert "usuario_logado" not in mock_st.session_state
    assert mock_st.rerun.called


def test_renderizar_tela_login() -> None:
    """Verifica se a tela de login renderiza os componentes de formulário sem levantar exceções."""
    mock_st = MagicMock()
    mock_st.columns.return_value = (MagicMock(), MagicMock(), MagicMock())
    mock_form = MagicMock()
    mock_st.form.return_value.__enter__.return_value = mock_form
    mock_form.form_submit_button.return_value = False

    renderizar_tela_login(mock_st)
    assert mock_st.columns.called
    assert mock_st.form.called


def test_credenciais_vigilante_padrao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica se o usuário vigilante e a senha forte de 30 caracteres funcionam no fallback."""
    monkeypatch.delenv("VIGIA_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("VIGIA_ADMIN_PASSWORD", raising=False)

    assert verificar_credenciais("vigilante", "pkH%sIwunCo-le&Up6gD!aJVsam3yk") is True
    assert verificar_credenciais("VIGILANTE", "pkH%sIwunCo-le&Up6gD!aJVsam3yk") is True
    assert verificar_credenciais("vigilante", "   pkH%sIwunCo-le&Up6gD!aJVsam3yk   ") is True
    assert verificar_credenciais("vigilante", '"pkH%sIwunCo-le&Up6gD!aJVsam3yk"') is True


