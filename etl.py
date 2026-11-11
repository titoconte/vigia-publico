"""Fase 2 — Pipeline ETL de limpeza, normalização, cruzamento com IBGE/CNPJ e geração de tabelas agregadas."""

from __future__ import annotations

from pathlib import Path
import re
import unicodedata
from typing import Any

import pandas as pd

from collect_tce import DEFAULT_RAW_DIR, executar_coleta_completa
from database import DEFAULT_DB_PATH, conectar_banco, inicializar_schema
from enrich_cnpj import DEFAULT_ENRICHED_DIR, enriquecer_cnpj, enriquecer_lote_cnpjs, limpar_cnpj

DEFAULT_CLEAN_DIR = Path("data/clean")


def normalizar_municipio(nome: str | None) -> str:
    """Remove acentos, espaços excedentes e padroniza o nome do município em letras maiúsculas."""
    if not nome:
        return ""
    texto = str(nome).strip()
    sem_acentos = "".join(
        ch for ch in unicodedata.normalize("NFD", texto) if unicodedata.category(ch) != "Mn"
    )
    return " ".join(sem_acentos.upper().split())


def calcular_valor_per_capita(valor: float | int | None, populacao: int | float | None) -> float:
    """Calcula o valor per capita da emenda (valor_emenda / populacao) tratando divisões por zero com segurança."""
    if valor is None or populacao is None:
        return 0.0
    try:
        val_float = float(valor)
        pop_float = float(populacao)
    except (TypeError, ValueError):
        return 0.0
    if pop_float <= 0:
        return 0.0
    return round(val_float / pop_float, 4)


def localizar_arquivo_emendas_recente(raw_dir: Path, usar_rede: bool | None = None) -> Path:
    """Localiza o arquivo emendas_YYYYMMDD.csv mais recente na pasta data/raw (ou executa a coleta se vazio)."""
    arquivos = sorted(p for p in raw_dir.glob("emendas_*.csv") if re.match(r"^emendas_\d{8}\.csv$", p.name))
    if not arquivos:
        arquivos = sorted(raw_dir.glob("emendas_*.csv"))
    if not arquivos:
        executar_coleta_completa(raw_dir=raw_dir, usar_rede=usar_rede)
        arquivos = sorted(p for p in raw_dir.glob("emendas_*.csv") if re.match(r"^emendas_\d{8}\.csv$", p.name))
    return arquivos[-1]


def construir_agregados_parlamentar(df_clean: pd.DataFrame) -> pd.DataFrame:
    """Gera a tabela agregada por parlamentar com totais, média, área principal e concentração de fornecedor."""
    registros: list[dict[str, Any]] = []
    for parlamentar, grupo in df_clean.groupby("parlamentar", dropna=False):
        total = float(grupo["valor"].sum())
        qtd = int(len(grupo))
        media = round(total / qtd, 2) if qtd > 0 else 0.0
        partido = str(grupo["partido"].iloc[0]) if "partido" in grupo.columns else ""

        por_area = grupo.groupby("area")["valor"].sum().sort_values(ascending=False)
        principal_area = str(por_area.index[0]) if not por_area.empty else "Não informada"

        por_forn = (
            grupo.groupby(["fornecedor_cnpj", "fornecedor_nome"])["valor"]
            .sum()
            .reset_index()
            .sort_values("valor", ascending=False)
        )
        if not por_forn.empty and total > 0:
            maior_forn_nome = str(por_forn.iloc[0]["fornecedor_nome"])
            maior_forn_cnpj = str(por_forn.iloc[0]["fornecedor_cnpj"])
            perc_maior = round((float(por_forn.iloc[0]["valor"]) / total) * 100.0, 2)
        else:
            maior_forn_nome = ""
            maior_forn_cnpj = ""
            perc_maior = 0.0

        registros.append(
            {
                "parlamentar": str(parlamentar),
                "partido": partido,
                "total_emendas": round(total, 2),
                "quantidade_emendas": qtd,
                "media_valor": media,
                "principal_area": principal_area,
                "principal_fornecedor": maior_forn_nome,
                "principal_fornecedor_cnpj": maior_forn_cnpj,
                "percentual_maior_fornecedor": perc_maior,
            }
        )
    return pd.DataFrame(registros).sort_values("total_emendas", ascending=False).reset_index(drop=True)


def construir_agregados_municipio(df_clean: pd.DataFrame, df_pop: pd.DataFrame) -> pd.DataFrame:
    """Gera a tabela agregada por município incluindo população IBGE, total recebido e valor per capita."""
    agrupado = (
        df_clean.groupby(["codigo_ibge", "municipio", "municipio_normalizado", "populacao"], as_index=False)
        .agg(
            total_recebido=("valor", "sum"),
            quantidade_emendas=("id_emenda", "count"),
        )
    )
    agrupado["total_recebido"] = agrupado["total_recebido"].round(2)
    agrupado["valor_per_capita"] = agrupado.apply(
        lambda r: calcular_valor_per_capita(r["total_recebido"], r["populacao"]),
        axis=1,
    )

    codigos_com_emenda = set(agrupado["codigo_ibge"].astype(str))
    extras: list[dict[str, Any]] = []
    for _, row in df_pop.iterrows():
        cod = str(row["codigo_ibge"])
        if cod not in codigos_com_emenda:
            extras.append(
                {
                    "codigo_ibge": cod,
                    "municipio": str(row["municipio"]),
                    "municipio_normalizado": normalizar_municipio(str(row["municipio"])),
                    "populacao": int(row["populacao"]),
                    "total_recebido": 0.0,
                    "quantidade_emendas": 0,
                    "valor_per_capita": 0.0,
                }
            )
    if extras:
        agrupado = pd.concat([agrupado, pd.DataFrame(extras)], ignore_index=True)

    return agrupado.sort_values("total_recebido", ascending=False).reset_index(drop=True)


def construir_agregados_fornecedor(df_clean: pd.DataFrame) -> pd.DataFrame:
    """Gera a tabela agregada por fornecedor/entidade beneficiária com dados da Receita Federal e totais."""
    agrupado = (
        df_clean.groupby(
            [
                "fornecedor_cnpj",
                "fornecedor_nome",
                "uf_fornecedor",
                "data_abertura_fornecedor",
                "capital_social_fornecedor",
                "cnae_fornecedor",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            total_recebido=("valor", "sum"),
            quantidade_emendas=("id_emenda", "count"),
            parlamentares_distintos=("parlamentar", "nunique"),
        )
        .rename(
            columns={
                "data_abertura_fornecedor": "data_abertura",
                "capital_social_fornecedor": "capital_social",
                "cnae_fornecedor": "cnae_principal",
            }
        )
    )
    agrupado["total_recebido"] = agrupado["total_recebido"].round(2)
    return agrupado.sort_values("total_recebido", ascending=False).reset_index(drop=True)


def executar_etl(
    raw_dir: Path | str = DEFAULT_RAW_DIR,
    enriched_dir: Path | str = DEFAULT_ENRICHED_DIR,
    clean_dir: Path | str = DEFAULT_CLEAN_DIR,
    db_path: Path | str = DEFAULT_DB_PATH,
    usar_rede: bool | None = None,
) -> dict[str, pd.DataFrame]:
    """Executa o pipeline ETL completo: normaliza municípios, faz join com IBGE/CNPJ, calcula agregados e salva no banco."""
    pasta_raw = Path(raw_dir)
    pasta_enriched = Path(enriched_dir)
    pasta_clean = Path(clean_dir)
    pasta_clean.mkdir(parents=True, exist_ok=True)

    arquivo_emendas = localizar_arquivo_emendas_recente(pasta_raw, usar_rede=usar_rede)
    arquivo_pop = pasta_raw / "populacao_ibge.csv"
    if not arquivo_pop.exists():
        executar_coleta_completa(raw_dir=pasta_raw, usar_rede=usar_rede)

    df_emendas = pd.read_csv(arquivo_emendas, dtype={"fornecedor_cnpj": str, "codigo_ibge": str})
    df_pop = pd.read_csv(arquivo_pop, dtype={"codigo_ibge": str})

    df_emendas["municipio_normalizado"] = df_emendas["municipio"].apply(normalizar_municipio)
    df_pop["municipio_normalizado"] = df_pop["municipio"].apply(normalizar_municipio)

    mapa_pop_por_ibge = dict(zip(df_pop["codigo_ibge"].astype(str), df_pop["populacao"].astype(int)))
    mapa_pop_por_nome = dict(zip(df_pop["municipio_normalizado"], df_pop["populacao"].astype(int)))
    mapa_ibge_por_nome = dict(zip(df_pop["municipio_normalizado"], df_pop["codigo_ibge"].astype(str)))

    populacoes: list[int] = []
    codigos_ibge: list[str] = []
    for _, row in df_emendas.iterrows():
        cod = str(row.get("codigo_ibge") or "").strip()
        mun_norm = str(row["municipio_normalizado"])
        if not cod or cod not in mapa_pop_por_ibge:
            cod = mapa_ibge_por_nome.get(mun_norm, cod or "4200000")
        pop = mapa_pop_por_ibge.get(cod) or mapa_pop_por_nome.get(mun_norm) or 50000
        codigos_ibge.append(cod)
        populacoes.append(int(pop))

    df_emendas["codigo_ibge"] = codigos_ibge
    df_emendas["populacao"] = populacoes
    df_emendas["valor"] = df_emendas["valor"].astype(float).round(2)
    df_emendas["valor_per_capita"] = [
        calcular_valor_per_capita(v, p) for v, p in zip(df_emendas["valor"], df_emendas["populacao"])
    ]
    df_emendas["ano_mes"] = df_emendas["data"].astype(str).str.slice(0, 7)

    # Pré-enriquece CNPJs únicos em lote caso ainda não estejam no cache local
    cnpjs_unicos = df_emendas["fornecedor_cnpj"].dropna().astype(str).unique().tolist()
    enriquecer_lote_cnpjs(cnpjs_unicos, output_dir=pasta_enriched, usar_rede=usar_rede)

    datas_abertura: list[str] = []
    capitais_sociais: list[float] = []
    cnaes: list[str] = []
    ufs_forn: list[str] = []
    cnpjs_limpos: list[str] = []

    for _, row in df_emendas.iterrows():
        cnpj_limpo = limpar_cnpj(str(row["fornecedor_cnpj"]))
        nome_forn = str(row.get("fornecedor_nome") or "").strip()
        info_cnpj = enriquecer_cnpj(
            cnpj_limpo,
            output_dir=pasta_enriched,
            usar_rede=usar_rede,
            nome_fallback=nome_forn,
        )
        cnpjs_limpos.append(cnpj_limpo)
        datas_abertura.append(str(info_cnpj.get("data_abertura") or ""))
        capitais_sociais.append(float(info_cnpj.get("capital_social") or 0.0))
        cnaes.append(str(info_cnpj.get("cnae_principal") or "Não informado"))
        uf_row = str(row.get("uf_fornecedor") or "").strip().upper()
        uf_receita = str(info_cnpj.get("uf") or "").strip().upper()
        if uf_row and uf_row != "SC":
            ufs_forn.append(uf_row)
        elif uf_receita:
            ufs_forn.append(uf_receita)
        else:
            ufs_forn.append(uf_row or "SC")

    df_emendas["fornecedor_cnpj"] = cnpjs_limpos
    df_emendas["uf_fornecedor"] = ufs_forn
    df_emendas["data_abertura_fornecedor"] = datas_abertura
    df_emendas["capital_social_fornecedor"] = capitais_sociais
    df_emendas["cnae_fornecedor"] = cnaes

    colunas_clean = [
        "id_emenda",
        "parlamentar",
        "partido",
        "valor",
        "municipio",
        "municipio_normalizado",
        "codigo_ibge",
        "populacao",
        "valor_per_capita",
        "entidade_beneficiaria",
        "area",
        "data",
        "ano_mes",
        "fornecedor_nome",
        "fornecedor_cnpj",
        "uf_fornecedor",
        "data_abertura_fornecedor",
        "capital_social_fornecedor",
        "cnae_fornecedor",
        "status_execucao",
        "fonte_url",
    ]
    df_clean = df_emendas[colunas_clean].copy()

    df_parlamentares = construir_agregados_parlamentar(df_clean)
    df_municipios = construir_agregados_municipio(df_clean, df_pop)
    df_fornecedores = construir_agregados_fornecedor(df_clean)

    df_clean.to_csv(pasta_clean / "emendas_clean.csv", index=False, encoding="utf-8")
    df_parlamentares.to_csv(pasta_clean / "agregados_parlamentar.csv", index=False, encoding="utf-8")
    df_municipios.to_csv(pasta_clean / "agregados_municipio.csv", index=False, encoding="utf-8")
    df_fornecedores.to_csv(pasta_clean / "agregados_fornecedor.csv", index=False, encoding="utf-8")

    inicializar_schema(db_path=db_path)
    with conectar_banco(db_path=db_path) as conn:
        conn.execute("DELETE FROM emendas_clean")
        conn.execute("DELETE FROM agregados_parlamentar")
        conn.execute("DELETE FROM agregados_municipio")
        conn.execute("DELETE FROM agregados_fornecedor")
        df_clean.to_sql("emendas_clean", conn, if_exists="append", index=False)
        df_parlamentares.to_sql("agregados_parlamentar", conn, if_exists="append", index=False)
        df_municipios.to_sql("agregados_municipio", conn, if_exists="append", index=False)
        df_fornecedores.to_sql("agregados_fornecedor", conn, if_exists="append", index=False)
        conn.commit()
    # Recria os índices definidos em schema.sql caso o to_sql tenha alterado metadados
    inicializar_schema(db_path=db_path)

    return {
        "emendas_clean": df_clean,
        "agregados_parlamentar": df_parlamentares,
        "agregados_municipio": df_municipios,
        "agregados_fornecedor": df_fornecedores,
    }


if __name__ == "__main__":
    tabelas = executar_etl()
    print(
        f"ETL Fase 2 concluído: {len(tabelas['emendas_clean'])} emendas limpas, "
        f"{len(tabelas['agregados_parlamentar'])} parlamentares, "
        f"{len(tabelas['agregados_municipio'])} municípios, "
        f"{len(tabelas['agregados_fornecedor'])} fornecedores."
    )
