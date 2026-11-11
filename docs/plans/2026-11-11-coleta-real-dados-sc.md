# Coleta Real de Dados Públicos de SC Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Substituir a coleta sintética padrão por integração real e auditável com as APIs oficiais do Portal da Transparência de Santa Catarina (CIASC/SEF), IBGE (295 municípios), Portal de Dados Abertos SC (CKAN) e Receita Federal (BrasilAPI), mantendo suporte determinístico offline para a suíte de testes automatizados (CI).

**Architecture:** Os módulos `collect_tce.py`, `enrich_cnpj.py`, `etl.py` e `scheduler.py` passam a operar em modo real (`usar_rede=True`) por padrão fora do ambiente de testes unitários (`PYTEST_CURRENT_TEST`), com injeção opcional de `httpx.Client` para testes TDD determinísticos via `httpx.MockTransport`. A coleta de emendas baixa o índice oficial completo do Portal da Transparência SC (`exportcsv`), armazena cache incremental em disco por emenda (`data/raw/extratos_cache/`) respeitando o rate-limit de `300 req/min` do CIASC, cruza com os 295 municípios oficiais do IBGE e enriquece os CNPJs reais na BrasilAPI com cache persistente em `data/enriched/`.

**Tech Stack:** Python 3.11+, HTTPX, Pandas, SQLite, Pytest (`httpx.MockTransport`).

---

## 1. Resumo de Entendimento e Premissas (Understanding Lock & Decision Log)

### Escopo Validado
- **Emendas Estaduais de SC (`collect_tce.py`):** Consumo da API oficial `https://api-portal-transparencia.apps.sm.okd4.ciasc.sc.gov.br/api/emendaparlamentar/exportcsv` + `/extratoemenda`, extraindo número oficial (`2026EP...`), parlamentar/bancada, partido (20ª Legislatura ALESC), valor, município (`nmlocalidade`), credor/beneficiário e CNPJ (`identificacaocredor`), área temática (`nmsubacao`), datas reais de lançamento e link direto de auditoria.
- **População Oficial IBGE (`collect_tce.py`):** Consumo da API de Agregados do IBGE (`6579` / `4714` + `localidades`) cobrindo todos os **295 municípios de Santa Catarina**.
- **Dados Abertos SC (`collect_tce.py`):** Consumo do endpoint oficial de despesas estaduais (`despesa/exportcsv`) e da API CKAN (`dados.sc.gov.br/api/3/action/package_show?id=transferencias`) com leitura em streaming controlada.
- **Receita Federal (`enrich_cnpj.py`):** Consulta real em `https://brasilapi.com.br/api/cnpj/v1/{cnpj}` com *retry/backoff* e cache JSON em `data/enriched/cnpj_{cnpj}.json`.

### Decision Log
| Decisão | Alternativas Consideradas | Motivo da Escolha |
|---|---|---|
| Detecção automática de rede (`resolver_usar_rede`) | `usar_rede=True` fixo quebrando CI vs `usar_rede=False` exigindo flags manuais | Garante coleta real imediata ao rodar os scripts Python em produção/CLI e preserva 100% dos testes offline determinísticos no Pytest/GitHub Actions. |
| Coleta estratificada + cache de extratos (`VIGIA_MAX_EMENDAS`) | Baixar 4.292 extratos sequenciais sem cache (~20 min) vs baixar apenas CSV resumido sem CNPJ/município | O CSV resumido não traz CNPJ nem município; o cache por emenda em `data/raw/extratos_cache/` respeita o limite de 300 req/min do CIASC e permite carga rápida inicial (~250 emendas relevantes cobrindo todas as modalidades e parlamentares) ou 100% da base (`VIGIA_MAX_EMENDAS=0`). |
| Streaming limitado de CSVs grandes do CKAN (`max_linhas`) | Download integral de CSVs históricos multi-megabyte | Evita timeouts desnecessários em arquivos históricos extensos do CKAN, garantindo extração rápida e auditável em UTF-8. |

---

## 2. Tasks de Implementação (TDD + 1 Commit por Task)

### Task 1: Documentação do Plano de Implementação
- **Files:** Create `docs/plans/2026-11-11-coleta-real-dados-sc.md`
- **Commit:** `docs(plan): add implementation plan for real SC public data collection`

### Task 2: Coleta Real IBGE (295 Municípios) e Dados Abertos SC (CKAN / SEF)
- **Files:** Modify `collect_tce.py`, Create `tests/test_real_collection.py`
- **Steps:** Escrever testes falhando com `httpx.MockTransport` para `resolver_usar_rede`, `coletar_populacao_ibge` (API agregados IBGE) e `coletar_dados_abertos_sc` (SEF Despesas + CKAN Transferências) -> Verificar falha -> Implementar -> Verificar aprovação -> Commit.

### Task 3: Coleta Real de Emendas Estaduais de SC (API Portal da Transparência SC)
- **Files:** Modify `collect_tce.py`, Modify `tests/test_real_collection.py`
- **Steps:** Escrever testes falhando para parsing de `identificacaocredor`, limpeza de `nmsubacao`, decodificação `latin-1` de `exportcsv`, cache de `extratoemenda` e montagem das 14 colunas obrigatórias -> Verificar falha -> Implementar -> Verificar aprovação -> Commit.

### Task 4: Enriquecimento Real de CNPJ (BrasilAPI) e Propagação no ETL/Scheduler
- **Files:** Modify `enrich_cnpj.py`, `etl.py`, `scheduler.py`, `tests/test_real_collection.py`
- **Steps:** Escrever testes falhando para enriquecimento real via BrasilAPI com retry/fallback limpo e propagação de `usar_rede` no `etl.py` e `scheduler.py` -> Verificar falha -> Implementar -> Verificar aprovação -> Commit.

### Task 5: Download Real da Base de SC, Relatório de Validação e Changelog
- **Files:** Modify `.env.example`, `README.md`, `feedback.md`, `CHANGELOG.md` + atualização dos artefatos de dados reais (`data/raw/`, `data/clean/`, `data/vigia_publico.db`).
- **Steps:** Executar coleta real, enriquecimento real de CNPJs, ETL, motor de anomalias e geração do relatório Top 10 HTML; validar toda a suíte `pytest -v`; atualizar documentação e `CHANGELOG.md`; realizar commit e push.
