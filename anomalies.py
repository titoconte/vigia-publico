"""Fase 3 — Motor de Anomalias Auditável do Vigia Público SC (7 regras estatísticas e cadastrais)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from database import DEFAULT_DB_PATH, conectar_banco, inicializar_schema

NOTA_ETICA_PADRAO = (
    "Padrão estatístico/cadastral que merece verificação e análise documental. "
    "Não constitui prova de irregularidade."
)


def gerar_hash_auditoria(payload: dict[str, Any]) -> str:
    """Gera uma assinatura criptográfica SHA-256 determinística para garantir rastreabilidade do alerta."""
    serializado = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def _limitar_pontuacao(valor: float) -> float:
    """Garante que a pontuação da anomalia fique estritamente no intervalo [0.0, 100.0]."""
    return round(float(max(0.0, min(100.0, valor))), 1)


def _montar_registro_alerta(
    *,
    tipo: str,
    regra: str,
    pontuacao: float,
    parlamentar: str,
    municipio: str,
    codigo_ibge: str,
    valor: float,
    beneficiario: str,
    fornecedor_cnpj: str,
    justificativa: str,
    dados_contexto: dict[str, Any],
    fonte_url: str,
    data_deteccao: str | None = None,
) -> dict[str, Any]:
    """Padroniza o dicionário de um alerta com justificativa ética, contexto JSON e hash SHA-256."""
    momento = data_deteccao or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    justificativa_completa = f"{justificativa.strip()} ({NOTA_ETICA_PADRAO})"
    base_hash = {
        "regra": regra,
        "parlamentar": parlamentar,
        "municipio": municipio,
        "valor": round(float(valor), 2),
        "beneficiario": beneficiario,
        "fornecedor_cnpj": fornecedor_cnpj,
        "justificativa": justificativa_completa,
    }
    return {
        "tipo": tipo,
        "regra": regra,
        "pontuacao": _limitar_pontuacao(pontuacao),
        "parlamentar": parlamentar,
        "municipio": municipio,
        "codigo_ibge": str(codigo_ibge or ""),
        "valor": round(float(valor), 2),
        "beneficiario": beneficiario,
        "fornecedor_cnpj": str(fornecedor_cnpj or ""),
        "justificativa": justificativa_completa,
        "dados_contexto": json.dumps(dados_contexto, ensure_ascii=False),
        "fonte_url": fonte_url,
        "hash_auditoria": gerar_hash_auditoria(base_hash),
        "data_deteccao": momento,
    }


def regra_valor_absoluto_alto(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Regra 1: Detecta emendas individuais com valor absoluto acima do percentil 95 do conjunto."""
    if df.empty:
        return []
    p95 = float(np.percentile(df["valor"].astype(float), 95))
    max_val = float(df["valor"].max())
    alertas: list[dict[str, Any]] = []

    acima = df[df["valor"] > p95]
    for _, row in acima.iterrows():
        valor = float(row["valor"])
        razao = (valor - p95) / max(p95, 1.0)
        score = 75.0 + min(25.0, razao * 10.0)
        justificativa = (
            f"Emenda individual de R$ {valor:,.2f} destinada a {row['municipio']} situa-se acima do "
            f"percentil 95 do conjunto analisado (limiar P95 = R$ {p95:,.2f})."
        )
        alertas.append(
            _montar_registro_alerta(
                tipo="Valor Absoluto Alto",
                regra="REGRA_1_VALOR_ABSOLUTO_P95",
                pontuacao=score,
                parlamentar=str(row["parlamentar"]),
                municipio=str(row["municipio"]),
                codigo_ibge=str(row["codigo_ibge"]),
                valor=valor,
                beneficiario=str(row["entidade_beneficiaria"]),
                fornecedor_cnpj=str(row["fornecedor_cnpj"]),
                justificativa=justificativa,
                dados_contexto={
                    "id_emenda": str(row["id_emenda"]),
                    "valor_emenda": valor,
                    "percentil_95": round(p95, 2),
                    "maior_valor_conjunto": round(max_val, 2),
                    "multiplo_sobre_p95": round(valor / max(p95, 1.0), 2),
                },
                fonte_url=str(row["fonte_url"]),
            )
        )
    return alertas


def regra_valor_per_capita_alto(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Regra 2: Detecta emendas com valor_per_capita acima da média estadual + 2 desvios padrão."""
    if df.empty or "valor_per_capita" not in df.columns:
        return []
    serie = df["valor_per_capita"].astype(float)
    media = float(serie.mean())
    desvio = float(serie.std(ddof=0))
    limiar = media + (2.0 * desvio)
    if desvio <= 0:
        return []

    alertas: list[dict[str, Any]] = []
    acima = df[serie > limiar]
    for _, row in acima.iterrows():
        vpc = float(row["valor_per_capita"])
        z_score = (vpc - media) / desvio
        score = 70.0 + min(30.0, (z_score - 2.0) * 12.0)
        justificativa = (
            f"O valor per capita de R$ {vpc:,.2f}/hab em {row['municipio']} "
            f"(população: {int(row['populacao']):,} hab.) supera a média estadual mais 2 desvios padrão "
            f"(limiar = R$ {limiar:,.2f}/hab; Z-score = {z_score:.2f})."
        )
        alertas.append(
            _montar_registro_alerta(
                tipo="Valor Per Capita Alto",
                regra="REGRA_2_PER_CAPITA_ACIMA_2DP",
                pontuacao=score,
                parlamentar=str(row["parlamentar"]),
                municipio=str(row["municipio"]),
                codigo_ibge=str(row["codigo_ibge"]),
                valor=float(row["valor"]),
                beneficiario=str(row["entidade_beneficiaria"]),
                fornecedor_cnpj=str(row["fornecedor_cnpj"]),
                justificativa=justificativa,
                dados_contexto={
                    "id_emenda": str(row["id_emenda"]),
                    "populacao_municipio": int(row["populacao"]),
                    "valor_per_capita": round(vpc, 2),
                    "media_estadual_per_capita": round(media, 2),
                    "desvio_padrao_per_capita": round(desvio, 2),
                    "limiar_media_mais_2dp": round(limiar, 2),
                    "z_score": round(z_score, 2),
                },
                fonte_url=str(row["fonte_url"]),
            )
        )
    return alertas


def regra_concentracao_fornecedor(
    df: pd.DataFrame,
    limiar_percentual: float = 80.0,
    valor_minimo_relevante: float = 500000.0,
) -> list[dict[str, Any]]:
    """Regra 3: Detecta quando um parlamentar destina >80% do seu total a um único fornecedor/entidade."""
    if df.empty:
        return []
    alertas: list[dict[str, Any]] = []

    for parlamentar, grupo in df.groupby("parlamentar"):
        total_parlamentar = float(grupo["valor"].sum())
        if total_parlamentar < valor_minimo_relevante or len(grupo) < 2:
            continue

        por_forn = (
            grupo.groupby(["fornecedor_cnpj", "fornecedor_nome"], as_index=False)
            .agg(
                valor_fornecedor=("valor", "sum"),
                qtd_emendas=("id_emenda", "count"),
                municipio_exemplo=("municipio", "first"),
                codigo_ibge_exemplo=("codigo_ibge", "first"),
                fonte_exemplo=("fonte_url", "first"),
            )
            .sort_values("valor_fornecedor", ascending=False)
        )
        topo = por_forn.iloc[0]
        valor_forn = float(topo["valor_fornecedor"])
        perc = (valor_forn / total_parlamentar) * 100.0

        if perc > limiar_percentual and valor_forn >= valor_minimo_relevante:
            score = 75.0 + min(25.0, (perc - limiar_percentual) * 1.25)
            justificativa = (
                f"{parlamentar} direcionou {perc:.1f}% do total de suas emendas (R$ {valor_forn:,.2f} de "
                f"R$ {total_parlamentar:,.2f}) para um único fornecedor/entidade: "
                f"{topo['fornecedor_nome']} (CNPJ {topo['fornecedor_cnpj']})."
            )
            alertas.append(
                _montar_registro_alerta(
                    tipo="Concentração de Fornecedor",
                    regra="REGRA_3_CONCENTRACAO_FORNECEDOR_80",
                    pontuacao=score,
                    parlamentar=str(parlamentar),
                    municipio=str(topo["municipio_exemplo"]),
                    codigo_ibge=str(topo["codigo_ibge_exemplo"]),
                    valor=valor_forn,
                    beneficiario=str(topo["fornecedor_nome"]),
                    fornecedor_cnpj=str(topo["fornecedor_cnpj"]),
                    justificativa=justificativa,
                    dados_contexto={
                        "total_parlamentar": round(total_parlamentar, 2),
                        "valor_no_fornecedor": round(valor_forn, 2),
                        "percentual_concentrado": round(perc, 2),
                        "quantidade_emendas_fornecedor": int(topo["qtd_emendas"]),
                        "limiar_percentual": limiar_percentual,
                    },
                    fonte_url=str(topo["fonte_exemplo"]),
                )
            )
    return alertas


def regra_concentracao_temporal(
    df: pd.DataFrame,
    limiar_percentual_mes: float = 70.0,
    valor_minimo_anual: float = 500000.0,
) -> list[dict[str, Any]]:
    """Regra 4: Detecta quando um parlamentar destina >70% do seu valor anual em um único mês."""
    if df.empty:
        return []
    df_temp = df.copy()
    if "ano_mes" not in df_temp.columns:
        df_temp["ano_mes"] = df_temp["data"].astype(str).str.slice(0, 7)

    alertas: list[dict[str, Any]] = []
    for parlamentar, grupo in df_temp.groupby("parlamentar"):
        total_anual = float(grupo["valor"].sum())
        if total_anual < valor_minimo_anual or len(grupo) < 2:
            continue

        por_mes = (
            grupo.groupby("ano_mes", as_index=False)
            .agg(
                valor_mes=("valor", "sum"),
                qtd_mes=("id_emenda", "count"),
                municipio_exemplo=("municipio", "first"),
                codigo_ibge_exemplo=("codigo_ibge", "first"),
                beneficiario_exemplo=("entidade_beneficiaria", "first"),
                cnpj_exemplo=("fornecedor_cnpj", "first"),
                fonte_exemplo=("fonte_url", "first"),
            )
            .sort_values("valor_mes", ascending=False)
        )
        topo = por_mes.iloc[0]
        valor_mes = float(topo["valor_mes"])
        perc_mes = (valor_mes / total_anual) * 100.0

        if perc_mes > limiar_percentual_mes:
            score = 65.0 + min(30.0, (perc_mes - limiar_percentual_mes) * 1.0)
            justificativa = (
                f"{parlamentar} concentrou {perc_mes:.1f}% do valor anual de suas emendas "
                f"(R$ {valor_mes:,.2f} de R$ {total_anual:,.2f}) em um único mês ({topo['ano_mes']})."
            )
            alertas.append(
                _montar_registro_alerta(
                    tipo="Concentração Temporal",
                    regra="REGRA_4_CONCENTRACAO_TEMPORAL_70",
                    pontuacao=score,
                    parlamentar=str(parlamentar),
                    municipio=str(topo["municipio_exemplo"]),
                    codigo_ibge=str(topo["codigo_ibge_exemplo"]),
                    valor=valor_mes,
                    beneficiario=str(topo["beneficiario_exemplo"]),
                    fornecedor_cnpj=str(topo["cnpj_exemplo"]),
                    justificativa=justificativa,
                    dados_contexto={
                        "mes_concentracao": str(topo["ano_mes"]),
                        "valor_no_mes": round(valor_mes, 2),
                        "total_anual_parlamentar": round(total_anual, 2),
                        "percentual_no_mes": round(perc_mes, 2),
                        "quantidade_emendas_no_mes": int(topo["qtd_mes"]),
                    },
                    fonte_url=str(topo["fonte_exemplo"]),
                )
            )
    return alertas


def regra_beneficiario_recem_criado(df: pd.DataFrame, meses_limite: int = 12) -> list[dict[str, Any]]:
    """Regra 5: Detecta entidade beneficiária/fornecedor com CNPJ aberto há menos de 12 meses da data da emenda."""
    if df.empty or "data_abertura_fornecedor" not in df.columns:
        return []

    alertas: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        try:
            dt_emenda = pd.to_datetime(str(row["data"]), errors="coerce")
            dt_abertura = pd.to_datetime(str(row["data_abertura_fornecedor"]), errors="coerce")
        except Exception:
            continue
        if pd.isna(dt_emenda) or pd.isna(dt_abertura):
            continue

        dias_existencia = int((dt_emenda - dt_abertura).days)
        meses_existencia = round(dias_existencia / 30.44, 1)
        if 0 <= dias_existencia < (meses_limite * 30.5):
            score = 80.0 + min(20.0, max(0.0, (12.0 - meses_existencia) * 1.6))
            justificativa = (
                f"O beneficiário/fornecedor {row['fornecedor_nome']} (CNPJ {row['fornecedor_cnpj']}) "
                f"possuía {meses_existencia:.1f} meses de abertura cadastral (aberto em "
                f"{row['data_abertura_fornecedor']}) quando recebeu emenda de R$ {float(row['valor']):,.2f} "
                f"em {row['data']}."
            )
            alertas.append(
                _montar_registro_alerta(
                    tipo="Beneficiário Recém-Criado",
                    regra="REGRA_5_CNPJ_RECEM_CRIADO_12M",
                    pontuacao=score,
                    parlamentar=str(row["parlamentar"]),
                    municipio=str(row["municipio"]),
                    codigo_ibge=str(row["codigo_ibge"]),
                    valor=float(row["valor"]),
                    beneficiario=str(row["fornecedor_nome"]),
                    fornecedor_cnpj=str(row["fornecedor_cnpj"]),
                    justificativa=justificativa,
                    dados_contexto={
                        "id_emenda": str(row["id_emenda"]),
                        "data_abertura_cnpj": str(row["data_abertura_fornecedor"]),
                        "data_emenda": str(row["data"]),
                        "dias_entre_abertura_e_emenda": dias_existencia,
                        "meses_entre_abertura_e_emenda": meses_existencia,
                    },
                    fonte_url=str(row["fonte_url"]),
                )
            )
    return alertas


def regra_capital_social_baixo(
    df: pd.DataFrame,
    teto_capital_social: float = 10000.0,
    valor_minimo_emenda: float = 200000.0,
) -> list[dict[str, Any]]:
    """Regra 6: Detecta fornecedor com capital social < R$ 10.000 recebendo emenda de valor alto."""
    if df.empty or "capital_social_fornecedor" not in df.columns:
        return []

    alertas: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        capital = float(row.get("capital_social_fornecedor") or 0.0)
        valor = float(row.get("valor") or 0.0)
        if 0 < capital < teto_capital_social and valor >= valor_minimo_emenda:
            proporcao = valor / max(capital, 1.0)
            score = 75.0 + min(25.0, np.log10(max(proporcao, 1.0)) * 8.0)
            justificativa = (
                f"A empresa {row['fornecedor_nome']} (CNPJ {row['fornecedor_cnpj']}) possui capital social "
                f"declarado de R$ {capital:,.2f} (< R$ {teto_capital_social:,.2f}) e foi vinculada a "
                f"emenda de R$ {valor:,.2f} ({proporcao:.0f}x o capital social)."
            )
            alertas.append(
                _montar_registro_alerta(
                    tipo="Capital Social Baixo",
                    regra="REGRA_6_CAPITAL_SOCIAL_BAIXO",
                    pontuacao=score,
                    parlamentar=str(row["parlamentar"]),
                    municipio=str(row["municipio"]),
                    codigo_ibge=str(row["codigo_ibge"]),
                    valor=valor,
                    beneficiario=str(row["fornecedor_nome"]),
                    fornecedor_cnpj=str(row["fornecedor_cnpj"]),
                    justificativa=justificativa,
                    dados_contexto={
                        "id_emenda": str(row["id_emenda"]),
                        "capital_social": round(capital, 2),
                        "valor_emenda": round(valor, 2),
                        "razao_emenda_sobre_capital": round(proporcao, 2),
                    },
                    fonte_url=str(row["fonte_url"]),
                )
            )
    return alertas


def regra_discrepancia_geografica(df: pd.DataFrame, uf_esperada: str = "SC") -> list[dict[str, Any]]:
    """Regra 7: Detecta fornecedor sediado em outro estado recebendo emenda destinada a município de SC."""
    if df.empty or "uf_fornecedor" not in df.columns:
        return []

    alertas: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        uf = str(row.get("uf_fornecedor") or "").strip().upper()
        if uf and uf != uf_esperada.upper():
            valor = float(row["valor"])
            score = 70.0 + min(25.0, (valor / 1000000.0) * 10.0)
            justificativa = (
                f"Fornecedor {row['fornecedor_nome']} (CNPJ {row['fornecedor_cnpj']}) sediado fora de SC "
                f"(UF: {uf}) recebeu recursos de emenda parlamentar estadual (R$ {valor:,.2f}) "
                f"destinada ao município catarinense de {row['municipio']}."
            )
            alertas.append(
                _montar_registro_alerta(
                    tipo="Discrepância Geográfica",
                    regra="REGRA_7_DISCREPANCIA_GEOGRAFICA_UF",
                    pontuacao=score,
                    parlamentar=str(row["parlamentar"]),
                    municipio=str(row["municipio"]),
                    codigo_ibge=str(row["codigo_ibge"]),
                    valor=valor,
                    beneficiario=str(row["fornecedor_nome"]),
                    fornecedor_cnpj=str(row["fornecedor_cnpj"]),
                    justificativa=justificativa,
                    dados_contexto={
                        "id_emenda": str(row["id_emenda"]),
                        "uf_fornecedor": uf,
                        "uf_destino": uf_esperada.upper(),
                        "municipio_destino": str(row["municipio"]),
                        "valor_emenda": round(valor, 2),
                    },
                    fonte_url=str(row["fonte_url"]),
                )
            )
    return alertas


def executar_motor_anomalias(db_path: Path | str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """Executa todas as 7 regras de anomalia sobre emendas_clean, persiste na tabela alertas e retorna ordenado."""
    inicializar_schema(db_path=db_path)
    with conectar_banco(db_path=db_path) as conn:
        df_clean = pd.read_sql_query("SELECT * FROM emendas_clean", conn)

    todos_alertas: list[dict[str, Any]] = []
    regras = (
        regra_valor_absoluto_alto,
        regra_valor_per_capita_alto,
        regra_concentracao_fornecedor,
        regra_concentracao_temporal,
        regra_beneficiario_recem_criado,
        regra_capital_social_baixo,
        regra_discrepancia_geografica,
    )
    for funcao_regra in regras:
        todos_alertas.extend(funcao_regra(df_clean))

    todos_alertas.sort(key=lambda item: item["pontuacao"], reverse=True)

    with conectar_banco(db_path=db_path) as conn:
        feedbacks_existentes = {
            row["hash_auditoria"]: (int(row["util_count"]), int(row["falso_positivo_count"]))
            for row in conn.execute(
                "SELECT hash_auditoria, util_count, falso_positivo_count FROM alertas"
            ).fetchall()
        }
        conn.execute("DELETE FROM alertas")
        for idx, alerta in enumerate(todos_alertas, start=1):
            util_c, fp_c = feedbacks_existentes.get(alerta["hash_auditoria"], (0, 0))
            alerta["id"] = idx
            alerta["util_count"] = util_c
            alerta["falso_positivo_count"] = fp_c
            conn.execute(
                """
                INSERT INTO alertas (
                    id, tipo, regra, pontuacao, parlamentar, municipio, codigo_ibge,
                    valor, beneficiario, fornecedor_cnpj, justificativa, dados_contexto,
                    fonte_url, hash_auditoria, data_deteccao, util_count, falso_positivo_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alerta["id"],
                    alerta["tipo"],
                    alerta["regra"],
                    alerta["pontuacao"],
                    alerta["parlamentar"],
                    alerta["municipio"],
                    alerta["codigo_ibge"],
                    alerta["valor"],
                    alerta["beneficiario"],
                    alerta["fornecedor_cnpj"],
                    alerta["justificativa"],
                    alerta["dados_contexto"],
                    alerta["fonte_url"],
                    alerta["hash_auditoria"],
                    alerta["data_deteccao"],
                    alerta["util_count"],
                    alerta["falso_positivo_count"],
                ),
            )
        conn.commit()

    return todos_alertas


if __name__ == "__main__":
    detectados = executar_motor_anomalias()
    print(f"Motor de Anomalias Fase 3 concluído: {len(detectados)} alertas gerados.")
    for item in detectados[:5]:
        print(f" - [{item['pontuacao']} pts] {item['tipo']} | {item['parlamentar']} | R$ {item['valor']:,.2f}")
