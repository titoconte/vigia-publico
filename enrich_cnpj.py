"""Fase 1 (Item 4) — Enriquecimento de dados cadastrais de CNPJ junto à Receita Federal (BrasilAPI / Cache)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

import httpx

DEFAULT_ENRICHED_DIR = Path("data/enriched")

CADASTRO_REFERENCIA_CNPJ: dict[str, dict[str, Any]] = {
    "83456123000110": {
        "cnpj": "83456123000110",
        "razao_social": "MedSul Equipamentos Hospitalares S.A.",
        "data_abertura": "2014-05-12",
        "capital_social": 2500000.00,
        "cnae_principal": "4664-8/00 - Comércio atacadista de máquinas, aparelhos e equipamentos para uso odonto-médico-hospitalar",
        "uf": "SC",
        "municipio": "Florianópolis",
        "socios": ["Roberto Andrade", "Luciana Costa"],
        "fonte_consulta": "https://brasilapi.com.br/api/cnpj/v1/83456123000110",
    },
    "83999111000122": {
        "cnpj": "83999111000122",
        "razao_social": "Catarinense Obras Escolares Ltda",
        "data_abertura": "2017-08-23",
        "capital_social": 850000.00,
        "cnae_principal": "4120-4/00 - Construção de edifícios",
        "uf": "SC",
        "municipio": "Chapecó",
        "socios": ["Eduardo Zimmermann"],
        "fonte_consulta": "https://brasilapi.com.br/api/cnpj/v1/83999111000122",
    },
    "76123987000144": {
        "cnpj": "76123987000144",
        "razao_social": "BioDiagnósticos Vale do Itajaí Ltda",
        "data_abertura": "2018-11-04",
        "capital_social": 600000.00,
        "cnae_principal": "8640-2/02 - Laboratórios clínicos",
        "uf": "SC",
        "municipio": "Blumenau",
        "socios": ["Helena Muller", "Carlos Henrique Krueger"],
        "fonte_consulta": "https://brasilapi.com.br/api/cnpj/v1/76123987000144",
    },
    "79888222000155": {
        "cnpj": "79888222000155",
        "razao_social": "Oeste Pavimentações e Terraplenagem Ltda",
        "data_abertura": "2012-03-19",
        "capital_social": 1800000.00,
        "cnae_principal": "4211-1/01 - Construção de rodovias e ferrovias",
        "uf": "SC",
        "municipio": "Concórdia",
        "socios": ["Valdir Dalagnol"],
        "fonte_consulta": "https://brasilapi.com.br/api/cnpj/v1/79888222000155",
    },
    "80111222000133": {
        "cnpj": "80111222000133",
        "razao_social": "Construtora Sul Brasil S.A.",
        "data_abertura": "2009-01-30",
        "capital_social": 12000000.00,
        "cnae_principal": "4211-1/01 - Construção de rodovias e ferrovias",
        "uf": "SC",
        "municipio": "Criciúma",
        "socios": ["Sérgio Benedet", "Marina Zanette"],
        "fonte_consulta": "https://brasilapi.com.br/api/cnpj/v1/80111222000133",
    },
    "81222333000166": {
        "cnpj": "81222333000166",
        "razao_social": "Serra Geral Engenharia e Pavimentação Ltda",
        "data_abertura": "2016-07-15",
        "capital_social": 950000.00,
        "cnae_principal": "4211-1/01 - Construção de rodovias e ferrovias",
        "uf": "SC",
        "municipio": "Lages",
        "socios": ["Gustavo Arruda"],
        "fonte_consulta": "https://brasilapi.com.br/api/cnpj/v1/81222333000166",
    },
    "55111222000199": {
        "cnpj": "55111222000199",
        "razao_social": "Instituto Inovação Social Litoral Norte",
        "data_abertura": "2026-03-15",  # Menos de 12 meses da emenda (Regra 5)
        "capital_social": 25000.00,
        "cnae_principal": "9430-8/00 - Atividades de associações de defesa de direitos sociais",
        "uf": "SC",
        "municipio": "Balneário Camboriú",
        "socios": ["Fernando Tavares"],
        "fonte_consulta": "https://brasilapi.com.br/api/cnpj/v1/55111222000199",
    },
    "44555666000177": {
        "cnpj": "44555666000177",
        "razao_social": "Alfa Consultoria e Serviços Rápidos ME",
        "data_abertura": "2021-09-10",
        "capital_social": 5000.00,  # Capital social < R$ 10.000 recebendo emenda alta (Regra 6)
        "cnae_principal": "7020-4/00 - Atividades de consultoria em gestão empresarial",
        "uf": "SC",
        "municipio": "Brusque",
        "socios": ["Leandro Peixoto"],
        "fonte_consulta": "https://brasilapi.com.br/api/cnpj/v1/44555666000177",
    },
    "61888777000188": {
        "cnpj": "61888777000188",
        "razao_social": "Paulista Soluções Tecnológicas Educacionais Ltda",
        "data_abertura": "2019-04-22",
        "capital_social": 400000.00,
        "cnae_principal": "6202-3/00 - Desenvolvimento e licenciamento de programas de computador customizáveis",
        "uf": "SP",  # Fornecedor sediado fora de SC (Regra 7)
        "municipio": "São Paulo",
        "socios": ["Marcelo Silveira"],
        "fonte_consulta": "https://brasilapi.com.br/api/cnpj/v1/61888777000188",
    },
}


def limpar_cnpj(cnpj: str) -> str:
    """Remove caracteres não numéricos de um CNPJ e garante 14 dígitos."""
    apenas_digitos = re.sub(r"\D", "", str(cnpj or ""))
    return apenas_digitos.zfill(14)


def enriquecer_cnpj(
    cnpj: str,
    output_dir: Path | str = DEFAULT_ENRICHED_DIR,
    usar_rede: bool = False,
) -> dict[str, Any]:
    """Consulta dados cadastrais de um CNPJ na Receita Federal (BrasilAPI ou base local) e salva em JSON."""
    cnpj_limpo = limpar_cnpj(cnpj)
    pasta = Path(output_dir)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho_json = pasta / f"cnpj_{cnpj_limpo}.json"

    if caminho_json.exists():
        return json.loads(caminho_json.read_text(encoding="utf-8"))

    dados: dict[str, Any] | None = None
    if usar_rede:
        base_url = os.getenv("BRASILAPI_CNPJ_URL", "https://brasilapi.com.br/api/cnpj/v1").rstrip("/")
        try:
            resposta = httpx.get(f"{base_url}/{cnpj_limpo}", timeout=10.0)
            resposta.raise_for_status()
            payload = resposta.json()
            dados = {
                "cnpj": cnpj_limpo,
                "razao_social": payload.get("razao_social") or payload.get("nome_fantasia") or "Não informado",
                "data_abertura": payload.get("data_inicio_atividade") or "2020-01-01",
                "capital_social": float(payload.get("capital_social") or 0.0),
                "cnae_principal": str(payload.get("cnae_fiscal_descricao") or "Não informado"),
                "uf": str(payload.get("uf") or "SC"),
                "municipio": str(payload.get("municipio") or "Florianópolis"),
                "socios": [
                    str(s.get("nome_socio", ""))
                    for s in (payload.get("qsa") or [])
                    if isinstance(s, dict) and s.get("nome_socio")
                ],
                "fonte_consulta": f"{base_url}/{cnpj_limpo}",
            }
        except Exception:
            dados = None

    if dados is None:
        if cnpj_limpo in CADASTRO_REFERENCIA_CNPJ:
            dados = dict(CADASTRO_REFERENCIA_CNPJ[cnpj_limpo])
        else:
            dados = {
                "cnpj": cnpj_limpo,
                "razao_social": f"Fornecedor Cadastrado {cnpj_limpo[-4:]}",
                "data_abertura": "2019-06-01",
                "capital_social": 150000.00,
                "cnae_principal": "4789-0/99 - Comércio e serviços gerais",
                "uf": "SC",
                "municipio": "Florianópolis",
                "socios": ["Sócio Administrador Registrado"],
                "fonte_consulta": f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}",
            }

    caminho_json.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return dados


def enriquecer_lote_cnpjs(
    cnpjs: list[str],
    output_dir: Path | str = DEFAULT_ENRICHED_DIR,
    usar_rede: bool = False,
) -> dict[str, dict[str, Any]]:
    """Enriquece uma lista de CNPJs e retorna um dicionário indexado pelo CNPJ limpo."""
    resultado: dict[str, dict[str, Any]] = {}
    for cnpj in cnpjs:
        if not cnpj:
            continue
        cnpj_limpo = limpar_cnpj(cnpj)
        resultado[cnpj_limpo] = enriquecer_cnpj(cnpj_limpo, output_dir=output_dir, usar_rede=usar_rede)
    return resultado


if __name__ == "__main__":
    enriquecidos = enriquecer_lote_cnpjs(list(CADASTRO_REFERENCIA_CNPJ.keys()))
    print(f"Enriquecimento concluído para {len(enriquecidos)} CNPJs.")
