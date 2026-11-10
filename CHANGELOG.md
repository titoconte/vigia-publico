# Changelog

Todas as mudanças notáveis neste projeto serão documentadas neste arquivo.
O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

## [1.0.0] - 2026-11-10

### Adicionado
- **Fase 1 (Coleta de Dados):** Scripts `collect_tce.py` (emendas TCE/SC, estimativa populacional IBGE e Dados Abertos SC) e `enrich_cnpj.py` (enriquecimento cadastral de CNPJs com data de abertura, capital social, CNAE e sócios).
- **Fase 2 (Limpeza e Modelagem ETL):** `schema.sql`, `database.py` e `etl.py` com normalização de municípios sem acentos, cálculo de `valor_per_capita`, tabelas limpas (`emendas_clean`) e agregadas (`agregados_parlamentar`, `agregados_municipio`, `agregados_fornecedor`) com índices de performance.
- **Fase 3 (Motor de Anomalias):** `anomalies.py` implementando as 7 regras de detecção (Valor Absoluto P95, Valor Per Capita > Média + 2DP, Concentração de Fornecedor > 80%, Concentração Temporal > 70%, CNPJ Recém-Criado < 12 meses, Capital Social Baixo < R$ 10.000 e Discrepância Geográfica UF ≠ SC) com justificativa ética e hash SHA-256.
- **Fase 4 (API e Backend FastAPI):** `main.py` com documentação automática Swagger e endpoints `/api/emendas`, `/api/parlamentares`, `/api/alertas`, `/api/alertas/{id}`, `/api/municipios/{codigo}` e `POST /api/alertas/{id}/feedback`.
- **Fase 5 (Frontend Streamlit):** `app.py` com 4 páginas interativas (Painel de Alertas, Explorador de Emendas, Perfil do Parlamentar e Perfil do Município) e aviso ético permanente.
- **Fase 6 (Alertas Automáticos):** `scheduler.py` (execução semanal às segundas-feiras 8h, geração de relatório HTML Top 10 e envio SMTP) e `telegram_bot.py` (comandos `/alertas` e `/parlamentar <nome>`).
- **Fases 7 e 8 (Testes, Validação e Deploy):** Suíte completa de testes unitários e de integração em `tests/` (Pytest + HTTPX), validação manual e feedback de jornalistas em `feedback.md`, GitHub Actions CI (`.github/workflows/ci.yml`), `Dockerfile`, `railway.json` e `render.yaml`.
