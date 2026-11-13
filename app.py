"""Fase 5 — Frontend Streamlit do Vigia Público SC com 4 páginas interativas para controle social e auditoria cívica."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd

from cnpj_validator import (
    check_cnpj_anomalies,
    check_cnpj_status,
    obter_link_consulta_oficial,
    sincronizar_cnpjs_emendas_no_cache,
)
from database import conectar_banco, resolver_caminho_sqlite
from fund_tracker import check_fund_usage
from main import garantir_dados_iniciais

AVISO_ETICO_FRONTEND = (
    "⚠️ **Nota Ética e Metodológica:** Esta ferramenta não substitui a verificação documental "
    "nem a apuração oficial. Os alertas indicam padrões estatísticos e cadastrais em dados públicos "
    "que merecem verificação, e não provas de irregularidade."
)


def carregar_dados_painel(db_path: Path | str | None = None) -> dict[str, pd.DataFrame]:
    """Carrega os DataFrames de alertas, emendas, parlamentares e municípios a partir do banco de dados."""
    caminho = garantir_dados_iniciais(db_path)
    sincronizar_cnpjs_emendas_no_cache(caminho)
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


def calcular_valor_por_populacao_filtrada(df_filtrado: pd.DataFrame) -> dict[str, float]:
    """Calcula a soma de valores, a população única dos municípios contemplados e a razão valor total / população."""
    if df_filtrado.empty:
        return {"total_valor": 0.0, "populacao_total": 0, "valor_por_habitante": 0.0}
    total_valor = float(df_filtrado["valor"].sum())
    pop_total = int(df_filtrado.drop_duplicates(subset=["codigo_ibge"])["populacao"].sum())
    razao = round(total_valor / pop_total, 2) if pop_total > 0 else 0.0
    return {
        "total_valor": round(total_valor, 2),
        "populacao_total": pop_total,
        "valor_por_habitante": razao,
    }


def obter_valor_por_populacao_municipios(
    df_filtrado: pd.DataFrame,
    df_todos_municipios: pd.DataFrame | None = None,
    top_n: int | None = None,
    *,
    incluir_todos_sc: bool = False,
) -> pd.Series:
    """Calcula a razão (Valor Total / População) para os municípios, garantindo a presença de todos os municípios de SC."""
    if df_filtrado.empty:
        if incluir_todos_sc and df_todos_municipios is not None and not df_todos_municipios.empty:
            serie = pd.Series(0.0, index=df_todos_municipios["municipio"].dropna().unique()).sort_index()
            return serie.head(top_n) if top_n and top_n > 0 else serie
        return pd.Series(dtype=float)

    if "municipio" not in df_filtrado.columns or "populacao" not in df_filtrado.columns:
        return pd.Series(dtype=float)

    agg = df_filtrado.groupby("municipio").agg({"valor": "sum", "populacao": "first"})
    agg = agg[agg["populacao"] > 0]
    razoes = (agg["valor"] / agg["populacao"]).round(2)
    if incluir_todos_sc and df_todos_municipios is not None and not df_todos_municipios.empty:
        todos_muns = df_todos_municipios["municipio"].dropna().unique()
        razoes = razoes.reindex(todos_muns, fill_value=0.0)

    serie = razoes.sort_values(ascending=False)
    if top_n and top_n > 0:
        return serie.head(top_n)
    return serie


def obter_totais_por_municipio(
    df_filtrado: pd.DataFrame,
    df_todos_municipios: pd.DataFrame | None = None,
    *,
    incluir_todos_sc: bool = False,
    top_n: int | None = None,
) -> pd.Series:
    """Calcula o valor financeiro total de emendas por município, garantindo a exibição de todos os municípios."""
    if df_filtrado.empty:
        if incluir_todos_sc and df_todos_municipios is not None and not df_todos_municipios.empty:
            serie = pd.Series(0.0, index=df_todos_municipios["municipio"].dropna().unique()).sort_index()
            return serie.head(top_n) if top_n and top_n > 0 else serie
        return pd.Series(dtype=float)

    if "municipio" not in df_filtrado.columns or "valor" not in df_filtrado.columns:
        return pd.Series(dtype=float)

    totais = df_filtrado.groupby("municipio")["valor"].sum()
    if incluir_todos_sc and df_todos_municipios is not None and not df_todos_municipios.empty:
        todos_muns = df_todos_municipios["municipio"].dropna().unique()
        totais = totais.reindex(todos_muns, fill_value=0.0)

    serie = totais.sort_values(ascending=False)
    if top_n and top_n > 0:
        return serie.head(top_n)
    return serie


def obter_quantidade_emendas_por_autor(
    df_filtrado: pd.DataFrame,
    *,
    tipo_autor: str = "Todos",
    top_n: int | None = None,
) -> pd.Series:
    """Calcula o número total de emendas alocadas agrupado por autor (parlamentar individual ou bancada)."""
    if df_filtrado.empty or "parlamentar" not in df_filtrado.columns:
        return pd.Series(dtype=int)
    df = df_filtrado.copy()
    if tipo_autor in ("Bancadas", "Bancada Regional", "Bancadas Regionais", "Bancada"):
        df = df[df["parlamentar"].apply(eh_bancada_regional)]
    elif tipo_autor in ("Parlamentares", "Parlamentar Individual", "Parlamentares Individuais", "Parlamentar"):
        df = df[~df["parlamentar"].apply(eh_bancada_regional)]

    col_contagem = "id_emenda" if "id_emenda" in df.columns else "valor"
    serie = df.groupby("parlamentar")[col_contagem].count().sort_values(ascending=False)
    if top_n and top_n > 0:
        return serie.head(top_n)
    return serie


def formatar_cpf_cnpj(documento: str) -> str:
    """Formata uma string de CPF (11 dígitos) ou CNPJ (14 dígitos) com pontuação padrão oficial."""
    digitos = re.sub(r"\D", "", str(documento or "")).strip()
    if len(digitos) == 11:
        return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
    if len(digitos) == 14:
        return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"
    return documento or "Não informado"


def obter_totais_por_cpf_cnpj(
    df_emendas: pd.DataFrame,
    top_n: int | None = None,
) -> pd.DataFrame:
    """Consolida as emendas agrupadas por CPF/CNPJ do favorecido calculando valor total e contagem no período."""
    if df_emendas.empty or "fornecedor_cnpj" not in df_emendas.columns:
        return pd.DataFrame(
            columns=[
                "identificacao_cpf_cnpj",
                "fornecedor_cnpj",
                "doc_formatado",
                "valor_total",
                "quantidade_emendas",
                "fornecedor_nome",
            ]
        )

    df = df_emendas.copy()
    col_nome = "fornecedor_nome" if "fornecedor_nome" in df.columns else "entidade_beneficiaria"
    nomes = df[col_nome].fillna("Não informado") if col_nome in df.columns else ["Não informado"] * len(df)
    df["doc_formatado"] = df["fornecedor_cnpj"].apply(formatar_cpf_cnpj)
    df["identificacao_cpf_cnpj"] = [
        f"{doc} - {nome}" if nome and str(nome).strip() and str(nome).strip() != "Não informado" else str(doc)
        for doc, nome in zip(df["doc_formatado"], nomes)
    ]

    col_id = "id_emenda" if "id_emenda" in df.columns else "valor"
    agg = (
        df.groupby(["identificacao_cpf_cnpj", "fornecedor_cnpj", "doc_formatado"], as_index=False)
        .agg(
            valor_total=("valor", "sum"),
            quantidade_emendas=(col_id, "count"),
            fornecedor_nome=(col_nome, "first") if col_nome in df.columns else ("doc_formatado", "first"),
        )
        .sort_values("valor_total", ascending=False)
        .reset_index(drop=True)
    )
    if top_n and top_n > 0:
        return agg.head(top_n)
    return agg


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
    por_municipio = (
        df_emendas.groupby("municipio", as_index=False)["valor"]
        .sum()
        .sort_values("valor", ascending=False)
        if not df_emendas.empty
        else pd.DataFrame(columns=["municipio", "valor"])
    )
    por_cpf_cnpj = obter_totais_por_cpf_cnpj(df_emendas)
    return {
        "resumo": dict(resumo_row) if resumo_row else {"parlamentar": parlamentar, "total_emendas": 0.0},
        "emendas": df_emendas,
        "por_area": por_area,
        "por_municipio": por_municipio,
        "por_cpf_cnpj": por_cpf_cnpj,
        "alertas": df_alertas.to_dict(orient="records"),
    }


def carregar_mapa_macrorregioes_sc(caminho_json: Path | str | None = None) -> dict[str, str]:
    """Carrega o mapeamento oficial de código IBGE (7 dígitos) para Macrorregião (Mesorregião IBGE) de SC.
    
    Lê o arquivo data/raw/macrorregioes_ibge_sc.json obtido da API de localidades do IBGE.
    """
    if caminho_json is None:
        caminho_json = Path("data/raw/macrorregioes_ibge_sc.json")
    else:
        caminho_json = Path(caminho_json)

    if caminho_json.exists():
        with open(caminho_json, encoding="utf-8") as f:
            return json.load(f)
    return {}


def obter_totais_por_macrorregiao(
    df_emendas: pd.DataFrame,
    mapa_macro: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Calcula o valor total em reais e a quantidade total de emendas por Macrorregião do IBGE em SC.
    
    Mapeia o código IBGE para a mesorregião do IBGE (Grande Florianópolis, Norte Catarinense,
    Oeste Catarinense, Serrana, Sul Catarinense, Vale do Itajaí) e agrega os valores.
    """
    if df_emendas.empty:
        return pd.DataFrame(columns=["macrorregiao", "valor_total", "quantidade_emendas"])

    if mapa_macro is None:
        mapa_macro = carregar_mapa_macrorregioes_sc()

    df = df_emendas.copy()
    df["codigo_ibge_str"] = df["codigo_ibge"].astype(str).str.strip()
    df["macrorregiao"] = df["codigo_ibge_str"].map(mapa_macro).fillna("Não classificada")

    agregado = (
        df.groupby("macrorregiao", as_index=False)
        .agg(
            valor_total=("valor", "sum"),
            quantidade_emendas=("id_emenda", "count"),
        )
        .sort_values(by="valor_total", ascending=False)
        .reset_index(drop=True)
    )
    return agregado


def obter_totais_gerais_municipios(
    df_emendas: pd.DataFrame,
    df_municipios: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Consolida valor total e quantidade de emendas por município em SC para visualização comparativa."""
    if df_emendas.empty and (df_municipios is None or df_municipios.empty):
        return pd.DataFrame(columns=["municipio", "codigo_ibge", "valor_total", "quantidade_emendas"])

    agregado_emendas = (
        df_emendas.groupby(["codigo_ibge", "municipio"], as_index=False)
        .agg(
            valor_total=("valor", "sum"),
            quantidade_emendas=("id_emenda", "count"),
        )
    )

    if df_municipios is not None and not df_municipios.empty:
        df_base = df_municipios[["codigo_ibge", "municipio"]].copy()
        df_base["codigo_ibge"] = df_base["codigo_ibge"].astype(str).str.strip()
        agregado_emendas["codigo_ibge"] = agregado_emendas["codigo_ibge"].astype(str).str.strip()
        resultado = df_base.merge(
            agregado_emendas[["codigo_ibge", "valor_total", "quantidade_emendas"]],
            on="codigo_ibge",
            how="left",
            suffixes=("", "_emendas"),
        )
        resultado["valor_total"] = resultado["valor_total"].fillna(0.0)
        resultado["quantidade_emendas"] = resultado["quantidade_emendas"].fillna(0).astype(int)
    else:
        resultado = agregado_emendas

    return resultado.sort_values(by="valor_total", ascending=False).reset_index(drop=True)


def obter_metricas_detalhadas_municipio(df_emendas_mun: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Calcula as métricas detalhadas de um município específico para visualização gráfica antes dos alertas.
    
    Retorna os seguintes conjuntos de dados:
    - 1.1 por_area_valor: Total em reais de valor das emendas por área beneficiada.
    - 1.2 por_area_qtd: Número de emendas por área.
    - 2.1 por_deputado_valor: Soma total de valor por deputado em reais.
    - 2.2 ranking_emendas: Relação das emendas individuais com identificador e valores.
    - 3.1 por_partido_valor: Valor total por partido em reais.
    - 3.2 por_partido_qtd: Número total de emendas por partido.
    - 4 por_cnpj_total_top50: Valor total por CNPJ/favorecido (50 maiores valores).
    - 5 por_cnpj_maior_emenda_top50: Valor da maior emenda por CNPJ/favorecido (50 maiores valores).
    """
    if df_emendas_mun.empty:
        return {
            "por_area_valor": pd.DataFrame(columns=["area", "valor_total"]),
            "por_area_qtd": pd.DataFrame(columns=["area", "quantidade"]),
            "por_deputado_valor": pd.DataFrame(columns=["parlamentar", "valor_total"]),
            "ranking_emendas": pd.DataFrame(columns=["id_rotulo", "id_emenda", "parlamentar", "area", "valor"]),
            "por_partido_valor": pd.DataFrame(columns=["partido", "valor_total"]),
            "por_partido_qtd": pd.DataFrame(columns=["partido", "quantidade"]),
            "por_cnpj_total_top50": pd.DataFrame(
                columns=["identificador_cnpj", "cnpj_formatado", "fornecedor_nome", "valor_total", "quantidade_emendas"]
            ),
            "por_cnpj_maior_emenda_top50": pd.DataFrame(
                columns=["identificador_cnpj", "cnpj_formatado", "fornecedor_nome", "maior_valor", "quantidade_emendas"]
            ),
        }

    df = df_emendas_mun.copy()

    # 1.1 e 1.2: Área
    col_area = "area" if "area" in df.columns else ("funcao" if "funcao" in df.columns else None)
    if col_area:
        df["area_ajustada"] = df[col_area].fillna("Não informada")
        por_area_valor = (
            df.groupby("area_ajustada", as_index=False)["valor"]
            .sum()
            .rename(columns={"area_ajustada": "area", "valor": "valor_total"})
            .sort_values(by="valor_total", ascending=False)
            .reset_index(drop=True)
        )
        por_area_qtd = (
            df.groupby("area_ajustada", as_index=False)["id_emenda"]
            .count()
            .rename(columns={"area_ajustada": "area", "id_emenda": "quantidade"})
            .sort_values(by="quantidade", ascending=False)
            .reset_index(drop=True)
        )
    else:
        por_area_valor = pd.DataFrame(columns=["area", "valor_total"])
        por_area_qtd = pd.DataFrame(columns=["area", "quantidade"])

    # 2.1: Soma total de valor por deputado em reais
    por_deputado_valor = (
        df.groupby("parlamentar", as_index=False)["valor"]
        .sum()
        .rename(columns={"valor": "valor_total"})
        .sort_values(by="valor_total", ascending=False)
        .reset_index(drop=True)
    )

    # 2.2: Soma/valor por emenda (individual)
    df_ranking_emendas = df.copy().sort_values(by="valor", ascending=False).reset_index(drop=True)
    df_ranking_emendas["id_rotulo"] = df_ranking_emendas.apply(
        lambda r: f"{r.get('id_emenda', 'Emenda')} ({r.get('parlamentar', 'Autor')} - R$ {float(r.get('valor', 0.0)):,.2f})",
        axis=1,
    )
    cols_ranking = [c for c in ["id_rotulo", "id_emenda", "parlamentar", "area", "valor"] if c in df_ranking_emendas.columns]
    ranking_emendas = df_ranking_emendas[cols_ranking]

    # 3.1 e 3.2: Partido
    df["partido_ajustado"] = df["partido"].fillna("Não informado")
    por_partido_valor = (
        df.groupby("partido_ajustado", as_index=False)["valor"]
        .sum()
        .rename(columns={"partido_ajustado": "partido", "valor": "valor_total"})
        .sort_values(by="valor_total", ascending=False)
        .reset_index(drop=True)
    )
    por_partido_qtd = (
        df.groupby("partido_ajustado", as_index=False)["id_emenda"]
        .count()
        .rename(columns={"partido_ajustado": "partido", "id_emenda": "quantidade"})
        .sort_values(by="quantidade", ascending=False)
        .reset_index(drop=True)
    )

    # 4 e 5: CNPJs (50 maiores valores totais e 50 maiores emendas individuais)
    df_cnpj = df[df["fornecedor_cnpj"].notna() & (df["fornecedor_cnpj"].astype(str).str.strip() != "")].copy()
    if not df_cnpj.empty:
        df_cnpj["cnpj_formatado"] = df_cnpj["fornecedor_cnpj"].apply(formatar_cpf_cnpj)
        df_cnpj["fornecedor_nome"] = df_cnpj["fornecedor_nome"].fillna("Não informado")
        df_cnpj["identificador_cnpj"] = df_cnpj.apply(
            lambda r: f"{str(r['fornecedor_nome'])[:25]} ({r['cnpj_formatado']})",
            axis=1,
        )

        por_cnpj_total_top50 = (
            df_cnpj.groupby(["identificador_cnpj", "cnpj_formatado", "fornecedor_nome"], as_index=False)
            .agg(
                valor_total=("valor", "sum"),
                quantidade_emendas=("id_emenda", "count"),
            )
            .sort_values(by="valor_total", ascending=False)
            .head(50)
            .reset_index(drop=True)
        )

        por_cnpj_maior_emenda_top50 = (
            df_cnpj.groupby(["identificador_cnpj", "cnpj_formatado", "fornecedor_nome"], as_index=False)
            .agg(
                maior_valor=("valor", "max"),
                quantidade_emendas=("id_emenda", "count"),
            )
            .sort_values(by="maior_valor", ascending=False)
            .head(50)
            .reset_index(drop=True)
        )
    else:
        por_cnpj_total_top50 = pd.DataFrame(
            columns=["identificador_cnpj", "cnpj_formatado", "fornecedor_nome", "valor_total", "quantidade_emendas"]
        )
        por_cnpj_maior_emenda_top50 = pd.DataFrame(
            columns=["identificador_cnpj", "cnpj_formatado", "fornecedor_nome", "maior_valor", "quantidade_emendas"]
        )

    return {
        "por_area_valor": por_area_valor,
        "por_area_qtd": por_area_qtd,
        "por_deputado_valor": por_deputado_valor,
        "ranking_emendas": ranking_emendas,
        "por_partido_valor": por_partido_valor,
        "por_partido_qtd": por_partido_qtd,
        "por_cnpj_total_top50": por_cnpj_total_top50,
        "por_cnpj_maior_emenda_top50": por_cnpj_maior_emenda_top50,
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
            return {"resumo": {}, "emendas": pd.DataFrame(), "detalhes": {}, "alertas": []}
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

    detalhes = obter_metricas_detalhadas_municipio(df_emendas)
    return {
        "resumo": resumo,
        "emendas": df_emendas,
        "detalhes": detalhes,
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
    """Renderiza a Página 1: Central de Alertas dedicada exclusivamente à triagem e auditoria dos novos alertas."""
    st.header("🚨 Central de Alertas — Triagem e Auditoria Cívica")
    st.caption(
        "Aba dedicada exclusivamente à análise detalhada dos novos alertas estatísticos oficiais: "
        "(1) Triplo Desvio simultâneo (Valor, Per Capita Municipal e Área Temática) e "
        "(2) Valor na Área Temática acima da média setorial + 1 STD."
    )
    df_alertas = dados["alertas"]

    # Indicadores globais da Central de Alertas
    if not df_alertas.empty:
        qtd_triplo = (df_alertas["tipo"] == "Triplo Desvio: Valor, Per Capita e Área").sum()
        qtd_area = (df_alertas["tipo"] == "Valor na Área Acima da Média + 1 STD").sum()
        val_total_alertas = float(df_alertas["valor"].sum())
        total_geral = len(df_alertas)
    else:
        qtd_triplo = 0
        qtd_area = 0
        val_total_alertas = 0.0
        total_geral = 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total de Alertas", f"{total_geral}")
    m2.metric("Triplo Desvio (Regra 1)", f"{qtd_triplo}")
    m3.metric("Destaque na Área (Regra 2)", f"{qtd_area}")
    m4.metric("Valor Total Sob Alerta", f"R$ {val_total_alertas:,.2f}")

    st.markdown("---")

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

    st.caption(f"Exibindo **{len(df_view)}** alertas detectados com base nos filtros selecionados.")
    st.dataframe(
        df_view[["id", "pontuacao", "tipo", "parlamentar", "municipio", "valor", "beneficiario"]],
        use_container_width=True,
        hide_index=True,
    )

    # Gráficos de síntese na Central de Alertas
    if not df_view.empty:
        st.markdown("##### 📊 Distribuição dos Alertas Filtrados")
        c_gr1, c_gr2 = st.columns(2)
        with c_gr1:
            st.caption("Quantidade de Alertas por Tipo")
            st.bar_chart(df_view["tipo"].value_counts())
        with c_gr2:
            st.caption("Municípios com Mais Alertas Filtrados (Top 15)")
            st.bar_chart(df_view["municipio"].value_counts().head(15))

    st.subheader("🔍 Ver Detalhes e Calibrar Regras")
    for _, alerta in df_view.iterrows():
        titulo_card = (
            f"[{alerta['pontuacao']:.1f} pts] {alerta['tipo']} — {alerta['parlamentar']} "
            f"| {alerta['municipio']} (R$ {float(alerta['valor']):,.2f})"
        )
        with st.expander(titulo_card):
            st.markdown(f"**Justificativa Técnica:** {alerta['justificativa']}")
            st.markdown(f"**Beneficiário / Fornecedor:** `{alerta['beneficiario']}` (CNPJ `{alerta['fornecedor_cnpj']}`)")

            # Validação cadastral do CNPJ com as tags recomendadas (Situação, Recém-criada, EI 2135, etc.)
            cnpj_forn = str(alerta.get("fornecedor_cnpj") or "")
            val_emenda = float(alerta.get("valor") or 0.0)
            validacao_cnpj = check_cnpj_anomalies(cnpj_forn, val_emenda)
            tags_formatadas = " ".join([f"`{t}`" for t in validacao_cnpj["tags"]])
            st.markdown(f"**Validação Cadastral CNPJ:** {tags_formatadas}")
            st.markdown(
                f"🔗 [Consultar CNPJ no Gov.br / Portal da Transparência]({validacao_cnpj['link_consulta_oficial']}) "
                f"*(verificação manual pública e gratuita sem login)*"
            )
            if validacao_cnpj["anomalias_detectadas"]:
                for anom in validacao_cnpj["anomalias_detectadas"]:
                    st.warning(f"⚠️ **Anomalia Cadastral ({anom['categoria'].replace('_', ' ').title()})**: {anom['descricao']}")

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

    resumo_calc = calcular_valor_por_populacao_filtrada(df_filtrado)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Filtrado", f"R$ {resumo_calc['total_valor']:,.2f}")
    m2.metric("Quantidade de Emendas", f"{len(df_filtrado)}")
    m3.metric("Municípios Contemplados", f"{df_filtrado['codigo_ibge'].nunique()}")
    m4.metric(
        "Valor Total / População",
        f"R$ {resumo_calc['valor_por_habitante']:,.2f} / hab",
        help=f"População total dos municípios do recorte: {resumo_calc['populacao_total']:,} habitantes (IBGE).",
    )

    st.dataframe(
        df_filtrado[
            [
                "id_emenda",
                "parlamentar",
                "partido",
                "municipio",
                "populacao",
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

    st.markdown("---")
    st.subheader("📊 Gráficos Analíticos do Recorte Filtrado")

    # Linha 1: Separação de Total por Parlamentar Individual vs Bancadas Regionais
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("##### 👤 Total por Parlamentar Individual (R$)")
        df_parl = df_filtrado[~df_filtrado["parlamentar"].apply(eh_bancada_regional)]
        if not df_parl.empty:
            por_parl = df_parl.groupby("parlamentar")["valor"].sum().sort_values(ascending=False)
            st.bar_chart(por_parl)
        else:
            st.caption("Nenhum parlamentar individual no recorte filtrado.")

    with g2:
        st.markdown("##### 🏛️ Total por Bancada Regional (R$)")
        df_banc = df_filtrado[df_filtrado["parlamentar"].apply(eh_bancada_regional)]
        if not df_banc.empty:
            por_banc = df_banc.groupby("parlamentar")["valor"].sum().sort_values(ascending=False)
            st.bar_chart(por_banc)
        else:
            st.caption("Nenhuma bancada regional no recorte filtrado.")

    # Linha 2: Valor Total / População por Município e Número Total de Emendas por Autor
    g3, g4 = st.columns(2)
    apenas_um_mun = df_filtrado["municipio"].nunique() == 1 if not df_filtrado.empty else False
    with g3:
        st.markdown("##### 📈 Valor Total / População por Município (R$ / hab)")
        serie_per_capita = obter_valor_por_populacao_municipios(
            df_filtrado,
            dados.get("municipios"),
            top_n=None,
            incluir_todos_sc=not apenas_um_mun,
        )
        if not serie_per_capita.empty:
            st.bar_chart(serie_per_capita)
        else:
            st.caption("Sem dados populacionais no recorte selecionado.")

    with g4:
        st.markdown("##### 📋 Número Total de Emendas por Autor")
        serie_qtd = obter_quantidade_emendas_por_autor(df_filtrado, top_n=None)
        if not serie_qtd.empty:
            st.bar_chart(serie_qtd)
        else:
            st.caption("Sem emendas no recorte selecionado.")

    # Linha 3: Total Financeiro por Município (garante a exibição de todos os municípios)
    st.markdown("##### 🏙️ Total Financeiro por Município (R$)")
    totais_mun = obter_totais_por_municipio(
        df_filtrado,
        dados.get("municipios"),
        incluir_todos_sc=not apenas_um_mun,
        top_n=None,
    )
    if not totais_mun.empty:
        st.bar_chart(totais_mun)
    else:
        st.caption("Nenhum município encontrado para o recorte.")


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

    st.markdown("##### 🏙️ Distribuição de Recursos por Município Destino (R$)")
    if not perfil["por_municipio"].empty:
        st.bar_chart(perfil["por_municipio"].set_index("municipio")["valor"])
    else:
        st.caption("Nenhum município cadastrado para este autor.")

    st.markdown("##### 💳 Destinações por CPF / CNPJ do Beneficiário no Período")
    c_cpf1, c_cpf2 = st.columns(2)
    with c_cpf1:
        st.markdown("###### 💰 Valor Total por CPF / CNPJ (R$)")
        if not perfil["por_cpf_cnpj"].empty:
            serie_val_cpf = perfil["por_cpf_cnpj"].set_index("identificacao_cpf_cnpj")["valor_total"]
            st.bar_chart(serie_val_cpf)
        else:
            st.caption("Nenhum favorecido cadastrado para este autor.")

    with c_cpf2:
        st.markdown("###### 📋 Número Total de Emendas por CPF / CNPJ")
        if not perfil["por_cpf_cnpj"].empty:
            serie_qtd_cpf = perfil["por_cpf_cnpj"].set_index("identificacao_cpf_cnpj")["quantidade_emendas"]
            st.bar_chart(serie_qtd_cpf)
        else:
            st.caption("Nenhum favorecido cadastrado para este autor.")

    with st.expander("Ver detalhamento dos favorecidos (CPF / CNPJ) deste autor"):
        if not perfil["por_cpf_cnpj"].empty:
            df_tab_cpf = perfil["por_cpf_cnpj"][
                ["doc_formatado", "fornecedor_nome", "fornecedor_cnpj", "quantidade_emendas", "valor_total"]
            ].copy()
            total_autor_val = float(resumo.get("total_emendas", 0.0))
            if total_autor_val > 0:
                df_tab_cpf["% do Total"] = (
                    df_tab_cpf["valor_total"] / total_autor_val * 100
                ).round(2)
            df_tab_cpf["Situação Cadastral"] = [
                check_cnpj_status(cnpj)["situacao_cadastral"] for cnpj in df_tab_cpf["fornecedor_cnpj"]
            ]
            df_tab_cpf["Link Gov.br"] = [
                obter_link_consulta_oficial(cnpj) for cnpj in df_tab_cpf["fornecedor_cnpj"]
            ]
            df_tab_cpf = df_tab_cpf.drop(columns=["fornecedor_cnpj"])
            cols_ordem = ["doc_formatado", "fornecedor_nome", "Situação Cadastral", "quantidade_emendas", "valor_total"]
            if "% do Total" in df_tab_cpf.columns:
                cols_ordem.append("% do Total")
            cols_ordem.append("Link Gov.br")
            df_tab_cpf = df_tab_cpf[cols_ordem]
            df_tab_cpf.columns = [
                "CPF / CNPJ", "Favorecido", "Situação Cadastral", "Nº de Emendas",
                "Valor Total (R$)", *(["% do Total"] if "% do Total" in cols_ordem else []), "Consulta Gov.br"
            ]
            st.dataframe(df_tab_cpf, use_container_width=True, hide_index=True)

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

    st.caption("ℹ️ Os alertas e apontamentos estatísticos estão concentrados exclusivamente na aba **1. Central de Alertas**.")
    st.subheader(f"Emendas Cadastradas ({escolhido})")
    st.dataframe(perfil["emendas"], use_container_width=True, hide_index=True)


def renderizar_pagina_perfil_municipio(st: Any, dados: dict[str, pd.DataFrame]) -> None:
    """Renderiza a Página 4: Perfil do Município com macrorregiões do IBGE, gráficos detalhados e alertas."""
    st.header("🗺️ Página 4 — Perfil do Município Catarinense")
    df_mun = dados["municipios"]
    df_emendas_todas = dados.get("emendas", pd.DataFrame())

    # --- Panorama Geral de Santa Catarina: Macrorregião (IBGE) vs. Município ---
    st.subheader("📊 Panorama Geral: Macrorregião (IBGE) ou Município")
    st.caption(
        "Compare a alocação de recursos em Santa Catarina visualizando por Macrorregião oficial do IBGE "
        "ou individualmente por Município."
    )
    col_sel_pan, _ = st.columns([2, 2])
    with col_sel_pan:
        modo_panorama = st.radio(
            "Visualizar panorama por:",
            ["Macrorregião (IBGE)", "Município"],
            horizontal=True,
            key="modo_panorama_sc",
        )

    col_pan1, col_pan2 = st.columns(2)
    if modo_panorama == "Macrorregião (IBGE)":
        totais_macro = obter_totais_por_macrorregiao(df_emendas_todas)
        with col_pan1:
            st.markdown("##### 💰 Valor Total das Emendas por Macrorregião (IBGE)")
            if not totais_macro.empty:
                st.bar_chart(totais_macro.set_index("macrorregiao")["valor_total"])
            else:
                st.caption("Sem dados de emendas.")
        with col_pan2:
            st.markdown("##### 🔢 Número Total de Emendas por Macrorregião (IBGE)")
            if not totais_macro.empty:
                st.bar_chart(totais_macro.set_index("macrorregiao")["quantidade_emendas"])
            else:
                st.caption("Sem dados de emendas.")
    else:
        totais_mun_todos = obter_totais_gerais_municipios(df_emendas_todas, df_mun)
        with col_pan1:
            st.markdown("##### 💰 Valor Total das Emendas por Município (Maiores Destinações)")
            if not totais_mun_todos.empty:
                st.bar_chart(totais_mun_todos.head(30).set_index("municipio")["valor_total"])
            else:
                st.caption("Sem dados de municípios.")
        with col_pan2:
            st.markdown("##### 🔢 Número Total de Emendas por Município (Maiores Quantidades)")
            if not totais_mun_todos.empty:
                totais_mun_qtd = totais_mun_todos.sort_values(by="quantidade_emendas", ascending=False)
                st.bar_chart(totais_mun_qtd.head(30).set_index("municipio")["quantidade_emendas"])
            else:
                st.caption("Sem dados de municípios.")

    st.markdown("---")

    # --- Seletor e Indicadores do Município Específico ---
    st.subheader("🎯 Seleção e Indicadores do Município")
    opcoes = [f"{r['municipio']} ({r['codigo_ibge']})" for _, r in df_mun.iterrows()]
    mapa_cod = {f"{r['municipio']} ({r['codigo_ibge']})": str(r["codigo_ibge"]) for _, r in df_mun.iterrows()}

    escolha = st.selectbox("Selecione o Município de SC", opcoes)
    codigo_ibge = mapa_cod[escolha]
    perfil = obter_dados_perfil_municipio(codigo_ibge)
    resumo = perfil["resumo"]
    detalhes = perfil.get("detalhes", {})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("População (IBGE)", f"{int(resumo.get('populacao', 0)):,} hab.")
    c2.metric("Total Recebido", f"R$ {float(resumo.get('total_recebido', 0.0)):,.2f}")
    c3.metric("Valor Per Capita", f"R$ {float(resumo.get('valor_per_capita', 0.0)):,.2f} / hab.")
    c4.metric("Emendas Recebidas", f"{int(resumo.get('quantidade_emendas', 0))}")

    # --- Gráficos Detalhados ANTES dos alertas ---
    st.subheader(f"📈 Gráficos Detalhados: {resumo.get('municipio', escolha)}")

    # 1.1 e 1.2: Áreas que o município recebeu emenda
    st.markdown("#### 1. Áreas Temáticas Beneficiadas")
    c_area1, c_area2 = st.columns(2)
    with c_area1:
        st.markdown("###### 1.1 Total em Reais (R$) por Área Beneficiada")
        df_av = detalhes.get("por_area_valor", pd.DataFrame())
        if not df_av.empty:
            st.bar_chart(df_av.set_index("area")["valor_total"])
        else:
            st.caption("Sem emendas registradas para este município.")
    with c_area2:
        st.markdown("###### 1.2 Número de Emendas por Área Beneficiada")
        df_aq = detalhes.get("por_area_qtd", pd.DataFrame())
        if not df_aq.empty:
            st.bar_chart(df_aq.set_index("area")["quantidade"])
        else:
            st.caption("Sem emendas registradas para este município.")

    # 2.1 e 2.2: Deputados e Emendas Individuais
    st.markdown("#### 2. Parlamentares e Emendas Individuais")
    c_dep1, c_dep2 = st.columns(2)
    with c_dep1:
        st.markdown("###### 2.1 Soma Total de Valor por Deputado (R$)")
        df_dep = detalhes.get("por_deputado_valor", pd.DataFrame())
        if not df_dep.empty:
            st.bar_chart(df_dep.set_index("parlamentar")["valor_total"])
        else:
            st.caption("Sem emendas registradas para este município.")
    with c_dep2:
        st.markdown("###### 2.2 Soma Total do Valor por Emenda Individual (R$)")
        df_rank = detalhes.get("ranking_emendas", pd.DataFrame())
        if not df_rank.empty:
            st.bar_chart(df_rank.head(40).set_index("id_rotulo")["valor"])
        else:
            st.caption("Sem emendas registradas para este município.")

    # 3.1 e 3.2: Partidos Políticos
    st.markdown("#### 3. Distribuição por Partido Político")
    c_part1, c_part2 = st.columns(2)
    with c_part1:
        st.markdown("###### 3.1 Valor Total por Partido (R$)")
        df_pv = detalhes.get("por_partido_valor", pd.DataFrame())
        if not df_pv.empty:
            st.bar_chart(df_pv.set_index("partido")["valor_total"])
        else:
            st.caption("Sem emendas registradas para este município.")
    with c_part2:
        st.markdown("###### 3.2 Número de Emendas por Partido")
        df_pq = detalhes.get("por_partido_qtd", pd.DataFrame())
        if not df_pq.empty:
            st.bar_chart(df_pq.set_index("partido")["quantidade"])
        else:
            st.caption("Sem emendas registradas para este município.")

    # 4 e 5: Favorecidos por CNPJ (50 maiores valores totais e 50 maiores individuais)
    st.markdown("#### 4 e 5. Favorecidos e Credores por CNPJ (Top 50)")
    c_cnpj1, c_cnpj2 = st.columns(2)
    with c_cnpj1:
        st.markdown("###### 4. Valor Total por CNPJ (50 Maiores Valores)")
        df_ctop = detalhes.get("por_cnpj_total_top50", pd.DataFrame())
        if not df_ctop.empty:
            st.bar_chart(df_ctop.set_index("identificador_cnpj")["valor_total"])
        else:
            st.caption("Nenhum favorecido/CNPJ registrado para este município.")
    with c_cnpj2:
        st.markdown("###### 5. Valor da Maior Emenda por CNPJ (50 Maiores Valores)")
        df_cmax = detalhes.get("por_cnpj_maior_emenda_top50", pd.DataFrame())
        if not df_cmax.empty:
            st.bar_chart(df_cmax.set_index("identificador_cnpj")["maior_valor"])
        else:
            st.caption("Nenhum favorecido/CNPJ registrado para este município.")

    with st.expander("Ver tabela detalhada dos favorecidos (CNPJ) deste município"):
        if not df_ctop.empty:
            df_tab_mun_cnpj = df_ctop[["cnpj_formatado", "fornecedor_nome", "quantidade_emendas", "valor_total"]].copy()
            df_tab_mun_cnpj["Situação Cadastral"] = [
                check_cnpj_status(cnpj)["situacao_cadastral"] for cnpj in df_tab_mun_cnpj["cnpj_formatado"]
            ]
            df_tab_mun_cnpj["Consulta Gov.br"] = [
                obter_link_consulta_oficial(cnpj) for cnpj in df_tab_mun_cnpj["cnpj_formatado"]
            ]
            df_tab_mun_cnpj = df_tab_mun_cnpj[
                ["cnpj_formatado", "fornecedor_nome", "Situação Cadastral", "quantidade_emendas", "valor_total", "Consulta Gov.br"]
            ]
            df_tab_mun_cnpj.columns = ["CNPJ", "Favorecido", "Situação Cadastral", "Nº de Emendas", "Valor Total (R$)", "Consulta Gov.br"]
            st.dataframe(df_tab_mun_cnpj, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.caption("ℹ️ Os alertas e desvios estatísticos municipais estão concentrados exclusivamente na aba **1. Central de Alertas**.")
    st.subheader("📋 Emendas Destinadas ao Município")
    st.dataframe(perfil["emendas"], use_container_width=True, hide_index=True)


def renderizar_pagina_fluxo_recursos(st: Any, dados: dict[str, pd.DataFrame]) -> None:
    """Renderiza a Página 5: Rastreabilidade e Fluxo de Recursos com dados cruzados do TCE/SC e e-Sfinge."""
    st.header("🔄 Página 5 — Rastreabilidade & Fluxo de Recursos (TCE/SC & e-Sfinge)")
    st.caption(
        "Auditoria de ponta a ponta: verificação de planos de trabalho exigidos por medida cautelar do TCE/SC, "
        "estágios de repasse financeiro, declarações no sistema e-Sfinge, conformidade de fornecedores (CNPJ) "
        "e canais de transparência ativa municipal."
    )

    df_mun = dados["municipios"]
    opcoes_mun = [f"{r['municipio']} ({r['codigo_ibge']})" for _, r in df_mun.iterrows()]
    mapa_cod = {f"{r['municipio']} ({r['codigo_ibge']})": str(r["codigo_ibge"]) for _, r in df_mun.iterrows()}

    c_sel, _ = st.columns([2, 2])
    with c_sel:
        escolha = st.selectbox("Selecione o Município de SC para Auditoria do Fluxo", opcoes_mun, key="sel_mun_fluxo")

    codigo_ibge = mapa_cod[escolha]
    relatorio_fluxo = check_fund_usage(codigo_ibge)
    contagem_sinais = relatorio_fluxo.get("contagem_sinais", {"verde": 0, "amarelo": 0, "vermelho": 0})

    # 1. Indicadores de Rastreabilidade e Conformidade
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("População (IBGE)", f"{relatorio_fluxo.get('populacao', 0):,} hab.")
    c2.metric("Total Repassado", f"R$ {relatorio_fluxo.get('total_recebido', 0.0):,.2f}")
    c3.metric("Emendas Rastreadas", f"{relatorio_fluxo.get('quantidade_emendas', 0)}")
    c4.metric(
        "Índice de Conformidade Documental",
        f"{relatorio_fluxo.get('score_conformidade', 0.0):.1f}%",
        help="Calculado a partir das 5 dimensões técnicas de rastreabilidade (Plano de Trabalho, e-Sfinge, Ritmo, Fornecedor e Transparência).",
    )

    # 2. Painel de Acesso Rápido a Portais Oficiais de Auditoria
    st.markdown("##### 🔗 Portais Oficiais para Verificação Manual (Sem Login / Acesso Público)")
    links = relatorio_fluxo.get("links_oficiais", {})
    l1, l2, l3, l4 = st.columns(4)
    l1.markdown(f"📊 [**Painel TCE/SC: Fluxo de Recursos**]({links.get('tce_fluxo_recursos', '#')})")
    l2.markdown(f"🏛️ [**Sistema e-Sfinge TCE/SC**]({links.get('tce_esfinge', '#')})")
    l3.markdown(f"⚖️ [**Cautelar TCE/SC: Planos de Trabalho**]({links.get('tce_medida_cautelar', '#')})")
    l4.markdown(f"🌐 [**Transparência Municipal**]({links.get('portal_transparencia_municipio', '#')})")

    st.markdown("---")

    # 3. Sumário dos Sinais Técnicos de Rastreabilidade
    st.markdown("##### 📋 Resumo das 5 Dimensões de Verificação Técnica")
    c_s1, c_s2, c_s3 = st.columns(3)
    c_s1.info(f"🟢 **{contagem_sinais.get('verde', 0)} registros regulares**: Objeto compatível, fluxo formalizado e fornecedor regular.")
    c_s2.warning(f"🟡 **{contagem_sinais.get('amarelo', 0)} pontos de atenção**: Plano de trabalho genérico ou em tramitação inicial.")
    c_s3.error(f"🔴 **{contagem_sinais.get('vermelho', 0)} pendências de evidência**: Fornecedor com apontamento cadastral ou ausência de prestação de contas.")

    # 4. Detalhamento de cada emenda com rastreamento ponta a ponta
    emendas = relatorio_fluxo.get("emendas_analisadas", [])
    st.subheader(f"🔍 Rastreamento Individual das Emendas: {relatorio_fluxo.get('municipio', escolha)}")

    if emendas:
        for em in emendas:
            titulo_expander = (
                f"[{em['estagio_fluxo']}] {em['id_emenda']} — {em['parlamentar']} "
                f"| R$ {em['valor']:,.2f} ({em['area']})"
            )
            with st.expander(titulo_expander):
                st.markdown(f"**Beneficiário / Fornecedor Contratado:** `{em['fornecedor_nome']}` (CNPJ: `{em['fornecedor_cnpj']}`)")
                st.markdown(
                    f"🔗 [Consultar Fornecedor no Gov.br]({em['cnpj_link_gov']}) | "
                    f"🔗 [Ver Emenda no TCE/SC]({em['tce_link']})"
                )

                st.markdown("###### Sinais de Conformidade e Rastreabilidade:")
                for sinal in em["sinais"]:
                    tag = sinal.get("tag", "")
                    desc = sinal.get("descricao", "")
                    if sinal.get("status") == "verde":
                        st.success(f"**{tag}**: {desc}")
                    elif sinal.get("status") == "amarelo":
                        st.warning(f"**{tag}**: {desc}")
                    else:
                        st.error(f"**{tag}**: {desc}")
    else:
        st.info("Nenhuma emenda registrada para este município na base de dados.")


def executar_interface_streamlit() -> None:
    """Inicializa a aplicação Streamlit com menu lateral de navegação entre as 5 páginas e aviso ético."""
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
            "1. Central de Alertas (Exclusiva)",
            "2. Explorador de Emendas",
            "3. Perfil do Parlamentar",
            "4. Perfil do Município",
            "5. Rastreabilidade & Fluxo de Recursos (TCE/SC)",
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
    elif pagina.startswith("4."):
        renderizar_pagina_perfil_municipio(st, dados)
    else:
        renderizar_pagina_fluxo_recursos(st, dados)


if __name__ == "__main__":
    executar_interface_streamlit()
