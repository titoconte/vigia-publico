# 🔍 Vigia Público SC

**Monitoramento transparente e auditável de emendas parlamentares estaduais de Santa Catarina para controle social e auditoria cívica.**

> ⚠️ **Aviso Ético Obrigatório:** *Esta ferramenta não substitui a verificação documental nem a apuração oficial. Os alertas gerados apontam padrões estatísticos e cadastrais em dados públicos que merecem verificação, não constituindo prova de irregularidade nem acusação.*

---

## 📌 Descrição do Projeto e Propósito

O **Vigia Público SC** é uma plataforma cívica open source desenvolvida para auxiliar pesquisadores, analistas de controle social e cidadãos de Santa Catarina no acompanhamento da execução das emendas parlamentares estaduais.

A ferramenta automatiza o cruzamento de múltiplas fontes públicas oficiais em tempo real:
1. **Portal da Transparência SC / SIGEF-CIASC e Painel TCE/SC** (índice integral das ~4.290 emendas estaduais impositivas + extratos oficiais com parlamentar/bancada, valor, município, entidade beneficiária, CNPJ do credor, área temática e status de execução).
2. **IBGE (API de Agregados `6579`)** (estimativa populacional oficial dos **295 municípios catarinenses** para cálculo exato do valor *per capita*).
3. **Portal de Dados Abertos SC (CKAN / SEF)** (despesas orçamentárias estaduais e transferências voluntárias).
4. **Receita Federal / BrasilAPI + MinhaReceita + CNPJ.ws** (data real de abertura do CNPJ, natureza jurídica CONCLA, capital social, CNAE principal e CNAEs secundários, UF de sede e quadro societário).

---

## ⚖️ Limitações Éticas e Legais

Este projeto segue diretrizes éticas estritas em todas as suas camadas (banco de dados, motor de anomalias, API, frontend e alertas):
- **Apenas Dados Públicos e Oficiais:** Nenhuma informação privada ou obtida fora de portais de transparência é utilizada.
- **Ausência de Juízo de Valor:** Os alertas são classificados exclusivamente como *"padrões que merecem verificação"*, nunca como *"provas de irregularidade"* ou *"indícios de crime"*.
- **Transparência e Auditabilidade:** Cada alerta exibe a memória de cálculo completa (`dados_contexto`), a justificativa textual da regra, o link para a fonte original (`fonte_url`) e uma assinatura criptográfica **SHA-256** (`hash_auditoria`).
- **Conformidade com a LGPD:** O sistema não cria *"scores de corrupção"* de pessoas físicas nem armazena dados pessoais além do estritamente público no exercício da função parlamentar ou empresarial.

---

## 🧠 Motor de Anomalias (7 Regras Auditáveis)

Cada regra em [`anomalies.py`](file:///C:/Users/titoc/OneDrive/Documentos/vigia-publico/anomalies.py) atribui uma pontuação objetiva de **0 a 100** e uma justificativa textual:

1. **Valor Absoluto Alto (`REGRA_1_VALOR_ABSOLUTO_P95`)**: Emenda individual acima do **percentil 95** do conjunto analisado.
2. **Valor Per Capita Alto (`REGRA_2_PER_CAPITA_ACIMA_2DP`)**: `valor_per_capita` acima da **média estadual + 2 desvios padrão**.
3. **Concentração de Fornecedor (`REGRA_3_CONCENTRACAO_FORNECEDOR_80`)**: Parlamentar que destinou **>80%** do seu volume total a um único fornecedor/entidade, com valor absoluto relevante.
4. **Concentração Temporal (`REGRA_4_CONCENTRACAO_TEMPORAL_70`)**: Parlamentar que concentrou **>70%** do valor anual de suas emendas em um único mês.
5. **Beneficiário Recém-Criado (`REGRA_5_CNPJ_RECEM_CRIADO_12M`)**: Entidade beneficiária ou fornecedor com CNPJ aberto há **menos de 12 meses** da data da emenda.
6. **Capital Social Baixo (`REGRA_6_CAPITAL_SOCIAL_BAIXO`)**: Empresa fornecedora com **capital social < R$ 10.000** recebendo emenda de alto valor.
7. **Discrepância Geográfica (`REGRA_7_DISCREPANCIA_GEOGRAFICA_UF`)**: Fornecedor sediado em **outro estado (UF ≠ SC)** recebendo recursos destinados a município catarinense.

---

## 🚀 Como Rodar Localmente (Passo a Passo)

### 1. Pré-requisitos
- **Python 3.11+**
- **Git**

### 2. Clonar o repositório e instalar dependências
```bash
git clone https://github.com/titoconte/vigia-publico.git
cd vigia-publico
pip install -r requirements.txt
cp .env.example .env
```

### 3. Executar o Pipeline de Dados Reais (Coleta → Enriquecimento → ETL → Anomalias)
```bash
# 1. Coleta dados reais do Portal da Transparência SC, IBGE (295 municípios) e Dados Abertos SC em data/raw/
#    (Por padrão detalha 250 emendas prioritárias; defina VIGIA_MAX_EMENDAS=0 para detalhar 100% da base)
python collect_tce.py

# 2. Enriquece CNPJs reais na Receita Federal (BrasilAPI) em data/enriched/
python enrich_cnpj.py

# 3. Normaliza municípios, calcula per capita e gera tabelas limpas/agregadas no banco
python etl.py

# 4. Executa as 7 regras do motor de anomalias e popula a tabela de alertas
python anomalies.py
```

### 4. Iniciar a API FastAPI (Backend + Swagger)
```bash
uvicorn main:app --reload --port 8000
```
- **Documentação interativa (Swagger UI):** `http://localhost:8000/docs`
- **Endpoints principais:**
  - `GET /api/emendas` — Lista com filtros (`parlamentar`, `municipio`, `area`, `valor_minimo`)
  - `GET /api/parlamentares` — Lista de parlamentares com totais agregados
  - `GET /api/alertas` — Lista de anomalias detectadas, ordenadas por pontuação
  - `GET /api/alertas/{id}` — Detalhe de um alerta com justificativa e dados de contexto
  - `GET /api/municipios/{codigo}` — Perfil do município (população, total recebido, per capita, emendas, alertas)
  - `POST /api/alertas/{id}/feedback` — Usuário marca alerta como `"útil"` ou `"falso positivo"`

### 5. Iniciar o Frontend (Streamlit — 5 Páginas)
```bash
streamlit run app.py
```
O painel abrirá em `http://localhost:8501` com as 5 páginas:
1. **Painel de Alertas** (ordenado por pontuação, filtros, memória de cálculo e botões de feedback)
2. **Explorador de Emendas** (filtros por autor, município, área e grupo de CNPJ — *CNPJs de Municípios* vs. *Outros CNPJs* —, métricas comparativas, gráficos por grupo e seção expansível de CNAEs principal e secundários)
3. **Perfil do Parlamentar** (totais por fase orçamentária, separação entre CNPJs de Municípios e Outros CNPJs, seção expansível de CNAEs dos favorecidos e alertas associados)
4. **Perfil do Município** (população IBGE, total recebido, valor *per capita*, separação de favorecidos e filtro direto na tabela de emendas destinadas ao município entre *CNPJs de Municípios* e *Outros CNPJs*, consulta expansível de CNAEs e alertas)
5. **Regras e Metodologia** (documentação transparente dos critérios estatísticos e cadastrais de cada regra)

### 6. Executar o Agendador Semanal e Bot do Telegram
```bash
# Gera o relatório HTML semanal (Top 10 alertas) imediatamente
python scheduler.py

# Testar resposta do bot do Telegram localmente
python telegram_bot.py
```

### 7. Executar os Testes Automatizados
```bash
pytest -v
```

---

## 🤝 Como Contribuir

Contribuições de auditores cívicos, pesquisadores, analistas de dados e desenvolvedores são muito bem-vindas!

1. Faça um **Fork** do projeto e crie uma branch a partir da `develop` (`git checkout -b feature/minha-melhoria`).
2. Adicione testes unitários em `tests/` cobrindo qualquer nova regra ou endpoint (seguimos **TDD**).
3. Documente todas as funções com docstrings claras e mantenha o compromisso ético de neutralidade textual.
4. Certifique-se de que toda a suíte passa (`pytest -v`) e abra um **Pull Request**.

---

## 📄 Licença

Distribuído sob a licença **MIT**. Consulte o arquivo [`LICENSE`](file:///C:/Users/titoc/OneDrive/Documentos/vigia-publico/LICENSE) para mais informações.
