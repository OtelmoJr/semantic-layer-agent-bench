# Business case

[English](business-case.md)

## Problema

Times que colocam agentes de "converse com seus dados" na frente de usuários de negócio enfrentam uma escolha
de design com custo real: dar ao agente SQL sobre o warehouse, ou construir e manter um
semantic layer (dbt MetricFlow, Cube, Databricks Metric Views, Snowflake Semantic Views)
e deixar o agente consultar apenas métricas governadas.

A defesa do semantic layer se apoia principalmente em benchmarks de fornecedores que comparam schema cru
com semantic layer. Essas comparações mudam duas coisas ao mesmo tempo: a abstração e
as definições de negócio que vêm junto com ela. Um time que já tem boa documentação
não consegue concluir, a partir delas, se a camada vale o custo de modelagem e manutenção.

## Pergunta que este projeto responde

Quanto do ganho de acurácia de um semantic layer para agentes de text-to-SQL vem da camada
em si, e quanto vem das definições de negócio que ela carrega?

## Quem usa a resposta

| Stakeholder | Decisão que ela embasa |
|---|---|
| Líder de plataforma de dados | Construir/manter um semantic layer vs investir em documentação e catálogos |
| Analytics engineer | Quais regras de negócio codificar como métricas primeiro |
| AI engineer | Qual superfície de tools expor a um agente analítico, e se o tamanho do modelo muda a resposta |

## Opções comparadas

| Opção | Paga | Ganha |
|---|---|---|
| A. SQL cru | Definições inconsistentes, números errados plausíveis | Cobertura total, sem modelagem |
| B. SQL cru + glossário no contexto | Escrever e manter um glossário atualizado, prompts mais longos | Definições sem um sistema novo |
| C. Semantic layer | Modelagem, um componente novo para operar, cobertura limitada ao que foi modelado | Definições garantidas por construção, menos graus de liberdade |

## Critérios de sucesso

1. Um resultado reproduzível: qualquer pessoa consegue rodar localmente com um comando e obter o mesmo
   hash do gold set, o mesmo parity e os mesmos resultados de testes.
2. Um número defensável: execution accuracy no holdout por braço com ICs de 95%, testes pareados,
   e a parcela da documentação (B−A)/(C−A) com o seu IC.
3. Limitações honestas: o que o tamanho da amostra não consegue resolver fica declarado no relatório.

## Custo

| Item | Custo |
|---|---|
| Infraestrutura | Máquina local; DuckDB, dbt e MetricFlow são open source |
| Execuções com modelo local | Energia e tempo (GPU recomendada) |
| Execuções com Claude | Custo de tokens, limitado por `--budget-usd` e calibrado antes no split dev |

## Fora de escopo

Deploy em produção, controle de acesso para usuários finais, conversas multi-turn,
perguntas em idiomas que não o inglês, operações de escrita.
