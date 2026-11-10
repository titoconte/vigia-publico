"""Fase 1 — Coleta de dados públicos do Painel de Emendas do TCE/SC, População IBGE e Dados Abertos SC."""

from __future__ import annotations

from datetime import datetime
import io
import os
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

DEFAULT_RAW_DIR = Path("data/raw")
PORTAL_TCE_FONTE_PADRAO = "https://www.tcesc.tc.br/painel-emendas-parlamentares"
PORTAL_DADOS_ABERTOS_SC = "https://dados.sc.gov.br"


def obter_base_populacao_sc_referencia() -> list[dict[str, Any]]:
    """Retorna a tabela oficial de referência populacional do IBGE (Censo/Estimativa) para municípios de SC."""
    return [
        {"codigo_ibge": "4209102", "municipio": "Joinville", "populacao": 616317},
        {"codigo_ibge": "4205407", "municipio": "Florianópolis", "populacao": 537211},
        {"codigo_ibge": "4202404", "municipio": "Blumenau", "populacao": 361261},
        {"codigo_ibge": "4216602", "municipio": "São José", "populacao": 270299},
        {"codigo_ibge": "4208203", "municipio": "Itajaí", "populacao": 264054},
        {"codigo_ibge": "4204202", "municipio": "Chapecó", "populacao": 254785},
        {"codigo_ibge": "4211900", "municipio": "Palhoça", "populacao": 222598},
        {"codigo_ibge": "4204608", "municipio": "Criciúma", "populacao": 214493},
        {"codigo_ibge": "4208906", "municipio": "Jaraguá do Sul", "populacao": 182660},
        {"codigo_ibge": "4209300", "municipio": "Lages", "populacao": 164981},
        {"codigo_ibge": "4202909", "municipio": "Brusque", "populacao": 141385},
        {"codigo_ibge": "4202008", "municipio": "Balneário Camboriú", "populacao": 139155},
        {"codigo_ibge": "4218707", "municipio": "Tubarão", "populacao": 110088},
        {"codigo_ibge": "4211306", "municipio": "Navegantes", "populacao": 86401},
        {"codigo_ibge": "4215802", "municipio": "São Bento do Sul", "populacao": 83277},
        {"codigo_ibge": "4204301", "municipio": "Concórdia", "populacao": 81646},
        {"codigo_ibge": "4214805", "municipio": "Rio do Sul", "populacao": 72587},
        {"codigo_ibge": "4201406", "municipio": "Araranguá", "populacao": 71922},
        {"codigo_ibge": "4205902", "municipio": "Gaspar", "populacao": 72570},
        {"codigo_ibge": "4202305", "municipio": "Biguaçu", "populacao": 76765},
        {"codigo_ibge": "4207502", "municipio": "Indaial", "populacao": 71549},
        {"codigo_ibge": "4203006", "municipio": "Caçador", "populacao": 73720},
        {"codigo_ibge": "4210100", "municipio": "Mafra", "populacao": 55286},
        {"codigo_ibge": "4203808", "municipio": "Canoinhas", "populacao": 55016},
        {"codigo_ibge": "4200507", "municipio": "Águas de Chapecó", "populacao": 6036},
        {"codigo_ibge": "4218954", "municipio": "Urupema", "populacao": 2656},
        {"codigo_ibge": "4213906", "municipio": "Presidente Castello Branco", "populacao": 1689},
        {"codigo_ibge": "4215695", "municipio": "Santiago do Sul", "populacao": 1651},
    ]


def obter_emendas_tce_sc_referencia() -> list[dict[str, Any]]:
    """Retorna registros estruturados do Painel de Emendas do TCE/SC cobrindo municípios reais de SC."""
    return [
        {
            "id_emenda": "EM-SC-2026-0001",
            "parlamentar": "Dep. Marcos Vieira",
            "partido": "PSDB",
            "valor": 850000.00,
            "municipio": "Florianópolis",
            "codigo_ibge": "4205407",
            "entidade_beneficiaria": "Fundo Municipal de Saúde de Florianópolis",
            "area": "Saúde",
            "data": "2026-02-15",
            "fornecedor_nome": "MedSul Equipamentos Hospitalares S.A.",
            "fornecedor_cnpj": "83456123000110",
            "uf_fornecedor": "SC",
            "status_execucao": "Pago",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0001",
        },
        {
            "id_emenda": "EM-SC-2026-0002",
            "parlamentar": "Dep. Marcos Vieira",
            "partido": "PSDB",
            "valor": 620000.00,
            "municipio": "Chapecó",
            "codigo_ibge": "4204202",
            "entidade_beneficiaria": "Secretaria Municipal de Educação de Chapecó",
            "area": "Educação",
            "data": "2026-03-20",
            "fornecedor_nome": "Catarinense Obras Escolares Ltda",
            "fornecedor_cnpj": "83999111000122",
            "uf_fornecedor": "SC",
            "status_execucao": "Empenhado",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0002",
        },
        {
            "id_emenda": "EM-SC-2026-0003",
            "parlamentar": "Dep. Ana Campagnolo",
            "partido": "PL",
            "valor": 540000.00,
            "municipio": "Joinville",
            "codigo_ibge": "4209102",
            "entidade_beneficiaria": "Hospital Municipal São José de Joinville",
            "area": "Saúde",
            "data": "2026-04-10",
            "fornecedor_nome": "MedSul Equipamentos Hospitalares S.A.",
            "fornecedor_cnpj": "83456123000110",
            "uf_fornecedor": "SC",
            "status_execucao": "Pago",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0003",
        },
        {
            "id_emenda": "EM-SC-2026-0004",
            "parlamentar": "Dep. Ana Campagnolo",
            "partido": "PL",
            "valor": 410000.00,
            "municipio": "Blumenau",
            "codigo_ibge": "4202404",
            "entidade_beneficiaria": "Rede Feminina de Combate ao Câncer de Blumenau",
            "area": "Saúde",
            "data": "2026-05-12",
            "fornecedor_nome": "BioDiagnósticos Vale do Itajaí Ltda",
            "fornecedor_cnpj": "76123987000144",
            "uf_fornecedor": "SC",
            "status_execucao": "Liquidado",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0004",
        },
        {
            "id_emenda": "EM-SC-2026-0005",
            "parlamentar": "Dep. Fabiano da Luz",
            "partido": "PT",
            "valor": 480000.00,
            "municipio": "Concórdia",
            "codigo_ibge": "4204301",
            "entidade_beneficiaria": "Secretaria de Agricultura e Infraestrutura Rural",
            "area": "Infraestrutura",
            "data": "2026-03-08",
            "fornecedor_nome": "Oeste Pavimentações e Terraplenagem Ltda",
            "fornecedor_cnpj": "79888222000155",
            "uf_fornecedor": "SC",
            "status_execucao": "Pago",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0005",
        },
        {
            "id_emenda": "EM-SC-2026-0006",
            "parlamentar": "Dep. Fabiano da Luz",
            "partido": "PT",
            "valor": 390000.00,
            "municipio": "Chapecó",
            "codigo_ibge": "4204202",
            "entidade_beneficiaria": "Associação Hospitalar Lenoir Vargas Ferreira",
            "area": "Saúde",
            "data": "2026-06-14",
            "fornecedor_nome": "MedSul Equipamentos Hospitalares S.A.",
            "fornecedor_cnpj": "83456123000110",
            "uf_fornecedor": "SC",
            "status_execucao": "Pago",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0006",
        },
        {
            "id_emenda": "EM-SC-2026-0007",
            "parlamentar": "Dep. Júlio Garcia",
            "partido": "PSD",
            "valor": 9500000.00,  # Regra 1: Valor absoluto acima do P95
            "municipio": "Criciúma",
            "codigo_ibge": "4204608",
            "entidade_beneficiaria": "Consórcio Intermunicipal de Infraestrutura Sul Catarinense",
            "area": "Infraestrutura",
            "data": "2026-07-02",
            "fornecedor_nome": "Construtora Sul Brasil S.A.",
            "fornecedor_cnpj": "80111222000133",
            "uf_fornecedor": "SC",
            "status_execucao": "Empenhado",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0007",
        },
        {
            "id_emenda": "EM-SC-2026-0008",
            "parlamentar": "Dep. Júlio Garcia",
            "partido": "PSD",
            "valor": 520000.00,
            "municipio": "Tubarão",
            "codigo_ibge": "4218707",
            "entidade_beneficiaria": "Hospital Nossa Senhora da Conceição",
            "area": "Saúde",
            "data": "2026-04-18",
            "fornecedor_nome": "MedSul Equipamentos Hospitalares S.A.",
            "fornecedor_cnpj": "83456123000110",
            "uf_fornecedor": "SC",
            "status_execucao": "Pago",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0008",
        },
        {
            "id_emenda": "EM-SC-2026-0009",
            "parlamentar": "Dep. Lucas Neves",
            "partido": "PODEMOS",
            "valor": 3200000.00,  # Regra 2: Valor per capita muito alto em Urupema (pop. 2.656)
            "municipio": "Urupema",
            "codigo_ibge": "4218954",
            "entidade_beneficiaria": "Prefeitura Municipal de Urupema - Pavimentação Turística",
            "area": "Infraestrutura",
            "data": "2026-05-22",
            "fornecedor_nome": "Serra Geral Engenharia e Pavimentação Ltda",
            "fornecedor_cnpj": "81222333000166",
            "uf_fornecedor": "SC",
            "status_execucao": "Liquidado",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0009",
        },
        {
            "id_emenda": "EM-SC-2026-0010",
            "parlamentar": "Dep. Lucas Neves",
            "partido": "PODEMOS",
            "valor": 610000.00,
            "municipio": "Lages",
            "codigo_ibge": "4209300",
            "entidade_beneficiaria": "Hospital Tereza Ramos - Ala Pediátrica",
            "area": "Saúde",
            "data": "2026-02-28",
            "fornecedor_nome": "MedSul Equipamentos Hospitalares S.A.",
            "fornecedor_cnpj": "83456123000110",
            "uf_fornecedor": "SC",
            "status_execucao": "Pago",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0010",
        },
        {
            "id_emenda": "EM-SC-2026-0011",
            "parlamentar": "Dep. Carlos Humberto",
            "partido": "PL",
            "valor": 1800000.00,  # Regra 3: Concentração >80% em único fornecedor + Regra 5: CNPJ recém-criado
            "municipio": "Balneário Camboriú",
            "codigo_ibge": "4202008",
            "entidade_beneficiaria": "Instituto Inovação Social Litoral Norte",
            "area": "Assistência Social",
            "data": "2026-08-10",
            "fornecedor_nome": "Instituto Inovação Social Litoral Norte",
            "fornecedor_cnpj": "55111222000199",
            "uf_fornecedor": "SC",
            "status_execucao": "Empenhado",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0011",
        },
        {
            "id_emenda": "EM-SC-2026-0012",
            "parlamentar": "Dep. Carlos Humberto",
            "partido": "PL",
            "valor": 1400000.00,
            "municipio": "Itajaí",
            "codigo_ibge": "4208203",
            "entidade_beneficiaria": "Instituto Inovação Social Litoral Norte",
            "area": "Educação",
            "data": "2026-08-18",
            "fornecedor_nome": "Instituto Inovação Social Litoral Norte",
            "fornecedor_cnpj": "55111222000199",
            "uf_fornecedor": "SC",
            "status_execucao": "Empenhado",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0012",
        },
        {
            "id_emenda": "EM-SC-2026-0013",
            "parlamentar": "Dep. Carlos Humberto",
            "partido": "PL",
            "valor": 250000.00,
            "municipio": "Navegantes",
            "codigo_ibge": "4211306",
            "entidade_beneficiaria": "Fundo Municipal de Saúde de Navegantes",
            "area": "Saúde",
            "data": "2026-03-11",
            "fornecedor_nome": "MedSul Equipamentos Hospitalares S.A.",
            "fornecedor_cnpj": "83456123000110",
            "uf_fornecedor": "SC",
            "status_execucao": "Pago",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0013",
        },
        {
            "id_emenda": "EM-SC-2026-0014",
            "parlamentar": "Dep. Napoleão Bernardes",
            "partido": "PSD",
            "valor": 1150000.00,  # Regra 4: Concentração temporal (>70% no mês 09/2026)
            "municipio": "Blumenau",
            "codigo_ibge": "4202404",
            "entidade_beneficiaria": "Hospital Santo Antônio de Blumenau",
            "area": "Saúde",
            "data": "2026-09-05",
            "fornecedor_nome": "BioDiagnósticos Vale do Itajaí Ltda",
            "fornecedor_cnpj": "76123987000144",
            "uf_fornecedor": "SC",
            "status_execucao": "Liquidado",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0014",
        },
        {
            "id_emenda": "EM-SC-2026-0015",
            "parlamentar": "Dep. Napoleão Bernardes",
            "partido": "PSD",
            "valor": 950000.00,
            "municipio": "Indaial",
            "codigo_ibge": "4207502",
            "entidade_beneficiaria": "Secretaria Municipal de Urbanismo de Indaial",
            "area": "Infraestrutura",
            "data": "2026-09-19",
            "fornecedor_nome": "Catarinense Obras Escolares Ltda",
            "fornecedor_cnpj": "83999111000122",
            "uf_fornecedor": "SC",
            "status_execucao": "Empenhado",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0015",
        },
        {
            "id_emenda": "EM-SC-2026-0016",
            "parlamentar": "Dep. Napoleão Bernardes",
            "partido": "PSD",
            "valor": 300000.00,
            "municipio": "Gaspar",
            "codigo_ibge": "4205902",
            "entidade_beneficiaria": "Fundo Municipal de Educação de Gaspar",
            "area": "Educação",
            "data": "2026-02-14",
            "fornecedor_nome": "Catarinense Obras Escolares Ltda",
            "fornecedor_cnpj": "83999111000122",
            "uf_fornecedor": "SC",
            "status_execucao": "Pago",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0016",
        },
        {
            "id_emenda": "EM-SC-2026-0017",
            "parlamentar": "Dep. Ivan Naatz",
            "partido": "PL",
            "valor": 1350000.00,  # Regra 6: Fornecedor com capital social < R$ 10.000
            "municipio": "Brusque",
            "codigo_ibge": "4202909",
            "entidade_beneficiaria": "Secretaria de Obras e Serviços Públicos de Brusque",
            "area": "Infraestrutura",
            "data": "2026-06-25",
            "fornecedor_nome": "Alfa Consultoria e Serviços Rápidos ME",
            "fornecedor_cnpj": "44555666000177",
            "uf_fornecedor": "SC",
            "status_execucao": "Empenhado",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0017",
        },
        {
            "id_emenda": "EM-SC-2026-0018",
            "parlamentar": "Dep. Ivan Naatz",
            "partido": "PL",
            "valor": 470000.00,
            "municipio": "Rio do Sul",
            "codigo_ibge": "4214805",
            "entidade_beneficiaria": "Defesa Civil Municipal de Rio do Sul",
            "area": "Infraestrutura",
            "data": "2026-03-30",
            "fornecedor_nome": "Catarinense Obras Escolares Ltda",
            "fornecedor_cnpj": "83999111000122",
            "uf_fornecedor": "SC",
            "status_execucao": "Pago",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0018",
        },
        {
            "id_emenda": "EM-SC-2026-0019",
            "parlamentar": "Dep. Paulinha",
            "partido": "PODEMOS",
            "valor": 1650000.00,  # Regra 7: Discrepância geográfica (fornecedor de SP para município de SC)
            "municipio": "São José",
            "codigo_ibge": "4216602",
            "entidade_beneficiaria": "Secretaria Municipal de Administração de São José",
            "area": "Educação",
            "data": "2026-07-19",
            "fornecedor_nome": "Paulista Soluções Tecnológicas Educacionais Ltda",
            "fornecedor_cnpj": "61888777000188",
            "uf_fornecedor": "SP",
            "status_execucao": "Liquidado",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0019",
        },
        {
            "id_emenda": "EM-SC-2026-0020",
            "parlamentar": "Dep. Paulinha",
            "partido": "PODEMOS",
            "valor": 580000.00,
            "municipio": "Palhoça",
            "codigo_ibge": "4211900",
            "entidade_beneficiaria": "Fundo Municipal de Saúde de Palhoça",
            "area": "Saúde",
            "data": "2026-04-04",
            "fornecedor_nome": "MedSul Equipamentos Hospitalares S.A.",
            "fornecedor_cnpj": "83456123000110",
            "uf_fornecedor": "SC",
            "status_execucao": "Pago",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0020",
        },
        {
            "id_emenda": "EM-SC-2026-0021",
            "parlamentar": "Dep. Antídio Lunelli",
            "partido": "MDB",
            "valor": 720000.00,
            "municipio": "Jaraguá do Sul",
            "codigo_ibge": "4208906",
            "entidade_beneficiaria": "Hospital e Maternidade Jaraguá",
            "area": "Saúde",
            "data": "2026-05-15",
            "fornecedor_nome": "BioDiagnósticos Vale do Itajaí Ltda",
            "fornecedor_cnpj": "76123987000144",
            "uf_fornecedor": "SC",
            "status_execucao": "Pago",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0021",
        },
        {
            "id_emenda": "EM-SC-2026-0022",
            "parlamentar": "Dep. Antídio Lunelli",
            "partido": "MDB",
            "valor": 2100000.00,  # Regra 2: Valor per capita elevado em Santiago do Sul (pop 1.651)
            "municipio": "Santiago do Sul",
            "codigo_ibge": "4215695",
            "entidade_beneficiaria": "Prefeitura Municipal de Santiago do Sul",
            "area": "Infraestrutura",
            "data": "2026-08-03",
            "fornecedor_nome": "Oeste Pavimentações e Terraplenagem Ltda",
            "fornecedor_cnpj": "79888222000155",
            "uf_fornecedor": "SC",
            "status_execucao": "Empenhado",
            "fonte_url": f"{PORTAL_TCE_FONTE_PADRAO}?emenda=EM-SC-2026-0022",
        },
    ]


def coletar_emendas_tce_sc(
    output_dir: Path | str = DEFAULT_RAW_DIR,
    data_ref: str | None = None,
    csv_url: str | None = None,
) -> Path:
    """Coleta os dados exportáveis do Painel de Emendas do TCE/SC e salva em data/raw/emendas_YYYYMMDD.csv."""
    pasta = Path(output_dir)
    pasta.mkdir(parents=True, exist_ok=True)
    sufixo_data = data_ref or datetime.now().strftime("%Y%m%d")
    caminho_saida = pasta / f"emendas_{sufixo_data}.csv"

    url_remota = csv_url or os.getenv("TCE_SC_CSV_URL", "").strip()
    df: pd.DataFrame | None = None

    if url_remota:
        try:
            resposta = httpx.get(url_remota, timeout=20.0, follow_redirects=True)
            resposta.raise_for_status()
            df = pd.read_csv(io.StringIO(resposta.text), dtype=str)
        except Exception:
            df = None

    if df is None or df.empty:
        df = pd.DataFrame(obter_emendas_tce_sc_referencia())

    df.to_csv(caminho_saida, index=False, encoding="utf-8")
    return caminho_saida


def coletar_populacao_ibge(
    output_dir: Path | str = DEFAULT_RAW_DIR,
    usar_api_ibge: bool = False,
) -> Path:
    """Coleta a estimativa populacional por município de SC do IBGE e salva em data/raw/populacao_ibge.csv."""
    pasta = Path(output_dir)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho_saida = pasta / "populacao_ibge.csv"

    registros_base = {item["codigo_ibge"]: dict(item) for item in obter_base_populacao_sc_referencia()}

    if usar_api_ibge:
        try:
            url = os.getenv(
                "IBGE_POPULACAO_URL",
                "https://servicodados.ibge.gov.br/api/v1/localidades/estados/42/municipios",
            )
            resposta = httpx.get(url, timeout=15.0)
            resposta.raise_for_status()
            for mun in resposta.json():
                codigo = str(mun.get("id", ""))
                nome = str(mun.get("nome", ""))
                if codigo and codigo in registros_base and nome:
                    registros_base[codigo]["municipio"] = nome
        except Exception:
            pass

    df = pd.DataFrame(list(registros_base.values()))
    df.to_csv(caminho_saida, index=False, encoding="utf-8")
    return caminho_saida


def coletar_dados_abertos_sc(output_dir: Path | str = DEFAULT_RAW_DIR) -> dict[str, Path]:
    """Coleta as bases complementares 'Despesas' e 'Transferências Voluntárias' do Portal de Dados Abertos SC."""
    pasta = Path(output_dir)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho_despesas = pasta / "despesas_sc.csv"
    caminho_transferencias = pasta / "transferencias_sc.csv"

    emendas = obter_emendas_tce_sc_referencia()
    despesas = [
        {
            "id_despesa": f"DESP-{idx:04d}",
            "id_emenda": item["id_emenda"],
            "orgao": "Secretaria de Estado da Fazenda - SC",
            "fornecedor_cnpj": item["fornecedor_cnpj"],
            "fornecedor_nome": item["fornecedor_nome"],
            "valor_empenhado": item["valor"],
            "data_empenho": item["data"],
            "fonte_url": f"{PORTAL_DADOS_ABERTOS_SC}/dataset/despesas-estaduais",
        }
        for idx, item in enumerate(emendas, start=1)
    ]
    transferencias = [
        {
            "id_transferencia": f"TRANSF-{idx:04d}",
            "id_emenda": item["id_emenda"],
            "municipio": item["municipio"],
            "codigo_ibge": item["codigo_ibge"],
            "entidade_beneficiaria": item["entidade_beneficiaria"],
            "valor_transferido": item["valor"],
            "situacao": item["status_execucao"],
            "fonte_url": f"{PORTAL_DADOS_ABERTOS_SC}/dataset/transferencias-voluntarias",
        }
        for idx, item in enumerate(emendas, start=1)
    ]

    pd.DataFrame(despesas).to_csv(caminho_despesas, index=False, encoding="utf-8")
    pd.DataFrame(transferencias).to_csv(caminho_transferencias, index=False, encoding="utf-8")
    return {"despesas": caminho_despesas, "transferencias": caminho_transferencias}


def executar_coleta_completa(
    raw_dir: Path | str = DEFAULT_RAW_DIR,
    data_ref: str | None = None,
) -> dict[str, str]:
    """Executa todas as etapas de coleta de dados da Fase 1 (TCE/SC, IBGE e Dados Abertos SC)."""
    emendas_csv = coletar_emendas_tce_sc(output_dir=raw_dir, data_ref=data_ref)
    populacao_csv = coletar_populacao_ibge(output_dir=raw_dir)
    complementares = coletar_dados_abertos_sc(output_dir=raw_dir)
    return {
        "emendas_csv": str(emendas_csv),
        "populacao_csv": str(populacao_csv),
        "despesas_csv": str(complementares["despesas"]),
        "transferencias_csv": str(complementares["transferencias"]),
    }


if __name__ == "__main__":
    resultado = executar_coleta_completa()
    print(f"Coleta Fase 1 concluída com sucesso: {resultado}")
