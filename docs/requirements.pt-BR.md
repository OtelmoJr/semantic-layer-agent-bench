# Especificação de requisitos de software

[English](requirements.md)

SRS enxuta no espírito da ISO/IEC/IEEE 29148: cada requisito é atômico, verificável e
rastreado até o artefato que o verifica.

## 1. Escopo

Um harness de benchmark que mede a execution accuracy de agentes de text-to-SQL sob três
condições (schema cru, schema cru com glossário, semantic layer) em um gold set congelado,
de forma local e reproduzível.

## 2. Requisitos funcionais

| ID | Requisito | Verificado por |
|---|---|---|
| FR-01 | O sistema deve gerar o TPC-H em um scale factor configurável e carregá-lo no DuckDB com tipos de coluna fixos. | `slab data`, MANIFEST.json |
| FR-02 | O sistema deve conter 150 perguntas gold distribuídas em cinco categorias (40/40/25/25/20). | `slab gold-check` |
| FR-03 | Toda pergunta com cobertura `in` ou `raw_only` deve ter um SQL de referência que roda, é determinístico, retorna 1–200 linhas e não tem empate na fronteira de um LIMIT. | `slab gold-check` |
| FR-04 | O gold set deve ser fixado por um hash SHA-256, e uma execução deve se recusar a começar se o hash for diferente. | `test_gold_changed_after_freeze_refuses_to_run` |
| FR-05 | As perguntas devem ser divididas em dev e holdout de forma determinística, estratificadas por categoria, sem depender de nenhuma escolha humana. | `gold.split_of` |
| FR-06 | O semantic layer deve reproduzir o resultado de referência de toda pergunta dentro da cobertura. | `slab parity` (130/130) |
| FR-07 | Os braços A e B devem expor as mesmas tools MCP; B deve diferir apenas pelo glossário no system prompt. | `test_prompts.py`, `test_contract.py` |
| FR-08 | O braço C deve acessar dados somente por meio de métricas governadas. | `test_contract.py`, `test_semantic_layer.py` |
| FR-09 | As definições de métricas mostradas ao braço C devem ser iguais ao texto do glossário mostrado ao braço B. | `test_semantic_layer_matches_glossary_verbatim` |
| FR-10 | A avaliação deve executar a submissão do agente e comparar os conjuntos de resultado pelas regras do comparador (ADR-003). | `test_comparator.py` |
| FR-11 | Perguntas fora da cobertura devem ser avaliadas como corretas somente quando o agente recusa onde a recusa é esperada. | `Question.expected_outcome`, smoke |
| FR-12 | O runner deve suportar Ollama, Anthropic e um provedor stub determinístico com o mesmo loop. | `test_loop.py`, `test_providers.py`, smoke |
| FR-13 | O relatório deve mostrar EX por braço com IC bootstrap de 95% sobre as perguntas, pass^k, McNemar exato pareado, a parcela da documentação e EX por categoria. | `test_report_builds` |
| FR-14 | Um comando A/A deve comparar o mesmo braço entre duas execuções. | `slab aa`, `test_aa_*` |

## 3. Requisitos não funcionais

| ID | Requisito | Verificado por |
|---|---|---|
| NFR-01 | O SQL do agente não deve ler arquivos, alterar configurações, gravar dados ou ler tabelas fora da allow-list do seu braço. | `test_guards.py` (32 casos) |
| NFR-02 | Uma query não deve rodar por mais de 20 s; uma pergunta não deve rodar por mais de 60 s. | `test_timeout_*` |
| NFR-03 | Rodar de novo uma execução não deve duplicar resultados; uma execução morta em qualquer ponto deve retomar até um resultado completo e sem duplicatas. | `test_kill_9_mid_run_then_resume_*` |
| NFR-04 | Toda linha de resultado deve referenciar um trace que existe. | `test_smoke_exact_accuracy_and_idempotency` |
| NFR-05 | O pipeline completo (dados, checagens, testes, smoke) deve rodar em uma máquina limpa sem acesso de rede a provedores de modelo e sem recursos de nuvem. | CI, saída do README |
| NFR-06 | O gasto com modelos hospedados deve ser limitado por um orçamento fornecido pelo usuário, estimado antes do início e aplicado durante a execução. | `runner.BudgetExceeded` |
| NFR-07 | Cada execução deve registrar id e digest do modelo, SHA do git, hash do gold set e limites. | `runs/<id>/run.json` |

## 4. Restrições

- Python 3.11–3.12 (suporte do MetricFlow e do dbt), DuckDB 2.x, MCP SDK 2.x.
- Os preços não ficam hardcoded; o usuário os informa em `config/prices.yaml`.
