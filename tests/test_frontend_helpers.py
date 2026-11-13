"""Testes unitários para a Fase 5 — Funções de carregamento, filtragem e perfis do Frontend Streamlit (app.py)."""

from __future__ import annotations

from pathlib import Path

from anomalies import executar_motor_anomalias
from app import (
    AVISO_ETICO_FRONTEND,
    calcular_valor_por_populacao_filtrada,
    carregar_dados_painel,
    carregar_estilos_customizados,
    carregar_mapa_macrorregioes_sc,
    eh_bancada_regional,
    filtrar_emendas_explorador,
    formatar_cpf_cnpj,
    obter_dados_perfil_municipio,
    obter_dados_perfil_parlamentar,
    obter_metricas_detalhadas_municipio,
    obter_quantidade_emendas_por_autor,
    obter_totais_gerais_municipios,
    obter_totais_por_ano,
    obter_totais_por_cpf_cnpj,
    obter_totais_por_macrorregiao,
    obter_totais_por_municipio,
    obter_totais_por_parlamentar,
    obter_totais_por_partido,
    obter_valor_por_populacao_municipios,
    registrar_feedback_local,
    separar_autores_por_tipo,
)
from collect_tce import executar_coleta_completa
from enrich_cnpj import CADASTRO_REFERENCIA_CNPJ, enriquecer_lote_cnpjs
from etl import executar_etl


def _preparar_banco_frontend(tmp_path: Path) -> Path:
    """Cria e popula um banco SQLite temporário para validar as visões do Streamlit."""
    raw_dir = tmp_path / "raw"
    enriched_dir = tmp_path / "enriched"
    clean_dir = tmp_path / "clean"
    db_path = tmp_path / "vigia_frontend.db"

    executar_coleta_completa(raw_dir=raw_dir, data_ref="20261110")
    enriquecer_lote_cnpjs(list(CADASTRO_REFERENCIA_CNPJ.keys()), output_dir=enriched_dir, usar_rede=False)
    executar_etl(raw_dir=raw_dir, enriched_dir=enriched_dir, clean_dir=clean_dir, db_path=db_path)
    executar_motor_anomalias(db_path=db_path)
    return db_path


def test_aviso_etico_obrigatorio_presente() -> None:
    """Verifica se a frase ética exigida está presente no banner do frontend."""
    assert (
        "Esta ferramenta não substitui a verificação documental nem a apuração oficial."
        in AVISO_ETICO_FRONTEND
    )


def test_carregar_dados_painel_e_explorador(tmp_path: Path) -> None:
    """Verifica se as 4 tabelas base são carregadas e filtradas corretamente para as Páginas 1 e 2."""
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    assert not dados["alertas"].empty
    assert not dados["emendas"].empty
    assert not dados["parlamentares"].empty
    assert not dados["municipios"].empty

    df_filtrado = filtrar_emendas_explorador(
        dados["emendas"],
        parlamentar="Todos",
        municipio="Florianópolis",
        area="Saúde",
        valor_minimo=100000.0,
    )
    assert len(df_filtrado) >= 1
    assert (df_filtrado["municipio"] == "Florianópolis").all()


def test_perfis_parlamentar_e_municipio_e_feedback(tmp_path: Path) -> None:
    """Verifica os dados das Páginas 3 (Perfil do Parlamentar) e 4 (Perfil do Município) e o feedback."""
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)

    parlamentar_nome = str(dados["parlamentares"].iloc[0]["parlamentar"])
    perfil_parl = obter_dados_perfil_parlamentar(parlamentar_nome, db_path=db_path)
    assert perfil_parl["resumo"]["parlamentar"] == parlamentar_nome
    assert not perfil_parl["por_area"].empty
    assert not perfil_parl["por_municipio"].empty
    assert "municipio" in perfil_parl["por_municipio"].columns
    assert "valor" in perfil_parl["por_municipio"].columns
    assert round(perfil_parl["por_municipio"]["valor"].sum(), 2) == round(perfil_parl["emendas"]["valor"].sum(), 2)
    assert not perfil_parl["por_cpf_cnpj"].empty
    assert "fornecedor_cnpj" in perfil_parl["por_cpf_cnpj"].columns
    assert "valor_total" in perfil_parl["por_cpf_cnpj"].columns
    assert "quantidade_emendas" in perfil_parl["por_cpf_cnpj"].columns
    assert round(perfil_parl["por_cpf_cnpj"]["valor_total"].sum(), 2) == round(perfil_parl["emendas"]["valor"].sum(), 2)
    assert perfil_parl["por_cpf_cnpj"]["quantidade_emendas"].sum() == len(perfil_parl["emendas"])

    perfil_mun = obter_dados_perfil_municipio("4218954", db_path=db_path)
    assert perfil_mun["resumo"]["municipio"] == "Urupema"
    assert perfil_mun["resumo"]["populacao"] == 2656
    assert isinstance(perfil_mun["alertas"], list)

    alerta_id = int(dados["alertas"].iloc[0]["id"])
    atualizado = registrar_feedback_local(
        alerta_id=alerta_id,
        avaliacao="util",
        comentario="Verificado pela reportagem",
        jornalista="Jornalista SC",
        db_path=db_path,
    )
    assert atualizado["util_count"] == 1


def test_eh_bancada_regional_e_separacao_autores() -> None:
    """Verifica se bancadas regionais são diferenciadas por iniciar estritamente com 'BANCADA '."""
    assert eh_bancada_regional("BANCADA DA SERRA") is True
    assert eh_bancada_regional("Bancada do Vale do Itajai") is True
    assert eh_bancada_regional("bancada do oeste") is True
    assert eh_bancada_regional("BANCADA") is False
    assert eh_bancada_regional("BANCADA_TESTE") is False
    assert eh_bancada_regional("Dep. Paulinha") is False
    assert eh_bancada_regional("Luciane Carminatti") is False
    assert eh_bancada_regional("") is False
    assert eh_bancada_regional(None) is False

    autores = [
        "BANCADA DA SERRA",
        "Dep. Paulinha",
        "BANCADA DO NORTE",
        "Ivan Naatz",
        "BANCADA DO SUL",
    ]
    separados = separar_autores_por_tipo(autores)
    assert len(separados["bancadas"]) == 3
    assert len(separados["parlamentares"]) == 2
    assert "BANCADA DA SERRA" in separados["bancadas"]
    assert "Dep. Paulinha" in separados["parlamentares"]


def test_histogramas_partido_parlamentar_ano(tmp_path: Path) -> None:
    """Verifica o cálculo correto dos histogramas por partido, por parlamentar e por ano para o Perfil Parlamentar."""
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    df_emendas = dados["emendas"]

    totais_partido = obter_totais_por_partido(df_emendas)
    assert not totais_partido.empty
    assert totais_partido.sum() == df_emendas["valor"].sum()
    assert "PSD" in totais_partido.index or "PL" in totais_partido.index or "MDB" in totais_partido.index

    totais_bancadas = obter_totais_por_parlamentar(df_emendas, tipo_autor="Bancadas")
    totais_individuais = obter_totais_por_parlamentar(df_emendas, tipo_autor="Parlamentares")
    totais_todos = obter_totais_por_parlamentar(df_emendas, tipo_autor="Todos")

    assert not totais_bancadas.empty
    assert not totais_individuais.empty
    assert len(totais_bancadas) + len(totais_individuais) == len(totais_todos)
    assert all("BANCADA" in str(nome).upper() for nome in totais_bancadas.index)
    assert all("BANCADA" not in str(nome).upper() for nome in totais_individuais.index)

    totais_ano = obter_totais_por_ano(df_emendas)
    assert not totais_ano.empty
    assert "2026" in totais_ano.index
    assert totais_ano["2026"] == df_emendas["valor"].sum()


def test_filtrar_emendas_por_tipo_autor(tmp_path: Path) -> None:
    """Verifica a filtragem de emendas separando parlamentares individuais de bancadas regionais."""
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    df_emendas = dados["emendas"]

    df_bancadas = filtrar_emendas_explorador(df_emendas, tipo_autor="Bancada Regional")
    df_individuais = filtrar_emendas_explorador(df_emendas, tipo_autor="Parlamentar Individual")
    df_todos = filtrar_emendas_explorador(df_emendas, tipo_autor="Todos")

    assert len(df_bancadas) > 0
    assert len(df_individuais) > 0
    assert len(df_bancadas) + len(df_individuais) == len(df_todos)
    assert df_bancadas["parlamentar"].apply(eh_bancada_regional).all()
    assert (~df_individuais["parlamentar"].apply(eh_bancada_regional)).all()


def test_calcular_valor_por_populacao_filtrada(tmp_path: Path) -> None:
    """Verifica o cálculo da razão valor total / população total dos municípios contemplados no Explorador."""
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    df_emendas = dados["emendas"]

    # Caso geral com base completa
    resumo_geral = calcular_valor_por_populacao_filtrada(df_emendas)
    assert resumo_geral["total_valor"] == df_emendas["valor"].sum()
    assert resumo_geral["populacao_total"] > 0
    assert resumo_geral["valor_por_habitante"] > 0
    esperado = round(resumo_geral["total_valor"] / resumo_geral["populacao_total"], 2)
    assert resumo_geral["valor_por_habitante"] == esperado

    # Caso filtrado por um município específico (Florianópolis)
    df_floripa = df_emendas[df_emendas["municipio"] == "Florianópolis"]
    resumo_floripa = calcular_valor_por_populacao_filtrada(df_floripa)
    assert resumo_floripa["total_valor"] == df_floripa["valor"].sum()
    assert resumo_floripa["populacao_total"] == 537211  # População IBGE de Florianópolis
    assert resumo_floripa["valor_por_habitante"] == round(df_floripa["valor"].sum() / 537211, 2)

    # Caso DataFrame vazio
    resumo_vazio = calcular_valor_por_populacao_filtrada(df_emendas.iloc[0:0])
    assert resumo_vazio["total_valor"] == 0.0
    assert resumo_vazio["populacao_total"] == 0
    assert resumo_vazio["valor_por_habitante"] == 0.0


def test_obter_valor_por_populacao_municipios_e_qtd_emendas(tmp_path: Path) -> None:
    """Valida a geração das séries para gráficos de Valor/População por município e Número de Emendas por autor."""
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    df_emendas = dados["emendas"]

    # 1. Gráfico de Valor / População por município
    serie_per_capita = obter_valor_por_populacao_municipios(df_emendas, top_n=10)
    assert not serie_per_capita.empty
    assert len(serie_per_capita) <= 10
    # Urupema tem população 2656 e valor alto, deve ter razão alta
    assert serie_per_capita.iloc[0] >= serie_per_capita.iloc[-1]

    # Vazio
    serie_vazia = obter_valor_por_populacao_municipios(df_emendas.iloc[0:0])
    assert serie_vazia.empty

    # 2. Gráfico de Quantidade de Emendas por Autor (separando Todos, Bancadas e Parlamentares)
    qtd_todos = obter_quantidade_emendas_por_autor(df_emendas, tipo_autor="Todos")
    qtd_bancadas = obter_quantidade_emendas_por_autor(df_emendas, tipo_autor="Bancadas")
    qtd_individuais = obter_quantidade_emendas_por_autor(df_emendas, tipo_autor="Parlamentares")

    assert not qtd_todos.empty
    assert not qtd_bancadas.empty
    assert not qtd_individuais.empty
    assert qtd_todos.sum() == len(df_emendas)
    assert qtd_bancadas.sum() + qtd_individuais.sum() == len(df_emendas)

    # Verifica se os índices contêm estritamente bancadas / individuais
    assert all(eh_bancada_regional(str(b)) for b in qtd_bancadas.index)
    assert all(not eh_bancada_regional(str(p)) for p in qtd_individuais.index)


def test_graficos_garantem_todos_municipios(tmp_path: Path) -> None:
    """Garante que todos os municípios cadastrados no estado aparecem nos gráficos analíticos quando solicitado."""
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    df_emendas = dados["emendas"]
    df_municipios = dados["municipios"]

    # 1. Total financeiro por município incluindo todos de SC
    serie_totais = obter_totais_por_municipio(df_emendas, df_municipios, incluir_todos_sc=True, top_n=None)
    assert not serie_totais.empty
    assert len(serie_totais) == len(df_municipios)
    # Todos os municípios da base estão presentes no índice
    for mun in df_municipios["municipio"]:
        assert mun in serie_totais.index

    # 2. Razão Valor / População incluindo todos de SC
    serie_per_capita = obter_valor_por_populacao_municipios(
        df_filtrado=df_emendas,
        df_todos_municipios=df_municipios,
        incluir_todos_sc=True,
        top_n=None,
    )
    assert not serie_per_capita.empty
    assert len(serie_per_capita) == len(df_municipios)
    for mun in df_municipios["municipio"]:
        assert mun in serie_per_capita.index

    # 3. Caso filtrado por um município específico (exibe apenas aquele município)
    df_apenas_um = df_emendas[df_emendas["municipio"] == "Florianópolis"]
    serie_um_mun = obter_totais_por_municipio(df_apenas_um, df_municipios, incluir_todos_sc=False, top_n=None)
    assert len(serie_um_mun) == 1
    assert "Florianópolis" in serie_um_mun.index


def test_obter_totais_por_cpf_cnpj_e_formatacao(tmp_path: Path) -> None:
    """Valida a formatação de CPF/CNPJ e agregação por documento (valor total e quantidade de emendas)."""
    # 1. Valida formatação de CPF e CNPJ
    assert formatar_cpf_cnpj("12345678901") == "123.456.789-01"
    assert formatar_cpf_cnpj("123.456.789-01") == "123.456.789-01"
    assert formatar_cpf_cnpj("83108357000115") == "83.108.357/0001-15"
    assert formatar_cpf_cnpj("83.108.357/0001-15") == "83.108.357/0001-15"
    assert formatar_cpf_cnpj("") == "Não informado"

    # 2. Valida agregação com banco de dados
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    df_emendas = dados["emendas"]

    totais_cpf = obter_totais_por_cpf_cnpj(df_emendas)
    assert not totais_cpf.empty
    assert "doc_formatado" in totais_cpf.columns
    assert "valor_total" in totais_cpf.columns
    assert "quantidade_emendas" in totais_cpf.columns

    # O total financeiro e de emendas agrupados por CPF/CNPJ deve bater com o total geral da base
    assert round(totais_cpf["valor_total"].sum(), 2) == round(df_emendas["valor"].sum(), 2)
    assert totais_cpf["quantidade_emendas"].sum() == len(df_emendas)

    # 3. Caso vazio
    vazio_cpf = obter_totais_por_cpf_cnpj(df_emendas.iloc[0:0])
    assert vazio_cpf.empty


def test_macrorregioes_ibge_sc_e_totais(tmp_path: Path) -> None:
    """Verifica o carregamento do mapa IBGE e os totais de emendas por Macrorregião de Santa Catarina."""
    # 1. Mapa de macrorregiões
    mapa = carregar_mapa_macrorregioes_sc()
    assert isinstance(mapa, dict)
    assert len(mapa) >= 295
    assert mapa.get("4205407") == "Grande Florianópolis"

    # Caso arquivo inexistente
    mapa_inexistente = carregar_mapa_macrorregioes_sc(tmp_path / "nao_existe.json")
    assert mapa_inexistente == {}

    # 2. Agregação por Macrorregião com dados reais do banco
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    df_emendas = dados["emendas"]

    totais_macro = obter_totais_por_macrorregiao(df_emendas, mapa)
    assert not totais_macro.empty
    assert "macrorregiao" in totais_macro.columns
    assert "valor_total" in totais_macro.columns
    assert "quantidade_emendas" in totais_macro.columns

    # A soma das macrorregiões deve bater 100% com o total das emendas
    assert round(totais_macro["valor_total"].sum(), 2) == round(df_emendas["valor"].sum(), 2)
    assert totais_macro["quantidade_emendas"].sum() == len(df_emendas)

    # 3. Caso de dataframe vazio
    totais_vazio = obter_totais_por_macrorregiao(df_emendas.iloc[0:0], mapa)
    assert totais_vazio.empty


def test_obter_totais_gerais_municipios(tmp_path: Path) -> None:
    """Verifica a consolidação geral de emendas por município em SC para o panorama comparativo."""
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    df_emendas = dados["emendas"]
    df_municipios = dados["municipios"]

    resultado = obter_totais_gerais_municipios(df_emendas, df_municipios)
    assert not resultado.empty
    assert len(resultado) == len(df_municipios)
    assert "municipio" in resultado.columns
    assert "valor_total" in resultado.columns
    assert "quantidade_emendas" in resultado.columns

    # Municípios com emendas devem ter valor maior que zero
    assert resultado["valor_total"].max() > 0


def test_obter_metricas_detalhadas_municipio(tmp_path: Path) -> None:
    """Verifica as 8 métricas detalhadas do município antes dos alertas (áreas, deputados, emendas, partidos, CNPJ)."""
    db_path = _preparar_banco_frontend(tmp_path)
    dados = carregar_dados_painel(db_path=db_path)
    df_emendas = dados["emendas"]

    # Testa com emendas de Florianópolis
    df_floripa = df_emendas[df_emendas["municipio"] == "Florianópolis"]
    assert not df_floripa.empty

    detalhes = obter_metricas_detalhadas_municipio(df_floripa)
    assert isinstance(detalhes, dict)

    # 1.1 e 1.2: Áreas
    assert not detalhes["por_area_valor"].empty
    assert round(detalhes["por_area_valor"]["valor_total"].sum(), 2) == round(df_floripa["valor"].sum(), 2)
    assert not detalhes["por_area_qtd"].empty
    assert detalhes["por_area_qtd"]["quantidade"].sum() == len(df_floripa)

    # 2.1 e 2.2: Deputados e Emendas Individuais
    assert not detalhes["por_deputado_valor"].empty
    assert round(detalhes["por_deputado_valor"]["valor_total"].sum(), 2) == round(df_floripa["valor"].sum(), 2)
    assert not detalhes["ranking_emendas"].empty
    assert len(detalhes["ranking_emendas"]) == len(df_floripa)
    assert "id_rotulo" in detalhes["ranking_emendas"].columns

    # 3.1 e 3.2: Partidos
    assert not detalhes["por_partido_valor"].empty
    assert round(detalhes["por_partido_valor"]["valor_total"].sum(), 2) == round(df_floripa["valor"].sum(), 2)
    assert not detalhes["por_partido_qtd"].empty
    assert detalhes["por_partido_qtd"]["quantidade"].sum() == len(df_floripa)

    # 4 e 5: CNPJ (Top 50)
    assert not detalhes["por_cnpj_total_top50"].empty
    assert len(detalhes["por_cnpj_total_top50"]) <= 50
    assert "identificador_cnpj" in detalhes["por_cnpj_total_top50"].columns
    assert "valor_total" in detalhes["por_cnpj_total_top50"].columns

    assert not detalhes["por_cnpj_maior_emenda_top50"].empty
    assert len(detalhes["por_cnpj_maior_emenda_top50"]) <= 50
    assert "identificador_cnpj" in detalhes["por_cnpj_maior_emenda_top50"].columns
    assert "maior_valor" in detalhes["por_cnpj_maior_emenda_top50"].columns

    # 6. Verifica integração com obter_dados_perfil_municipio
    perfil_mun = obter_dados_perfil_municipio("4205407", db_path=db_path)
    assert "detalhes" in perfil_mun
    assert not perfil_mun["detalhes"]["por_area_valor"].empty

    # 7. Caso de dataframe vazio
    detalhes_vazio = obter_metricas_detalhadas_municipio(df_emendas.iloc[0:0])
    assert detalhes_vazio["por_area_valor"].empty
    assert detalhes_vazio["por_cnpj_total_top50"].empty


def test_carregar_estilos_customizados_e_arquivos_tema(tmp_path: Path) -> None:
    """Verifica a integridade dos arquivos de tema Dark Mode e a injeção de CSS em carregar_estilos_customizados."""
    from unittest.mock import MagicMock

    # 1. Valida existência e diretivas de .streamlit/config.toml
    config_path = Path(".streamlit/config.toml")
    assert config_path.exists(), "O arquivo .streamlit/config.toml deve existir na raiz do projeto."
    conteudo_config = config_path.read_text(encoding="utf-8")
    assert "[theme]" in conteudo_config
    assert 'base = "dark"' in conteudo_config
    assert 'primaryColor = "#00B4D8"' in conteudo_config
    assert 'backgroundColor = "#0E1117"' in conteudo_config

    # 2. Valida existência e regras de assets/style.css
    css_path = Path("assets/style.css")
    assert css_path.exists(), "O arquivo assets/style.css deve existir."
    conteudo_css = css_path.read_text(encoding="utf-8")
    assert "data-testid=\"stMetric\"" in conteudo_css
    assert "border-top: 3px solid #00B4D8" in conteudo_css
    assert "JetBrains Mono" in conteudo_css
    assert "badge-status" in conteudo_css

    # 3. Testa injeção de CSS com Mock do Streamlit
    mock_st = MagicMock()
    carregar_estilos_customizados(mock_st, caminho_css=css_path)
    assert mock_st.markdown.called
    args, kwargs = mock_st.markdown.call_args
    assert "<style>" in args[0]
    assert "</style>" in args[0]
    assert kwargs.get("unsafe_allow_html") is True

    # 4. Testa comportamento com arquivo inexistente (graceful skip)
    mock_st_inexistente = MagicMock()
    caminho_inexistente = tmp_path / "arquivo_inexistente.css"
    carregar_estilos_customizados(mock_st_inexistente, caminho_css=caminho_inexistente)
    assert not mock_st_inexistente.markdown.called





