"""Fase 4 — API REST e Backend FastAPI do Vigia Público SC com documentação Swagger automática."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from anomalies import executar_motor_anomalias
from collect_tce import executar_coleta_completa
from database import conectar_banco, inicializar_schema, resolver_caminho_sqlite
from enrich_cnpj import CADASTRO_REFERENCIA_CNPJ, enriquecer_lote_cnpjs
from etl import executar_etl, normalizar_municipio

AVISO_ETICO_API = (
    "Esta ferramenta não substitui a verificação documental nem a apuração oficial. "
    "Os alertas representam padrões estatísticos e cadastrais que merecem verificação."
)


class FeedbackPayload(BaseModel):
    """Modelo de entrada para registro de feedback dos usuários e analistas sobre um alerta."""

    avaliacao: str = Field(
        ...,
        description="Classificação do analista/usuário: 'util' ('útil') ou 'falso_positivo' ('falso positivo').",
    )
    comentario: str | None = Field(
        default=None,
        description="Observação opcional da análise documental para calibragem das regras.",
    )
    usuario: str | None = Field(
        default=None,
        description="Identificação opcional do analista ou usuário avaliador.",
    )
    jornalista: str | None = Field(
        default=None,
        description="Identificação do avaliador (mantido para compatibilidade retroativa).",
    )


def garantir_dados_iniciais(db_path: Path | str | None = None) -> Path:
    """Garante que o banco de dados exista e esteja populado antes de responder às requisições da API."""
    caminho = resolver_caminho_sqlite(db_path)
    inicializar_schema(caminho)
    with conectar_banco(caminho) as conn:
        qtd = int(conn.execute("SELECT COUNT(*) FROM emendas_clean").fetchone()[0])
    if qtd == 0:
        executar_coleta_completa()
        enriquecer_lote_cnpjs(list(CADASTRO_REFERENCIA_CNPJ.keys()), usar_rede=False)
        executar_etl(db_path=caminho)
        executar_motor_anomalias(db_path=caminho)
    return caminho


def _normalizar_avaliacao_feedback(avaliacao: str) -> str:
    """Normaliza o texto de avaliação enviado pelo usuário/analista para 'util' ou 'falso_positivo'."""
    limpo = normalizar_municipio(avaliacao).replace("_", " ").strip()
    if limpo in ("UTIL", "RELEVANTE", "POSITIVO"):
        return "util"
    if limpo in ("FALSO POSITIVO", "FALSOPOSITIVO", "DESCARTADO"):
        return "falso_positivo"
    raise HTTPException(
        status_code=422,
        detail="O campo 'avaliacao' deve ser 'útil' ('util') ou 'falso positivo' ('falso_positivo').",
    )


def _desserializar_alerta(row_dict: dict[str, Any]) -> dict[str, Any]:
    """Converte o campo dados_contexto de string JSON para dicionário Python na resposta da API."""
    item = dict(row_dict)
    bruto = item.get("dados_contexto")
    if isinstance(bruto, str):
        try:
            item["dados_contexto"] = json.loads(bruto)
        except Exception:
            item["dados_contexto"] = {"raw": bruto}
    item["aviso_etico"] = AVISO_ETICO_API
    return item


def criar_app(db_path: Path | str | None = None) -> FastAPI:
    """Cria e configura a aplicação FastAPI com todos os endpoints documentados do Vigia Público SC."""
    app = FastAPI(
        title="Vigia Público SC — API de Monitoramento de Emendas e Anomalias",
        description=(
            "API pública e auditável para monitoramento de emendas parlamentares estaduais de "
            "Santa Catarina, controle social e auditoria cívica. "
            f"**Aviso Ético:** {AVISO_ETICO_API}"
        ),
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", tags=["Sistema"])
    def healthcheck() -> dict[str, str]:
        """Retorna o status operacional da API e o aviso ético institucional."""
        return {"status": "ok", "aviso_etico": AVISO_ETICO_API}

    @app.get("/api/emendas", tags=["Emendas"])
    def listar_emendas(
        parlamentar: str | None = Query(default=None, description="Filtra por nome parcial ou completo do parlamentar"),
        municipio: str | None = Query(default=None, description="Filtra por nome do município (com ou sem acentos)"),
        area: str | None = Query(default=None, description="Filtra pela área temática (ex.: Saúde, Educação, Infraestrutura)"),
        valor_minimo: float | None = Query(default=None, ge=0, description="Filtra emendas com valor igual ou superior"),
        tipo_autor: str | None = Query(default=None, description="Filtra por 'parlamentar' individual ou 'bancada' regional"),
        limit: int = Query(default=200, ge=1, le=1000, description="Quantidade máxima de registros retornados"),
        offset: int = Query(default=0, ge=0, description="Deslocamento para paginação"),
    ) -> list[dict[str, Any]]:
        """Lista as emendas parlamentares limpas permitindo filtros combinados por autor, bancada, município, área e valor mínimo."""
        caminho = garantir_dados_iniciais(db_path)
        clausulas: list[str] = ["1=1"]
        parametros: list[Any] = []

        if tipo_autor:
            tl = tipo_autor.strip().lower()
            if tl in ("bancada", "bancadas", "bancada regional"):
                clausulas.append("LOWER(parlamentar) LIKE 'bancada%'")
            elif tl in ("parlamentar", "parlamentares", "parlamentar individual"):
                clausulas.append("LOWER(parlamentar) NOT LIKE 'bancada%'")

        if parlamentar:
            clausulas.append("LOWER(parlamentar) LIKE ?")
            parametros.append(f"%{parlamentar.strip().lower()}%")
        if municipio:
            mun_norm = normalizar_municipio(municipio)
            clausulas.append("(municipio_normalizado LIKE ? OR codigo_ibge = ?)")
            parametros.extend([f"%{mun_norm}%", municipio.strip()])
        if area:
            clausulas.append("LOWER(area) = ?")
            parametros.append(area.strip().lower())
        if valor_minimo is not None:
            clausulas.append("valor >= ?")
            parametros.append(float(valor_minimo))

        sql = f"""
            SELECT * FROM emendas_clean
            WHERE {' AND '.join(clausulas)}
            ORDER BY valor DESC
            LIMIT ? OFFSET ?
        """
        parametros.extend([limit, offset])

        with conectar_banco(caminho) as conn:
            linhas = conn.execute(sql, parametros).fetchall()
        return [dict(r) for r in linhas]

    @app.get("/api/parlamentares", tags=["Parlamentares"])
    def listar_parlamentares(
        tipo_autor: str | None = Query(default=None, description="Filtra por 'parlamentar' individual ou 'bancada' regional"),
    ) -> list[dict[str, Any]]:
        """Lista todos os parlamentares com totais agregados, médias, principal área e concentração de fornecedor."""
        caminho = garantir_dados_iniciais(db_path)
        clausula = "1=1"
        if tipo_autor:
            tl = tipo_autor.strip().lower()
            if tl in ("bancada", "bancadas", "bancada regional"):
                clausula = "LOWER(parlamentar) LIKE 'bancada%'"
            elif tl in ("parlamentar", "parlamentares", "parlamentar individual"):
                clausula = "LOWER(parlamentar) NOT LIKE 'bancada%'"

        with conectar_banco(caminho) as conn:
            linhas = conn.execute(
                f"SELECT * FROM agregados_parlamentar WHERE {clausula} ORDER BY total_emendas DESC"
            ).fetchall()
        return [dict(r) for r in linhas]

    @app.get("/api/alertas", tags=["Alertas"])
    def listar_alertas(
        tipo: str | None = Query(default=None, description="Filtra pelo tipo ou código da regra de anomalia"),
        parlamentar: str | None = Query(default=None, description="Filtra alertas associados a um parlamentar"),
        municipio: str | None = Query(default=None, description="Filtra alertas associados a um município"),
        pontuacao_minima: float | None = Query(default=None, ge=0, le=100, description="Pontuação mínima do alerta"),
        tipo_autor: str | None = Query(default=None, description="Filtra por 'parlamentar' individual ou 'bancada' regional"),
    ) -> list[dict[str, Any]]:
        """Lista as anomalias detectadas ordenadas por pontuação decrescente com suporte a filtro por bancada ou parlamentar."""
        caminho = garantir_dados_iniciais(db_path)
        clausulas: list[str] = ["1=1"]
        parametros: list[Any] = []

        if tipo_autor:
            tl = tipo_autor.strip().lower()
            if tl in ("bancada", "bancadas", "bancada regional"):
                clausulas.append("LOWER(parlamentar) LIKE 'bancada%'")
            elif tl in ("parlamentar", "parlamentares", "parlamentar individual"):
                clausulas.append("LOWER(parlamentar) NOT LIKE 'bancada%'")

        if tipo:
            clausulas.append("(LOWER(tipo) LIKE ? OR LOWER(regra) LIKE ?)")
            termo = f"%{tipo.strip().lower()}%"
            parametros.extend([termo, termo])
        if parlamentar:
            clausulas.append("LOWER(parlamentar) LIKE ?")
            parametros.append(f"%{parlamentar.strip().lower()}%")
        if municipio:
            clausulas.append("(UPPER(municipio) LIKE ? OR codigo_ibge = ?)")
            parametros.extend([f"%{municipio.strip().upper()}%", municipio.strip()])
        if pontuacao_minima is not None:
            clausulas.append("pontuacao >= ?")
            parametros.append(float(pontuacao_minima))

        sql = f"""
            SELECT * FROM alertas
            WHERE {' AND '.join(clausulas)}
            ORDER BY pontuacao DESC, valor DESC
        """
        with conectar_banco(caminho) as conn:
            linhas = conn.execute(sql, parametros).fetchall()
        return [_desserializar_alerta(dict(r)) for r in linhas]

    @app.get("/api/alertas/{id}", tags=["Alertas"])
    def obter_detalhe_alerta(id: int) -> dict[str, Any]:
        """Retorna os detalhes completos de um alerta com justificativa, dados de contexto, fonte e feedbacks."""
        caminho = garantir_dados_iniciais(db_path)
        with conectar_banco(caminho) as conn:
            linha = conn.execute("SELECT * FROM alertas WHERE id = ?", (id,)).fetchone()
            if not linha:
                raise HTTPException(status_code=404, detail=f"Alerta {id} não encontrado.")
            feedbacks = conn.execute(
                "SELECT * FROM alertas_feedback WHERE alerta_id = ? ORDER BY id DESC",
                (id,),
            ).fetchall()

        detalhe = _desserializar_alerta(dict(linha))
        detalhe["feedbacks"] = [dict(f) for f in feedbacks]
        return detalhe

    @app.get("/api/municipios", tags=["Municípios"])
    def listar_municipios() -> list[dict[str, Any]]:
        """Lista todos os municípios catarinenses monitorados com população, total recebido e valor per capita."""
        caminho = garantir_dados_iniciais(db_path)
        with conectar_banco(caminho) as conn:
            linhas = conn.execute(
                "SELECT * FROM agregados_municipio ORDER BY total_recebido DESC, populacao DESC"
            ).fetchall()
        return [dict(r) for r in linhas]

    @app.get("/api/municipios/{codigo}", tags=["Municípios"])
    def obter_perfil_municipio(codigo: str) -> dict[str, Any]:
        """Retorna o perfil consolidado de um município (população, total recebido, per capita, emendas e alertas)."""
        caminho = garantir_dados_iniciais(db_path)
        termo_norm = normalizar_municipio(codigo)
        with conectar_banco(caminho) as conn:
            mun = conn.execute(
                """
                SELECT * FROM agregados_municipio
                WHERE codigo_ibge = ? OR municipio_normalizado = ?
                """,
                (codigo.strip(), termo_norm),
            ).fetchone()
            if not mun:
                raise HTTPException(status_code=404, detail=f"Município '{codigo}' não encontrado.")

            mun_dict = dict(mun)
            cod_ibge = str(mun_dict["codigo_ibge"])
            emendas = conn.execute(
                "SELECT * FROM emendas_clean WHERE codigo_ibge = ? ORDER BY valor DESC",
                (cod_ibge,),
            ).fetchall()
            alertas = conn.execute(
                "SELECT * FROM alertas WHERE codigo_ibge = ? ORDER BY pontuacao DESC",
                (cod_ibge,),
            ).fetchall()

        mun_dict["emendas"] = [dict(e) for e in emendas]
        mun_dict["alertas"] = [_desserializar_alerta(dict(a)) for a in alertas]
        mun_dict["aviso_etico"] = AVISO_ETICO_API
        return mun_dict

    @app.post("/api/alertas/{id}/feedback", tags=["Alertas"])
    def registrar_feedback_alerta(id: int, payload: FeedbackPayload) -> dict[str, Any]:
        """Registra a avaliação de um usuário/analista ('útil' ou 'falso positivo') para calibragem futura das regras."""
        caminho = garantir_dados_iniciais(db_path)
        avaliacao_norm = _normalizar_avaliacao_feedback(payload.avaliacao)
        agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        identificador_autor = payload.usuario or payload.jornalista

        with conectar_banco(caminho) as conn:
            alerta = conn.execute("SELECT * FROM alertas WHERE id = ?", (id,)).fetchone()
            if not alerta:
                raise HTTPException(status_code=404, detail=f"Alerta {id} não encontrado.")

            conn.execute(
                """
                INSERT INTO alertas_feedback (alerta_id, avaliacao, comentario, jornalista, criado_em)
                VALUES (?, ?, ?, ?, ?)
                """,
                (id, avaliacao_norm, payload.comentario, identificador_autor, agora),
            )
            if avaliacao_norm == "util":
                conn.execute("UPDATE alertas SET util_count = util_count + 1 WHERE id = ?", (id,))
            else:
                conn.execute(
                    "UPDATE alertas SET falso_positivo_count = falso_positivo_count + 1 WHERE id = ?",
                    (id,),
                )
            conn.commit()
            atualizado = conn.execute("SELECT * FROM alertas WHERE id = ?", (id,)).fetchone()

        resultado = _desserializar_alerta(dict(atualizado))
        resultado["ultimo_feedback"] = {
            "avaliacao": avaliacao_norm,
            "comentario": payload.comentario,
            "usuario": identificador_autor,
            "jornalista": identificador_autor,
            "criado_em": agora,
        }
        return resultado

    return app


app = criar_app()
