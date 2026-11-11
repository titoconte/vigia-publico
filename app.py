"""Fase 5 — Frontend Streamlit do Vigia Público SC com 4 páginas interativas para controle social e auditoria cívica."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pandas as pd

from database import conectar_banco, resolver_caminho_sqlite
from main import garantir_dados_iniciais

AVISO_ETICO_FRONTEND = (
    "⚠️ **Nota Ética e Metodológica:** Esta ferramenta não substitui a verificação documental "
    "nem a apuração oficial. Os alertas indicam padrões estatísticos e cadastrais em dados públicos "
    "que merecem verificação, e não provas de irregularidade."
)


def carregar_dados_painel(db_path: Path | str | None = None) -> dict[str, pd.DataFrame]:
    """Carrega os DataFrames de alertas, emendas, parlamentares e municípios a partir do banco de dados."""
    caminho = garantir_dados_iniciais(db_path)
    with conectar_banco(caminho) as conn:
        df_alertas = pd.read_sql_query("SELECT * FROM alertas ORDER BY pontuacao DESC, valor DESC", conn)
        df_emendas = pd.read_sql_query("SELECT * FROM emendas_clean ORDER BY valor DESC", conn)
        df_parlamentares = pd.read_sql_query(
            "SELECT * FROM agregados_parlamentar ORDER BY total_emendas DESC", conn
        )
        df_municipios = pd.read_sql_query(
            "SELECT * FROM agregados_municipio ORDER BY total_recebido DESC", conn
        )
    return {
        "alertas": df_alertas,
        "emendas": df_emendas,
        "parlamentares": df_parlamentares,
        "municipios": df_municipios,
    }


def eh_bancada_regional(nome_autor: Any) -> bool:
    """Verifica se o nome informado corresponde a uma bancada regional da ALESC (se a string começar com 'BANCADA ')."""
    if nome_autor is None or pd.isna(nome_autor):
        return False
    return str(nome_autor).strip().upper().startswith("BANCADA ")


def separar_autores_por_tipo(lista_autores: list[str]) -> dict[str, list[str]]:
    """Separa uma lista de nomes de autores entre 'parlamentares' individuais e 'bancadas' regionais."""
    bancadas = sorted([a for a in lista_autores if eh_bancada_regional(a)])
    parlamentares = sorted([a for a in lista_autores if not eh_bancada_regional(a)])
    return {"parlamentares": parlamentares, "bancadas": bancadas}


def obter_totais_por_partido(df_emendas: pd.DataFrame) -> pd.Series:
    """Calcula o somatório total financeiro (R$) de emendas agrupado por partido político."""
    if df_emendas.empty or "partido" not in df_emendas.columns:
        return pd.Series(dtype=float)
    return df_emendas.groupby("partido")["valor"].sum().sort_values(ascending=False)


def obter_totais_por_parlamentar(
    df_emendas: pd.DataFrame,
    *,
    tipo_autor: str = "Todos",
    top_n: int | None = None,
) -> pd.Series:
    """Calcula o valor total acumulado de emendas por parlamentar ou bancada em ordem decrescente."""
    if df_emendas.empty or "parlamentar" not in df_emendas.columns:
        return pd.Series(dtype=float)
    df = df_emendas.copy()
    if tipo_autor in ("Bancadas", "Bancada Regional", "Bancada", "Bancadas Regionais"):
        df = df[df["parlamentar"].apply(eh_bancada_regional)]
    elif tipo_autor in ("Parlamentares", "Parlamentar Individual", "Parlamentar", "Parlamentares Individuais"):
        df = df[~df["parlamentar"].apply(eh_bancada_regional)]

    agrupado = df.groupby("parlamentar")["valor"].sum().sort_values(ascending=False)
    if top_n and top_n > 0:
        return agrupado.head(top_n)
    return agrupado


def obter_totais_por_ano(
    df_emendas: pd.DataFrame,
    *,
    parlamentar: str | None = None,
) -> pd.Series:
    """Calcula o somatório financeiro (R$) de emendas agrupado por ano de referência."""
    if df_emendas.empty or "data" not in df_emendas.columns:
        return pd.Series(dtype=float)
    df = df_emendas.copy()
    if parlamentar and parlamentar != "Todos":
        df = df[df["parlamentar"] == parlamentar]

    anos = df["data"].astype(str).str.slice(0, 4)
    df["ano"] = anos
    return df.groupby("ano")["valor"].sum().sort_index()


def filtrar_emendas_explorador(
    df_emendas: pd.DataFrame,
    *,
    parlamentar: str = "Todos",
    municipio: str = "Todos",
    area: str = "Todas",
    valor_minimo: float = 0.0,
    tipo_autor: str = "Todos",
) -> pd.DataFrame:
    """Aplica os filtros selecionados pelo usuário na Página 2 (Explorador de Emendas)."""
    df = df_emendas.copy()
    if tipo_autor in ("Parlamentar", "Parlamentar Individual", "Parlamentares", "Parlamentares Individuais"):
        df = df[~df["parlamentar"].apply(eh_bancada_regional)]
    elif tipo_autor in ("Bancada", "Bancada Regional", "Bancadas", "Bancadas Regionais"):
        df = df[df["parlamentar"].apply(eh_bancada_regional)]

    if parlamentar and parlamentar != "Todos":
        df = df[df["parlamentar"] == parlamentar]
    if municipio and municipio != "Todos":
        df = df[df["municipio"] == municipio]
    if area and area != "Todas":
        df = df[df["area"] == area]
    if valor_minimo > 0:
        df = df[df["valor"] >= float(valor_minimo)]
    return df.reset_index(drop=True)


def obter_dados_perfil_parlamentar(
    parlamentar: str,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Consolida os totais, distribuição por área, emendas e alertas associados a um parlamentar (Página 3)."""
    caminho = resolver_caminho_sqlite(db_path)
    with conectar_banco(caminho) as conn:
        resumo_row = conn.execute(
            "SELECT * FROM agregados_parlamentar WHERE parlamentar = ?",
            (parlamentar,),
        ).fetchone()
        df_emendas = pd.read_sql_query(
            "SELECT * FROM emendas_clean WHERE parlamentar = ? ORDER BY valor DESC",
            conn,
            params=(parlamentar,),
        )
        df_alertas = pd.read_sql_query(
            "SELECT * FROM alertas WHERE parlamentar = ? ORDER BY pontuacao DESC",
            conn,
            params=(parlamentar,),
        )

    por_area = (
        df_emendas.groupby("area", as_index=False)["valor"]
        .sum()
        .sort_values("valor", ascending=False)
        if not df_emendas.empty
        else pd.DataFrame(columns=["area", "valor"])
    )
    return {
        "resumo": dict(resumo_row) if resumo_row else {"parlamentar": parlamentar, "total_emendas": 0.0},
        "emendas": df_emendas,
        "por_area": por_area,
        "alertas": df_alertas.to_dict(orient="records"),
    }


def obter_dados_perfil_municipio(
    codigo_ou_nome: str,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Consolida população, total recebido, per capita, emendas e alertas de um município (Página 4)."""
    caminho = resolver_caminho_sqlite(db_path)
    with conectar_banco(caminho) as conn:
        mun_row = conn.execute(
            "SELECT * FROM agregados_municipio WHERE codigo_ibge = ? OR municipio = ?",
            (codigo_ou_nome, codigo_ou_nome),
        ).fetchone()
        if not mun_row:
            return {"resumo": {}, "emendas": pd.DataFrame(), "alertas": []}
        resumo = dict(mun_row)
        cod_ibge = str(resumo["codigo_ibge"])
        df_emendas = pd.read_sql_query(
            "SELECT * FROM emendas_clean WHERE codigo_ibge = ? ORDER BY valor DESC",
            conn,
            params=(cod_ibge,),
        )
        df_alertas = pd.read_sql_query(
            "SELECT * FROM alertas WHERE codigo_ibge = ? ORDER BY pontuacao DESC",
            conn,
            params=(cod_ibge,),
        )

    return {
        "resumo": resumo,
        "emendas": df_emendas,
        "alertas": df_alertas.to_dict(orient="records"),
    }


def registrar_feedback_local(
    *,
    alerta_id: int,
    avaliacao: str,
    comentario: str = "",
    usuario: str = "",
    jornalista: str = "",
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Registra diretamente no banco o feedback do usuário/analista ('util' ou 'falso_positivo') a partir do Streamlit."""
    caminho = resolver_caminho_sqlite(db_path)
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    aval = "util" if avaliacao in ("util", "útil") else "falso_positivo"
    identificador_autor = usuario or jornalista or ""

    with conectar_banco(caminho) as conn:
        conn.execute(
            """
            INSERT INTO alertas_feedback (alerta_id, avaliacao, comentario, jornalista, criado_em)
            VALUES (?, ?, ?, ?, ?)
            """,
            (alerta_id, aval, comentario, identificador_autor, agora),
        )
        if aval == "util":
            conn.execute("UPDATE alertas SET util_count = util_count + 1 WHERE id = ?", (alerta_id,))
        else:
            conn.execute(
                "UPDATE alertas SET falso_positivo_count = falso_positivo_count + 1 WHERE id = ?",
                (alerta_id,),
            )
        conn.commit()
        atualizado = conn.execute("SELECT * FROM alertas WHERE id = ?", (alerta_id,)).fetchone()
    return dict(atualizado) if atualizado else {}


def renderizar_pagina_painel_alertas(st: Any, dados: dict[str, pd.DataFrame]) -> None:
    """Renderiza a Página 1: Painel de Alertas com verificação separada por bancada ou parlamentar."""
    st.header("🚨 Página 1 — Painel de Alertas e Análise de Risco")
    df_alertas = dados["alertas"]

    c_tipo_autor, col1, col2, col3, col4 = st.columns([1.2, 1.2, 1.2, 1.2, 1.0])
    filtro_tipo_autor = c_tipo_autor.selectbox(
        "Tipo de Autor",
        ["Todos", "Parlamentar Individual", "Bancada Regional"],
        key="p1_tipo_autor",
    )

    autores_alertas = df_alertas["parlamentar"].dropna().unique().tolist()
    divisao_autores = separar_autores_por_tipo(autores_alertas)
    if filtro_tipo_autor == "Bancada Regional":
        opcoes_autor = ["Todos"] + divisao_autores["bancadas"]
    elif filtro_tipo_autor == "Parlamentar Individual":
        opcoes_autor = ["Todos"] + divisao_autores["parlamentares"]
    else:
        opcoes_autor = ["Todos"] + sorted(autores_alertas)

    tipos = ["Todos"] + sorted(df_alertas["tipo"].dropna().unique().tolist())
    municipios = ["Todos"] + sorted(df_alertas["municipio"].dropna().unique().tolist())

    filtro_tipo = col1.selectbox("Regra / Tipo de Padrão", tipos)
    filtro_parl = col2.selectbox("Autor Específico", opcoes_autor, key=f"p1_autor_{filtro_tipo_autor}")
    filtro_mun = col3.selectbox("Município", municipios)
    filtro_score = col4.slider("Pontuação Mínima", min_value=0, max_value=100, value=60, step=5)

    df_view = df_alertas[df_alertas["pontuacao"] >= filtro_score].copy()
    if filtro_tipo_autor == "Bancada Regional":
        df_view = df_view[df_view["parlamentar"].apply(eh_bancada_regional)]
    elif filtro_tipo_autor == "Parlamentar Individual":
        df_view = df_view[~df_view["parlamentar"].apply(eh_bancada_regional)]
    if filtro_tipo != "Todos":
        df_view = df_view[df_view["tipo"] == filtro_tipo]
    if filtro_parl != "Todos":
        df_view = df_view[df_view["parlamentar"] == filtro_parl]
    if filtro_mun != "Todos":
        df_view = df_view[df_view["municipio"] == filtro_mun]

    st.caption(f"Exibindo **{len(df_view)}** padrões detectados ordenados por pontuação de prioridade.")
    st.dataframe(
        df_view[["id", "pontuacao", "tipo", "parlamentar", "municipio", "valor", "beneficiario"]],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("🔍 Ver Detalhes e Calibrar Regras")
    for _, alerta in df_view.iterrows():
        titulo_card = (
            f"[{alerta['pontuacao']:.1f} pts] {alerta['tipo']} — {alerta['parlamentar']} "
            f"| {alerta['municipio']} (R$ {float(alerta['valor']):,.2f})"
        )
        with st.expander(titulo_card):
            st.markdown(f"**Justificativa Técnica:** {alerta['justificativa']}")
            st.markdown(f"**Beneficiário / Fornecedor:** `{alerta['beneficiario']}` (CNPJ `{alerta['fornecedor_cnpj']}`)")
            st.markdown(f"**Fonte Oficial:** [{alerta['fonte_url']}]({alerta['fonte_url']})")
            st.markdown(f"**Hash de Auditoria SHA-256:** `{alerta['hash_auditoria']}`")

            try:
                contexto = json.loads(str(alerta["dados_contexto"]))
            except Exception:
                contexto = {"raw": str(alerta["dados_contexto"])}
            st.json(contexto)

            c_btn1, c_btn2, c_info = st.columns([1, 1, 2])
            if c_btn1.button("👍 Marcar como Útil", key=f"util_{alerta['id']}"):
                registrar_feedback_local(alerta_id=int(alerta["id"]), avaliacao="util")
                st.success("Feedback 'Útil' registrado para calibragem das regras!")
            if c_btn2.button("⚠️ Falso Positivo", key=f"fp_{alerta['id']}"):
                registrar_feedback_local(alerta_id=int(alerta["id"]), avaliacao="falso_positivo")
                st.warning("Feedback 'Falso Positivo' registrado para calibragem das regras!")
            c_info.caption(
                f"Avaliações dos usuários: 👍 {int(alerta['util_count'])} úteis | "
                f"⚠️ {int(alerta['falso_positivo_count'])} falsos positivos"
            )


def renderizar_pagina_explorador_emendas(st: Any, dados: dict[str, pd.DataFrame]) -> None:
    """Renderiza a Página 2: Explorador de Emendas com tabela filtrável por bancada ou parlamentar."""
    st.header("📊 Página 2 — Explorador de Emendas Parlamentares")
    df_emendas = dados["emendas"]

    c_tipo, col1, col2, col3, col4 = st.columns([1.2, 1.2, 1.2, 1.2, 1.0])
    f_tipo_autor = c_tipo.selectbox(
        "Tipo de Autor",
        ["Todos", "Parlamentar Individual", "Bancada Regional"],
        key="p2_tipo_autor",
    )

    autores_emendas = df_emendas["parlamentar"].unique().tolist()
    divisao_emendas = separar_autores_por_tipo(autores_emendas)
    if f_tipo_autor == "Bancada Regional":
        opcoes_parl = ["Todos"] + divisao_emendas["bancadas"]
    elif f_tipo_autor == "Parlamentar Individual":
        opcoes_parl = ["Todos"] + divisao_emendas["parlamentares"]
    else:
        opcoes_parl = ["Todos"] + sorted(autores_emendas)

    municipios = ["Todos"] + sorted(df_emendas["municipio"].unique().tolist())
    areas = ["Todas"] + sorted(df_emendas["area"].unique().tolist())

    f_parl = col1.selectbox("Autor Específico", opcoes_parl, key=f"p2_autor_{f_tipo_autor}")
    f_mun = col2.selectbox("Filtrar por Município", municipios)
    f_area = col3.selectbox("Filtrar por Área", areas)
    f_val = col4.number_input("Valor Mínimo (R$)", min_value=0.0, value=0.0, step=50000.0)

    df_filtrado = filtrar_emendas_explorador(
        df_emendas,
        parlamentar=f_parl,
        municipio=f_mun,
        area=f_area,
        valor_minimo=f_val,
        tipo_autor=f_tipo_autor,
    )

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Filtrado", f"R$ {df_filtrado['valor'].sum():,.2f}")
    m2.metric("Quantidade de Emendas", f"{len(df_filtrado)}")
    m3.metric("Municípios Contemplados", f"{df_filtrado['codigo_ibge'].nunique()}")

    st.dataframe(
        df_filtrado[
            [
                "id_emenda",
                "parlamentar",
                "partido",
                "municipio",
                "area",
                "valor",
                "valor_per_capita",
                "entidade_beneficiaria",
                "fornecedor_nome",
                "fornecedor_cnpj",
                "status_execucao",
                "data",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    g1, g2 = st.columns(2)
    with g1:
        st.subheader("Total por Parlamentar (R$)")
        if not df_filtrado.empty:
            por_parl = df_filtrado.groupby("parlamentar")["valor"].sum().sort_values(ascending=False)
            st.bar_chart(por_parl)
    with g2:
        st.subheader("Total por Município (R$)")
        if not df_filtrado.empty:
            por_mun = df_filtrado.groupby("municipio")["valor"].sum().sort_values(ascending=False)
            st.bar_chart(por_mun)


def renderizar_pagina_perfil_parlamentar(st: Any, dados: dict[str, pd.DataFrame]) -> None:
    """Renderiza a Página 3: Perfil do Parlamentar com histogramas gerais e verificação separada por bancada."""
    st.header("🏛️ Página 3 — Perfil do Parlamentar e Bancadas Regionais")

    st.subheader("📊 Histogramas Orçamentários Gerais")
    st.caption("Visão comparativa do valor total de emendas em Santa Catarina separada por partido, por autor e por ano:")

    tab_partido, tab_parlamentar, tab_ano = st.tabs([
        "🏛️ Valor Total por Partido",
        "👤 Valor Total por Parlamentar / Bancada",
        "📅 Valor Total por Ano",
    ])

    with tab_partido:
        st.markdown("##### Histograma: Valor Total por Partido Político (R$)")
        totais_partido = obter_totais_por_partido(dados["emendas"])
        if not totais_partido.empty:
            st.bar_chart(totais_partido)
            df_partidos = totais_partido.reset_index()
            df_partidos.columns = ["Partido", "Valor Total (R$)"]
            df_partidos["% do Total"] = (
                df_partidos["Valor Total (R$)"] / df_partidos["Valor Total (R$)"].sum() * 100
            ).round(2)
            st.dataframe(df_partidos, use_container_width=True, hide_index=True)

    with tab_parlamentar:
        st.markdown("##### Histograma: Valor Total por Parlamentar e Bancada (R$)")
        c_filtro_graf, c_top = st.columns([2, 1])
        sub_tipo = c_filtro_graf.radio(
            "Separar Histograma por Categoria:",
            ["Parlamentares Individuais", "Bancadas Regionais", "Todos"],
            horizontal=True,
            key="sub_tipo_hist_parl",
        )
        top_escolha = c_top.selectbox("Exibir:", ["Top 10", "Top 20", "Todos"], index=1, key="hist_top_parl")
        top_n_val = 10 if top_escolha == "Top 10" else (20 if top_escolha == "Top 20" else None)

        totais_autores = obter_totais_por_parlamentar(dados["emendas"], tipo_autor=sub_tipo, top_n=top_n_val)
        if not totais_autores.empty:
            st.bar_chart(totais_autores)
            df_autores = totais_autores.reset_index()
            df_autores.columns = ["Autor", "Valor Total (R$)"]
            st.dataframe(df_autores, use_container_width=True, hide_index=True)

    with tab_ano:
        st.markdown("##### Histograma: Valor Total por Ano de Exercício (R$)")
        totais_ano = obter_totais_por_ano(dados["emendas"])
        if not totais_ano.empty:
            st.bar_chart(totais_ano)
            df_anos = totais_ano.reset_index()
            df_anos.columns = ["Ano", "Valor Total (R$)"]
            st.dataframe(df_anos, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("🔍 Verificação Detalhada por Autor (Separada por Categoria)")
    st.caption("Verificação isolada: bancadas regionais (iniciadas com 'BANCADA ') e parlamentares individuais são analisados separadamente.")

    c_tipo_perfil, c_escolha = st.columns([1, 2])
    tipo_analise = c_tipo_perfil.radio(
        "Selecione a Categoria para Análise:",
        ["Parlamentar Individual", "Bancada Regional"],
        horizontal=False,
        key="p3_radio_tipo_autor",
    )

    todos_autores = dados["parlamentares"]["parlamentar"].tolist()
    divisao = separar_autores_por_tipo(todos_autores)
    if tipo_analise == "Bancada Regional":
        lista_opcoes = divisao["bancadas"]
        rotulo_seletor = "Selecione a Bancada Regional (inicia com 'BANCADA ')"
    else:
        lista_opcoes = divisao["parlamentares"]
        rotulo_seletor = "Selecione o Parlamentar Individual"

    if not lista_opcoes:
        lista_opcoes = todos_autores
    escolhido = c_escolha.selectbox(rotulo_seletor, lista_opcoes, key=f"p3_seletor_autor_{tipo_analise}")

    perfil = obter_dados_perfil_parlamentar(escolhido)
    resumo = perfil["resumo"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Destinado", f"R$ {float(resumo.get('total_emendas', 0.0)):,.2f}")
    c2.metric("Nº de Emendas", f"{int(resumo.get('quantidade_emendas', 0))}")
    c3.metric("Área Principal", str(resumo.get("principal_area", "-")))
    c4.metric("Maior Concentração Fornecedor", f"{float(resumo.get('percentual_maior_fornecedor', 0.0)):.1f}%")

    c_graf1, c_graf2 = st.columns(2)
    with c_graf1:
        st.subheader("Distribuição por Área Temática")
        if not perfil["por_area"].empty:
            st.bar_chart(perfil["por_area"].set_index("area")["valor"])
    with c_graf2:
        st.subheader(f"Evolução Anual ({escolhido})")
        ano_autor = obter_totais_por_ano(perfil["emendas"])
        if not ano_autor.empty:
            st.bar_chart(ano_autor)

    st.subheader(f"Padrões / Alertas Associados ({escolhido})")
    if perfil["alertas"]:
        for alerta in perfil["alertas"]:
            st.info(f"**[{alerta['pontuacao']} pts] {alerta['tipo']}**: {alerta['justificativa']}")
    else:
        st.success("Nenhum alerta estatístico associado a este autor.")

    st.subheader(f"Emendas Cadastradas ({escolhido})")
    st.dataframe(perfil["emendas"], use_container_width=True, hide_index=True)


def renderizar_pagina_perfil_municipio(st: Any, dados: dict[str, pd.DataFrame]) -> None:
    """Renderiza a Página 4: Perfil do Município com população, total recebido, per capita e alertas."""
    st.header("🗺️ Página 4 — Perfil do Município Catarinense")
    df_mun = dados["municipios"]
    opcoes = [f"{r['municipio']} ({r['codigo_ibge']})" for _, r in df_mun.iterrows()]
    mapa_cod = {f"{r['municipio']} ({r['codigo_ibge']})": str(r["codigo_ibge"]) for _, r in df_mun.iterrows()}

    escolha = st.selectbox("Selecione o Município de SC", opcoes)
    codigo_ibge = mapa_cod[escolha]
    perfil = obter_dados_perfil_municipio(codigo_ibge)
    resumo = perfil["resumo"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("População (IBGE)", f"{int(resumo.get('populacao', 0)):,} hab.")
    c2.metric("Total Recebido", f"R$ {float(resumo.get('total_recebido', 0.0)):,.2f}")
    c3.metric("Valor Per Capita", f"R$ {float(resumo.get('valor_per_capita', 0.0)):,.2f} / hab.")
    c4.metric("Emendas Recebidas", f"{int(resumo.get('quantidade_emendas', 0))}")

    st.subheader("Alertas Associados ao Município")
    if perfil["alertas"]:
        for alerta in perfil["alertas"]:
            st.warning(f"**[{alerta['pontuacao']} pts] {alerta['tipo']}**: {alerta['justificativa']}")
    else:
        st.success("Nenhum alerta registrado para este município.")

    st.subheader("Emendas Destinadas ao Município")
    st.dataframe(perfil["emendas"], use_container_width=True, hide_index=True)


def executar_interface_streamlit() -> None:
    """Inicializa a aplicação Streamlit com menu lateral de navegação entre as 4 páginas e aviso ético."""
    import streamlit as st

    st.set_page_config(
        page_title="Vigia Público SC — Monitoramento de Emendas",
        page_icon="🔍",
        layout="wide",
    )

    st.title("🔍 Vigia Público SC — Monitoramento de Emendas Parlamentares")
    st.warning(AVISO_ETICO_FRONTEND)

    dados = carregar_dados_painel()

    pagina = st.sidebar.radio(
        "Navegação",
        [
            "1. Painel de Alertas",
            "2. Explorador de Emendas",
            "3. Perfil do Parlamentar",
            "4. Perfil do Município",
        ],
    )
    st.sidebar.markdown("---")
    st.sidebar.caption(
        "Dados públicos: TCE/SC, IBGE, Portal de Dados Abertos SC e Receita Federal. "
        "Foco em transparência ativa, controle social e auditoria cívica."
    )

    if pagina.startswith("1."):
        renderizar_pagina_painel_alertas(st, dados)
    elif pagina.startswith("2."):
        renderizar_pagina_explorador_emendas(st, dados)
    elif pagina.startswith("3."):
        renderizar_pagina_perfil_parlamentar(st, dados)
    else:
        renderizar_pagina_perfil_municipio(st, dados)


if __name__ == "__main__":
    executar_interface_streamlit()
