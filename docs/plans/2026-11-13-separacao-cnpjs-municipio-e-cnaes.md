# Separação de CNPJs de Municípios vs. Outros CNPJs e Exibição de CNAEs — Plano de Implementação

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Separar todos os CNPJs favorecidos por emendas parlamentares entre **"CNPJs de Municípios"** (Administração Municipal completa) e **"Outros CNPJs"** (Entidades Privadas/OSCs/Empresas e Órgãos Estaduais), sanear os códigos e descrições de CNAE Principal + Secundários no cache local via Receita Federal/BrasilAPI, e disponibilizar seletores/gráficos comparativos e seções recolhidas (`st.expander`) com os CNAEs nas Abas 2, 3 e 4 do painel Streamlit.

**Architecture:** A classificação determinística e híbrida (por código oficial de Natureza Jurídica IBGE/RFB e por padrões nominais da Administração Municipal) será centralizada em `cnpj_validator.py`, junto à persistência da lista `cnaes_secundarios` (JSON) na tabela `cnpj_cache` com migração automática retrocompatível. O enriquecimento (`enrich_cnpj.py`) passará a capturar código numérico formatado (`XXXX-X/XX`) + descrição do CNAE principal, CNAEs secundários e código/descrição de natureza jurídica, incluindo rotina de saneamento para registros legados de fallback. No frontend (`app.py`), um mapa em memória de `cnpj_cache` evitará consultas N+1 ao SQLite e alimentará filtros, métricas comparativas e `st.expander` recolhidos nas Abas 2, 3 e 4.

**Tech Stack:** Python 3.13, SQLite3, Pandas, HTTPX (BrasilAPI / CNPJ.ws), Streamlit, Pytest (TDD estrito).

---

## Resumo de Entendimento e Registro de Decisões (Decision Log)

### Resumo de Entendimento
- **O que está sendo construído:** Classificação estruturada de CNPJs em dois grupos (`CNPJ de Município` vs. `Outro CNPJ`) e apresentação recolhida (`st.expander(..., expanded=False)`) dos CNAEs (principal e secundários) de cada CNPJ.
- **Por que existe:** Permitir distinguir imediatamente repasses fundo-a-fundo / prefeituras de transferências a entidades privadas (OSCs, associações, hospitais filantrópicos, empresas) ou órgãos estaduais, além de auditar a compatibilidade temática das atividades econômicas (CNAEs) sem poluir visualmente a tela.
- **Público-alvo:** Auditores cívicos, controle social e analistas de políticas públicas em Santa Catarina.
- **Restrições e Não-Objetivos:** Preservar linguagem estritamente técnica e neutra (sem termos proibidos em `tests/test_neutrality_and_terms.py`), manter testes Pytest 100% offline e determinísticos, e não criar uma 6ª aba separada.

### Premissas (Assumptions)
1. Códigos de Natureza Jurídica CONCLA/IBGE da Administração Pública Municipal (`103-1`, `106-6`, `112-0`, `115-5`, `118-0`, `124-4`, `127-9`, `130-9`, `133-3`) identificam inequivocamente `CNPJ de Município`.
2. Quando o cache contiver código genérico legado (`2062` sintético ou vazio), a classificação nominal identifica entes municipais (`MUNICIPIO DE ...`, `PREFEITURA ...`, `FUNDO MUNICIPAL ...`, `CAMARA MUNICIPAL ...`, `AUTARQUIA MUNICIPAL ...`, `SAMAE`, `FUNDACAO MUNICIPAL ...`, `HOSPITAL MUNICIPAL ...`, `FACULDADE MUNICIPAL ...`, `INSTITUTO DE PREVIDENCIA MUNICIPAL ...`), excluindo explicitamente associações privadas cujo nome contenha `"DO MUNICIPIO DE"` (`ASSOCIACAO ...`, `SOCIEDADE ...`, `REDE FEMININA ...`, `CONSORCIO ...`, `FUNDO ESTADUAL ...`, `SECRETARIA DE ESTADO ...`).
3. Entes municipais sem retorno na API pública recebem o CNAE oficial `8411-6/00 - Administração pública em geral` e natureza jurídica `1244 - Município` (ou `1333 - Fundo Público da Administração Direta Municipal` quando fundo).

### Decision Log
| # | Decisão | Alternativas Consideradas | Motivo da Escolha |
|---|---|---|---|
| **1** | **Critério de Separação (Opção A):** `CNPJs de Municípios` engloba toda a Administração Municipal (Prefeituras + Fundos, Fundações, Câmaras e Autarquias Municipais); `Outros CNPJs` reúne OSCs, empresas, consórcios e órgãos estaduais. | B) Apenas CNPJ matriz da Prefeitura; C) Todos os órgãos públicos (incluindo estaduais) vs. privados. | Em SC, grande parte dos repasses às prefeituras entra via Fundo Municipal de Saúde (`FMS`); agrupá-los reflete fielmente o recurso municipal. |
| **2** | **Escopo de Exibição (Opção A):** Integrar filtro/seletor de grupo de CNPJ e `st.expander` recolhido de CNAEs nas **Abas 2 (Explorador), 3 (Perfil Parlamentar) e 4 (Perfil Município)**. | B) Apenas Abas 3 e 4; C) Nova aba 6 exclusiva. | Mantém o contexto analítico exatamente onde os CNPJs já são inspecionados, sem fragmentar a navegação. |
| **3** | **Profundidade e Saneamento de CNAEs (Opção A):** Exibir **CNAE Principal + Secundários** formatados (`XXXX-X/XX - Descrição`) e sanear o cache local via BrasilAPI + regra `8411-6/00` para entes municipais. | B) Apenas CNAE principal; C) Somente base offline atual. | Elimina os 917 registros com fallback genérico `4789-0/99` e entrega visibilidade integral das atividades econômicas secundárias. |

---

## Estrutura de Tarefas (TDD)

### Task 1: Documentação do Design e Plano de Implementação
- **Files:** Create `docs/plans/2026-11-13-separacao-cnpjs-municipio-e-cnaes.md`
- **Commit:** `docs(plan): adiciona especificacao e plano TDD para separacao de CNPJs de municipios e CNAEs`

### Task 2: Classificador Municipal/Outros e Suporte a CNAEs Secundários no Validador e Schema
- **Files:**
  - Modify: `schema.sql`
  - Modify: `cnpj_validator.py`
  - Test: `tests/test_cnpj_validator.py`
- **Behavior:**
  - `formatar_cnae(codigo, descricao) -> str`
  - `eh_cnpj_municipio(...) -> bool` e `classificar_grupo_cnpj(...) -> str` (`"CNPJ de Município"` | `"Outro CNPJ"`)
  - Coluna `cnaes_secundarios TEXT DEFAULT '[]'` em `schema.sql` e migração `ALTER TABLE` segura em `inicializar_tabela_cnpj_cache`.
  - `salvar_cnpj_cache`, `obter_cnpj_cache`, `carregar_mapa_cnpjs_cache` e `obter_cnaes_cnpj` suportando lista `cnaes_secundarios` e grupo do CNPJ.
  - `sincronizar_cnpjs_emendas_no_cache` lendo `data/enriched/cnpj_<cnpj>.json` quando disponível e aplicando `8411-6/00 - Administração pública em geral` para entes municipais sem cache prévio.

### Task 3: Enriquecimento Completo (CNAE Principal + Secundários + Natureza Jurídica) e Saneamento
- **Files:**
  - Modify: `enrich_cnpj.py`
  - Test: `tests/test_collect_and_enrich.py`
- **Behavior:**
  - `_consultar_cnpj_remoto` extrai `cnae_principal` com código formatado + descrição, `cnaes_secundarios` (filtrando códigos vazios/`0`), `natureza_juridica_codigo`, `natureza_juridica` e `situacao_cadastral`.
  - Fallback offline de `enriquecer_cnpj` respeita entes municipais (`8411-6/00`).
  - `sanear_cnpjs_fallback(...)` atualiza CNPJs com fallback genérico em `data/enriched`, `cnpj_cache` e `emendas_clean`.

### Task 4: Saneamento Real do Banco de Dados Local (`data/vigia_publico.db`)
- **Files:**
  - Update data: `data/vigia_publico.db`, `data/clean/emendas_clean.csv`, `data/clean/agregados_fornecedor.csv` e JSONs rastreados em `data/enriched/`.
- **Behavior:**
  - Executa `sanear_cnpjs_fallback` consultando a Receita Federal (`BrasilAPI` / `CNPJ.ws`) para eliminar os fallbacks genéricos e popular `cnaes_secundarios` e `natureza_juridica_codigo` reais.

### Task 5: Integração Visual nas Abas 2, 3 e 4 do Streamlit (`app.py`)
- **Files:**
  - Modify: `app.py`
  - Test: `tests/test_frontend_helpers.py`
- **Behavior:**
  - `filtrar_emendas_explorador` com parâmetro `grupo_cnpj`.
  - `calcular_resumo_grupos_cnpj`, `obter_totais_por_cpf_cnpj(..., grupo_cnpj=...)`, `obter_metricas_detalhadas_municipio(..., grupo_cnpj=...)` e `montar_tabela_cnaes_cnpjs(...)`.
  - Aba 2: seletor `"Grupo de CNPJ"`, métricas comparativas `CNPJs de Municípios` vs. `Outros CNPJs`, coluna `Grupo CNPJ` e `st.expander(..., expanded=False)` com CNAEs.
  - Aba 3: seletor `"Filtrar Favorecidos por Grupo de CNPJ"`, métricas comparativas, gráficos/tabela filtrados e `st.expander(..., expanded=False)` com CNAEs dos favorecidos do autor.
  - Aba 4: seletor `"Separar Favorecidos por Grupo de CNPJ"`, métricas comparativas, gráficos Top 50/tabela filtrados e `st.expander(..., expanded=False)` com CNAEs dos favorecidos do município.

### Task 6: Atualização do `CHANGELOG.md` (v1.2.0), Verificação Integral e Push
- **Files:**
  - Modify: `CHANGELOG.md`
  - Modify: `README.md`
- **Verification:** `python -m pytest -v` (100% pass) + validação de integridade da base SQLite real + `git push`.
