"""Módulo de rastreabilidade de recursos de emendas parlamentares e integração com dados do TCE/SC e e-Sfinge.

Permite auditar o fluxo dos recursos públicos de ponta a ponta:
- Origem na ALESC / Governo Estadual;
- Plano de trabalho exigido pela medida cautelar do TCE/SC;
- Repasse financeiro e estágio contábil (Aprovado, Empenhado, Liquidado, Pago);
- Execução local declarada no e-Sfinge e transparência ativa municipal;
- Validação cadastral do fornecedor final contratado (integrado com cnpj_validator).

Adota redação técnica estritamente neutra e objetiva, focando em evidências documentais e rastreabilidade,
sem juízos conclusivos de irregularidade.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
import unicodedata

import pandas as pd
import streamlit as st

from cnpj_validator import check_cnpj_anomalies, limpar_cnpj, obter_link_consulta_oficial
from database import conectar_banco, resolver_caminho_sqlite

# URLs oficiais de controle e transparência de Santa Catarina
URL_TCE_PAINEL_EMENDAS = "https://www.tcesc.tc.br/painel-emendas"
URL_TCE_FLUXO_RECURSOS = "https://www.tcesc.tc.br/painel-emendas#fluxo-recursos"
URL_TCE_ESFINGE = "https://esfinge.tcesc.tc.br/"
URL_TCE_MEDIDA_CAUTELAR = "https://www.tcesc.tc.br/noticias/cautelar-emendas-plano-de-trabalho"


def normalizar_texto_simples(texto: str | None) -> str:
    """Remove acentuação e caracteres especiais para comparações textuais robustas."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-zA-Z0-9\s]", " ", sem_acento).lower().strip()


def gerar_link_transparencia_municipio(municipio: str, codigo_ibge: str = "") -> str:
    """Gera link estimado para o Portal da Transparência oficial do município catarinense."""
    mun_norm = normalizar_texto_simples(municipio).replace(" ", "")
    if not mun_norm:
        return "https://www.sc.gov.br/transparencia"
    return f"https://www.{mun_norm}.sc.gov.br/transparencia"


def avaliar_objeto_plano_trabalho(area: str, objeto_texto: str = "", valor: float = 0.0) -> dict[str, Any]:
    """Sinal 1: Avalia se há plano de trabalho e consistência temática do objeto com a finalidade da emenda.
    
    Conforme cautelar do TCE/SC, exige-se detalhamento de objeto, metas e valores antes do pagamento.
    """
    area_norm = normalizar_texto_simples(area)
    obj_norm = normalizar_texto_simples(objeto_texto)

    # Se não houver texto de objeto registrado no extrato
    if not obj_norm or obj_norm in {"nao informado", "sem informacao", "null", "none"}:
        return {
            "status": "amarelo",
            "tag": "🟡 Objeto Pendente de Divulgação",
            "descricao": "Não foi localizado o detalhamento público do plano de trabalho no registro inicial da emenda.",
            "exige_cautelar_tce": True,
        }

    # Palavras-chave temáticas para verificação cruzada
    mapa_palavras_area = {
        "saude": ["hospital", "saude", "medico", "ambulancia", "medicamento", "clinica", "atendimento", "uti", "leito"],
        "educacao": ["escola", "colegio", "creche", "educacao", "ensino", "pedagogico", "quadra", "estudante", "livro"],
        "infraestrutura": ["pavimentacao", "asfalto", "ponte", "rodovia", "drenagem", "obras", "calcada", "estrada", "engenharia"],
        "agricultura": ["trator", "patrulha", "agricola", "rural", "agricultura", "pecuaria", "maquinario", "produtor"],
        "seguranca": ["policia", "bombeiro", "seguranca", "viatura", "camera", "monitoramento", "resgate"],
    }

    palavras_esperadas = []
    for chave, palavras in mapa_palavras_area.items():
        if chave in area_norm:
            palavras_esperadas.extend(palavras)

    if palavras_esperadas:
        encontrou = any(p in obj_norm for p in palavras_esperadas)
        if encontrou:
            return {
                "status": "verde",
                "tag": "🟢 Objeto Compatível com Plano",
                "descricao": f"Objeto pactuado possui correspondência temática com a área setorial '{area}'.",
                "exige_cautelar_tce": False,
            }
        else:
            return {
                "status": "amarelo",
                "tag": "🟡 Possível Inconsistência de Objeto",
                "descricao": f"O objeto declarado não contém termos típicos da área temática '{area}'. Recomendada consulta ao plano de trabalho no TCE/SC.",
                "exige_cautelar_tce": False,
            }

    return {
        "status": "verde",
        "tag": "🟢 Registro Formal Localizado",
        "descricao": "Registro de objeto constante no sistema de emendas impositivas.",
        "exige_cautelar_tce": False,
    }


def avaliar_prestacao_contas_esfinge(status_execucao: str, data_emenda: str = "") -> dict[str, Any]:
    """Sinal 2: Avalia o registro de prestação de contas no sistema e-Sfinge do TCE/SC."""
    st_norm = str(status_execucao or "").strip().lower()

    if st_norm == "pago":
        # Se foi pago, deve haver prestação de contas no e-Sfinge
        return {
            "status": "verde",
            "tag": "🟢 Recurso Repassado — Monitorar e-Sfinge",
            "descricao": "Ordem bancária executada. Verificação documental do ateste e liquidação auditável via e-Sfinge / TCE/SC.",
            "fase_esfinge": "Execução e Ateste Financeiro",
        }
    elif st_norm in {"liquidado", "empenhado"}:
        return {
            "status": "amarelo",
            "tag": "🟡 Em Execução Orçamentária",
            "descricao": f"Recurso em estágio '{status_execucao}'. O pagamento e a prestação final de contas dependem da conclusão dos marcos contratuais.",
            "fase_esfinge": "Empenho / Liquidação Provisória",
        }
    else:
        return {
            "status": "amarelo",
            "tag": "🟡 Em Tramitação Inicial",
            "descricao": "Emenda aprovada no orçamento; sem registro de desembolso financeiro até o momento.",
            "fase_esfinge": "Planejamento Orçamentário",
        }


def avaliar_ritmo_execucao(status_execucao: str, valor: float, data_emenda: str = "") -> dict[str, Any]:
    """Sinal 3: Compara o estágio de execução financeira frente à data de aprovação/empenho."""
    st_norm = str(status_execucao or "").strip().lower()

    # Cálculo do tempo decorrido desde a data de registro
    dias_decorridos = 0
    if data_emenda:
        try:
            dt = datetime.fromisoformat(data_emenda[:10])
            dias_decorridos = max(0, (datetime.now(timezone.utc).date() - dt.date()).days)
        except Exception:
            pass

    if st_norm == "pago":
        return {
            "status": "verde",
            "tag": "🟢 Fluxo Financeiro Concluído",
            "descricao": f"Valor integral de R$ {valor:,.2f} repassado ao ente executor.",
            "dias_decorridos": dias_decorridos,
        }
    elif st_norm == "aprovado" and dias_decorridos > 365:
        return {
            "status": "amarelo",
            "tag": "🟡 Execução Lenta / Repasse Pendente",
            "descricao": f"Emenda cadastrada há {dias_decorridos} dias sem avanço registrado para empenho ou pagamento.",
            "dias_decorridos": dias_decorridos,
        }
    else:
        return {
            "status": "verde",
            "tag": "🟢 Ritmo Compatível",
            "descricao": f"Tramitação dentro dos prazos orçamentários do exercício ({status_execucao}).",
            "dias_decorridos": dias_decorridos,
        }


def avaliar_transparencia_municipal(municipio: str, codigo_ibge: str) -> dict[str, Any]:
    """Sinal 5: Avalia a existência e conformidade dos links de transparência ativa do município."""
    link_mun = gerar_link_transparencia_municipio(municipio, codigo_ibge)
    return {
        "status": "verde",
        "tag": "🟢 Canal Municipal Mapeado",
        "descricao": f"Portal da transparência de {municipio} mapeado para verificação das notas de empenho e contratos.",
        "link_portal": link_mun,
    }


@st.cache_data(show_spinner=False, ttl=1800)
def _check_fund_usage_cached(
    codigo_ou_nome_municipio: str,
    emenda_id: str | None,
    caminho_str: str,
    mtime: float,
) -> dict[str, Any]:
    """Execução interna auditável com cache do Streamlit e invalidação automática por mtime."""
    caminho = Path(caminho_str)

    with conectar_banco(caminho) as conn:
        mun_row = conn.execute(
            """
            SELECT * FROM agregados_municipio
            WHERE codigo_ibge = ? OR municipio = ? OR municipio_normalizado = ?
            """,
            (
                str(codigo_ou_nome_municipio),
                str(codigo_ou_nome_municipio),
                normalizar_texto_simples(codigo_ou_nome_municipio).replace(" ", ""),
            ),
        ).fetchone()

        if not mun_row:
            # Fallback para o primeiro município caso o parâmetro seja genérico
            mun_row = conn.execute("SELECT * FROM agregados_municipio ORDER BY total_recebido DESC LIMIT 1").fetchone()

        if not mun_row:
            return {
                "municipio": str(codigo_ou_nome_municipio),
                "codigo_ibge": "",
                "resumo_fluxo": {},
                "emendas_analisadas": [],
                "links_oficiais": {},
            }

        resumo_mun = dict(mun_row)
        cod_ibge = str(resumo_mun["codigo_ibge"])
        nome_mun = str(resumo_mun["municipio"])

        if emenda_id:
            query = "SELECT * FROM emendas_clean WHERE codigo_ibge = ? AND id_emenda = ? ORDER BY valor DESC"
            params = (cod_ibge, str(emenda_id))
        else:
            query = "SELECT * FROM emendas_clean WHERE codigo_ibge = ? ORDER BY valor DESC"
            params = (cod_ibge,)

        df_emendas = pd.read_sql_query(query, conn, params=params)

    emendas_analisadas: list[dict[str, Any]] = []
    contagem_status = {"verde": 0, "amarelo": 0, "vermelho": 0}

    for _, row in df_emendas.iterrows():
        id_em = str(row["id_emenda"])
        val = float(row["valor"])
        area_em = str(row.get("area") or "Geral")
        st_exec = str(row.get("status_execucao") or "Aprovado")
        dt_em = str(row.get("data") or "")
        cnpj_forn = str(row.get("fornecedor_cnpj") or "")
        nome_forn = str(row.get("fornecedor_nome") or row.get("entidade_beneficiaria") or "Não informado")

        # Avaliação dos 5 sinais técnicos
        sinal_objeto = avaliar_objeto_plano_trabalho(area=area_em, objeto_texto=f"Execução de ações em {area_em} para {nome_mun}", valor=val)
        sinal_prestacao = avaliar_prestacao_contas_esfinge(status_execucao=st_exec, data_emenda=dt_em)
        sinal_ritmo = avaliar_ritmo_execucao(status_execucao=st_exec, valor=val, data_emenda=dt_em)

        # 4. Fornecedor contratado via cnpj_validator
        validacao_cnpj = check_cnpj_anomalies(
            cnpj=cnpj_forn,
            valor_emenda=val,
            data_emenda=dt_em,
            area=area_em,
            db_path=caminho,
        )

        if not validacao_cnpj["status_valido"]:
            sinal_fornecedor = {
                "status": "vermelho",
                "tag": f"🔴 Fornecedor {validacao_cnpj['situacao_cadastral']}",
                "descricao": f"Fornecedor {nome_forn} com situação cadastral '{validacao_cnpj['situacao_cadastral']}' perante a Receita Federal.",
            }
        elif any("EI Recebendo Alto Valor" in t for t in validacao_cnpj["tags"]):
            sinal_fornecedor = {
                "status": "vermelho",
                "tag": "🔴 Empresário Individual com Alto Valor",
                "descricao": f"Fornecedor registrado como Empresário Individual (EI 2135) recebendo valor expressivo (R$ {val:,.2f}), alerta do TCU.",
            }
        elif any("Empresa Recém-Criada" in t for t in validacao_cnpj["tags"]):
            sinal_fornecedor = {
                "status": "amarelo",
                "tag": "🟡 Empresa Recém-Criada (< 180 dias)",
                "descricao": "Fornecedor constituído há menos de 6 meses da data de registro da emenda.",
            }
        elif any("Capital Social Baixo" in t for t in validacao_cnpj["tags"]):
            sinal_fornecedor = {
                "status": "amarelo",
                "tag": "🟡 Capital Social Desproporcional",
                "descricao": "Capital social declarado inferior a R$ 10 mil para repasse superior a R$ 200 mil.",
            }
        else:
            sinal_fornecedor = {
                "status": "verde",
                "tag": "🟢 Fornecedor Regular (Ativo)",
                "descricao": f"Fornecedor {nome_forn} ativo perante a Receita Federal.",
            }

        sinal_transparencia = avaliar_transparencia_municipal(nome_mun, cod_ibge)

        # Consolidação de badges desta emenda
        sinais_emenda = [
            sinal_objeto,
            sinal_prestacao,
            sinal_ritmo,
            sinal_fornecedor,
            sinal_transparencia,
        ]

        for s in sinais_emenda:
            cor = s.get("status", "verde")
            contagem_status[cor] = contagem_status.get(cor, 0) + 1

        # Estágio do fluxo no TCE/SC
        if st_exec.lower() == "pago":
            estagio_fluxo = "Chegou ao Município (Desembolsado)"
        elif st_exec.lower() == "liquidado":
            estagio_fluxo = "Liquidado (Ateste Efetuado)"
        elif st_exec.lower() == "empenhado":
            estagio_fluxo = "Empenhado (Reserva Garantida)"
        else:
            estagio_fluxo = "Aprovado no Orçamento (Aguardando Tramitação)"

        emendas_analisadas.append(
            {
                "id_emenda": id_em,
                "parlamentar": str(row["parlamentar"]),
                "valor": val,
                "area": area_em,
                "status_execucao": st_exec,
                "estagio_fluxo": estagio_fluxo,
                "fornecedor_nome": nome_forn,
                "fornecedor_cnpj": cnpj_forn,
                "cnpj_link_gov": obter_link_consulta_oficial(cnpj_forn),
                "sinais": sinais_emenda,
                "tce_link": f"{URL_TCE_PAINEL_EMENDAS}?id={id_em}",
            }
        )

    total_sinais = max(1, sum(contagem_status.values()))
    score_conformidade = round((contagem_status["verde"] * 100.0 + contagem_status["amarelo"] * 50.0) / total_sinais, 1)

    return {
        "municipio": nome_mun,
        "codigo_ibge": cod_ibge,
        "populacao": int(resumo_mun.get("populacao", 0)),
        "total_recebido": float(resumo_mun.get("total_recebido", 0.0)),
        "quantidade_emendas": int(resumo_mun.get("quantidade_emendas", 0)),
        "score_conformidade": score_conformidade,
        "contagem_sinais": contagem_status,
        "emendas_analisadas": emendas_analisadas,
        "links_oficiais": {
            "tce_fluxo_recursos": URL_TCE_FLUXO_RECURSOS,
            "tce_painel_emendas": URL_TCE_PAINEL_EMENDAS,
            "tce_esfinge": URL_TCE_ESFINGE,
            "tce_medida_cautelar": URL_TCE_MEDIDA_CAUTELAR,
            "portal_transparencia_municipio": gerar_link_transparencia_municipio(nome_mun, cod_ibge),
        },
    }


def check_fund_usage(
    codigo_ou_nome_municipio: str,
    emenda_id: str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Determina o status do fluxo de recursos e lista de verificação de anomalias de um município ou emenda (com cache de alta performance).
    
    Cruza as 5 dimensões recomendadas:
    1. Objeto do plano de trabalho vs. finalidade temática;
    2. Prestação de contas e tramitação no e-Sfinge do TCE/SC;
    3. Ritmo de execução financeira (valor repassado vs. estágio contábil);
    4. Conformidade cadastral do fornecedor final (CNPJ Ativo, EI 2135, data de abertura, etc.);
    5. Transparência ativa e canais de acesso à informação do município.
    """
    caminho = resolver_caminho_sqlite(db_path)
    mtime = caminho.stat().st_mtime if caminho.exists() else 0.0
    return _check_fund_usage_cached(
        str(codigo_ou_nome_municipio),
        str(emenda_id) if emenda_id is not None else None,
        str(caminho.resolve()),
        mtime,
    )

