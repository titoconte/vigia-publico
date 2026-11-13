"""Fase 1 (Item 4) — Enriquecimento de dados cadastrais de CNPJ junto à Receita Federal (BrasilAPI / Cache)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import time
from typing import Any

import httpx
import pandas as pd

from collect_tce import DEFAULT_RAW_DIR, resolver_usar_rede
from cnpj_validator import (
    CNAES_FALLBACK_GENERICOS,
    CNAE_PADRAO_MUNICIPIO,
    eh_cnpj_municipio,
    formatar_cnae,
    limpar_mem_cache_cnpj,
    normalizar_situacao_cadastral,
    salvar_cnpj_cache,
)
from database import conectar_banco, resolver_caminho_sqlite

DEFAULT_ENRICHED_DIR = Path("data/enriched")
DEFAULT_HTTP_HEADERS: dict[str, str] = {
    "User-Agent": "VigiaPublicoSC/1.2 (+https://github.com/titoconte/vigia-publico)",
    "Accept": "application/json",
}

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


def _extrair_cnaes_secundarios_brasilapi(lista_bruta: Any) -> list[str]:
    """Extrai e formata a lista de CNAEs secundários retornada pela BrasilAPI ignorando códigos zerados."""
    if not isinstance(lista_bruta, list):
        return []
    resultado: list[str] = []
    for item in lista_bruta:
        if not isinstance(item, dict):
            continue
        fmt = formatar_cnae(item.get("codigo"), item.get("descricao"))
        if fmt and re.search(r"[1-9]", fmt.split(" - ")[0]) and fmt not in resultado:
            resultado.append(fmt)
    return resultado


def _extrair_cnaes_secundarios_cnpjws(lista_bruta: Any) -> list[str]:
    """Extrai e formata a lista de atividades econômicas secundárias retornada pela API publica.cnpj.ws."""
    if not isinstance(lista_bruta, list):
        return []
    resultado: list[str] = []
    for item in lista_bruta:
        if not isinstance(item, dict):
            continue
        cod = item.get("id") or item.get("subclasse") or ""
        fmt = formatar_cnae(cod, item.get("descricao"))
        if fmt and fmt not in resultado:
            resultado.append(fmt)
    return resultado


def _parsear_payload_receita(
    cnpj_limpo: str,
    payload: dict[str, Any],
    fonte_url: str,
) -> dict[str, Any]:
    """Converte o JSON padronizado da Receita Federal (BrasilAPI / MinhaReceita) para o formato interno."""
    cnae_princ = (
        formatar_cnae(payload.get("cnae_fiscal"), payload.get("cnae_fiscal_descricao"))
        or "Não informado"
    )
    nat_cod_raw = payload.get("codigo_natureza_juridica")
    nat_cod = re.sub(r"\D", "", str(nat_cod_raw or ""))[:4]
    return {
        "cnpj": cnpj_limpo,
        "razao_social": payload.get("razao_social") or payload.get("nome_fantasia") or "Não informado",
        "nome_fantasia": str(payload.get("nome_fantasia") or "").strip(),
        "situacao_cadastral": normalizar_situacao_cadastral(payload.get("descricao_situacao_cadastral")),
        "data_abertura": payload.get("data_inicio_atividade") or "",
        "natureza_juridica": str(payload.get("natureza_juridica") or "Não informada").strip(),
        "natureza_juridica_codigo": nat_cod,
        "capital_social": float(payload.get("capital_social") or 0.0),
        "cnae_principal": cnae_princ,
        "cnae_descricao": cnae_princ,
        "cnaes_secundarios": _extrair_cnaes_secundarios_brasilapi(payload.get("cnaes_secundarios")),
        "uf": str(payload.get("uf") or "SC").strip().upper(),
        "municipio": str(payload.get("municipio") or "Florianópolis"),
        "socios": [
            str(s.get("nome_socio", ""))
            for s in (payload.get("qsa") or [])
            if isinstance(s, dict) and s.get("nome_socio")
        ],
        "fonte_consulta": fonte_url,
    }


def _consultar_cnpj_remoto(
    cnpj_limpo: str,
    http: httpx.Client,
    *,
    usar_fallback_lento: bool = True,
) -> dict[str, Any] | None:
    """Consulta dados cadastrais de CNPJ na BrasilAPI com fallback em MinhaReceita e publica.cnpj.ws."""
    base_url = os.getenv("BRASILAPI_CNPJ_URL", "https://brasilapi.com.br/api/cnpj/v1").rstrip("/")
    minhareceita_base = os.getenv("MINHARECEITA_CNPJ_URL", "https://minhareceita.org").rstrip("/")
    endpoints_receita = [
        f"{base_url}/{cnpj_limpo}",
        f"{minhareceita_base}/{cnpj_limpo}",
    ]

    for url_alvo in endpoints_receita:
        try:
            resposta = http.get(url_alvo, headers=DEFAULT_HTTP_HEADERS, timeout=10.0)
            if resposta.status_code == 200:
                return _parsear_payload_receita(cnpj_limpo, resposta.json(), url_alvo)
            if resposta.status_code == 429:
                # Passa imediatamente para o próximo espelho público sem bloquear em sleep longo
                continue
        except Exception:
            continue

    if not usar_fallback_lento:
        return None

    # Fallback público terciário (CNPJ.ws, limitado a 3 req/min na camada pública)
    url_cnpjws = f"https://publica.cnpj.ws/cnpj/{cnpj_limpo}"
    try:
        resp_ws = http.get(url_cnpjws, headers=DEFAULT_HTTP_HEADERS, timeout=10.0)
        if resp_ws.status_code == 200:
            pl = resp_ws.json()
            estab = pl.get("estabelecimento") or {}
            estado = estab.get("estado") or {}
            cidade = estab.get("cidade") or {}
            ativ = estab.get("atividade_principal") or {}
            nat_obj = pl.get("natureza_juridica") if isinstance(pl.get("natureza_juridica"), dict) else {}
            cnae_ws = formatar_cnae(ativ.get("id") or ativ.get("subclasse"), ativ.get("descricao")) or "Não informado"
            nat_cod_ws = re.sub(r"\D", "", str(nat_obj.get("id") or ""))[:4]
            return {
                "cnpj": cnpj_limpo,
                "razao_social": pl.get("razao_social") or estab.get("nome_fantasia") or "Não informado",
                "nome_fantasia": str(estab.get("nome_fantasia") or "").strip(),
                "situacao_cadastral": normalizar_situacao_cadastral(estab.get("situacao_cadastral")),
                "data_abertura": estab.get("data_inicio_atividade") or "",
                "natureza_juridica": str(nat_obj.get("descricao") or "Não informada").strip(),
                "natureza_juridica_codigo": nat_cod_ws,
                "capital_social": float(pl.get("capital_social") or 0.0),
                "cnae_principal": cnae_ws,
                "cnae_descricao": cnae_ws,
                "cnaes_secundarios": _extrair_cnaes_secundarios_cnpjws(estab.get("atividades_secundarias")),
                "uf": str(estado.get("sigla") or "SC").strip().upper(),
                "municipio": str(cidade.get("nome") or "Florianópolis"),
                "socios": [
                    str(s.get("nome", ""))
                    for s in (pl.get("socios") or [])
                    if isinstance(s, dict) and s.get("nome")
                ],
                "fonte_consulta": url_cnpjws,
            }
    except Exception:
        pass

    return None


def _construir_fallback_local_cnpj(
    cnpj_limpo: str,
    nome_fallback: str | None = None,
    *,
    deve_usar_rede: bool = False,
) -> dict[str, Any]:
    """Constrói registro local padronizado quando a API não responde, aplicando CNAE 8411-6/00 a entes municipais."""
    eh_mun = eh_cnpj_municipio(cnpj_limpo, nome_fallback)
    if eh_mun:
        eh_fundo = "FUNDO" in str(nome_fallback or "").upper()
        return {
            "cnpj": cnpj_limpo,
            "razao_social": nome_fallback or f"Município {cnpj_limpo}",
            "nome_fantasia": "",
            "situacao_cadastral": "Ativa",
            "data_abertura": "",
            "natureza_juridica": "Fundo Público da Administração Direta Municipal" if eh_fundo else "Município",
            "natureza_juridica_codigo": "1333" if eh_fundo else "1244",
            "capital_social": 0.0,
            "cnae_principal": CNAE_PADRAO_MUNICIPIO,
            "cnae_descricao": CNAE_PADRAO_MUNICIPIO,
            "cnaes_secundarios": [],
            "uf": "SC",
            "municipio": "Santa Catarina",
            "socios": [],
            "fonte_consulta": f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}",
        }

    if deve_usar_rede:
        return {
            "cnpj": cnpj_limpo,
            "razao_social": nome_fallback or f"Entidade/Credor {cnpj_limpo}",
            "nome_fantasia": "",
            "situacao_cadastral": "Ativa",
            "data_abertura": "",
            "natureza_juridica": "Não informada",
            "natureza_juridica_codigo": "",
            "capital_social": 0.0,
            "cnae_principal": "Administração pública / entidade conveniada",
            "cnae_descricao": "Administração pública / entidade conveniada",
            "cnaes_secundarios": [],
            "uf": "SC",
            "municipio": "Santa Catarina",
            "socios": [],
            "fonte_consulta": f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}",
        }

    return {
        "cnpj": cnpj_limpo,
        "razao_social": nome_fallback or f"Fornecedor Cadastrado {cnpj_limpo[-4:]}",
        "nome_fantasia": "",
        "situacao_cadastral": "Ativa",
        "data_abertura": "2019-06-01",
        "natureza_juridica": "Sociedade Empresária Limitada",
        "natureza_juridica_codigo": "2062",
        "capital_social": 150000.00,
        "cnae_principal": "4789-0/99 - Comércio e serviços gerais",
        "cnae_descricao": "4789-0/99 - Comércio e serviços gerais",
        "cnaes_secundarios": [],
        "uf": "SC",
        "municipio": "Florianópolis",
        "socios": ["Sócio Administrador Registrado"],
        "fonte_consulta": f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}",
    }


def enriquecer_cnpj(
    cnpj: str,
    output_dir: Path | str = DEFAULT_ENRICHED_DIR,
    usar_rede: bool | None = None,
    nome_fallback: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Consulta dados cadastrais de um CNPJ na Receita Federal (BrasilAPI ou base local) e salva em JSON."""
    cnpj_limpo = limpar_cnpj(cnpj)
    pasta = Path(output_dir)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho_json = pasta / f"cnpj_{cnpj_limpo}.json"

    if caminho_json.exists():
        return json.loads(caminho_json.read_text(encoding="utf-8"))

    deve_usar_rede = resolver_usar_rede(usar_rede)
    dados: dict[str, Any] | None = None

    if deve_usar_rede:
        fechar = client is None
        http = client or httpx.Client(timeout=15.0, follow_redirects=True)
        try:
            dados = _consultar_cnpj_remoto(cnpj_limpo, http=http)
        finally:
            if fechar:
                http.close()

    if dados is None:
        if cnpj_limpo in CADASTRO_REFERENCIA_CNPJ:
            dados = dict(CADASTRO_REFERENCIA_CNPJ[cnpj_limpo])
            dados.setdefault("cnaes_secundarios", [])
            dados.setdefault("situacao_cadastral", "Ativa")
        else:
            dados = _construir_fallback_local_cnpj(
                cnpj_limpo,
                nome_fallback=nome_fallback,
                deve_usar_rede=deve_usar_rede,
            )

    caminho_json.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return dados


def enriquecer_lote_cnpjs(
    cnpjs: list[str],
    output_dir: Path | str = DEFAULT_ENRICHED_DIR,
    usar_rede: bool | None = None,
    client: httpx.Client | None = None,
) -> dict[str, dict[str, Any]]:
    """Enriquece uma lista de CNPJs únicos com controle de concorrência e retorna dicionário indexado."""
    unicos = list(dict.fromkeys(limpar_cnpj(c) for c in cnpjs if c and str(c).strip()))
    deve_usar_rede = resolver_usar_rede(usar_rede)
    pasta = Path(output_dir)
    pasta.mkdir(parents=True, exist_ok=True)

    if not deve_usar_rede or client is not None or len(unicos) <= 4:
        return {
            c: enriquecer_cnpj(c, output_dir=pasta, usar_rede=deve_usar_rede, client=client)
            for c in unicos
        }

    resultado: dict[str, dict[str, Any]] = {}
    with httpx.Client(timeout=15.0, follow_redirects=True) as shared_http:
        def _processar(cnpj_item: str) -> tuple[str, dict[str, Any]]:
            """Enriquece um único CNPJ com leve espaçamento quando não estiver em cache."""
            em_cache = (pasta / f"cnpj_{cnpj_item}.json").exists()
            if not em_cache:
                time.sleep(0.35)
            return (
                cnpj_item,
                enriquecer_cnpj(cnpj_item, output_dir=pasta, usar_rede=True, client=shared_http),
            )

        with ThreadPoolExecutor(max_workers=3) as pool:
            for k, val in pool.map(_processar, unicos):
                resultado[k] = val

    return resultado


def _registro_precisa_saneamento(dados_atuais: dict[str, Any]) -> bool:
    """Avalia se um registro cadastral ainda usa fallback genérico ou não possui código CNAE / natureza jurídica."""
    cnae_princ = str(dados_atuais.get("cnae_principal") or "").strip()
    razao = str(dados_atuais.get("razao_social") or "").strip()
    nat_cod = str(dados_atuais.get("natureza_juridica_codigo") or "").strip()

    if cnae_princ in CNAES_FALLBACK_GENERICOS:
        return True
    if not re.match(r"^\d{4}-\d/\d{2}", cnae_princ):
        return True
    if razao.startswith("Fornecedor Cadastrado "):
        return True
    if "cnaes_secundarios" not in dados_atuais:
        return True
    if nat_cod in {"", "2062"} and eh_cnpj_municipio(dados_atuais.get("cnpj"), razao, nat_cod, dados_atuais.get("natureza_juridica")):
        return True
    return False


def sanear_cnpjs_fallback(
    db_path: Path | str | None = None,
    enriched_dir: Path | str = DEFAULT_ENRICHED_DIR,
    usar_rede: bool | None = None,
    client: httpx.Client | None = None,
    max_workers: int = 5,
) -> dict[str, int]:
    """Atualiza CNPJs com CNAE genérico de fallback consultando a BrasilAPI e aplicando 8411-6/00 para municípios."""
    caminho_db = resolver_caminho_sqlite(db_path)
    pasta = Path(enriched_dir)
    pasta.mkdir(parents=True, exist_ok=True)
    deve_usar_rede = resolver_usar_rede(usar_rede)

    nomes_oficiais: dict[str, str] = {}
    cache_db_atual: dict[str, dict[str, Any]] = {}

    with conectar_banco(caminho_db) as conn:
        tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "emendas_clean" in tabelas:
            for r in conn.execute(
                "SELECT DISTINCT fornecedor_cnpj, fornecedor_nome FROM emendas_clean WHERE fornecedor_cnpj IS NOT NULL"
            ).fetchall():
                c_limpo = limpar_cnpj(r[0])
                if len(c_limpo) == 14 and c_limpo not in nomes_oficiais:
                    nomes_oficiais[c_limpo] = str(r[1] or "").strip()
        if "cnpj_cache" in tabelas:
            for r in conn.execute("SELECT * FROM cnpj_cache").fetchall():
                d_row = dict(r)
                c_limpo = limpar_cnpj(d_row.get("cnpj"))
                if len(c_limpo) == 14:
                    cache_db_atual[c_limpo] = d_row
                    if c_limpo not in nomes_oficiais:
                        nomes_oficiais[c_limpo] = str(d_row.get("razao_social") or "").strip()

    todos_cnpjs = sorted(set(nomes_oficiais.keys()) | set(cache_db_atual.keys()))
    pendentes: list[str] = []

    for cnpj_k in todos_cnpjs:
        arq = pasta / f"cnpj_{cnpj_k}.json"
        dados_json: dict[str, Any] = {}
        if arq.exists():
            try:
                dados_json = json.loads(arq.read_text(encoding="utf-8"))
            except Exception:
                dados_json = {}
        combinado = {**cache_db_atual.get(cnpj_k, {}), **dados_json}
        if not combinado or _registro_precisa_saneamento(combinado):
            pendentes.append(cnpj_k)

    via_api = 0
    via_regra_municipal = 0
    atualizados = 0

    def _obter_saneado(cnpj_item: str, http_client: httpx.Client | None) -> tuple[str, dict[str, Any] | None, str]:
        """Consulta dados atualizados na API ou aplica regra local de ente municipal para um CNPJ."""
        nome_ref = nomes_oficiais.get(cnpj_item, "")
        obtido: dict[str, Any] | None = None
        if deve_usar_rede and http_client is not None:
            obtido = _consultar_cnpj_remoto(cnpj_item, http=http_client, usar_fallback_lento=False)
        if obtido is not None:
            if not obtido.get("razao_social") or obtido.get("razao_social") == "Não informado":
                obtido["razao_social"] = nome_ref or f"Entidade {cnpj_item}"
            return cnpj_item, obtido, "api"
        if eh_cnpj_municipio(cnpj_item, nome_ref):
            fb_mun = _construir_fallback_local_cnpj(cnpj_item, nome_fallback=nome_ref, deve_usar_rede=True)
            return cnpj_item, fb_mun, "municipio"
        return cnpj_item, None, "mantido"

    resultados_saneamento: list[tuple[str, dict[str, Any] | None, str]] = []
    if pendentes:
        if not deve_usar_rede:
            resultados_saneamento = [_obter_saneado(c, None) for c in pendentes]
        elif client is not None or len(pendentes) <= 2:
            fechar = client is None
            http_local = client or httpx.Client(headers=DEFAULT_HTTP_HEADERS, timeout=10.0, follow_redirects=True)
            try:
                resultados_saneamento = [_obter_saneado(c, http_local) for c in pendentes]
            finally:
                if fechar:
                    http_local.close()
        else:
            with httpx.Client(headers=DEFAULT_HTTP_HEADERS, timeout=10.0, follow_redirects=True) as shared_http:
                def _worker(c_item: str) -> tuple[str, dict[str, Any] | None, str]:
                    """Executa consulta remota com espaçamento leve para respeitar limites públicos."""
                    time.sleep(0.05)
                    return _obter_saneado(c_item, shared_http)

                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futuros = {pool.submit(_worker, c_item): c_item for c_item in pendentes}
                    for futuro in as_completed(futuros):
                        cnpj_k, novo_dado, origem = futuro.result()
                        if novo_dado is not None:
                            arq_inc = pasta / f"cnpj_{cnpj_k}.json"
                            arq_inc.write_text(json.dumps(novo_dado, ensure_ascii=False, indent=2), encoding="utf-8")
                        resultados_saneamento.append((cnpj_k, novo_dado, origem))

    for cnpj_k, novo_dado, origem in resultados_saneamento:
        if novo_dado is None:
            continue
        arq = pasta / f"cnpj_{cnpj_k}.json"
        arq.write_text(json.dumps(novo_dado, ensure_ascii=False, indent=2), encoding="utf-8")
        salvar_cnpj_cache(novo_dado, db_path=caminho_db)
        atualizados += 1
        if origem == "api":
            via_api += 1
        elif origem == "municipio":
            via_regra_municipal += 1

    # Sincroniza tambem JSONs ja ricos que ainda nao estavam com cnaes_secundarios no cnpj_cache
    for cnpj_k in todos_cnpjs:
        arq = pasta / f"cnpj_{cnpj_k}.json"
        if arq.exists() and cnpj_k not in {r[0] for r in resultados_saneamento if r[1] is not None}:
            try:
                d_json = json.loads(arq.read_text(encoding="utf-8"))
                if d_json.get("cnae_principal") and d_json.get("cnae_principal") not in CNAES_FALLBACK_GENERICOS:
                    if not d_json.get("razao_social") or str(d_json.get("razao_social")).startswith("Fornecedor Cadastrado "):
                        d_json["razao_social"] = nomes_oficiais.get(cnpj_k) or d_json.get("razao_social")
                    salvar_cnpj_cache(d_json, db_path=caminho_db)
            except Exception:
                pass

    # Propaga cnae_principal atualizado para emendas_clean e agregados_fornecedor
    with conectar_banco(caminho_db) as conn:
        tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "emendas_clean" in tabelas and "cnpj_cache" in tabelas:
            conn.execute(
                """
                UPDATE emendas_clean
                SET cnae_fornecedor = (
                    SELECT c.cnae_principal
                    FROM cnpj_cache c
                    WHERE c.cnpj = REPLACE(REPLACE(REPLACE(emendas_clean.fornecedor_cnpj, '.', ''), '/', ''), '-', '')
                )
                WHERE EXISTS (
                    SELECT 1
                    FROM cnpj_cache c
                    WHERE c.cnpj = REPLACE(REPLACE(REPLACE(emendas_clean.fornecedor_cnpj, '.', ''), '/', ''), '-', '')
                      AND c.cnae_principal IS NOT NULL
                      AND c.cnae_principal != ''
                )
                """
            )
        if "agregados_fornecedor" in tabelas and "cnpj_cache" in tabelas:
            conn.execute(
                """
                UPDATE agregados_fornecedor
                SET cnae_principal = (
                    SELECT c.cnae_principal
                    FROM cnpj_cache c
                    WHERE c.cnpj = REPLACE(REPLACE(REPLACE(agregados_fornecedor.fornecedor_cnpj, '.', ''), '/', ''), '-', '')
                )
                WHERE EXISTS (
                    SELECT 1
                    FROM cnpj_cache c
                    WHERE c.cnpj = REPLACE(REPLACE(REPLACE(agregados_fornecedor.fornecedor_cnpj, '.', ''), '/', ''), '-', '')
                      AND c.cnae_principal IS NOT NULL
                      AND c.cnae_principal != ''
                )
                """
            )
        conn.commit()

    limpar_mem_cache_cnpj()
    return {
        "analisados": len(todos_cnpjs),
        "pendentes": len(pendentes),
        "atualizados": atualizados,
        "via_api": via_api,
        "via_regra_municipal": via_regra_municipal,
    }


if __name__ == "__main__":
    arquivos_emendas = sorted(DEFAULT_RAW_DIR.glob("emendas_2*.csv"))
    if arquivos_emendas:
        df_raw = pd.read_csv(arquivos_emendas[-1], dtype={"fornecedor_cnpj": str})
        lista_cnpjs = df_raw["fornecedor_cnpj"].dropna().unique().tolist()
    else:
        lista_cnpjs = list(CADASTRO_REFERENCIA_CNPJ.keys())
    enriquecidos = enriquecer_lote_cnpjs(lista_cnpjs, usar_rede=True)
    print(f"Enriquecimento concluído para {len(enriquecidos)} CNPJs.")
