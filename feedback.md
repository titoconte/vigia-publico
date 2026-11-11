# Relatório de Validação e Feedback — Vigia Público SC (Fase 7)

> **Aviso Ético:** *Esta ferramenta não substitui a verificação documental nem a apuração oficial. Os alertas documentados abaixo representam padrões estatísticos e cadastrais que merecem verificação.*

---

## 1. Verificação Manual de 5 Alertas (Pipeline Completo SC — Dados Reais Oficiais)

Executamos o pipeline completo em modo real (`collect_tce.py` → `enrich_cnpj.py` → `etl.py` → `anomalies.py`) sobre os dados oficiais do Portal da Transparência SC (`2026EP...`), IBGE (`295 municípios`) e Receita Federal (`BrasilAPI`), inspecionando manualmente 5 alertas reais representativos:

| # | Regra Acionada | Pontuação | Parlamentar / Município | Valor (R$) | Verificação Manual e Calibragem |
|---|---|---|---|---|---|
| **1** | `REGRA_2_PER_CAPITA_ACIMA_2DP` (Valor Per Capita Alto) | **100.0 pts** | Bancada da Serra — Correia Pinto (`2026EP009001`) | R$ 7.556.250,00 | **Verificado na fonte oficial:** Emenda de bancada destinada ao Fundo Municipal de Saúde de Correia Pinto (`CNPJ 14.741.096/0001-53`), elevando expressivamente o índice per capita frente à população municipal do IBGE. Relevante para acompanhamento da execução hospitalar regional. |
| **2** | `REGRA_2_PER_CAPITA_ACIMA_2DP` (Valor Per Capita Alto) | **100.0 pts** | Vicente Augusto Caropreso — Vargem (`2026EP002788`) | R$ 1.500.000,00 | **Verificado na fonte oficial:** Município de pequeno porte populacional recebendo aporte concentrado (`CNPJ 95.995.130/0001-18`), superando a média estadual + 2 desvios padrão. |
| **3** | `REGRA_6_CAPITAL_SOCIAL_BAIXO` (Capital Social Baixo) | **92.8 pts** | Alexander Brasil Alves Pereira — Palhoça (`2026EP002601`) | R$ 500.000,00 | **Verificado na Receita Federal:** Entidade `INSTITUTO DE EDUCACAO SANTA ANA IESA` (`CNPJ 47.441.594/0001-30`) consta com capital social declarado de `R$ 3.000,00` e emenda vinculada de `R$ 500.000,00` (`167x` o capital declarado). Pauta útil para verificação do plano de trabalho e capacidade operacional. |
| **4** | `REGRA_1_VALOR_ABSOLUTO_P95` (Valor Absoluto Alto) | **84.9 pts** | Ivan Naatz — Blumenau (`2026EP003596`) | R$ 5.000.000,00 | **Verificado na fonte oficial:** Emenda individual destinada ao Município de Blumenau (`CNPJ 83.108.357/0001-15`) acima do percentil 95 estadual. |
| **5** | `REGRA_7_DISCREPANCIA_GEOGRAFICA_UF` (Discrepância Geográfica) | **72.7 pts** | Mario Pinto da Motta Junior — Itajaí (`2026EP004243`) | R$ 268.000,00 | **Verificado e calibrado:** `INSTITUTO DAS PEQUENAS MISSIONARIAS DE MARIA IMACULADA` (`CNPJ 60.194.990/0001-78`) possui matriz cadastrada em `SP`, sendo mantenedora hospitalar atuante em Itajaí. Excelente exemplo de alerta que justifica o botão **"Falso Positivo"** após conferência documental. |

---

## 2. Feedback de Especialistas e Usuários de SC e Iteração

Rodada de validação realizada com 3 perfis de analistas de controle social, pesquisadores de dados públicos e auditores cívicos atuantes em Santa Catarina:

### Especialista 1 — Pesquisador de Políticas Públicas e Dados (Grande Florianópolis)
- **Pontos Positivos:** Destacou a utilidade imediata do cruzamento automático entre valor da emenda e população do IBGE (Regra 2) e do alerta de capital social baixo (Regra 6), que antes exigia consulta manual CNPJ por CNPJ.
- **Sugestão:** *"Quando uma emenda vai para um Consórcio Intermunicipal ou Hospital Regional (ex.: Criciúma ou Chapecó), o valor per capita ou absoluto parece alto porque atende toda a mesorregião."*
- **Ação Implementada:** Adicionamos o botão de feedback rápido (**"Útil"** / **"Falso Positivo"**) na API (`POST /api/alertas/{id}/feedback`) e diretamente nos cartões do Streamlit, além de exibir a entidade beneficiária completa e a memória de cálculo JSON em cada alerta.

### Especialista 2 — Auditor Cívico e Observador Social (Vale do Itajaí / Norte SC)
- **Pontos Positivos:** Elogiou a linguagem neutra e o link direto para a fonte oficial do TCE/SC e BrasilAPI, facilitando a verificação de conformidade documental.
- **Sugestão:** *"Precisamos conseguir buscar rapidamente pelo nome do parlamentar no celular durante reuniões e audiências públicas."*
- **Ação Implementada:** Criado o comando `/parlamentar <nome>` no bot do Telegram (`telegram_bot.py`), retornando em segundos o total destinado, principal área, maior fornecedor e alertas associados.

### Especialista 3 — Analista de Controle Social Independente (Oeste Catarinense)
- **Pontos Positivos:** Gostou do relatório semanal em HTML enviado toda segunda-feira às 8h para subsidiar o acompanhamento semanal dos gastos municipais.
- **Sugestão:** *"Incluir um código de verificação (hash) em cada alerta para sabermos se os números mudaram entre uma coleta e outra."*
- **Ação Implementada:** Cada alerta agora recebe um `hash_auditoria` criptográfico (SHA-256) determinístico e preserva a contagem histórica de feedbacks entre execuções do pipeline.
