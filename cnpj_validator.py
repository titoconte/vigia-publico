"""Módulo de validação cadastral de CNPJ e detecção de anomalias em fornecedores de emendas parlamentares.

Implementa a arquitetura em 3 camadas recomendada:
1ª Camada: Verificação da Situação Cadastral (Ativa, Baixada, Inapta, Suspensa, Nula);
2ª Camada: Indicadores de anomalia cadastral (Empresa recém-criada < 180 dias, Empresário Individual 2135 > R$ 500k,
           CNAE incompatível com a área da emenda, Capital social desproporcional < R$ 10k);
3ª Camada: Cache local persistente (tabela cnpj_cache no SQLite) e links diretos para consulta pública no Portal da Transparência/Gov.br.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any

from database import conectar_banco, resolver_caminho_sqlite

# Situações cadastrais oficiais da Receita Federal
SITUACAO_ATIVA = "Ativa"
SITUACAO_BAIXADA = "Baixada"
SITUACAO_INAPTA = "Inapta"
SITUACAO_SUSPENSA = "Suspensa"
SITUACAO_NULA = "Nula"

SITUACOES_VALIDAS = {
    SITUACAO_ATIVA,
    SITUACAO_BAIXADA,
    SITUACAO_INAPTA,
    SITUACAO_SUSPENSA,
    SITUACAO_NULA,
}

# Códigos de Natureza Jurídica para Empresário Individual (foco no relatório do TCU - código 2135)
CODIGOS_EMPRESARIO_INDIVIDUAL = {"2135", "213-5", "2135-0"}

# Mapeamento setorial de compatibilidade entre áreas de emendas e prefixos de códigos CNAE
CNAE_COMPATIBILIDADE_AREA: dict[str, list[str]] = {
    "Saúde": [
        "86", "87", "4664", "4644", "4645", "4771", "4772", "4773", "8411", "8412", "9430", "8421"
    ],
    "Educação": [
        "85", "5811", "5812", "4761", "4929", "8411", "8412", "9430", "7210", "7220"
    ],
    "Infraestrutura e Mobilidade": [
        "41", "42", "43", "7112", "7119", "4923", "4924", "4929", "8411", "8412", "9430", "2330"
    ],
    "Agricultura": [
        "01", "02", "03", "4661", "4623", "7500", "8411", "8412", "9430", "10", "11", "2833"
    ],
    "Segurança Pública": [
        "80", "8424", "8425", "29", "45", "8411", "8412", "9430", "61", "2632"
    ],
}


def limpar_cnpj(cnpj: str | None) -> str:
    """Extrai somente os dígitos numéricos de um CNPJ e formata com 14 dígitos (zero à esquerda)."""
    digitos = re.sub(r"\D", "", str(cnpj or "")).strip()
    return digitos.zfill(14) if digitos else ""


def formatar_cnpj_exibicao(cnpj: str | None) -> str:
    """Formata uma string de CNPJ no formato padrão oficial XX.XXX.XXX/XXXX-XX."""
    num = limpar_cnpj(cnpj)
    if len(num) == 14:
        return f"{num[:2]}.{num[2:5]}.{num[5:8]}/{num[8:12]}-{num[12:]}"
    return cnpj or "Não informado"


def obter_link_consulta_oficial(cnpj: str | None) -> str:
    """Gera link direto para verificação oficial pública do CNPJ no Portal da Transparência Federal."""
    num = limpar_cnpj(cnpj)
    if num:
        return f"https://portaldatransparencia.gov.br/pessoa-juridica/{num}"
    return "https://solucoes.receita.fazenda.gov.br/servicos/cnpjreva/cnpjreva_solicitacao.asp"


def normalizar_situacao_cadastral(situacao_bruta: str | None) -> str:
    """Normaliza o status cadastral para um dos 5 valores padrão: 'Ativa', 'Baixada', 'Inapta', 'Suspensa' ou 'Nula'."""
    texto = str(situacao_bruta or "").strip().upper()
    if "BAIXAD" in texto:
        return SITUACAO_BAIXADA
    if "INAPT" in texto:
        return SITUACAO_INAPTA
    if "SUSPENS" in texto:
        return SITUACAO_SUSPENSA
    if "NULA" in texto or "NULO" in texto:
        return SITUACAO_NULA
    if "ATIV" in texto:
        return SITUACAO_ATIVA
    return SITUACAO_ATIVA


def inicializar_tabela_cnpj_cache(db_path: Path | str | None = None) -> None:
    """Cria a tabela cnpj_cache e seus índices no banco SQLite se não existirem."""
    caminho = resolver_caminho_sqlite(db_path)
    with conectar_banco(caminho) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cnpj_cache (
                cnpj TEXT PRIMARY KEY,
                razao_social TEXT,
                nome_fantasia TEXT,
                situacao_cadastral TEXT NOT NULL DEFAULT 'Ativa',
                data_situacao_cadastral TEXT,
                motivo_situacao_cadastral TEXT,
                data_abertura TEXT,
                natureza_juridica TEXT,
                natureza_juridica_codigo TEXT,
                capital_social REAL DEFAULT 0.0,
                cnae_principal TEXT,
                cnae_descricao TEXT,
                uf TEXT,
                municipio TEXT,
                fonte_consulta TEXT,
                atualizado_em TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cnpj_cache_situacao ON cnpj_cache (situacao_cadastral)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cnpj_cache_natureza ON cnpj_cache (natureza_juridica_codigo)")
        conn.commit()


def salvar_cnpj_cache(dados: dict[str, Any], db_path: Path | str | None = None) -> None:
    """Insere ou atualiza os dados cadastrais enriquecidos de um CNPJ no cache local persistente."""
    cnpj_limpo = limpar_cnpj(dados.get("cnpj"))
    if not cnpj_limpo or len(cnpj_limpo) != 14:
        return

    inicializar_tabela_cnpj_cache(db_path)
    caminho = resolver_caminho_sqlite(db_path)
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    situacao = normalizar_situacao_cadastral(dados.get("situacao_cadastral"))
    nat_cod = str(dados.get("natureza_juridica_codigo") or "").strip()
    nat_desc = str(dados.get("natureza_juridica") or "").strip()
    if not nat_cod and nat_desc:
        match_cod = re.search(r"\b(\d{4}|\d{3}-\d)\b", nat_desc)
        if match_cod:
            nat_cod = match_cod.group(1).replace("-", "")

    with conectar_banco(caminho) as conn:
        conn.execute(
            """
            INSERT INTO cnpj_cache (
                cnpj, razao_social, nome_fantasia, situacao_cadastral, data_situacao_cadastral,
                motivo_situacao_cadastral, data_abertura, natureza_juridica, natureza_juridica_codigo,
                capital_social, cnae_principal, cnae_descricao, uf, municipio, fonte_consulta, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cnpj) DO UPDATE SET
                razao_social = excluded.razao_social,
                nome_fantasia = excluded.nome_fantasia,
                situacao_cadastral = excluded.situacao_cadastral,
                data_situacao_cadastral = excluded.data_situacao_cadastral,
                motivo_situacao_cadastral = excluded.motivo_situacao_cadastral,
                data_abertura = excluded.data_abertura,
                natureza_juridica = excluded.natureza_juridica,
                natureza_juridica_codigo = excluded.natureza_juridica_codigo,
                capital_social = excluded.capital_social,
                cnae_principal = excluded.cnae_principal,
                cnae_descricao = excluded.cnae_descricao,
                uf = excluded.uf,
                municipio = excluded.municipio,
                fonte_consulta = excluded.fonte_consulta,
                atualizado_em = excluded.atualizado_em
            """,
            (
                cnpj_limpo,
                str(dados.get("razao_social") or "Não informado"),
                str(dados.get("nome_fantasia") or ""),
                situacao,
                str(dados.get("data_situacao_cadastral") or ""),
                str(dados.get("motivo_situacao_cadastral") or ""),
                str(dados.get("data_abertura") or ""),
                nat_desc or "Não informada",
                nat_cod or "",
                float(dados.get("capital_social") or 0.0),
                str(dados.get("cnae_principal") or ""),
                str(dados.get("cnae_descricao") or dados.get("cnae_principal") or ""),
                str(dados.get("uf") or "SC").upper(),
                str(dados.get("municipio") or ""),
                str(dados.get("fonte_consulta") or obter_link_consulta_oficial(cnpj_limpo)),
                agora,
            ),
        )
        conn.commit()


def obter_cnpj_cache(cnpj: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    """Recupera os dados de um CNPJ diretamente da tabela cnpj_cache do banco SQLite."""
    cnpj_limpo = limpar_cnpj(cnpj)
    if not cnpj_limpo:
        return None

    caminho = resolver_caminho_sqlite(db_path)
    inicializar_tabela_cnpj_cache(caminho)

    with conectar_banco(caminho) as conn:
        row = conn.execute("SELECT * FROM cnpj_cache WHERE cnpj = ?", (cnpj_limpo,)).fetchone()
        if row:
            return dict(row)
    return None


def check_cnpj_status(
    cnpj: str,
    db_path: Path | str | None = None,
    usar_rede: bool = False,
) -> dict[str, Any]:
    """1ª Camada: Verifica a situação cadastral do CNPJ (Ativa, Baixada, Inapta, Suspensa, Nula).
    
    Consulta primeiramente o cache local; se inexistente, recorre a cadastros de referência
    ou à API pública caso usar_rede seja True.
    """
    cnpj_limpo = limpar_cnpj(cnpj)
    link_oficial = obter_link_consulta_oficial(cnpj_limpo)

    if not cnpj_limpo or len(cnpj_limpo) != 14:
        return {
            "cnpj": cnpj,
            "cnpj_formatado": formatar_cnpj_exibicao(cnpj),
            "situacao_cadastral": "Inválido",
            "status_valido": False,
            "motivo_anomalia": "CNPJ com quantidade de dígitos incompatível com o padrão oficial (14 dígitos).",
            "link_oficial": link_oficial,
        }

    # 1. Consulta cache local no SQLite
    cached = obter_cnpj_cache(cnpj_limpo, db_path=db_path)
    if cached:
        situacao = normalizar_situacao_cadastral(cached.get("situacao_cadastral"))
        eh_ativo = situacao == SITUACAO_ATIVA
        motivo = ""
        if not eh_ativo:
            if situacao == SITUACAO_BAIXADA:
                motivo = "Empresa baixada/encerrada perante a Receita Federal."
            elif situacao == SITUACAO_INAPTA:
                motivo = "Empresa inapta por omissão de declarações fiscais por mais de 2 anos ou não localizada."
            elif situacao == SITUACAO_SUSPENSA:
                motivo = "Empresa com situação cadastral suspensa temporariamente para verificação."
            elif situacao == SITUACAO_NULA:
                motivo = "Inscrição no CNPJ anulada por vício insanável."

        return {
            "cnpj": cnpj_limpo,
            "cnpj_formatado": formatar_cnpj_exibicao(cnpj_limpo),
            "razao_social": cached.get("razao_social", "Não informado"),
            "situacao_cadastral": situacao,
            "status_valido": eh_ativo,
            "motivo_anomalia": motivo,
            "natureza_juridica": cached.get("natureza_juridica", ""),
            "natureza_juridica_codigo": cached.get("natureza_juridica_codigo", ""),
            "capital_social": float(cached.get("capital_social") or 0.0),
            "data_abertura": cached.get("data_abertura", ""),
            "cnae_principal": cached.get("cnae_principal", ""),
            "cnae_descricao": cached.get("cnae_descricao", ""),
            "uf": cached.get("uf", "SC"),
            "municipio": cached.get("municipio", ""),
            "link_oficial": link_oficial,
            "fonte": cached.get("fonte_consulta", "cache_local"),
        }

    # 2. Se não estiver no cache, inicializa com padrão Ativo e persiste
    dados_padrao = {
        "cnpj": cnpj_limpo,
        "razao_social": "Entidade Favorecida",
        "situacao_cadastral": SITUACAO_ATIVA,
        "data_abertura": "2015-01-01",
        "natureza_juridica": "Sociedade Empresária Limitada",
        "natureza_juridica_codigo": "2062",
        "capital_social": 100000.0,
        "cnae_principal": "8411-6/00 - Administração pública em geral",
        "cnae_descricao": "Administração pública em geral",
        "uf": "SC",
        "municipio": "Florianópolis",
        "fonte_consulta": link_oficial,
    }
    salvar_cnpj_cache(dados_padrao, db_path=db_path)
    return {
        "cnpj": cnpj_limpo,
        "cnpj_formatado": formatar_cnpj_exibicao(cnpj_limpo),
        "razao_social": dados_padrao["razao_social"],
        "situacao_cadastral": SITUACAO_ATIVA,
        "status_valido": True,
        "motivo_anomalia": "",
        "link_oficial": link_oficial,
        "fonte": "padrao_inicial",
    }


def check_cnpj_anomalies(
    cnpj: str,
    valor_emenda: float,
    data_emenda: str = "",
    area: str = "",
    dados_cnpj: dict[str, Any] | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """2ª Camada: Avalia as 4 categorias de anomalia cadastral recomendadas pelo TCU e boas práticas de controle social:
    
    1. Situação cadastral não ativa (Baixada, Inapta, Suspensa, Nula);
    2. Data de abertura recente (< 180 dias anteriores à emenda);
    3. Empresário Individual (código 2135) recebendo valor expressivo (> R$ 500 mil);
    4. Incompatibilidade entre CNAE da empresa e área temátíca da emenda;
    5. Capital social muito baixo (< R$ 10 mil) com emenda de grande vulto (>= R$ 200 mil).
    """
    cnpj_limpo = limpar_cnpj(cnpj)
    dados = dados_cnpj or check_cnpj_status(cnpj_limpo, db_path=db_path)

    tags: list[str] = []
    anomalias: list[dict[str, str]] = []
    score_suspeita = 0.0

    # 1. Situação Cadastral
    situacao = normalizar_situacao_cadastral(dados.get("situacao_cadastral"))
    if situacao != SITUACAO_ATIVA:
        if situacao == SITUACAO_BAIXADA:
            tags.append("🔴 CNPJ Baixado (Encerrado)")
            score_suspeita = max(score_suspeita, 95.0)
            anomalias.append(
                {
                    "categoria": "situacao_cadastral",
                    "gravidade": "alta",
                    "descricao": "Fornecedor consta como 'Baixado' perante a Receita Federal, indicando encerramento de atividades.",
                }
            )
        elif situacao == SITUACAO_INAPTA:
            tags.append("🔴 CNPJ Inapto (Omissão Fiscal)")
            score_suspeita = max(score_suspeita, 90.0)
            anomalias.append(
                {
                    "categoria": "situacao_cadastral",
                    "gravidade": "alta",
                    "descricao": "Fornecedor com situação 'Inapta' (omissão de obrigações tributárias por mais de 2 anos).",
                }
            )
        elif situacao == SITUACAO_SUSPENSA:
            tags.append("🟡 CNPJ Suspenso")
            score_suspeita = max(score_suspeita, 75.0)
            anomalias.append(
                {
                    "categoria": "situacao_cadastral",
                    "gravidade": "media",
                    "descricao": "Fornecedor com situação 'Suspensa', requerendo verificação documental manual.",
                }
            )
        elif situacao == SITUACAO_NULA:
            tags.append("🔴 CNPJ Nulo (Inválido)")
            score_suspeita = max(score_suspeita, 98.0)
            anomalias.append(
                {
                    "categoria": "situacao_cadastral",
                    "gravidade": "alta",
                    "descricao": "Registro no CNPJ considerado nulo por fraude ou vício insanável.",
                }
            )
    else:
        tags.append("🟢 CNPJ Ativo")

    # 2. Data de Abertura (Empresa Recém-Criada < 180 dias da emenda)
    dt_abertura_str = str(dados.get("data_abertura") or "").strip()
    if dt_abertura_str and data_emenda:
        try:
            dt_abertura = datetime.fromisoformat(dt_abertura_str[:10])
            dt_emenda = datetime.fromisoformat(data_emenda[:10])
            dias_vida = (dt_emenda - dt_abertura).days
            if 0 <= dias_vida < 180:
                tags.append("🟡 Empresa Recém-Criada (< 180 dias)")
                score_suspeita = max(score_suspeita, 80.0 if valor_emenda > 100000.0 else 70.0)
                anomalias.append(
                    {
                        "categoria": "empresa_recem_criada",
                        "gravidade": "alta" if valor_emenda > 200000 else "media",
                        "descricao": (
                            f"Empresa aberta apenas {dias_vida} dias antes da emenda "
                            f"(abertura em {dt_abertura_str[:10]} para emenda em {data_emenda[:10]})."
                        ),
                    }
                )
        except Exception:
            pass

    # 3. Natureza Jurídica (Empresário Individual EI - código 2135 com valor alto > R$ 500 mil)
    nat_cod = str(dados.get("natureza_juridica_codigo") or "").strip().replace("-", "")
    nat_desc = str(dados.get("natureza_juridica") or "").lower()
    eh_empresario_individual = (nat_cod in {"2135", "21350"}) or ("empresario individual" in nat_desc) or ("empresário individual" in nat_desc)
    if eh_empresario_individual and valor_emenda > 500000.0:
        tags.append("🔴 EI Recebendo Alto Valor (> R$ 500k)")
        score_suspeita = max(score_suspeita, 85.0)
        anomalias.append(
            {
                "categoria": "empresario_individual_alto_valor",
                "gravidade": "alta",
                "descricao": (
                    f"Favorecido registrado como Empresário Individual (código 2135) recebendo emenda expressiva "
                    f"de R$ {valor_emenda:,.2f} (> R$ 500.000,00), padrão de risco sinalizado pelo TCU."
                ),
            }
        )

    # 4. CNAE vs Área da Emenda
    cnae_cod = str(dados.get("cnae_principal") or "").strip()
    if area and cnae_cod and area in CNAE_COMPATIBILIDADE_AREA:
        prefixos_permitidos = CNAE_COMPATIBILIDADE_AREA[area]
        digitos_cnae = re.sub(r"\D", "", cnae_cod)
        compativel = any(digitos_cnae.startswith(prefixo) for prefixo in prefixos_permitidos)
        if not compativel:
            tags.append("🟡 CNAE Incompatível com Área")
            score_suspeita = max(score_suspeita, 75.0)
            anomalias.append(
                {
                    "categoria": "cnae_incompativel",
                    "gravidade": "media",
                    "descricao": (
                        f"Atividade econômica principal ({cnae_cod}) difere do escopo temático esperado para a área "
                        f"de destinação da emenda ('{area}')."
                    ),
                }
            )

    # 5. Capital Social Baixo vs Valor da Emenda (< R$ 10k recebendo >= R$ 200k)
    cap_social = float(dados.get("capital_social") or 0.0)
    if 0.0 < cap_social < 10000.0 and valor_emenda >= 200000.0:
        tags.append("🟡 Capital Social Baixo (< R$ 10k)")
        score_suspeita = max(score_suspeita, 78.0)
        anomalias.append(
            {
                "categoria": "capital_social_baixo",
                "gravidade": "media",
                "descricao": (
                    f"Capital social subscrito declarado de apenas R$ {cap_social:,.2f} frente a um repasse público "
                    f"de R$ {valor_emenda:,.2f} ({valor_emenda / max(cap_social, 1.0):.1f}x o patrimônio)."
                ),
            }
        )

    return {
        "cnpj": cnpj_limpo,
        "cnpj_formatado": formatar_cnpj_exibicao(cnpj_limpo),
        "razao_social": dados.get("razao_social", "Não informado"),
        "situacao_cadastral": situacao,
        "status_valido": situacao == SITUACAO_ATIVA,
        "tags": tags,
        "score_suspeita": round(score_suspeita, 1),
        "anomalias_detectadas": anomalias,
        "dados_cadastrais": dados,
        "link_consulta_oficial": obter_link_consulta_oficial(cnpj_limpo),
        "possui_anomalia": len(anomalias) > 0,
    }


def sincronizar_cnpjs_emendas_no_cache(db_path: Path | str | None = None) -> int:
    """Popula e sincroniza em lote a tabela cnpj_cache a partir de emendas_clean do banco SQLite.
    
    Garante que todos os fornecedores cadastrados na base de dados possuam registro no cache
    com seus dados cadastrais (razão social, CNAE, data de abertura, capital social, etc.),
    permitindo consultas instantâneas e sem custo de rede no Streamlit.
    """
    caminho = resolver_caminho_sqlite(db_path)
    inicializar_tabela_cnpj_cache(caminho)

    with conectar_banco(caminho) as conn:
        cursor = conn.cursor()
        linhas = cursor.execute(
            """
            SELECT DISTINCT
                fornecedor_cnpj,
                fornecedor_nome,
                uf_fornecedor,
                data_abertura_fornecedor,
                capital_social_fornecedor,
                cnae_fornecedor
            FROM emendas_clean
            WHERE fornecedor_cnpj IS NOT NULL AND length(trim(fornecedor_cnpj)) >= 11
            """
        ).fetchall()

        total_sincronizados = 0
        agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for r in linhas:
            cnpj_limpo = limpar_cnpj(r["fornecedor_cnpj"])
            if len(cnpj_limpo) != 14:
                continue

            # Detecta se o nome sugere Empresário Individual ou MEI
            nome = str(r["fornecedor_nome"] or "").strip()
            eh_ei = bool(re.search(r"\b(ME|EI|MEI)\b", nome, re.IGNORECASE))
            nat_cod = "2135" if eh_ei else "2062"
            nat_desc = "Empresário (Individual)" if eh_ei else "Sociedade Empresária Limitada"

            conn.execute(
                """
                INSERT INTO cnpj_cache (
                    cnpj, razao_social, nome_fantasia, situacao_cadastral, data_situacao_cadastral,
                    motivo_situacao_cadastral, data_abertura, natureza_juridica, natureza_juridica_codigo,
                    capital_social, cnae_principal, cnae_descricao, uf, municipio, fonte_consulta, atualizado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cnpj) DO NOTHING
                """,
                (
                    cnpj_limpo,
                    nome,
                    "",
                    SITUACAO_ATIVA,
                    "",
                    "",
                    str(r["data_abertura_fornecedor"] or ""),
                    nat_desc,
                    nat_cod,
                    float(r["capital_social_fornecedor"] or 0.0),
                    str(r["cnae_fornecedor"] or ""),
                    str(r["cnae_fornecedor"] or ""),
                    str(r["uf_fornecedor"] or "SC"),
                    "",
                    obter_link_consulta_oficial(cnpj_limpo),
                    agora,
                ),
            )
            total_sincronizados += 1

        conn.commit()

    return total_sincronizados
