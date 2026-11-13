"""Testes unitários para a Fase 3 — Motor de Anomalias (todas as 7 regras com dados sintéticos e conformidade ética)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from anomalies import (
    executar_motor_anomalias,
    regra_beneficiario_recem_criado,
    regra_capital_social_baixo,
    regra_concentracao_fornecedor,
    regra_concentracao_temporal,
    regra_discrepancia_geografica,
    regra_triplo_desvio_valor_per_capita_area,
    regra_valor_absoluto_alto,
    regra_valor_area_acima_media_1std,
    regra_valor_per_capita_alto,
)
from collect_tce import executar_coleta_completa
from enrich_cnpj import CADASTRO_REFERENCIA_CNPJ, enriquecer_lote_cnpjs
from etl import executar_etl


def _criar_df_sintetico_base() -> pd.DataFrame:
    """Cria um DataFrame sintético de emendas para testar isoladamente cada regra do motor de anomalias."""
    linhas = []
    for i in range(1, 21):
        linhas.append(
            {
                "id_emenda": f"SIN-{i:03d}",
                "parlamentar": f"Dep. Sintético {i % 5}",
                "partido": "PSD",
                "valor": 100000.0 + (i * 5000.0),
                "municipio": "Florianópolis",
                "municipio_normalizado": "FLORIANOPOLIS",
                "codigo_ibge": "4205407",
                "populacao": 500000,
                "valor_per_capita": (100000.0 + (i * 5000.0)) / 500000.0,
                "entidade_beneficiaria": f"Entidade {i}",
                "area": "Saúde",
                "data": f"2026-0{(i % 6) + 1}-15",
                "ano_mes": f"2026-0{(i % 6) + 1}",
                "fornecedor_nome": f"Fornecedor {i}",
                "fornecedor_cnpj": f"{10000000000100 + i:014d}",
                "uf_fornecedor": "SC",
                "data_abertura_fornecedor": "2015-01-10",
                "capital_social_fornecedor": 500000.0,
                "cnae_fornecedor": "8610-1/01 - Atividades de atendimento hospitalar",
                "status_execucao": "Pago",
                "fonte_url": f"https://www.tcesc.tc.br/painel-emendas?id=SIN-{i:03d}",
            }
        )
    return pd.DataFrame(linhas)


def test_regra_1_valor_absoluto_alto_acima_percentil_95() -> None:
    """Verifica se a Regra 1 detecta emenda com valor individual acima do percentil 95."""
    df = _criar_df_sintetico_base()
    df.loc[len(df)] = {
        **df.iloc[0].to_dict(),
        "id_emenda": "SIN-OUTLIER",
        "parlamentar": "Dep. Outlier Valor",
        "valor": 8000000.0,
    }
    alertas = regra_valor_absoluto_alto(df)
    assert len(alertas) >= 1
    alerta_top = alertas[0]
    assert alerta_top["parlamentar"] == "Dep. Outlier Valor"
    assert 0 < alerta_top["pontuacao"] <= 100
    assert "percentil 95" in alerta_top["justificativa"].lower()


def test_regra_2_valor_per_capita_alto_acima_media_mais_2dp() -> None:
    """Verifica se a Regra 2 detecta valor_per_capita acima da média estadual + 2 desvios padrão."""
    df = _criar_df_sintetico_base()
    df.loc[len(df)] = {
        **df.iloc[0].to_dict(),
        "id_emenda": "SIN-PERCAPITA",
        "parlamentar": "Dep. Per Capita",
        "municipio": "Urupema",
        "codigo_ibge": "4218954",
        "populacao": 2000,
        "valor": 3000000.0,
        "valor_per_capita": 1500.0,
    }
    alertas = regra_valor_per_capita_alto(df)
    assert len(alertas) == 1
    assert alertas[0]["parlamentar"] == "Dep. Per Capita"
    assert 0 < alertas[0]["pontuacao"] <= 100
    assert "desvios padrão" in alertas[0]["justificativa"].lower()


def test_regra_3_concentracao_fornecedor_acima_80_porcento() -> None:
    """Verifica se a Regra 3 detecta parlamentar que destinou >80% do total a um único fornecedor."""
    df = _criar_df_sintetico_base()
    novas = [
        {
            **df.iloc[0].to_dict(),
            "id_emenda": "SIN-CONC-1",
            "parlamentar": "Dep. Concentrador",
            "valor": 900000.0,
            "fornecedor_nome": "Fornecedor Único S.A.",
            "fornecedor_cnpj": "99888777000166",
            "entidade_beneficiaria": "Fornecedor Único S.A.",
        },
        {
            **df.iloc[0].to_dict(),
            "id_emenda": "SIN-CONC-2",
            "parlamentar": "Dep. Concentrador",
            "valor": 100000.0,
            "fornecedor_nome": "Outro Fornecedor Ltda",
            "fornecedor_cnpj": "11222333000144",
            "entidade_beneficiaria": "Outro Fornecedor Ltda",
        },
    ]
    df = pd.concat([df, pd.DataFrame(novas)], ignore_index=True)
    alertas = regra_concentracao_fornecedor(df)
    assert any(a["parlamentar"] == "Dep. Concentrador" for a in alertas)
    alerta = next(a for a in alertas if a["parlamentar"] == "Dep. Concentrador")
    assert 0 < alerta["pontuacao"] <= 100
    assert "90.0%" in alerta["justificativa"] or "90%" in alerta["justificativa"]


def test_regra_4_concentracao_temporal_acima_70_porcento_mes() -> None:
    """Verifica se a Regra 4 detecta parlamentar que destinou >70% do valor anual em um único mês."""
    df = _criar_df_sintetico_base()
    novas = [
        {
            **df.iloc[0].to_dict(),
            "id_emenda": "SIN-TEMP-1",
            "parlamentar": "Dep. Sazonal",
            "valor": 800000.0,
            "data": "2026-10-05",
            "ano_mes": "2026-10",
        },
        {
            **df.iloc[0].to_dict(),
            "id_emenda": "SIN-TEMP-2",
            "parlamentar": "Dep. Sazonal",
            "valor": 150000.0,
            "data": "2026-03-10",
            "ano_mes": "2026-03",
        },
    ]
    df = pd.concat([df, pd.DataFrame(novas)], ignore_index=True)
    alertas = regra_concentracao_temporal(df)
    assert any(a["parlamentar"] == "Dep. Sazonal" for a in alertas)
    alerta = next(a for a in alertas if a["parlamentar"] == "Dep. Sazonal")
    assert 0 < alerta["pontuacao"] <= 100
    assert "2026-10" in alerta["justificativa"]


def test_regra_5_beneficiario_recem_criado_menos_12_meses() -> None:
    """Verifica se a Regra 5 detecta entidade/fornecedor com CNPJ aberto há menos de 12 meses."""
    df = _criar_df_sintetico_base()
    df.loc[len(df)] = {
        **df.iloc[0].to_dict(),
        "id_emenda": "SIN-NOVO-CNPJ",
        "parlamentar": "Dep. Novo CNPJ",
        "data": "2026-08-15",
        "data_abertura_fornecedor": "2026-02-10",
        "fornecedor_nome": "Associação Recém Criada",
        "fornecedor_cnpj": "55111222000199",
    }
    alertas = regra_beneficiario_recem_criado(df)
    assert len(alertas) == 1
    assert alertas[0]["parlamentar"] == "Dep. Novo CNPJ"
    assert 0 < alertas[0]["pontuacao"] <= 100
    assert "meses" in alertas[0]["justificativa"].lower()


def test_regra_6_fornecedor_capital_social_baixo() -> None:
    """Verifica se a Regra 6 detecta fornecedor com capital social < R$ 10.000 recebendo valor alto."""
    df = _criar_df_sintetico_base()
    df.loc[len(df)] = {
        **df.iloc[0].to_dict(),
        "id_emenda": "SIN-CAP-BAIXO",
        "parlamentar": "Dep. Capital Baixo",
        "valor": 600000.0,
        "capital_social_fornecedor": 3000.0,
        "fornecedor_nome": "Microempresa Capital Baixo ME",
        "fornecedor_cnpj": "44555666000177",
    }
    alertas = regra_capital_social_baixo(df)
    assert len(alertas) == 1
    assert alertas[0]["parlamentar"] == "Dep. Capital Baixo"
    assert 0 < alertas[0]["pontuacao"] <= 100
    assert "capital social" in alertas[0]["justificativa"].lower()


def test_regra_7_discrepancia_geografica_outro_estado() -> None:
    """Verifica se a Regra 7 detecta fornecedor sediado fora de SC recebendo emenda para município de SC."""
    df = _criar_df_sintetico_base()
    df.loc[len(df)] = {
        **df.iloc[0].to_dict(),
        "id_emenda": "SIN-UF-FORA",
        "parlamentar": "Dep. Interestadual",
        "municipio": "Joinville",
        "uf_fornecedor": "SP",
        "fornecedor_nome": "Empresa Paulista Ltda",
        "fornecedor_cnpj": "61888777000188",
    }
    alertas = regra_discrepancia_geografica(df)
    assert len(alertas) == 1
    assert alertas[0]["parlamentar"] == "Dep. Interestadual"
    assert 0 < alertas[0]["pontuacao"] <= 100
    assert "sp" in alertas[0]["justificativa"].lower()


def test_regra_triplo_desvio_valor_per_capita_area() -> None:
    """Verifica se a Regra 1 exige os 3 requisitos simultâneos: valor alto, per capita alto e área alta."""
    df = _criar_df_sintetico_base()

    # Caso 1: Atende aos 3 requisitos simultâneos (município pequeno, valor elevado e área específica)
    df_triplo = df.copy()
    df_triplo.loc[len(df_triplo)] = {
        **df_triplo.iloc[0].to_dict(),
        "id_emenda": "SIN-TRIPLO-SIM",
        "parlamentar": "Dep. Triplo Desvio",
        "municipio": "Urupema",
        "codigo_ibge": "4218954",
        "populacao": 2500,
        "valor": 3000000.0,
        "valor_per_capita": 3000000.0 / 2500,
        "area": "Saúde",
    }
    alertas = regra_triplo_desvio_valor_per_capita_area(df_triplo)
    assert len(alertas) >= 1
    alerta_hit = next((a for a in alertas if a["parlamentar"] == "Dep. Triplo Desvio"), None)
    assert alerta_hit is not None
    assert alerta_hit["regra"] == "REGRA_1_TRIPLO_DESVIO_VALOR_PER_CAPITA_AREA"
    assert "3 requisitos" in alerta_hit["justificativa"].lower()
    assert 80.0 <= alerta_hit["pontuacao"] <= 100.0

    # Caso 2: Emenda com valor alto e área alta, mas em município enorme com per capita baixo
    df_falha_pc = df.copy()
    df_falha_pc.loc[len(df_falha_pc)] = {
        **df_falha_pc.iloc[0].to_dict(),
        "id_emenda": "SIN-FALHA-PC",
        "parlamentar": "Dep. Falha Per Capita",
        "municipio": "Joinville",
        "codigo_ibge": "4209102",
        "populacao": 6000000,
        "valor": 250000.0,
        "valor_per_capita": 250000.0 / 6000000,
        "area": "Saúde",
    }
    alertas_falha = regra_triplo_desvio_valor_per_capita_area(df_falha_pc)
    assert not any(a["parlamentar"] == "Dep. Falha Per Capita" for a in alertas_falha)


def test_regra_valor_area_acima_media_1std() -> None:
    """Verifica se a Regra 2 detecta emenda cujo valor na respectiva área supera a média setorial + 1 STD."""
    df = _criar_df_sintetico_base()
    # Adiciona emendas normais na área de Educação e uma outlier expressiva
    novas_educ = [
        {**df.iloc[0].to_dict(), "id_emenda": f"SIN-EDU-{i}", "area": "Educação", "valor": 100000.0}
        for i in range(5)
    ]
    novas_educ.append(
        {
            **df.iloc[0].to_dict(),
            "id_emenda": "SIN-AREA-ALTO",
            "parlamentar": "Dep. Destaque Area",
            "area": "Educação",
            "valor": 2500000.0,
        }
    )
    df_area = pd.concat([df, pd.DataFrame(novas_educ)], ignore_index=True)
    alertas = regra_valor_area_acima_media_1std(df_area)
    assert len(alertas) >= 1
    alerta_hit = next((a for a in alertas if a["parlamentar"] == "Dep. Destaque Area"), None)
    assert alerta_hit is not None
    assert alerta_hit["regra"] == "REGRA_2_VALOR_AREA_ACIMA_MEDIA_1STD"
    assert "educação" in alerta_hit["justificativa"].lower()
    assert 70.0 <= alerta_hit["pontuacao"] <= 100.0


def test_executar_motor_anomalias_persiste_alertas_e_respeita_etica(tmp_path: Path) -> None:
    """Verifica se a execução completa do motor de anomalias salva alertas ordenados e sem termos acusatórios."""
    raw_dir = tmp_path / "raw"
    enriched_dir = tmp_path / "enriched"
    clean_dir = tmp_path / "clean"
    db_path = tmp_path / "vigia_anomalies.db"

    executar_coleta_completa(raw_dir=raw_dir, data_ref="20261110")
    enriquecer_lote_cnpjs(list(CADASTRO_REFERENCIA_CNPJ.keys()), output_dir=enriched_dir, usar_rede=False)
    executar_etl(raw_dir=raw_dir, enriched_dir=enriched_dir, clean_dir=clean_dir, db_path=db_path)

    alertas = executar_motor_anomalias(db_path=db_path)
    assert len(alertas) >= 2
    pontuacoes = [a["pontuacao"] for a in alertas]
    assert pontuacoes == sorted(pontuacoes, reverse=True)

    regras_acionadas = {a["regra"] for a in alertas}
    assert len(regras_acionadas) >= 1

    termos_proibidos = ("corrupção", "fraude comprovada", "crime", "desvio ilegal", "culpado")
    for alerta in alertas:
        texto = alerta["justificativa"].lower()
        for proibido in termos_proibidos:
            assert proibido not in texto
        assert alerta["fonte_url"].startswith("https://")
        assert len(alerta["hash_auditoria"]) == 64
