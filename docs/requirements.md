# Software requirements specification

[Português](requirements.pt-BR.md)

Lean SRS in the spirit of ISO/IEC/IEEE 29148: each requirement is atomic, verifiable and
traced to the artifact that verifies it.

## 1. Scope

A benchmark harness that measures the execution accuracy of text-to-SQL agents under three
conditions (raw schema, raw schema with glossary, semantic layer) on a frozen gold set,
locally and reproducibly.

## 2. Functional requirements

| ID | Requirement | Verified by |
|---|---|---|
| FR-01 | The system shall generate TPC-H at a configurable scale factor and load it into DuckDB with fixed column types. | `slab data`, MANIFEST.json |
| FR-02 | The system shall hold 150 gold questions across five categories (40/40/25/25/20). | `slab gold-check` |
| FR-03 | Every question with coverage `in` or `raw_only` shall have a reference SQL that runs, is deterministic, returns 1–200 rows and has no tie at a LIMIT boundary. | `slab gold-check` |
| FR-04 | The gold set shall be pinned by a SHA-256 hash, and a run shall refuse to start if the hash differs. | `test_gold_changed_after_freeze_refuses_to_run` |
| FR-05 | Questions shall be split into dev and holdout deterministically, stratified by category, independent of any human choice. | `gold.split_of` |
| FR-06 | The semantic layer shall reproduce the reference result of every in-coverage question. | `slab parity` (130/130) |
| FR-07 | Arms A and B shall expose the same MCP tools; B shall differ only by the glossary in the system prompt. | `test_prompts.py`, `test_contract.py` |
| FR-08 | Arm C shall reach data only through governed metrics. | `test_contract.py`, `test_semantic_layer.py` |
| FR-09 | The metric definitions shown to arm C shall equal the glossary text shown to arm B. | `test_semantic_layer_matches_glossary_verbatim` |
| FR-10 | Grading shall execute the agent's submission and compare result sets by the comparator rules (ADR-003). | `test_comparator.py` |
| FR-11 | Questions outside coverage shall be graded as correct only when the agent refuses where refusal is expected. | `Question.expected_outcome`, smoke |
| FR-12 | The runner shall support Ollama, Anthropic and a deterministic stub provider with the same loop. | `test_loop.py`, `test_providers.py`, smoke |
| FR-13 | The report shall show per-arm EX with 95% bootstrap CI over questions, pass^k, paired exact McNemar, the documentation share and per-category EX. | `test_report_builds` |
| FR-14 | An A/A command shall compare the same arm across two runs. | `slab aa`, `test_aa_*` |

## 3. Non-functional requirements

| ID | Requirement | Verified by |
|---|---|---|
| NFR-01 | Agent SQL shall not read files, change settings, write data or read tables outside its arm's allow-list. | `test_guards.py` (32 cases) |
| NFR-02 | A query shall not run longer than 20 s; a question shall not run longer than 60 s. | `test_timeout_*` |
| NFR-03 | Re-running a run shall not duplicate results; a run killed at any point shall resume to a complete, duplicate-free result. | `test_kill_9_mid_run_then_resume_*` |
| NFR-04 | Every result row shall reference a trace that exists. | `test_smoke_exact_accuracy_and_idempotency` |
| NFR-05 | The full pipeline (data, checks, tests, smoke) shall run on a clean machine without network access to model providers and without cloud resources. | CI, README output |
| NFR-06 | Hosted-model spend shall be capped by a user-provided budget, estimated before start and enforced during the run. | `runner.BudgetExceeded` |
| NFR-07 | Each run shall record model id and digest, git SHA, gold hash and limits. | `runs/<id>/run.json` |

## 4. Constraints

- Python 3.11–3.12 (MetricFlow and dbt support), DuckDB 2.x, MCP SDK 2.x.
- Prices are not hardcoded; the user provides them in `config/prices.yaml`.
