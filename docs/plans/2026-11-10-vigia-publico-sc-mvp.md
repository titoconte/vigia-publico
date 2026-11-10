# Vigia Público SC — Plano de Implementação e Contratos (MVP)

> **Skills Aplicadas:** `creating-and-documenting-projects`, `writing-plans`, `test-driven-development`

**Goal:** Construir o MVP completo do **Vigia Público SC**, permitindo que jornalistas de Santa Catarina monitorem emendas parlamentares estaduais, identifiquem padrões atípicos com transparência e recebam alertas semanais auditáveis.

**Architecture:** Pipeline modular em Python 3.11+ composto por Coleta (`collect_tce.py`, `enrich_cnpj.py`), Limpeza/Modelagem (`etl.py`, `schema.sql`, `database.py`), Motor de Anomalias (`anomalies.py` com 7 regras auditáveis e assinatura SHA-256), Backend REST (`main.py` em FastAPI), Frontend interativo de 4 páginas (`app.py` em Streamlit) e Alertas Automáticos (`scheduler.py` + `telegram_bot.py`).

**Tech Stack:** Python 3.11+, FastAPI, Pandas, NumPy, SQLite/PostgreSQL, Streamlit, APScheduler, HTTPX, Pytest, GitHub Actions, Railway/Render.

---

## 1. Diretrizes Éticas e Legais (Obrigatórias)

- **Dados Públicos e Oficiais:** Exclusivamente fontes públicas (TCE/SC, IBGE, Portal de Dados Abertos SC, Receita Federal via BrasilAPI).
- **Neutralidade e Sem Juízo de Valor:** Alertas são descritos estritamente como *"padrões estatísticos que merecem verificação jornalística"*, nunca como *"provas de irregularidade"* ou *"acusações"*.
- **Transparência e Rastreabilidade:** Todo alerta inclui justificativa textual clara, memória de cálculo (`dados_contexto`), link para a fonte original (`fonte_url`) e hash criptográfico SHA-256 (`hash_auditoria`).
- **Conformidade com a LGPD:** Sem armazenamento de dados pessoais sensíveis ou criação de "scores de corrupção" individuais.
- **Aviso Legal Visível:** Exibição obrigatória no frontend e relatórios: *"Esta ferramenta não substitui a verificação jornalística nem a apuração oficial."*

---

## 2. Contratos de Dados (API FastAPI)

### `GET /api/emendas`
- **Query Params:** `parlamentar` (str), `municipio` (str), `area` (str), `valor_minimo` (float), `limit` (int), `offset` (int)
- **Response 200:** Lista de objetos de emendas limpas com `valor_per_capita`, `populacao`, `fornecedor_cnpj` e `fonte_url`.

### `GET /api/parlamentares`
- **Response 200:** Lista de parlamentares com `total_emendas`, `quantidade_emendas`, `media_valor`, `principal_area`, `principal_fornecedor` e `percentual_maior_fornecedor`.

### `GET /api/alertas`
- **Query Params:** `tipo` (str), `parlamentar` (str), `municipio` (str), `pontuacao_minima` (float)
- **Response 200:** Lista de anomalias detectadas ordenadas por `pontuacao` (0 a 100) decrescente.

### `GET /api/alertas/{id}`
- **Response 200:** Detalhe do alerta com `justificativa`, `dados_contexto` (JSON), `fonte_url`, `hash_auditoria`, `util_count`, `falso_positivo_count` e histórico de feedbacks.

### `GET /api/municipios/{codigo}`
- **Response 200:** Perfil completo do município (`codigo_ibge`, `municipio`, `populacao`, `total_recebido`, `valor_per_capita`, lista de `emendas` e lista de `alertas`).

### `POST /api/alertas/{id}/feedback`
- **Request Body:** `{"avaliacao": "util" | "falso_positivo", "comentario": "opcional", "jornalista": "opcional"}`
- **Response 200:** Confirmação do registro e contadores atualizados do alerta.

---

## 3. Tasks de Implementação (1 Commit por Task + TDD)

1. **Task 1 (Fase 1 — Coleta de Dados):** `collect_tce.py` (TCE/SC + IBGE + Dados Abertos SC), `enrich_cnpj.py` (Receita Federal) e testes em `tests/test_collect_and_enrich.py`.
2. **Task 2 (Fase 2 — Limpeza e Modelagem ETL):** `schema.sql`, `database.py`, `etl.py` (normalização, join IBGE, cálculo per capita, tabelas limpas e agregadas) e testes em `tests/test_etl.py`.
3. **Task 3 (Fase 3 — Motor de Anomalias):** `anomalies.py` com as 7 regras (valor absoluto P95, valor per capita média+2DP, concentração de fornecedor >80%, concentração temporal >70%, CNPJ recém-criado <12m, capital social baixo <R$10k, discrepância geográfica UF!=SC) e testes em `tests/test_anomalies.py`.
4. **Task 4 (Fase 4 — API FastAPI):** `main.py` expondo os 6 endpoints documentados com Swagger automático e testes em `tests/test_api.py`.
5. **Task 5 (Fase 5 — Frontend Streamlit):** `app.py` com as 4 páginas (Painel de Alertas, Explorador de Emendas, Perfil do Parlamentar, Perfil do Município) + testes em `tests/test_frontend_helpers.py`.
6. **Task 6 (Fase 6 — Alertas Automáticos):** `scheduler.py` (execução semanal segunda-feira 8h + relatório HTML Top 10 + envio SMTP) e `telegram_bot.py` (`/alertas`, `/parlamentar <nome>`) + testes em `tests/test_scheduler_and_bot.py`.
7. **Task 7 (Fases 7 e 8 — Validação Real SC, Deploy e Documentação):** Validação dos alertas gerados, `feedback.md`, arquivos de deploy Railway/Render (`Dockerfile`, `railway.json`, `render.yaml`), GitHub Actions (`.github/workflows/ci.yml`), `README.md` e `CHANGELOG.md`.
