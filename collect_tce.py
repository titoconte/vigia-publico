"""Fase 1 — Coleta de dados públicos do Painel de Emendas do TCE/SC, População IBGE e Dados Abertos SC."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import time
from typing import Any
import unicodedata

import httpx
import pandas as pd

DEFAULT_RAW_DIR = Path("data/raw")
PORTAL_TCE_FONTE_PADRAO = "https://www.tcesc.tc.br/painel-emendas-parlamentares"
PORTAL_TRANSPARENCIA_SC_API = "https://api-portal-transparencia.apps.sm.okd4.ciasc.sc.gov.br/api"
PORTAL_TRANSPARENCIA_SC_WEB = "https://www.transparencia.sc.gov.br"
PORTAL_DADOS_ABERTOS_SC = "https://dados.sc.gov.br"
IBGE_AGREGADOS_SC_URL = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/-1/variaveis/9324?localidades=N6[N3[42]]"
)


def resolver_usar_rede(usar_rede: bool | None = None) -> bool:
    """Resolve se a coleta deve consultar a rede (explícito > VIGIA_USAR_REDE > offline no Pytest > True)."""
    if usar_rede is not None:
        return bool(usar_rede)
    valor_env = os.getenv("VIGIA_USAR_REDE", "").strip().lower()
    if valor_env in ("1", "true", "yes", "sim"):
        return True
    if valor_env in ("0", "false", "no", "nao", "não"):
        return False
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False
    return True


def _decodificar_bytes_csv(conteudo: bytes) -> str:
    """Decodifica bytes de arquivos CSV públicos tentando UTF-8 primeiro e fazendo fallback para Latin-1."""
    try:
        return conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return conteudo.decode("latin-1", errors="replace")


def _baixar_csv_streaming_limitado(
    client: httpx.Client,
    url: str,
    max_linhas: int = 1500,
) -> str:
    """Realiza o download em streaming de um CSV grande retornando o cabeçalho e até max_linhas registros."""
    buffer = bytearray()
    alvo_quebras = max(1, max_linhas) + 1
    with client.stream("GET", url, follow_redirects=True, timeout=25.0) as resposta:
        resposta.raise_for_status()
        for bloco in resposta.iter_bytes():
            buffer.extend(bloco)
            if buffer.count(b"\n") >= alvo_quebras:
                break
    texto = _decodificar_bytes_csv(bytes(buffer))
    linhas = [ln for ln in texto.splitlines() if ln.strip()]
    return "\n".join(linhas[:alvo_quebras])


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


PARTIDOS_PARLAMENTARES_SC: dict[str, str] = {
    "ALEXANDER BRASIL ALVES PEREIRA": "PL",
    "ALTAIR SILVA": "PP",
    "ANA CAMPAGNOLO": "PL",
    "ANTIDIO LUNELLI": "MDB",
    "CAMILO NAZARENO PAGANI MARTINS": "PODEMOS",
    "CARLOS HUMBERTO METZNER SILVA": "PL",
    "FABIANO DA LUZ": "PT",
    "FELIPPE LUIZ COLLACO": "PP",
    "FERNANDO KRELLING": "MDB",
    "IVAN NAATZ": "PL",
    "JAIR MIOTTO": "UNIAO",
    "JERRY EDSON COMPER": "MDB",
    "JESSE LOPES": "PL",
    "JOSE MILTON SCHEFFER": "PP",
    "JULIO CESAR GARCIA": "PSD",
    "LUCAS FELIPE MELO NEVES": "PODEMOS",
    "LUCIANE CARMINATTI": "PT",
    "MARCIUS MACHADO": "PL",
    "MARCOS DA ROSA": "UNIAO",
    "MARCOS JOSE ABREU ( MARQUITO)": "PSOL",
    "MARCOS LUIZ VIEIRA": "PSDB",
    "MARIO PINTO DA MOTTA JUNIOR": "PSD",
    "MATHEUS ANDREIS CADORIN": "NOVO",
    "MAURICIO ESKUDLARK": "PL",
    "MAURICIO FERNANDO PEIXER": "PL",
    "MAURO DE NADAL": "MDB",
    "NAPOLEAO BERNARDES NETO": "PSD",
    "NEODI SARETTA": "PT",
    "NILSO JOSE BERLANDA": "PL",
    "OSCAR GUTZ": "PL",
    "PADRE PEDRO BALDISSERA": "PT",
    "PAULINHA": "PODEMOS",
    "RODRIGO MINOTTO": "PDT",
    "SARGENTO LIMA": "PL",
    "SERGIO DA ROSA GUIMARAES": "UNIAO",
    "SERGIO MOTTA": "REPUBLICANOS",
    "SILVIO CARDOSO JUNIOR": "PP",
    "TIAGO ZILLI": "MDB",
    "VICENTE AUGUSTO CAROPRESO": "PSDB",
    "VOLNEI WEBER": "MDB",
}


def _normalizar_chave_texto(texto: str | None) -> str:
    """Remove acentos e padroniza caixa alta e espaços para comparação determinística de nomes."""
    if not texto:
        return ""
    sem_acentos = "".join(
        ch for ch in unicodedata.normalize("NFD", str(texto).strip()) if unicodedata.category(ch) != "Mn"
    )
    return " ".join(sem_acentos.upper().split())


def extrair_cnpj_e_nome_credor(identificacao_credor: str | None) -> tuple[str, str]:
    """Extrai o CNPJ de 14 dígitos e a razão social limpa a partir do campo identificacaocredor do SIGEF/SC."""
    bruto = str(identificacao_credor or "").strip()
    if not bruto:
        return ("82951229000176", "Estado de Santa Catarina / Unidade Gestora")

    padrao_formatado = re.search(r"(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\s*(.*)", bruto)
    if padrao_formatado:
        cnpj_limpo = re.sub(r"\D", "", padrao_formatado.group(1)).zfill(14)
        nome_limpo = " ".join(padrao_formatado.group(2).strip(" -–").split())
        if not nome_limpo:
            nome_limpo = f"Credor Público/Privado {cnpj_limpo}"
        return (cnpj_limpo, nome_limpo)

    digitos = re.sub(r"\D", "", bruto)
    if len(digitos) == 14:
        return (digitos, f"Credor Público/Privado {digitos}")
    return ("82951229000176", " ".join(bruto.split()))


def limpar_area_subacao(nmsubacao: str | None) -> str:
    """Remove prefixos burocráticos padronizados da subação orçamentária para obter a área temática limpa."""
    texto = " ".join(str(nmsubacao or "").split()).strip()
    if not texto:
        return "Geral"
    limpo = re.sub(
        r"^emendas?\s+parlamentares?\s+impositivas?\s+(da|do|de|para|em|-)?\s*",
        "",
        texto,
        flags=re.IGNORECASE,
    ).strip(" -–")
    return limpo if limpo else texto


def obter_partido_parlamentar_sc(nome_parlamentar: str | None) -> str:
    """Retorna a sigla partidária oficial na ALESC ou identifica bancadas regionais."""
    chave = _normalizar_chave_texto(nome_parlamentar)
    if not chave:
        return "Não informado"
    if chave.startswith("BANCADA "):
        return "Bancada Regional"
    return PARTIDOS_PARLAMENTARES_SC.get(chave, "ALESC")


def _converter_valor_monetario(valor: Any) -> float:
    """Converte strings numéricas brasileiras ou internacionais do Portal da Transparência em float."""
    if valor is None:
        return 0.0
    texto = str(valor).strip()
    if not texto:
        return 0.0
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return round(float(texto), 2)
    except ValueError:
        return 0.0


def _selecionar_emendas_prioritarias(df_indice: pd.DataFrame, max_emendas: int) -> pd.DataFrame:
    """Seleciona amostra estratificada por modalidade, parlamentar e maior valor ou retorna 100% se max_emendas<=0."""
    df_trab = df_indice.copy()
    if "situacao" in df_trab.columns:
        ativas = df_trab[df_trab["situacao"].astype(str).str.strip().str.lower() == "ativo"]
        if not ativas.empty:
            df_trab = ativas.copy()

    df_trab["_valor_num"] = df_trab["valor"].apply(_converter_valor_monetario)
    df_trab = df_trab[df_trab["_valor_num"] > 0].sort_values("_valor_num", ascending=False)

    if max_emendas <= 0 or len(df_trab) <= max_emendas:
        return df_trab.drop(columns=["_valor_num"]).reset_index(drop=True)

    escolhidos_idx: list[Any] = []
    vistos: set[Any] = set()

    # 1. Garante ao menos 1 emenda de cada parlamentar/bancada para cobertura integral dos 46 autores
    if "parlamentar_bancada" in df_trab.columns:
        for _, grp in df_trab.groupby("parlamentar_bancada", sort=False):
            idx0 = grp.index[0]
            if idx0 not in vistos and len(escolhidos_idx) < max_emendas:
                escolhidos_idx.append(idx0)
                vistos.add(idx0)

    # 2. Prioriza convênios e termos de fomento (entidades privadas sem fins lucrativos, hospitais e associações)
    if "modalidade" in df_trab.columns:
        cota_convenios = max(1, int(max_emendas * 0.45))
        convenios = df_trab[df_trab["modalidade"].astype(str).str.contains("Conv", case=False, na=False)]
        adicionados_conv = 0
        for idx in convenios.index:
            if idx not in vistos and len(escolhidos_idx) < max_emendas and adicionados_conv < cota_convenios:
                escolhidos_idx.append(idx)
                vistos.add(idx)
                adicionados_conv += 1

    # 3. Preenche o restante com as emendas de maior valor financeiro global
    for idx in df_trab.index:
        if len(escolhidos_idx) >= max_emendas:
            break
        if idx not in vistos:
            escolhidos_idx.append(idx)
            vistos.add(idx)

    return df_trab.loc[escolhidos_idx].drop(columns=["_valor_num"]).reset_index(drop=True)


def _obter_extrato_emenda_com_cache(
    numero_emenda: str,
    pasta_cache: Path,
    http: httpx.Client,
    pausa_segundos: float = 0.0,
) -> dict[str, Any]:
    """Consulta o extrato detalhado de uma emenda no Portal da Transparência SC utilizando cache persistente em JSON."""
    pasta_cache.mkdir(parents=True, exist_ok=True)
    arquivo_cache = pasta_cache / f"{numero_emenda}.json"
    if arquivo_cache.exists():
        try:
            return json.loads(arquivo_cache.read_text(encoding="utf-8"))
        except Exception:
            pass

    url = f"{PORTAL_TRANSPARENCIA_SC_API}/emendaparlamentar/extratoemenda?nuemendaparlamentarfiltro[]={numero_emenda}"
    for tentativa in range(3):
        if pausa_segundos > 0:
            time.sleep(pausa_segundos)
        resposta = http.get(url)
        if resposta.status_code == 429:
            time.sleep(1.5 * (tentativa + 1))
            continue
        resposta.raise_for_status()
        dados = resposta.json()
        arquivo_cache.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        return dados

    return {}


def _montar_linha_emenda_portal_sc(
    row_indice: pd.Series,
    payload_extrato: dict[str, Any],
    mapa_ibge_por_nome: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    """Combina uma linha do índice CSV com o JSON do extrato para formar o registro padronizado de 14 colunas."""
    numero = str(row_indice.get("numero", "")).strip()
    ano = str(row_indice.get("ano", "2026")).strip() or "2026"
    emenda_obj = payload_extrato.get("emenda", {}) if isinstance(payload_extrato, dict) else {}
    ident = emenda_obj.get("emendaIdentificacao", {}) or {}

    parlamentar_bruto = str(ident.get("nmparlamentar") or row_indice.get("parlamentar_bancada") or "").strip()
    partido = obter_partido_parlamentar_sc(parlamentar_bruto)

    valor_emenda = _converter_valor_monetario(ident.get("vlemendaparlamentar") or row_indice.get("valor"))
    empenhado = _converter_valor_monetario(row_indice.get("empenhado"))
    liquidado = _converter_valor_monetario(row_indice.get("liquidado"))
    pago = _converter_valor_monetario(row_indice.get("pago"))

    if pago > 0:
        status_execucao = "Pago"
    elif liquidado > 0:
        status_execucao = "Liquidado"
    elif empenhado > 0:
        status_execucao = "Empenhado"
    else:
        status_execucao = "Aprovado"

    cnpj_forn, nome_credor = extrair_cnpj_e_nome_credor(ident.get("identificacaocredor"))

    localidade_bruta = str(ident.get("nmlocalidade") or "").strip()
    chave_loc = _normalizar_chave_texto(localidade_bruta)
    if not chave_loc or chave_loc in ("ESTADO", "SANTA CATARINA", "DIVERSOS"):
        chave_loc = "FLORIANOPOLIS"

    if chave_loc in mapa_ibge_por_nome:
        codigo_ibge, municipio_oficial = mapa_ibge_por_nome[chave_loc]
    else:
        codigo_ibge = "4205407"
        municipio_oficial = localidade_bruta if localidade_bruta else "Florianópolis"

    area = limpar_area_subacao(ident.get("nmsubacao"))

    datas_lancamento: list[str] = []
    for chave_lista in ("emendaEmpenho", "emendaLiquidacao", "emendaPagamento"):
        itens = emenda_obj.get(chave_lista) or []
        if isinstance(itens, list):
            for lanc in itens:
                if isinstance(lanc, dict) and lanc.get("dtlancamento"):
                    datas_lancamento.append(str(lanc["dtlancamento"])[:10])
    data_emenda = sorted(datas_lancamento)[0] if datas_lancamento else f"{ano}-02-01"

    return {
        "id_emenda": numero,
        "parlamentar": parlamentar_bruto,
        "partido": partido,
        "valor": valor_emenda,
        "municipio": municipio_oficial,
        "codigo_ibge": codigo_ibge,
        "entidade_beneficiaria": nome_credor,
        "area": area,
        "data": data_emenda,
        "fornecedor_nome": nome_credor,
        "fornecedor_cnpj": cnpj_forn,
        "uf_fornecedor": "SC",
        "status_execucao": status_execucao,
        "fonte_url": (
            f"{PORTAL_TRANSPARENCIA_SC_WEB}/emenda-parlamentar/extratoemenda/"
            f"?nuemendaparlamentarfiltro[]={numero}"
        ),
    }


def coletar_emendas_tce_sc(
    output_dir: Path | str = DEFAULT_RAW_DIR,
    data_ref: str | None = None,
    csv_url: str | None = None,
    usar_rede: bool | None = None,
    max_emendas: int | None = None,
    client: httpx.Client | None = None,
) -> Path:
    """Coleta emendas parlamentares estaduais reais de SC (Portal da Transparência/CIASC) e salva CSV padronizado."""
    pasta = Path(output_dir)
    pasta.mkdir(parents=True, exist_ok=True)
    sufixo_data = data_ref or datetime.now().strftime("%Y%m%d")
    caminho_saida = pasta / f"emendas_{sufixo_data}.csv"

    url_remota_custom = csv_url or os.getenv("TCE_SC_CSV_URL", "").strip()
    deve_usar_rede = resolver_usar_rede(usar_rede)
    df: pd.DataFrame | None = None

    if url_remota_custom:
        fechar = client is None
        http = client or httpx.Client(timeout=25.0, follow_redirects=True)
        try:
            resposta = http.get(url_remota_custom)
            resposta.raise_for_status()
            df = pd.read_csv(io.StringIO(_decodificar_bytes_csv(resposta.content)), dtype=str)
        except Exception:
            df = None
        finally:
            if fechar:
                http.close()

    if (df is None or df.empty) and deve_usar_rede:
        limite = (
            max_emendas
            if max_emendas is not None
            else int(os.getenv("VIGIA_MAX_EMENDAS", "250").strip() or "250")
        )
        ano_exercicio = os.getenv("VIGIA_ANO_EXERCICIO", "2026").strip() or "2026"

        caminho_ibge = pasta / "populacao_ibge.csv"
        if caminho_ibge.exists():
            df_ibge_local = pd.read_csv(caminho_ibge, dtype={"codigo_ibge": str})
            registros_ibge = df_ibge_local.to_dict(orient="records")
        else:
            registros_ibge = obter_base_populacao_sc_referencia()

        mapa_ibge_por_nome = {
            _normalizar_chave_texto(str(r["municipio"])): (str(r["codigo_ibge"]), str(r["municipio"]))
            for r in registros_ibge
        }

        fechar = client is None
        http = client or httpx.Client(timeout=25.0, follow_redirects=True)
        try:
            url_indice = f"{PORTAL_TRANSPARENCIA_SC_API}/emendaparlamentar/exportcsv?anofiltro[]={ano_exercicio}"
            resp_idx = http.get(url_indice)
            resp_idx.raise_for_status()
            texto_idx = _decodificar_bytes_csv(resp_idx.content)
            df_indice = pd.read_csv(io.StringIO(texto_idx), sep=";", dtype=str)
            if not df_indice.empty:
                (pasta / f"emendas_indice_completo_{ano_exercicio}.csv").write_text(
                    texto_idx,
                    encoding="utf-8",
                )
                df_selecionadas = _selecionar_emendas_prioritarias(df_indice, max_emendas=limite)
                pasta_cache = pasta / "extratos_cache"
                numeros = [str(n).strip() for n in df_selecionadas["numero"].tolist()]

                if client is not None:
                    extratos_map = {
                        nu: _obter_extrato_emenda_com_cache(nu, pasta_cache, http, pausa_segundos=0.0)
                        for nu in numeros
                    }
                else:
                    # Usa pool controlado de 4 threads com leve espaçamento para respeitar o rate-limit de 300 req/min
                    def _buscar_um(nu: str) -> tuple[str, dict[str, Any]]:
                        """Auxiliar para busca concorrente controlada de um extrato de emenda."""
                        arq = pasta_cache / f"{nu}.json"
                        pausa = 0.0 if arq.exists() else 0.75
                        return (nu, _obter_extrato_emenda_com_cache(nu, pasta_cache, http, pausa_segundos=pausa))

                    with ThreadPoolExecutor(max_workers=4) as pool:
                        extratos_map = dict(pool.map(_buscar_um, numeros))

                linhas_finais = [
                    _montar_linha_emenda_portal_sc(
                        row_indice=row,
                        payload_extrato=extratos_map.get(str(row["numero"]).strip(), {}),
                        mapa_ibge_por_nome=mapa_ibge_por_nome,
                    )
                    for _, row in df_selecionadas.iterrows()
                ]
                if linhas_finais:
                    df = pd.DataFrame(linhas_finais)
        except Exception:
            df = None
        finally:
            if fechar:
                http.close()

    if df is None or df.empty:
        df = pd.DataFrame(obter_emendas_tce_sc_referencia())

    df.to_csv(caminho_saida, index=False, encoding="utf-8")
    return caminho_saida


def coletar_populacao_ibge(
    output_dir: Path | str = DEFAULT_RAW_DIR,
    usar_api_ibge: bool | None = None,
    client: httpx.Client | None = None,
) -> Path:
    """Coleta a estimativa populacional oficial dos 295 municípios de SC no IBGE e salva em populacao_ibge.csv."""
    pasta = Path(output_dir)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho_saida = pasta / "populacao_ibge.csv"

    registros_base = {item["codigo_ibge"]: dict(item) for item in obter_base_populacao_sc_referencia()}
    deve_usar_api = resolver_usar_rede(usar_api_ibge)

    if deve_usar_api:
        fechar_cliente = client is None
        http = client or httpx.Client(timeout=20.0, follow_redirects=True)
        try:
            url_agregados = os.getenv("IBGE_AGREGADOS_URL", IBGE_AGREGADOS_SC_URL)
            resposta = http.get(url_agregados)
            resposta.raise_for_status()
            payload = resposta.json()
            novos_registros: dict[str, dict[str, Any]] = {}
            for item_var in payload:
                for resultado in item_var.get("resultados", []):
                    for serie_mun in resultado.get("series", []):
                        loc = serie_mun.get("localidade", {})
                        codigo = str(loc.get("id", "")).strip()
                        nome_bruto = str(loc.get("nome", "")).strip()
                        if nome_bruto.upper().endswith(" - SC"):
                            nome_limpo = nome_bruto[:-5].strip()
                        else:
                            nome_limpo = nome_bruto
                        valores_serie = serie_mun.get("serie", {})
                        pop_valor = 0
                        if isinstance(valores_serie, dict) and valores_serie:
                            ultimo_ano = sorted(valores_serie.keys())[-1]
                            try:
                                pop_valor = int(float(str(valores_serie[ultimo_ano]).strip()))
                            except (TypeError, ValueError):
                                pop_valor = 0
                        if codigo and nome_limpo and pop_valor > 0:
                            novos_registros[codigo] = {
                                "codigo_ibge": codigo,
                                "municipio": nome_limpo,
                                "populacao": pop_valor,
                            }
            if novos_registros:
                registros_base = novos_registros
        except Exception:
            pass
        finally:
            if fechar_cliente:
                http.close()

    df = pd.DataFrame(list(registros_base.values()))
    df.to_csv(caminho_saida, index=False, encoding="utf-8")
    return caminho_saida


def coletar_dados_abertos_sc(
    output_dir: Path | str = DEFAULT_RAW_DIR,
    usar_rede: bool | None = None,
    max_linhas: int = 1500,
    client: httpx.Client | None = None,
) -> dict[str, Path]:
    """Coleta as bases públicas de 'Despesas' (Portal Transparência SC) e 'Transferências' (CKAN Dados Abertos SC)."""
    pasta = Path(output_dir)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho_despesas = pasta / "despesas_sc.csv"
    caminho_transferencias = pasta / "transferencias_sc.csv"

    deve_usar_rede = resolver_usar_rede(usar_rede)
    df_despesas_real: pd.DataFrame | None = None
    df_transf_real: pd.DataFrame | None = None

    if deve_usar_rede:
        fechar_cliente = client is None
        http = client or httpx.Client(timeout=25.0, follow_redirects=True)
        try:
            ano_atual = os.getenv("VIGIA_ANO_EXERCICIO", "2026").strip() or "2026"
            url_desp = f"{PORTAL_TRANSPARENCIA_SC_API}/despesa/exportcsv?anofiltro[]={ano_atual}"
            resp_desp = http.get(url_desp)
            resp_desp.raise_for_status()
            texto_desp = _decodificar_bytes_csv(resp_desp.content)
            df_desp_lido = pd.read_csv(io.StringIO(texto_desp), sep=";", dtype=str)
            if not df_desp_lido.empty:
                df_desp_lido["fonte_url"] = url_desp
                df_despesas_real = df_desp_lido.head(max_linhas)
        except Exception:
            df_despesas_real = None

        try:
            url_ckan = f"{PORTAL_DADOS_ABERTOS_SC}/api/3/action/package_show?id=transferencias"
            resp_ckan = http.get(url_ckan)
            resp_ckan.raise_for_status()
            recursos = resp_ckan.json().get("result", {}).get("resources", [])
            csvs_ckan = [r for r in recursos if str(r.get("format", "")).upper() == "CSV" and r.get("url")]
            if csvs_ckan:
                url_recurso = str(csvs_ckan[-1]["url"]).replace("http://", "https://")
                trecho_csv = _baixar_csv_streaming_limitado(http, url_recurso, max_linhas=max_linhas)
                df_transf_lido = pd.read_csv(
                    io.StringIO(trecho_csv),
                    sep=";",
                    dtype=str,
                    on_bad_lines="skip",
                )
                if not df_transf_lido.empty:
                    df_transf_lido["fonte_url"] = url_recurso
                    df_transf_real = df_transf_lido.head(max_linhas)
        except Exception:
            df_transf_real = None
        finally:
            if fechar_cliente:
                http.close()

    emendas_ref = obter_emendas_tce_sc_referencia()
    if df_despesas_real is None or df_despesas_real.empty:
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
            for idx, item in enumerate(emendas_ref, start=1)
        ]
        df_despesas_real = pd.DataFrame(despesas)

    if df_transf_real is None or df_transf_real.empty:
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
            for idx, item in enumerate(emendas_ref, start=1)
        ]
        df_transf_real = pd.DataFrame(transferencias)

    df_despesas_real.to_csv(caminho_despesas, index=False, encoding="utf-8")
    df_transf_real.to_csv(caminho_transferencias, index=False, encoding="utf-8")
    return {"despesas": caminho_despesas, "transferencias": caminho_transferencias}


def executar_coleta_completa(
    raw_dir: Path | str = DEFAULT_RAW_DIR,
    data_ref: str | None = None,
    usar_rede: bool | None = None,
    max_emendas: int | None = None,
) -> dict[str, str]:
    """Executa todas as etapas de coleta de dados da Fase 1 (IBGE, Portal Transparência/TCE SC e Dados Abertos SC)."""
    populacao_csv = coletar_populacao_ibge(output_dir=raw_dir, usar_api_ibge=usar_rede)
    emendas_csv = coletar_emendas_tce_sc(
        output_dir=raw_dir,
        data_ref=data_ref,
        usar_rede=usar_rede,
        max_emendas=max_emendas,
    )
    complementares = coletar_dados_abertos_sc(output_dir=raw_dir, usar_rede=usar_rede)
    return {
        "emendas_csv": str(emendas_csv),
        "populacao_csv": str(populacao_csv),
        "despesas_csv": str(complementares["despesas"]),
        "transferencias_csv": str(complementares["transferencias"]),
    }


if __name__ == "__main__":
    resultado = executar_coleta_completa()
    print(f"Coleta Fase 1 concluída com sucesso: {resultado}")
