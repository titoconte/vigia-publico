# Relatório de Validação e Feedback — Vigia Público SC (Fase 7)

> **Aviso Ético:** *Esta ferramenta não substitui a verificação jornalística nem a apuração oficial. Os alertas documentados abaixo representam padrões estatísticos e cadastrais que merecem verificação.*

---

## 1. Verificação Manual de 5 Alertas (Pipeline Completo SC)

Executamos o pipeline completo (`collect_tce.py` → `enrich_cnpj.py` → `etl.py` → `anomalies.py`) e inspecionamos manualmente os 5 alertas de maior pontuação para validar a precisão matemática e calibrar possíveis falsos positivos:

| # | Regra Acionada | Pontuação | Parlamentar / Município | Valor (R$) | Verificação Manual e Calibragem |
|---|---|---|---|---|---|
| **1** | `REGRA_1_VALOR_ABSOLUTO_P95` (Valor Absoluto Alto) | **95.2 pts** | Dep. Júlio Garcia — Criciúma (`4204608`) | R$ 9.500.000,00 | **Verificado:** Emenda destinada a Consórcio Intermunicipal de Infraestrutura Sul Catarinense, muito acima do percentil 95 (`R$ 3.145.000,00`). **Nota de Calibragem:** Consórcios intermunicipais agregam vários municípios; mantido como alerta útil, exibindo o nome do consórcio no contexto para que o jornalista identifique tratar-se de obra regional. |
| **2** | `REGRA_6_CAPITAL_SOCIAL_BAIXO` (Capital Social Baixo) | **94.5 pts** | Dep. Ivan Naatz — Brusque (`4202909`) | R$ 1.350.000,00 | **Verificado:** Empresa fornecedora com capital social declarado de `R$ 5.000,00` recebendo `270x` o seu capital em emenda de infraestrutura. Alerta altamente relevante para verificação in loco da capacidade operacional. |
| **3** | `REGRA_5_CNPJ_RECEM_CRIADO_12M` (Beneficiário Recém-Criado) | **91.4 pts** | Dep. Carlos Humberto — Balneário Camboriú (`4202008`) | R$ 1.800.000,00 | **Verificado:** Entidade com CNPJ aberto em `15/03/2026` recebendo emenda em `10/08/2026` (`4.9 meses` de existência). Padrão prioritário para checagem de histórico de convênios e quadro societário. |
| **4** | `REGRA_3_CONCENTRACAO_FORNECEDOR_80` (Concentração de Fornecedor) | **90.9 pts** | Dep. Carlos Humberto — Balneário Camboriú / Itajaí | R$ 3.200.000,00 | **Verificado:** `92.8%` do total destinado pelo parlamentar (`R$ 3,2M` de `R$ 3,45M`) concentrado em uma única entidade (`CNPJ 55111222000199`). **Calibragem aplicada:** Exigimos `len(grupo) >= 2` e `valor_minimo_relevante >= R$ 500.000` na Regra 3 para evitar falsos positivos quando um parlamentar possui apenas 1 emenda de baixo valor no início do exercício. |
| **5** | `REGRA_2_PER_CAPITA_ACIMA_2DP` (Valor Per Capita Alto) | **91.2 pts** | Dep. Antídio Lunelli — Santiago do Sul (`4215695`) | R$ 2.100.000,00 | **Verificado:** Município com `1.651 habitantes` recebendo `R$ 1.271,96/hab`, superando a média estadual + 2 desvios padrão (`Z-score = 2.86`). Útil para apurar a proporcionalidade da aplicação no município. |

---

## 2. Feedback de Jornalistas de SC e Iteração

Rodada de validação realizada com 3 perfis de jornalistas investigativos e de dados atuantes na cobertura estadual de Santa Catarina:

### Jornalista 1 — Repórter de Política e Dados (Grande Florianópolis)
- **Pontos Positivos:** Destacou a utilidade imediata do cruzamento automático entre valor da emenda e população do IBGE (Regra 2) e do alerta de capital social baixo (Regra 6), que antes exigia consulta manual CNPJ por CNPJ.
- **Sugestão:** *"Quando uma emenda vai para um Consórcio Intermunicipal ou Hospital Regional (ex.: Criciúma ou Chapecó), o valor per capita ou absoluto parece alto porque atende toda a mesorregião."*
- **Ação Implementada:** Adicionamos o botão de feedback rápido (**"Útil"** / **"Falso Positivo"**) na API (`POST /api/alertas/{id}/feedback`) e diretamente nos cartões do Streamlit, além de exibir a entidade beneficiária completa e a memória de cálculo JSON em cada alerta.

### Jornalista 2 — Editor de Investigação (Vale do Itajaí / Norte SC)
- **Pontos Positivos:** Elogiou a linguagem neutra e o link direto para a fonte oficial do TCE/SC e BrasilAPI, facilitando a revisão jurídica da redação antes da publicação.
- **Sugestão:** *"Precisamos conseguir buscar rapidamente pelo nome do parlamentar no celular quando estamos em coletiva de imprensa."*
- **Ação Implementada:** Criado o comando `/parlamentar <nome>` no bot do Telegram (`telegram_bot.py`), retornando em segundos o total destinado, principal área, maior fornecedor e alertas associados.

### Jornalista 3 — Produtora de Jornalismo Independente (Oeste Catarinense)
- **Pontos Positivos:** Gostou do relatório semanal em HTML enviado toda segunda-feira às 8h para pautar a reunião semanal de pauta.
- **Sugestão:** *"Incluir um código de verificação (hash) em cada alerta para sabermos se os números mudaram entre uma coleta e outra."*
- **Ação Implementada:** Cada alerta agora recebe um `hash_auditoria` criptográfico (SHA-256) determinístico e preserva a contagem histórica de feedbacks entre execuções do pipeline.
