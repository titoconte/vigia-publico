"""Módulo de auditoria e conformidade entre Contratos Estaduais (SIGEF/SICOP) e a Finalidade de Emendas.

Analisa se os contratos administrativos firmados pelos fornecedores e municípios beneficiários
estão tematicamente alinhados ao objeto e área carimbada da emenda parlamentar.

Classificação de Conformidade:
- 🟢 Conforme (Objeto Alinhado): Termos do contrato condizentes com a finalidade temática da emenda;
- 🔴 Inconsistência Temática: Objeto do contrato divergente da área da emenda (ex: Saúde vs Pavimentação);
- 🟡 Objeto Genérico / Requer Verificação: Descrição contratual vaga sem detalhamento suficiente.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any
import unicodedata

import pandas as pd
import streamlit as st

from dados_sc_loader import carregar_dados_abertos_sc
from database import conectar_banco, inicializar_schema, resolver_caminho_sqlite

URL_CONTRATOS_SIGEF_SC = "https://dados.sc.gov.br/dataset/contratos-sigef"

# Dicionário de termos setoriais obrigatórios / esperados por área
PALAVRAS_CHAVE_AREA: dict[str, list[str]] = {
    "Saúde": [
        "saude", "hospital", "hospitalar", "medicamento", "ambulancia", "insumo",
        "clinica", "medico", "enfermagem", "cirurg", "uti", "leito", "exame",
        "ubs", "psf", "upa", "pre hospitalar", "urgencia", "emergencia", "odontol"
    ],
    "Educação": [
        "educacao", "escola", "escolar", "aluno", "pedagogic", "livro", "creche",
        "didatico", "merenda", "transporte escolar", "sala de aula", "quadra poliesportiva"
    ],
    "Infraestrutura e Mobilidade": [
        "pavimentacao", "asfalto", "asfaltica", "drenagem", "ponte", "recapeamento",
        "via", "rua", "estrada", "rodovia", "obra", "reforma", "engenharia", "calcada"
    ],
    "Agricultura": [
        "agricultura", "rural", "agricola", "trator", "patrulha mecanizada",
        "calcario", "semente", "safra", "adubo", "produtor rural", "implemento"
    ],
    "Segurança Pública": [
        "seguranca", "policia", "policial", "viatura", "camera", "videomonitoramento",
        "armamento", "colete", "bombeiro", "salvamento", "defesa civil", "resgate"
    ],
    "Assistência Social": [
        "assistencia", "social", "cras", "creas", "comunitario", "vulnerabilidade",
        "acolhimento", "idoso", "crianca", "abrigo"
    ],
    "Cultura e Esporte": [
        "cultura", "esporte", "esportivo", "ginasio", "estadio", "atleta",
        "evento", "musical", "teatro", "danca", "festival", "festa"
    ],
}

# Termos que configuram nítido desvio se presentes em áreas como Saúde ou Educação
TERMOS_DISCREPANTES: dict[str, list[str]] = {
    "Saúde": [
        "pavimentacao", "asfalto", "trio eletrico", "iluminacao festiva", "som e luz",
        "terraplanagem", "recapeamento", "locacao de palco"
    ],
    "Educação": [
        "pavimentacao asfaltica", "trio eletrico", "rodeio", "recapeamento"
    ],
}


def normalizar_texto_contrato(texto: str | None) -> str:
    """Normaliza texto do contrato para análise semântica sem acentos e em minúsculas."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-zA-Z0-9\s]", " ", sem_acento).lower().strip()


def avaliar_aderencia_objeto_area(objeto_contrato: str, area_emenda: str) -> dict[str, Any]:
    """Avalia o alinhamento semântico entre o objeto do contrato e a área carimbada da emenda."""
    obj_norm = normalizar_texto_contrato(objeto_contrato)
    area_nome = str(area_emenda or "Geral").strip()

    # 1. Verifica termos manifestamente discrepantes (alerta vermelho)
    termos_proibidos = TERMOS_DISCREPANTES.get(area_nome, [])
    for tp in termos_proibidos:
        if tp in obj_norm:
            return {
                "status": "vermelho",
                "tag": "🔴 Inconsistência Temática Manifesta",
                "descricao": f"Objeto menciona '{tp}' em emenda destinada para '{area_nome}'.",
                "score_aderencia": 10.0,
            }

    # 2. Verifica palavras-chave esperadas para a área
    termos_esperados = PALAVRAS_CHAVE_AREA.get(area_nome, [])
    termos_encontrados = [t for t in termos_esperados if t in obj_norm]

    if termos_encontrados:
        return {
            "status": "verde",
            "tag": "🟢 Objeto Conforme e Alinhado",
            "descricao": f"Objeto condizente com a área '{area_nome}' (termos: {', '.join(termos_encontrados[:3])}).",
            "score_aderencia": 90.0,
        }

    # 3. Se o objeto for muito curto ou vago
    if len(obj_norm.split()) < 5 or "prestacao de servicos" in obj_norm:
        return {
            "status": "amarelo",
            "tag": "🟡 Objeto Genérico / Requer Verificação",
            "descricao": "Objeto do contrato sucinto ou genérico sem especificação técnica da destinação da verba.",
            "score_aderencia": 45.0,
        }

    return {
        "status": "amarelo",
        "tag": "🟡 Termos Específicos Não Localizados",
        "descricao": f"Não foram encontradas palavras-chave típicas de '{area_nome}' no extrato público do contrato.",
        "score_aderencia": 50.0,
    }


@st.cache_data(show_spinner=False, ttl=1800)
def _auditar_contratos_emendas_cached(caminho_str: str, mtime: float) -> dict[str, Any]:
    """Execução interna de auditoria cruzada de contratos SIGEF vs emendas com cache em memória."""
    caminho = Path(caminho_str)

    inicializar_schema(caminho)
    with conectar_banco(caminho) as conn:
        cont_contratos = conn.execute("SELECT COUNT(*) FROM contratos_estaduais").fetchone()[0]
        if cont_contratos == 0:
            carregar_dados_abertos_sc(caminho)

        # Cruza contratos com emendas pelo CNPJ do fornecedor contratado
        query = """
            SELECT 
                c.id_contrato,
                c.numero_contrato,
                c.ano as contrato_ano,
                c.orgao_contratante,
                c.fornecedor_nome as contrato_fornecedor_nome,
                c.fornecedor_cnpj,
                c.municipio as contrato_municipio,
                c.codigo_ibge as contrato_ibge,
                c.objeto_contrato,
                c.valor_contrato,
                c.data_assinatura,
                c.situacao as contrato_situacao,
                c.fonte_url as contrato_fonte_url,
                e.id_emenda,
                e.parlamentar,
                e.partido,
                e.valor as emenda_valor,
                e.area as emenda_area,
                e.municipio as emenda_municipio,
                e.status_execucao as emenda_status
            FROM contratos_estaduais c
            JOIN emendas_clean e ON c.fornecedor_cnpj = e.fornecedor_cnpj
            ORDER BY c.valor_contrato DESC
        """
        df_cruzado = pd.read_sql_query(query, conn)

    if df_cruzado.empty:
        return {
            "resumo": {
                "total_cruzamentos": 0,
                "contratos_analisados": 0,
                "emendas_vinculadas": 0,
                "inconsistencias_tematicas": 0,
                "conformes": 0,
                "genericos": 0,
                "valor_total_contratos": 0.0,
            },
            "auditorias": [],
            "df_agrupado": pd.DataFrame(),
        }

    auditorias: list[dict[str, Any]] = []

    for _, row in df_cruzado.iterrows():
        id_ct = str(row["id_contrato"])
        num_ct = str(row["numero_contrato"])
        obj_ct = str(row["objeto_contrato"])
        area_em = str(row["emenda_area"])
        val_ct = float(row["valor_contrato"])
        val_em = float(row["emenda_valor"])

        avaliacao = avaliar_aderencia_objeto_area(objeto_contrato=obj_ct, area_emenda=area_em)

        # Avaliação de descompasso financeiro
        razao_valor = (val_ct / val_em) if val_em > 0 else 1.0
        nota_financeira = ""
        if razao_valor > 3.0:
            nota_financeira = f"Valor contratado (R$ {val_ct:,.2f}) supera em mais de 3x a emenda vinculada."
        elif razao_valor < 0.3:
            nota_financeira = f"Valor contratado (R$ {val_ct:,.2f}) representa fração inferior a 30% da emenda prevista."

        auditorias.append({
            "id_contrato": id_ct,
            "numero_contrato": num_ct,
            "ano": int(row["contrato_ano"]),
            "orgao_contratante": str(row["orgao_contratante"]),
            "fornecedor_nome": str(row["contrato_fornecedor_nome"]),
            "fornecedor_cnpj": str(row["fornecedor_cnpj"]),
            "municipio": str(row["contrato_municipio"]),
            "objeto_contrato": obj_ct,
            "valor_contrato": val_ct,
            "data_assinatura": str(row["data_assinatura"]),
            "situacao": str(row["contrato_situacao"]),
            "id_emenda": str(row["id_emenda"]),
            "parlamentar": str(row["parlamentar"]),
            "partido": str(row["partido"]),
            "emenda_valor": val_em,
            "emenda_area": area_em,
            "emenda_municipio": str(row["emenda_municipio"]),
            "status_emenda": str(row["emenda_status"]),
            "status_conformidade": avaliacao["status"],
            "tag_conformidade": avaliacao["tag"],
            "descricao_conformidade": avaliacao["descricao"],
            "nota_financeira": nota_financeira,
            "fonte_url": str(row.get("contrato_fonte_url") or URL_CONTRATOS_SIGEF_SC),
        })

    # Ordenação: inconsistências primeiro, seguidas por valor do contrato
    auditorias.sort(key=lambda x: (0 if x["status_conformidade"] == "vermelho" else (1 if x["status_conformidade"] == "amarelo" else 2), -x["valor_contrato"]))

    total_inconsistencias = sum(1 for a in auditorias if a["status_conformidade"] == "vermelho")
    total_conformes = sum(1 for a in auditorias if a["status_conformidade"] == "verde")
    total_genericos = sum(1 for a in auditorias if a["status_conformidade"] == "amarelo")

    df_tabela = pd.DataFrame([
        {
            "Status": a["tag_conformidade"],
            "Contrato SIGEF": a["numero_contrato"],
            "Ano": a["ano"],
            "Fornecedor": a["fornecedor_nome"],
            "CNPJ": a["fornecedor_cnpj"],
            "Valor Contrato (R$)": a["valor_contrato"],
            "Área Emenda": a["emenda_area"],
            "Valor Emenda (R$)": a["emenda_valor"],
            "Deputado Autor": a["parlamentar"],
            "Município": a["municipio"],
            "Objeto do Contrato": a["objeto_contrato"],
        }
        for a in auditorias
    ])

    return {
        "resumo": {
            "total_cruzamentos": len(auditorias),
            "contratos_analisados": len(set(a["id_contrato"] for a in auditorias)),
            "emendas_vinculadas": len(set(a["id_emenda"] for a in auditorias)),
            "inconsistencias_tematicas": total_inconsistencias,
            "conformes": total_conformes,
            "genericos": total_genericos,
            "valor_total_contratos": sum(a["valor_contrato"] for a in auditorias),
        },
        "auditorias": auditorias,
        "df_agrupado": df_tabela,
    }


def auditar_contratos_emendas(db_path: Path | str | None = None) -> dict[str, Any]:
    """Audita a conformidade de objeto entre contratos do SIGEF e a finalidade das emendas parlamentares."""
    caminho = resolver_caminho_sqlite(db_path)
    mtime = caminho.stat().st_mtime if caminho.exists() else 0.0
    return _auditar_contratos_emendas_cached(str(caminho.resolve()), mtime)
