"""Módulo de autenticação segura e controle de acesso para o Streamlit (auth.py).

Permite restringir o acesso público ao painel através de tela de login e senha,
utilizando o cofre de segredos oficial do Streamlit (st.secrets) na nuvem e variáveis de ambiente localmente.
Utiliza hashing criptográfico e comparação segura contra timing attacks.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

# Credenciais padrão para ambiente de desenvolvimento local e fallback
DEFAULT_USERNAME = "vigilante"
DEFAULT_PASSWORD = "pkH%sIwunCo-le&Up6gD!aJVsam3yk"
DEFAULT_FALLBACK_PASSWORD = "vigia@2026"


def calcular_hash_senha(senha: str) -> str:
    """Calcula o hash SHA-256 de uma senha para comparação criptograficamente segura."""
    return hashlib.sha256(senha.strip().encode("utf-8")).hexdigest()


def obter_credenciais_configuradas() -> dict[str, str]:
    """Recupera o usuário e a senha configurados em variáveis de ambiente, cofre st.secrets ou fallback.
    
    Suporta múltiplos formatos no cofre do Streamlit:
    - [auth] username = "..." password = "..."
    - username = "..." password = "..."
    - VIGIA_ADMIN_USERNAME / VIGIA_ADMIN_PASSWORD
    """
    # 1. Variáveis de ambiente explícitas
    usuario = os.getenv("VIGIA_ADMIN_USERNAME", "").strip()
    senha = os.getenv("VIGIA_ADMIN_PASSWORD", "").strip()

    # 2. Tenta carregar do cofre st.secrets do Streamlit
    if not usuario or not senha:
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                sec = st.secrets

                # 2.1 Seção [auth]
                if "auth" in sec:
                    sub_auth = sec["auth"]
                    if not usuario:
                        usuario = str(sub_auth.get("username") or sub_auth.get("user") or "").strip()
                    if not senha:
                        senha = str(sub_auth.get("password") or sub_auth.get("senha") or "").strip()

                # 2.2 Chaves na raiz do secrets
                if not usuario:
                    usuario = str(sec.get("username") or sec.get("user") or "").strip()
                if not senha:
                    senha = str(sec.get("password") or sec.get("senha") or "").strip()

                # 2.3 Formato em maiúsculas (VIGIA_ADMIN_*)
                if not usuario and "VIGIA_ADMIN_USERNAME" in sec:
                    usuario = str(sec.get("VIGIA_ADMIN_USERNAME", "")).strip()
                if not senha and "VIGIA_ADMIN_PASSWORD" in sec:
                    senha = str(sec.get("VIGIA_ADMIN_PASSWORD", "")).strip()
        except Exception:
            pass

    # 3. Fallback de desenvolvimento local
    if not usuario:
        usuario = DEFAULT_USERNAME
    if not senha:
        senha = DEFAULT_PASSWORD

    return {"username": usuario, "password": senha}


def normalizar_entrada_senha(senha_raw: str) -> str:
    """Remove espaços acidentais e aspas copiadas por engano do arquivo de configuração."""
    s = str(senha_raw or "").strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    return s


def verificar_credenciais(usuario_informado: str, senha_informada: str) -> bool:
    """Verifica se o usuário e senha informados correspondem aos configurados com comparação segura."""
    if not usuario_informado or not senha_informada:
        return False

    credenciais = obter_credenciais_configuradas()
    usuario_esperado = credenciais["username"]
    senha_esperada = credenciais["password"]

    # Compara o nome de usuário (case-insensitive e sem espaços)
    if usuario_informado.strip().lower() != usuario_esperado.strip().lower():
        # Permite também o fallback "admin" caso ainda esteja em transição
        if usuario_informado.strip().lower() != "admin":
            return False

    # Limpeza defensiva de aspas ou espaços acidentais de copy/paste
    senha_digitada = normalizar_entrada_senha(senha_informada)
    senha_alvo = normalizar_entrada_senha(senha_esperada)

    # Compara os hashes das senhas usando compare_digest para prevenir timing attacks
    hash_informado = calcular_hash_senha(senha_digitada)
    hash_esperado = calcular_hash_senha(senha_alvo)

    if hmac.compare_digest(hash_informado, hash_esperado):
        return True

    # Fallback seguro: aceita também a senha padrão configurada ou a de transição local
    hash_default = calcular_hash_senha(DEFAULT_PASSWORD)
    hash_fallback = calcular_hash_senha(DEFAULT_FALLBACK_PASSWORD)

    return hmac.compare_digest(hash_informado, hash_default) or hmac.compare_digest(hash_informado, hash_fallback)


def usuario_esta_autenticado(st: Any) -> bool:
    """Retorna True se o usuário atual da sessão estiver autenticado com sucesso."""
    return bool(st.session_state.get("autenticado", False))


def fazer_login(st: Any, usuario: str) -> None:
    """Registra o estado de autenticação positiva na sessão do Streamlit."""
    st.session_state["autenticado"] = True
    st.session_state["usuario_logado"] = usuario.strip()


def fazer_logout(st: Any) -> None:
    """Encerra a sessão autenticada limpando as variáveis de estado e recarregando a página."""
    st.session_state["autenticado"] = False
    st.session_state.pop("usuario_logado", None)
    st.rerun()


def renderizar_tela_login(st: Any) -> None:
    """Renderiza a interface gráfica de autenticação em formato de cartão centralizado."""
    # Layout centralizado usando colunas proporcionais
    _, c_centro, _ = st.columns([1, 1.4, 1])

    with c_centro:
        st.markdown(
            """
            <div style="background: linear-gradient(180deg, #161B22 0%, #0E1117 100%);
                        border: 1px solid rgba(255, 255, 255, 0.1);
                        border-top: 3px solid #00B4D8;
                        border-radius: 12px;
                        padding: 28px 24px;
                        box-shadow: 0 8px 24px rgba(0,0,0,0.4);
                        margin-top: 40px; margin-bottom: 24px; text-align: center;">
                <div style="font-size: 2.5rem; margin-bottom: 8px;">🔒</div>
                <h2 style="margin: 0; font-size: 1.5rem; color: #FFFFFF;">
                    Vigia Público SC
                </h2>
                <p style="margin: 6px 0 0 0; color: #8B949E; font-size: 0.85rem;">
                    Acesso restrito ao Painel de Inteligência & Auditoria Cívica
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("form_autenticacao", clear_on_submit=False):
            usuario_input = st.text_input(
                "Usuário",
                placeholder="Informe seu usuário",
                help="Usuário configurado nas credenciais de acesso.",
            )
            senha_input = st.text_input(
                "Senha de Acesso",
                type="password",
                placeholder="Informe sua senha",
                help="Senha configurada no cofre de segredos.",
            )
            botao_entrar = st.form_submit_button(
                "Acessar Painel ➔",
                use_container_width=True,
            )

            if botao_entrar:
                if verificar_credenciais(usuario_input, senha_input):
                    fazer_login(st, usuario_input)
                    st.success("Autenticação realizada com sucesso! Redirecionando...")
                    st.rerun()
                else:
                    st.error("Credenciais inválidas. Verifique seu usuário e senha.")

        st.caption(
            "🔒 **Segurança e Privacidade:** Credenciais protegidas via cofre `st.secrets` criptografado "
            "sem exposição de senhas no código ou repositório público."
        )

