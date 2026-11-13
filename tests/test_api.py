"""Testes unitários e de integração da Fase 4 — Endpoints da API FastAPI (usando pytest + httpx/TestClient)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from anomalies import executar_motor_anomalias
from collect_tce import executar_coleta_completa
from enrich_cnpj import CADASTRO_REFERENCIA_CNPJ, enriquecer_lote_cnpjs
from etl import executar_etl
from main import criar_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Inicializa um banco de teste populado pelo pipeline completo e retorna o TestClient(httpx)."""
    raw_dir = tmp_path / "raw"
    enriched_dir = tmp_path / "enriched"
    clean_dir = tmp_path / "clean"
    db_path = tmp_path / "vigia_api_test.db"

    monkeypatch.setenv("VIGIA_DB_PATH", str(db_path))
    executar_coleta_completa(raw_dir=raw_dir, data_ref="20261110")
    enriquecer_lote_cnpjs(list(CADASTRO_REFERENCIA_CNPJ.keys()), output_dir=enriched_dir, usar_rede=False)
    executar_etl(raw_dir=raw_dir, enriched_dir=enriched_dir, clean_dir=clean_dir, db_path=db_path)
    executar_motor_anomalias(db_path=db_path)

    app = criar_app(db_path=db_path)
    return TestClient(app)


def test_get_api_emendas_com_filtros(client: TestClient) -> None:
    """Verifica listagem de emendas e filtros por parlamentar, município, área e valor_minimo."""
    resp_all = client.get("/api/emendas")
    assert resp_all.status_code == 200
    emendas = resp_all.json()
    assert len(emendas) >= 20

    resp_filtro = client.get(
        "/api/emendas",
        params={"municipio": "Florianopolis", "area": "Saúde", "valor_minimo": 500000},
    )
    assert resp_filtro.status_code == 200
    filtradas = resp_filtro.json()
    assert len(filtradas) >= 1
    for item in filtradas:
        assert item["area"] == "Saúde"
        assert item["valor"] >= 500000


def test_get_api_parlamentares_agregados(client: TestClient) -> None:
    """Verifica se GET /api/parlamentares retorna os parlamentares com totais agregados."""
    resp = client.get("/api/parlamentares")
    assert resp.status_code == 200
    parlamentares = resp.json()
    assert len(parlamentares) >= 5
    primeiro = parlamentares[0]
    for campo in ("parlamentar", "total_emendas", "quantidade_emendas", "media_valor", "principal_area"):
        assert campo in primeiro
    assert parlamentares[0]["total_emendas"] >= parlamentares[-1]["total_emendas"]


def test_get_api_alertas_e_detalhe_alerta(client: TestClient) -> None:
    """Verifica GET /api/alertas ordenados por pontuação e GET /api/alertas/{id} com contexto."""
    resp = client.get("/api/alertas")
    assert resp.status_code == 200
    alertas = resp.json()
    assert len(alertas) >= 2
    scores = [a["pontuacao"] for a in alertas]
    assert scores == sorted(scores, reverse=True)

    alerta_id = alertas[0]["id"]
    resp_detalhe = client.get(f"/api/alertas/{alerta_id}")
    assert resp_detalhe.status_code == 200
    detalhe = resp_detalhe.json()
    assert detalhe["id"] == alerta_id
    assert isinstance(detalhe["dados_contexto"], dict)
    assert "justificativa" in detalhe
    assert "fonte_url" in detalhe

    resp_404 = client.get("/api/alertas/999999")
    assert resp_404.status_code == 404


def test_get_api_municipio_perfil_completo(client: TestClient) -> None:
    """Verifica GET /api/municipios/{codigo} retornando população, total recebido, emendas e alertas."""
    resp = client.get("/api/municipios/4218954")  # Urupema
    assert resp.status_code == 200
    perfil = resp.json()
    assert perfil["codigo_ibge"] == "4218954"
    assert perfil["populacao"] == 2656
    assert perfil["total_recebido"] > 0
    assert perfil["valor_per_capita"] > 0
    assert isinstance(perfil["emendas"], list)
    assert len(perfil["emendas"]) >= 1
    assert isinstance(perfil["alertas"], list)


def test_post_api_alerta_feedback_util_e_falso_positivo(client: TestClient) -> None:
    """Verifica POST /api/alertas/{id}/feedback para marcar alerta como útil ou falso positivo."""
    alertas = client.get("/api/alertas").json()
    alerta_id = alertas[0]["id"]

    resp_util = client.post(
        f"/api/alertas/{alerta_id}/feedback",
        json={"avaliacao": "útil", "comentario": "Pauta relevante sobre concentração.", "jornalista": "Redação SC"},
    )
    assert resp_util.status_code == 200
    dados_util = resp_util.json()
    assert dados_util["util_count"] == 1
    assert dados_util["falso_positivo_count"] == 0

    resp_fp = client.post(
        f"/api/alertas/{alerta_id}/feedback",
        json={"avaliacao": "falso positivo", "comentario": "Consórcio regional justificado."},
    )
    assert resp_fp.status_code == 200
    dados_fp = resp_fp.json()
    assert dados_fp["util_count"] == 1
    assert dados_fp["falso_positivo_count"] == 1

    resp_invalido = client.post(
        f"/api/alertas/{alerta_id}/feedback",
        json={"avaliacao": "invalido"},
    )
    assert resp_invalido.status_code == 422


def test_filtros_por_tipo_autor_bancada_vs_parlamentar(client: TestClient) -> None:
    """Verifica se os endpoints /api/emendas, /api/parlamentares e /api/alertas filtram por tipo_autor."""
    resp_bancadas = client.get("/api/emendas", params={"tipo_autor": "bancada"})
    assert resp_bancadas.status_code == 200
    emendas_bancada = resp_bancadas.json()
    assert len(emendas_bancada) > 0
    assert all("bancada" in e["parlamentar"].lower() for e in emendas_bancada)

    resp_individuais = client.get("/api/emendas", params={"tipo_autor": "parlamentar"})
    assert resp_individuais.status_code == 200
    emendas_indiv = resp_individuais.json()
    assert len(emendas_indiv) > 0
    assert all("bancada" not in e["parlamentar"].lower() for e in emendas_indiv)

    resp_parl_bancadas = client.get("/api/parlamentares", params={"tipo_autor": "bancada"})
    assert resp_parl_bancadas.status_code == 200
    assert len(resp_parl_bancadas.json()) > 0
    assert all("bancada" in p["parlamentar"].lower() for p in resp_parl_bancadas.json())

    resp_alertas_bancada = client.get("/api/alertas", params={"tipo_autor": "bancada"})
    assert resp_alertas_bancada.status_code == 200
    for alerta in resp_alertas_bancada.json():
        assert "bancada" in alerta["parlamentar"].lower()
