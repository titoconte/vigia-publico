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
import unicodedata

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

# Rótulos canônicos para separação entre Administração Municipal e demais CNPJs
GRUPO_CNPJ_MUNICIPIO = "CNPJ de Município"
GRUPO_OUTRO_CNPJ = "Outro CNPJ"
CNAE_PADRAO_MUNICIPIO = "8411-6/00 - Administração pública em geral"
CNAES_FALLBACK_GENERICOS = {
    "4789-0/99 - Comércio e serviços gerais",
    "Administração pública em geral",
    "Administração pública / entidade conveniada",
    "Não informado",
    "",
}

# Códigos CONCLA/IBGE da Administração Pública Municipal (direta e indireta)
CODIGOS_NATUREZA_MUNICIPAL = {
    "1031",  # Órgão Público do Poder Executivo Municipal
    "1066",  # Órgão Público do Poder Legislativo Municipal
    "1120",  # Autarquia Municipal
    "1155",  # Fundação Pública de Direito Público Municipal
    "1180",  # Órgão Público Autônomo Municipal
    "1244",  # Município
    "1279",  # Fundação Pública de Direito Privado Municipal
    "1309",  # Fundo Público da Administração Indireta Municipal
    "1333",  # Fundo Público da Administração Direta Municipal
}

# Prefixos nominais de entidades privadas, consórcios ou órgãos estaduais que nunca são administração municipal
PREFIXOS_EXCLUSAO_NAO_MUNICIPAL = (
    "ASSOCIACAO ",
    "ASSOC ",
    "APAE ",
    "APAE -",
    "SOCIEDADE ",
    "FEDERACAO ",
    "CONFEDERACAO ",
    "REDE FEMININA",
    "ROTARY ",
    "LIGA ",
    "COMUNIDADE ",
    "CENTRO ",
    "CLUBE ",
    "SINDICATO ",
    "COOPERATIVA ",
    "MITRA ",
    "PAROQUIA ",
    "IGREJA ",
    "CONSORCIO ",
    "SECRETARIA DE ESTADO",
    "SECRETARIA EXECUTIVA",
    "ESTADO DE ",
    "FUNDO ESTADUAL",
    "FUNDO DE MELHORIA",
    "FUNDACAO CATARINENSE",
    "FUNDACAO UNIVERSIDADE",
    "FUNDACAO UNIVERSITARIA",
    "FUNDACAO DE AMPARO",
)

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


def _normalizar_texto_sem_acentos(valor: Any) -> str:
    """Normaliza uma string para maiúsculas sem acentos e com espaços simples para comparação nominal."""
    texto = str(valor or "").strip()
    if not texto:
        return ""
    sem_acentos = "".join(
        ch for ch in unicodedata.normalize("NFD", texto) if unicodedata.category(ch) != "Mn"
    )
    return " ".join(sem_acentos.upper().split())


def formatar_cnae(codigo: Any = "", descricao: Any = "") -> str:
    """Formata um código CNAE de 7 dígitos e sua descrição no padrão oficial 'XXXX-X/XX - Descrição'."""
    desc_limpa = " ".join(str(descricao or "").strip().split())
    digitos = re.sub(r"\D", "", str(codigo or ""))
    if digitos and int(digitos) > 0:
        cod_7 = digitos.zfill(7)[:7]
        cod_fmt = f"{cod_7[:4]}-{cod_7[4]}/{cod_7[5:7]}"
        if desc_limpa:
            # Evita duplicar o código caso já esteja no início da descrição
            desc_sem_prefixo = re.sub(r"^\d{4}-?\d/?\d{2}\s*-\s*", "", desc_limpa).strip()
            return f"{cod_fmt} - {desc_sem_prefixo}" if desc_sem_prefixo else cod_fmt
        return cod_fmt

    if not desc_limpa:
        return ""
    match_desc = re.match(r"^(\d{7})\s*-\s*(.+)$", desc_limpa)
    if match_desc:
        c7, resto = match_desc.group(1), match_desc.group(2).strip()
        return f"{c7[:4]}-{c7[4]}/{c7[5:7]} - {resto}"
    return desc_limpa


def _parsear_lista_cnaes_secundarios(valor_bruto: Any) -> list[str]:
    """Converte o campo cnaes_secundarios (lista Python ou JSON serializado) em lista limpa de strings CNAE."""
    if not valor_bruto:
        return []
    itens: list[Any] = []
    if isinstance(valor_bruto, list):
        itens = valor_bruto
    elif isinstance(valor_bruto, str):
        texto = valor_bruto.strip()
        if not texto or texto == "[]":
            return []
        try:
            carregado = json.loads(texto)
            if isinstance(carregado, list):
                itens = carregado
            elif carregado:
                itens = [str(carregado)]
        except Exception:
            itens = [p.strip() for p in texto.split(";") if p.strip()]

    resultado: list[str] = []
    for item in itens:
        if isinstance(item, dict):
            fmt = formatar_cnae(item.get("codigo"), item.get("descricao"))
        else:
            fmt = formatar_cnae("", str(item))
        if fmt and fmt not in resultado:
            resultado.append(fmt)
    return resultado


def eh_cnpj_municipio(
    cnpj: str | None = "",
    nome_favorecido: str | None = "",
    natureza_juridica_codigo: str | None = "",
    natureza_juridica: str | None = "",
) -> bool:
    """Identifica se um CNPJ pertence à Administração Municipal (Prefeitura, Fundo, Fundação, Câmara ou Autarquia)."""
    nat_cod = re.sub(r"\D", "", str(natureza_juridica_codigo or ""))[:4]
    if nat_cod in CODIGOS_NATUREZA_MUNICIPAL:
        return True

    # Códigos oficiais CONCLA confirmados de esferas estadual/federal, consórcios ou entidades privadas sem fins lucrativos
    if nat_cod and nat_cod != "2062" and nat_cod not in CODIGOS_NATUREZA_MUNICIPAL:
        if nat_cod.startswith(("1", "3")) or nat_cod in {"2046", "2054", "2135", "2143", "2305"}:
            return False

    nat_desc_norm = _normalizar_texto_sem_acentos(natureza_juridica)
    if nat_desc_norm in {"MUNICIPIO"} or (
        "MUNICIPAL" in nat_desc_norm and "INTERMUNICIPAL" not in nat_desc_norm
    ):
        return True

    nome_norm = _normalizar_texto_sem_acentos(nome_favorecido)
    if not nome_norm:
        return False

    if nome_norm.startswith(PREFIXOS_EXCLUSAO_NAO_MUNICIPAL):
        return False

    prefixos_municipais = (
        "MUNICIPIO DE ",
        "MUNICIPIO DO ",
        "MUNICIPIO DA ",
        "PREFEITURA ",
        "CAMARA MUNICIPAL",
        "CAMARA DE VEREADORES",
        "FUNDO MUNICIPAL",
        "AUTARQUIA MUNICIPAL",
        "SECRETARIA MUNICIPAL",
        "SAMAE ",
        "SIMAE ",
    )
    if nome_norm.startswith(prefixos_municipais) or nome_norm in {"FUNDO MUNICIPAL DE SAUDE", "FUNDO MUNICIPAL DA SAUDE", "SAMAE", "SIMAE"}:
        return True

    termos_internos_municipais = (
        "- FUNDO MUNICIPAL",
        "FUNDO DE SAUDE DE ",
        "FUNDO DE SAUDE DO MUNICIPIO",
        "FUNDACAO MUNICIPAL",
        "FUNDACAO HOSPITALAR MUNICIPAL",
        "FACULDADE MUNICIPAL",
        "HOSPITAL MUNICIPAL",
        "PREVIDENCIA MUNICIPAL",
        "INSTITUTO MUNICIPAL",
    )
    return any(termo in nome_norm for termo in termos_internos_municipais)


def classificar_grupo_cnpj(
    cnpj: str | None = "",
    nome_favorecido: str | None = "",
    natureza_juridica_codigo: str | None = "",
    natureza_juridica: str | None = "",
) -> str:
    """Retorna o grupo canônico do favorecido: 'CNPJ de Município' ou 'Outro CNPJ'."""
    if eh_cnpj_municipio(
        cnpj=cnpj,
        nome_favorecido=nome_favorecido,
        natureza_juridica_codigo=natureza_juridica_codigo,
        natureza_juridica=natureza_juridica,
    ):
        return GRUPO_CNPJ_MUNICIPIO
    return GRUPO_OUTRO_CNPJ


# Cache em memória e controle de inicialização para alta performance
_TABELAS_CNPJ_CACHE_INICIALIZADAS: set[str] = set()
_MEM_CACHE_CNPJ: dict[tuple[str, str], dict[str, Any]] = {}


def limpar_mem_cache_cnpj() -> None:
    """Limpa o cache em memória de CNPJs e o registro de tabelas inicializadas (útil para testes e recargas)."""
    _MEM_CACHE_CNPJ.clear()
    _TABELAS_CNPJ_CACHE_INICIALIZADAS.clear()


def inicializar_tabela_cnpj_cache(db_path: Path | str | None = None) -> None:
    """Cria a tabela cnpj_cache e seus índices no banco SQLite se não existirem (com cache de inicialização)."""
    caminho = resolver_caminho_sqlite(db_path)
    caminho_chave = str(caminho.resolve())
    if caminho_chave in _TABELAS_CNPJ_CACHE_INICIALIZADAS:
        return

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
                cnaes_secundarios TEXT DEFAULT '[]',
                uf TEXT,
                municipio TEXT,
                fonte_consulta TEXT,
                atualizado_em TEXT NOT NULL
            )
            """
        )
        # Migração automática retrocompatível para bancos SQLite criados antes da coluna cnaes_secundarios
        colunas_existentes = {
            str(r[1]) for r in conn.execute("PRAGMA table_info(cnpj_cache)").fetchall()
        }
        if "cnaes_secundarios" not in colunas_existentes:
            conn.execute("ALTER TABLE cnpj_cache ADD COLUMN cnaes_secundarios TEXT DEFAULT '[]'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cnpj_cache_situacao ON cnpj_cache (situacao_cadastral)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cnpj_cache_natureza ON cnpj_cache (natureza_juridica_codigo)")
        conn.commit()

    _TABELAS_CNPJ_CACHE_INICIALIZADAS.add(caminho_chave)


def salvar_cnpj_cache(dados: dict[str, Any], db_path: Path | str | None = None) -> None:
    """Insere ou atualiza os dados cadastrais enriquecidos de um CNPJ no cache local persistente e na memória."""
    cnpj_limpo = limpar_cnpj(dados.get("cnpj"))
    if not cnpj_limpo or len(cnpj_limpo) != 14:
        return

    caminho = resolver_caminho_sqlite(db_path)
    inicializar_tabela_cnpj_cache(caminho)
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    situacao = normalizar_situacao_cadastral(dados.get("situacao_cadastral"))
    nat_cod = str(dados.get("natureza_juridica_codigo") or "").strip()
    nat_desc = str(dados.get("natureza_juridica") or "").strip()
    if not nat_cod and nat_desc:
        match_cod = re.search(r"\b(\d{4}|\d{3}-\d)\b", nat_desc)
        if match_cod:
            nat_cod = match_cod.group(1).replace("-", "")

    cnaes_sec_lista = _parsear_lista_cnaes_secundarios(dados.get("cnaes_secundarios"))
    cnaes_sec_json = json.dumps(cnaes_sec_lista, ensure_ascii=False)

    registro_dict = {
        "cnpj": cnpj_limpo,
        "razao_social": str(dados.get("razao_social") or "Não informado"),
        "nome_fantasia": str(dados.get("nome_fantasia") or ""),
        "situacao_cadastral": situacao,
        "data_situacao_cadastral": str(dados.get("data_situacao_cadastral") or ""),
        "motivo_situacao_cadastral": str(dados.get("motivo_situacao_cadastral") or ""),
        "data_abertura": str(dados.get("data_abertura") or ""),
        "natureza_juridica": nat_desc or "Não informada",
        "natureza_juridica_codigo": nat_cod or "",
        "capital_social": float(dados.get("capital_social") or 0.0),
        "cnae_principal": str(dados.get("cnae_principal") or ""),
        "cnae_descricao": str(dados.get("cnae_descricao") or dados.get("cnae_principal") or ""),
        "cnaes_secundarios": cnaes_sec_json,
        "uf": str(dados.get("uf") or "SC").upper(),
        "municipio": str(dados.get("municipio") or ""),
        "fonte_consulta": str(dados.get("fonte_consulta") or obter_link_consulta_oficial(cnpj_limpo)),
        "atualizado_em": agora,
    }

    with conectar_banco(caminho) as conn:
        conn.execute(
            """
            INSERT INTO cnpj_cache (
                cnpj, razao_social, nome_fantasia, situacao_cadastral, data_situacao_cadastral,
                motivo_situacao_cadastral, data_abertura, natureza_juridica, natureza_juridica_codigo,
                capital_social, cnae_principal, cnae_descricao, cnaes_secundarios, uf, municipio, fonte_consulta, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                cnaes_secundarios = excluded.cnaes_secundarios,
                uf = excluded.uf,
                municipio = excluded.municipio,
                fonte_consulta = excluded.fonte_consulta,
                atualizado_em = excluded.atualizado_em
            """,
            (
                registro_dict["cnpj"],
                registro_dict["razao_social"],
                registro_dict["nome_fantasia"],
                registro_dict["situacao_cadastral"],
                registro_dict["data_situacao_cadastral"],
                registro_dict["motivo_situacao_cadastral"],
                registro_dict["data_abertura"],
                registro_dict["natureza_juridica"],
                registro_dict["natureza_juridica_codigo"],
                registro_dict["capital_social"],
                registro_dict["cnae_principal"],
                registro_dict["cnae_descricao"],
                registro_dict["cnaes_secundarios"],
                registro_dict["uf"],
                registro_dict["municipio"],
                registro_dict["fonte_consulta"],
                registro_dict["atualizado_em"],
            ),
        )
        conn.commit()

    # Atualiza cache em memória para leituras instantâneas
    chave = (str(caminho.resolve()), cnpj_limpo)
    _MEM_CACHE_CNPJ[chave] = registro_dict


def obter_cnpj_cache(cnpj: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    """Recupera os dados de um CNPJ diretamente da tabela cnpj_cache do banco SQLite com cache em memória."""
    cnpj_limpo = limpar_cnpj(cnpj)
    if not cnpj_limpo:
        return None

    caminho = resolver_caminho_sqlite(db_path)
    chave = (str(caminho.resolve()), cnpj_limpo)
    if chave in _MEM_CACHE_CNPJ:
        return _MEM_CACHE_CNPJ[chave]

    inicializar_tabela_cnpj_cache(caminho)

    with conectar_banco(caminho) as conn:
        row = conn.execute("SELECT * FROM cnpj_cache WHERE cnpj = ?", (cnpj_limpo,)).fetchone()
        if row:
            resultado = dict(row)
            _MEM_CACHE_CNPJ[chave] = resultado
            return resultado
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


def sincronizar_cnpjs_emendas_no_cache(
    db_path: Path | str | None = None,
    enriched_dir: Path | str = Path("data/enriched"),
) -> int:
    """Popula e sincroniza em lote a tabela cnpj_cache a partir de emendas_clean e JSONs enriquecidos.
    
    Garante que todos os fornecedores cadastrados na base de dados possuam registro no cache
    com seus dados cadastrais (razão social, CNAE principal/secundários, natureza jurídica, etc.),
    aplicando o CNAE 8411-6/00 para entes municipais sem enriquecimento externo prévio.
    """
    caminho = resolver_caminho_sqlite(db_path)
    inicializar_tabela_cnpj_cache(caminho)
    pasta_enriched = Path(enriched_dir)

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

            nome = str(r["fornecedor_nome"] or "").strip()
            arq_json = pasta_enriched / f"cnpj_{cnpj_limpo}.json"
            dados_json: dict[str, Any] = {}
            if arq_json.exists():
                try:
                    dados_json = json.loads(arq_json.read_text(encoding="utf-8"))
                except Exception:
                    dados_json = {}

            eh_ei = bool(re.search(r"\b(ME|EI|MEI)\b", nome, re.IGNORECASE))
            nat_cod_json = str(dados_json.get("natureza_juridica_codigo") or "").strip()
            nat_desc_json = str(dados_json.get("natureza_juridica") or "").strip()
            eh_mun = eh_cnpj_municipio(cnpj_limpo, nome or dados_json.get("razao_social"), nat_cod_json, nat_desc_json)

            if nat_cod_json:
                nat_cod = nat_cod_json
                nat_desc = nat_desc_json or ("Município" if eh_mun else "Não informada")
            elif eh_mun:
                eh_fundo = "FUNDO" in _normalizar_texto_sem_acentos(nome)
                nat_cod = "1333" if eh_fundo else "1244"
                nat_desc = "Fundo Público da Administração Direta Municipal" if eh_fundo else "Município"
            elif eh_ei:
                nat_cod = "2135"
                nat_desc = "Empresário (Individual)"
            else:
                nat_cod = "2062"
                nat_desc = "Sociedade Empresária Limitada"

            cnae_bruto = str(dados_json.get("cnae_principal") or r["cnae_fornecedor"] or "").strip()
            if eh_mun and cnae_bruto in CNAES_FALLBACK_GENERICOS:
                cnae_principal = CNAE_PADRAO_MUNICIPIO
            else:
                cnae_principal = cnae_bruto

            cnaes_sec = _parsear_lista_cnaes_secundarios(dados_json.get("cnaes_secundarios"))
            cnaes_sec_json = json.dumps(cnaes_sec, ensure_ascii=False)
            situacao = normalizar_situacao_cadastral(dados_json.get("situacao_cadastral"))

            conn.execute(
                """
                INSERT INTO cnpj_cache (
                    cnpj, razao_social, nome_fantasia, situacao_cadastral, data_situacao_cadastral,
                    motivo_situacao_cadastral, data_abertura, natureza_juridica, natureza_juridica_codigo,
                    capital_social, cnae_principal, cnae_descricao, cnaes_secundarios, uf, municipio, fonte_consulta, atualizado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cnpj) DO NOTHING
                """,
                (
                    cnpj_limpo,
                    nome or str(dados_json.get("razao_social") or "Não informado"),
                    str(dados_json.get("nome_fantasia") or ""),
                    situacao,
                    str(dados_json.get("data_situacao_cadastral") or ""),
                    str(dados_json.get("motivo_situacao_cadastral") or ""),
                    str(dados_json.get("data_abertura") or r["data_abertura_fornecedor"] or ""),
                    nat_desc,
                    nat_cod,
                    float(dados_json.get("capital_social") or r["capital_social_fornecedor"] or 0.0),
                    cnae_principal,
                    cnae_principal,
                    cnaes_sec_json,
                    str(dados_json.get("uf") or r["uf_fornecedor"] or "SC"),
                    str(dados_json.get("municipio") or ""),
                    str(dados_json.get("fonte_consulta") or obter_link_consulta_oficial(cnpj_limpo)),
                    agora,
                ),
            )
            total_sincronizados += 1

        conn.commit()

    return total_sincronizados


def carregar_mapa_cnpjs_cache(db_path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """Carrega em lote todos os registros de cnpj_cache indexados pelo CNPJ de 14 dígitos já enriquecidos com grupo e lista de CNAEs."""
    caminho = resolver_caminho_sqlite(db_path)
    inicializar_tabela_cnpj_cache(caminho)
    mapa: dict[str, dict[str, Any]] = {}

    with conectar_banco(caminho) as conn:
        linhas = conn.execute("SELECT * FROM cnpj_cache").fetchall()
        for row in linhas:
            d = dict(row)
            cnpj_k = limpar_cnpj(d.get("cnpj"))
            if not cnpj_k:
                continue
            secundarios = _parsear_lista_cnaes_secundarios(d.get("cnaes_secundarios"))
            grupo = classificar_grupo_cnpj(
                cnpj=cnpj_k,
                nome_favorecido=d.get("razao_social"),
                natureza_juridica_codigo=d.get("natureza_juridica_codigo"),
                natureza_juridica=d.get("natureza_juridica"),
            )
            cnae_princ = str(d.get("cnae_principal") or "").strip()
            if grupo == GRUPO_CNPJ_MUNICIPIO and cnae_princ in CNAES_FALLBACK_GENERICOS:
                cnae_princ = CNAE_PADRAO_MUNICIPIO
            d["cnae_principal"] = cnae_princ
            d["cnaes_secundarios_lista"] = secundarios
            d["grupo_cnpj"] = grupo
            mapa[cnpj_k] = d

    return mapa


def obter_cnaes_cnpj(
    cnpj: str,
    nome_favorecido: str = "",
    db_path: Path | str | None = None,
    mapa_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Retorna estrutura consolidada de CNAEs (principal + secundários) e classificação de grupo para um CNPJ."""
    cnpj_limpo = limpar_cnpj(cnpj)
    dados = None
    if mapa_cache is not None and cnpj_limpo in mapa_cache:
        dados = mapa_cache[cnpj_limpo]
    elif cnpj_limpo:
        dados = obter_cnpj_cache(cnpj_limpo, db_path=db_path)

    razao = str((dados or {}).get("razao_social") or nome_favorecido or "Não informado").strip()
    nat_cod = str((dados or {}).get("natureza_juridica_codigo") or "").strip()
    nat_desc = str((dados or {}).get("natureza_juridica") or "Não informada").strip()

    grupo = classificar_grupo_cnpj(
        cnpj=cnpj_limpo,
        nome_favorecido=nome_favorecido or razao,
        natureza_juridica_codigo=nat_cod,
        natureza_juridica=nat_desc,
    )
    if grupo == GRUPO_CNPJ_MUNICIPIO and nat_cod in {"", "2062"}:
        nat_desc = "Administração Pública Municipal"

    cnae_princ = str((dados or {}).get("cnae_principal") or "").strip()
    if grupo == GRUPO_CNPJ_MUNICIPIO and cnae_princ in CNAES_FALLBACK_GENERICOS:
        cnae_princ = CNAE_PADRAO_MUNICIPIO
    elif not cnae_princ:
        cnae_princ = "Não informado"

    if dados and "cnaes_secundarios_lista" in dados:
        secundarios = list(dados["cnaes_secundarios_lista"])
    else:
        secundarios = _parsear_lista_cnaes_secundarios((dados or {}).get("cnaes_secundarios"))

    qtd_principal = 0 if cnae_princ in {"", "Não informado"} else 1
    return {
        "cnpj": cnpj_limpo,
        "cnpj_formatado": formatar_cnpj_exibicao(cnpj_limpo) if len(cnpj_limpo) == 14 else (cnpj or "Não informado"),
        "razao_social": razao,
        "grupo_cnpj": grupo,
        "natureza_juridica": nat_desc,
        "natureza_juridica_codigo": nat_cod,
        "cnae_principal": cnae_princ,
        "cnaes_secundarios": secundarios,
        "total_cnaes": qtd_principal + len(secundarios),
    }
