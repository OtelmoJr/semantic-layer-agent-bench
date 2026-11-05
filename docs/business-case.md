# Business case

[Português](business-case.pt-BR.md)

## Problem

Teams putting "chat with your data" agents in front of business users face a design
choice with real cost: give the agent SQL over the warehouse, or build and maintain a
semantic layer (dbt MetricFlow, Cube, Databricks Metric Views, Snowflake Semantic Views)
and let the agent query governed metrics only.

The case for the semantic layer rests mostly on vendor benchmarks that compare raw schema
against semantic layer. Those comparisons change two things at once: the abstraction and
the business definitions that come with it. A team that already has good documentation
cannot tell from them whether the layer is worth its modeling and maintenance cost.

## Question this project answers

How much of a semantic layer's accuracy gain for text-to-SQL agents comes from the layer
itself, and how much from the business definitions it carries?

## Who uses the answer

| Stakeholder | Decision it informs |
|---|---|
| Data platform lead | Build/maintain a semantic layer vs invest in documentation and catalogs |
| Analytics engineer | Which business rules to encode as metrics first |
| AI engineer | Which tool surface to expose to an analytics agent, and whether model size changes the answer |

## Options compared

| Option | Pays | Gets |
|---|---|---|
| A. Raw SQL | Inconsistent definitions, plausible wrong numbers | Full coverage, no modeling |
| B. Raw SQL + glossary in context | Writing and keeping a glossary current, longer prompts | Definitions without a new system |
| C. Semantic layer | Modeling, a new component to run, coverage limited to what is modeled | Definitions enforced by construction, fewer degrees of freedom |

## Success criteria

1. A reproducible result: anyone can run it locally with one command and get the same
   gold set hash, parity and test results.
2. A defensible number: holdout execution accuracy per arm with 95% CIs, paired tests,
   and the documentation share (B−A)/(C−A) with its CI.
3. Honest limits: what the sample size cannot resolve is stated in the report.

## Cost

| Item | Cost |
|---|---|
| Infrastructure | Local machine; DuckDB, dbt and MetricFlow are open source |
| Local model runs | Electricity and time (GPU recommended) |
| Claude runs | Token cost, capped by `--budget-usd` and calibrated on the dev split first |

## Out of scope

Production deployment, access control for end users, multi-turn conversations,
non-English questions, write operations.
