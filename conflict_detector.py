"""Módulo de detecção e auditoria de Conflito de Interesses (Servidores Públicos vs. Sócios QSA).

Cruza dados abertos de Remuneração e Lotação de Servidores Públicos de SC (dados.sc.gov.br)
com o Quadro de Sócios e Administradores (QSA/Receita Federal) de fornecedores de emendas.

Regras de Análise:
- 🔴 Alto Risco (Conflito Direto de Pasta): Servidor estadual lotado na mesma área da emenda parlamentar;
- 🟡 Risco Moderado (Participação Societária): Servidor público estadual sócio de empresa contemplada por emendas;
- Tratamento ético de homônimos e links diretos para o Portal da Transparência de SC.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from dados_sc_loader import carregar_dados_abertos_sc, normalizar_nome_busca
from database import conectar_banco, inicializar_schema, resolver_caminho_sqlite

URL_TRANSPARENCIA_SERVIDORES_SC = "https://dados.sc.gov.br/dataset/remuneracao-servidores-do-executivo"
URL_PORTAL_TRANSPARENCIA_SC = "https://www.transparencia.sc.gov.br/servidores"

# Mapeamento semântico entre órgãos do Estado de SC e áreas temáticas de emendas
MAPA_ORGAO_AREA: dict[str, list[str]] = {
    "Saúde": [
        "SAUDE", "SES", "FES", "HOSPITAL", "MATERNIDADE", "HEMOSC", "CEPON"
    ],
    "Educação": [
        "EDUCACAO", "SED", "FEE", "ESCOLA", "UNIVERSIDADE", "UDESC"
    ],
    "Infraestrutura e Mobilidade": [
        "INFRAESTRUTURA", "SIE", "MOBILIDADE", "DEINFRA", "OBRAS", "TRANSPORTES", "CASAN", "CELESC"
    ],
    "Agricultura": [
        "AGRICULTURA", "SAR", "EPAGRI", "CIDASC", "PESCA", "DESENVOLVIMENTO RURAL"
    ],
    "Segurança Pública": [
        "SEGURANCA", "SSP", "POLICIA", "PCSC", "PMSC", "BOMBEIROS", "CBMSC", "PENITENCIARIO", "SAP"
    ],
    "Assistência Social": [
        "ASSISTENCIA", "DESENVOLVIMENTO SOCIAL", "SAS", "DIREITOS HUMANOS"
    ],
}


def checar_conflito_direto_pasta(orgao_lotacao: str, area_emenda: str) -> bool:
    """Verifica se há sobreposição temática entre o órgão de lotação do servidor e a área da emenda."""
    orgao_norm = normalizar_nome_busca(orgao_lotacao)
    area_norm = str(area_emenda or "").strip()

    palavras_chave = MAPA_ORGAO_AREA.get(area_norm, [])
    for termo in palavras_chave:
        if termo in orgao_norm:
            return True
    return False


@st.cache_data(show_spinner=False, ttl=1800)
def _detectar_conflitos_servidores_cached(caminho_str: str, mtime: float) -> dict[str, Any]:
    """Execução interna auditável com cache em memória do Streamlit e invalidação automática por mtime."""
    caminho = Path(caminho_str)

    inicializar_schema(caminho)
    with conectar_banco(caminho) as conn:
        # Garante que temos dados carregados
        cont_serv = conn.execute("SELECT COUNT(*) FROM servidores_estaduais").fetchone()[0]
        cont_socios = conn.execute("SELECT COUNT(*) FROM cnpj_socios").fetchone()[0]
        if cont_serv == 0 or cont_socios == 0:
            carregar_dados_abertos_sc(caminho)

        query = """
            SELECT 
                s.id as servidor_id,
                s.nome as servidor_nome,
                s.cpf_mascarado as servidor_cpf,
                s.cargo as servidor_cargo,
                s.orgao_lotacao as servidor_orgao,
                s.municipio_lotacao as servidor_municipio,
                s.remuneracao_bruta as servidor_salario,
                s.situacao_funcional as servidor_situacao,
                soc.cnpj as fornecedor_cnpj,
                soc.nome_socio as socio_nome,
                soc.qualificacao as socio_qualificacao,
                e.id_emenda,
                e.parlamentar,
                e.partido,
                e.valor as emenda_valor,
                e.municipio as emenda_municipio,
                e.codigo_ibge as emenda_codigo_ibge,
                e.area as emenda_area,
                e.entidade_beneficiaria,
                e.fornecedor_nome,
                e.status_execucao,
                e.data as emenda_data
            FROM servidores_estaduais s
            JOIN cnpj_socios soc ON s.nome_normalizado = soc.nome_socio_normalizado
            JOIN emendas_clean e ON soc.cnpj = e.fornecedor_cnpj
            ORDER BY e.valor DESC
        """
        df_bruto = pd.read_sql_query(query, conn)

    if df_bruto.empty:
        return {
            "resumo": {
                "total_casos": 0,
                "servidores_distintos": 0,
                "empresas_distintas": 0,
                "valor_total_sob_risco": 0.0,
                "alto_risco_count": 0,
                "risco_moderado_count": 0,
            },
            "casos_detalhados": [],
            "df_agrupado": pd.DataFrame(),
        }

    casos_detalhados: list[dict[str, Any]] = []
    chaves_vistas: set[tuple[str, str]] = set()

    # Agrupa por (servidor_nome, fornecedor_cnpj) para visão consolidada
    for (serv_nome, cnpj), df_grupo in df_bruto.groupby(["servidor_nome", "fornecedor_cnpj"]):
        primeira_linha = df_grupo.iloc[0]
        valor_acumulado = float(df_grupo["emenda_valor"].sum())
        qtd_emendas = len(df_grupo)

        orgao = str(primeira_linha["servidor_orgao"])
        areas_emendas = df_grupo["emenda_area"].unique().tolist()

        # Avaliação de severidade: se alguma emenda for na mesma pasta temática do servidor
        tem_conflito_direto = any(checar_conflito_direto_pasta(orgao, area) for area in areas_emendas)

        if tem_conflito_direto:
            severidade = "vermelho"
            tag = "🔴 Conflito Direto de Pasta / Área"
            descricao = (
                f"Servidor(a) lotado(a) em '{orgao}' e sócio(a) da empresa '{primeira_linha['fornecedor_nome']}', "
                f"beneficiária de R$ {valor_acumulado:,.2f} em emendas com destinação temática correlata."
            )
        else:
            severidade = "amarelo"
            tag = "🟡 Servidor Estadual Sócio de Fornecedor"
            descricao = (
                f"Servidor(a) público(a) estadual ativo(a) figurando como sócio(a) de empresa fornecedora "
                f"contemplada por emendas parlamentares (R$ {valor_acumulado:,.2f} total)."
            )

        casos_detalhados.append({
            "servidor_nome": serv_nome,
            "servidor_cpf": str(primeira_linha["servidor_cpf"]),
            "servidor_cargo": str(primeira_linha["servidor_cargo"]),
            "servidor_orgao": orgao,
            "servidor_municipio": str(primeira_linha["servidor_municipio"]),
            "servidor_salario": float(primeira_linha["servidor_salario"]),
            "fornecedor_cnpj": str(cnpj),
            "fornecedor_nome": str(primeira_linha["fornecedor_nome"]),
            "socio_qualificacao": str(primeira_linha["socio_qualificacao"]),
            "valor_total_emendas": valor_acumulado,
            "quantidade_emendas": qtd_emendas,
            "areas_emendas": ", ".join(areas_emendas),
            "severidade": severidade,
            "tag": tag,
            "descricao_conflito": descricao,
            "emendas_relacionadas": df_grupo[[
                "id_emenda", "parlamentar", "partido", "emenda_valor",
                "emenda_municipio", "emenda_area", "status_execucao", "emenda_data"
            ]].to_dict(orient="records"),
            "link_portal_servidor": URL_PORTAL_TRANSPARENCIA_SC,
        })

    # Ordena por severidade (vermelhos primeiro) e valor acumulado
    casos_detalhados.sort(key=lambda x: (0 if x["severidade"] == "vermelho" else 1, -x["valor_total_emendas"]))

    total_vermelhos = sum(1 for c in casos_detalhados if c["severidade"] == "vermelho")
    total_amarelos = sum(1 for c in casos_detalhados if c["severidade"] == "amarelo")
    valor_total_risco = sum(c["valor_total_emendas"] for c in casos_detalhados)

    # DataFrame tabular para consultas e exportação
    df_tabela = pd.DataFrame([
        {
            "Severidade": c["tag"],
            "Servidor Público": c["servidor_nome"],
            "Cargo": c["servidor_cargo"],
            "Órgão de Lotação": c["servidor_orgao"],
            "Empresa Fornecedora": c["fornecedor_nome"],
            "CNPJ": c["fornecedor_cnpj"],
            "Qualificação QSA": c["socio_qualificacao"],
            "Total em Emendas (R$)": c["valor_total_emendas"],
            "Qtd Emendas": c["quantidade_emendas"],
            "Áreas das Emendas": c["areas_emendas"],
        }
        for c in casos_detalhados
    ])

    return {
        "resumo": {
            "total_casos": len(casos_detalhados),
            "servidores_distintos": len(set(c["servidor_nome"] for c in casos_detalhados)),
            "empresas_distintas": len(set(c["fornecedor_cnpj"] for c in casos_detalhados)),
            "valor_total_sob_risco": valor_total_risco,
            "alto_risco_count": total_vermelhos,
            "risco_moderado_count": total_amarelos,
        },
        "casos_detalhados": casos_detalhados,
        "df_agrupado": df_tabela,
    }


def detectar_conflitos_servidores(db_path: Path | str | None = None) -> dict[str, Any]:
    """Identifica potenciais conflitos de interesse entre servidores estaduais de SC e sócios de fornecedores."""
    caminho = resolver_caminho_sqlite(db_path)
    mtime = caminho.stat().st_mtime if caminho.exists() else 0.0
    return _detectar_conflitos_servidores_cached(str(caminho.resolve()), mtime)
