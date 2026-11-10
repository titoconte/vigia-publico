"""Módulo de conexão e inicialização do banco de dados (SQLite local e PostgreSQL via SQLAlchemy)."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3

DEFAULT_DB_PATH = Path("data/vigia_publico.db")
SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"


def resolver_caminho_sqlite(db_path: Path | str | None = None) -> Path:
    """Resolve o caminho do banco SQLite local a partir do parâmetro ou das variáveis de ambiente."""
    if db_path is not None:
        caminho = Path(db_path)
    else:
        env_path = os.getenv("VIGIA_DB_PATH", "").strip()
        if env_path:
            caminho = Path(env_path)
        else:
            db_url = os.getenv("DATABASE_URL", "").strip()
            if db_url.startswith("sqlite:///"):
                caminho = Path(db_url.replace("sqlite:///", "", 1))
            else:
                caminho = DEFAULT_DB_PATH

    caminho.parent.mkdir(parents=True, exist_ok=True)
    return caminho


def conectar_banco(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Abre uma conexão SQLite configurada com Row factory para retorno em formato de dicionário."""
    caminho = resolver_caminho_sqlite(db_path)
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_schema(db_path: Path | str | None = None, schema_path: Path | str = SCHEMA_FILE) -> Path:
    """Executa o script schema.sql garantindo a criação das tabelas e dos índices de busca."""
    caminho_db = resolver_caminho_sqlite(db_path)
    sql_script = Path(schema_path).read_text(encoding="utf-8")
    with conectar_banco(caminho_db) as conn:
        conn.executescript(sql_script)
        conn.commit()
    return caminho_db
