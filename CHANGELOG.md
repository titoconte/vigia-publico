# Histórico de Alterações (Changelog)

Todas as mudanças notáveis neste projeto serão documentadas neste arquivo.
O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

## [1.2.0] - 2026-11-13

### 🚀 Novas Funcionalidades
- **`[cnpj_validator.py]` e `[schema.sql]`**: Classificação estruturada de favorecidos em dois grupos canônicos (`CNPJ de Município` — Administração Municipal Completa: prefeituras, fundos municipais, câmaras, autarquias e fundações municipais — vs. `Outro CNPJ` — OSCs, associações privadas, empresas, consórcios e órgãos estaduais), além de persistência de `cnaes_secundarios` em `cnpj_cache` com migração automática retrocompatível.
- **`[app.py]`**: Separação visual e analítica entre **CNPJs de Municípios** e **Outros CNPJs** nas abas **2. Explorador de Emendas**, **3. Perfil do Parlamentar** e **4. Perfil do Município**, incluindo cartões comparativos de volume/participação percentual, filtros rápidos de grupo, coluna `Grupo CNPJ` e seções expansíveis (`st.expander` recolhido por padrão) exibindo o **CNAE Principal** e os **CNAEs Secundários** de cada CNPJ favorecido.

### 🔧 Ajustes e Melhorias
- **`[enrich_cnpj.py]`**: Extração padronizada do código e descrição do CNAE principal (`XXXX-X/XX - Descrição`), lista de CNAEs secundários e código oficial de natureza jurídica CONCLA na Receita Federal (`BrasilAPI` com *fallback* imediato em `MinhaReceita` e `publica.cnpj.ws`), além da rotina `sanear_cnpjs_fallback` para atualização cadastral em lote.

### 🐛 Correções de Bugs
- **`[cnpj_validator.py]` e `[enrich_cnpj.py]`**: Correção de falsos positivos de associações privadas cujo nome continha `"DO MUNICIPIO DE ..."` e substituição dos registros legados com CNAE genérico de *fallback* (`4789-0/99 - Comércio e serviços gerais`), aplicando `8411-6/00 - Administração pública em geral` para entes municipais sem retorno externo.

## [1.1.0] - 2026-11-11

### 🚀 Novas Funcionalidades
- **`[collect_tce.py]`**: Integração real com a API oficial do Portal da Transparência SC / SIGEF-CIASC (`emendaparlamentar/exportcsv` e `emendaparlamentar/extratoemenda`), baixando o índice integral de 4.292 emendas estaduais e detalhando extratos oficiais com cache persistente em disco e controle de *rate-limit*.
- **`[collect_tce.py]`**: Coleta real da população estimada de todos os **295 municípios de Santa Catarina** na API de Agregados `6579` do IBGE, além do download real das bases de Despesas do Executivo SC (`despesa/exportcsv`) e Transferências Voluntárias na API CKAN (`dados.sc.gov.br`).
- **`[enrich_cnpj.py]`**: Ativação por padrão do enriquecimento real de CNPJs na Receita Federal via `BrasilAPI` (com *retry/backoff* e *fallback* em `publica.cnpj.ws`), enriquecendo 192 CNPJs reais de entidades e órgãos beneficiários.

### 🔧 Ajustes e Melhorias
- **`[etl.py]` e `[scheduler.py]`**: Propagação automática da UF cadastral oficial da Receita Federal e do modo de rede (`VIGIA_USAR_REDE` / `VIGIA_MAX_EMENDAS`), mantendo execução offline determinística na suíte automatizada Pytest/CI.
- **`[feedback.md]` e `[README.md]`**: Atualização do relatório de verificação manual com alertas reais detectados na base estadual de SC e documentação das novas variáveis de ambiente.

### 🐛 Correções de Bugs
- **`[etl.py]` e `[collect_tce.py]`**: Normalização de localidades de abrangência estadual (`* Santa Catarina` e `Estado de Santa Catarina`) e garantia de unicidade estrita de chaves primárias nas tabelas `agregados_municipio` (`codigo_ibge`) e `agregados_fornecedor` (`fornecedor_cnpj`).

## [1.0.0] - 2026-11-10

### Adicionado
- **Fase 1 (Coleta de Dados):** Scripts `collect_tce.py` (emendas TCE/SC, estimativa populacional IBGE e Dados Abertos SC) e `enrich_cnpj.py` (enriquecimento cadastral de CNPJs com data de abertura, capital social, CNAE e sócios).
- **Fase 2 (Limpeza e Modelagem ETL):** `schema.sql`, `database.py` e `etl.py` com normalização de municípios sem acentos, cálculo de `valor_per_capita`, tabelas limpas (`emendas_clean`) e agregadas (`agregados_parlamentar`, `agregados_municipio`, `agregados_fornecedor`) com índices de performance.
- **Fase 3 (Motor de Anomalias):** `anomalies.py` implementando as 7 regras de detecção (Valor Absoluto P95, Valor Per Capita > Média + 2DP, Concentração de Fornecedor > 80%, Concentração Temporal > 70%, CNPJ Recém-Criado < 12 meses, Capital Social Baixo < R$ 10.000 e Discrepância Geográfica UF ≠ SC) com justificativa ética e hash SHA-256.
- **Fase 4 (API e Backend FastAPI):** `main.py` com documentação automática Swagger e endpoints `/api/emendas`, `/api/parlamentares`, `/api/alertas`, `/api/alertas/{id}`, `/api/municipios/{codigo}` e `POST /api/alertas/{id}/feedback`.
- **Fase 5 (Frontend Streamlit):** `app.py` com 4 páginas interativas (Painel de Alertas, Explorador de Emendas, Perfil do Parlamentar e Perfil do Município) e aviso ético permanente.
- **Fase 6 (Alertas Automáticos):** `scheduler.py` (execução semanal às segundas-feiras 8h, geração de relatório HTML Top 10 e envio SMTP) e `telegram_bot.py` (comandos `/alertas` e `/parlamentar <nome>`).
- **Fases 7 e 8 (Testes, Validação e Deploy):** Suíte completa de testes unitários e de integração em `tests/` (Pytest + HTTPX), validação manual e feedback de jornalistas em `feedback.md`, GitHub Actions CI (`.github/workflows/ci.yml`), `Dockerfile`, `railway.json` e `render.yaml`.
