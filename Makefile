# Semantic Layer Agent Bench. Every target is idempotent.
PY      ?= .venv/bin/python
SLAB    ?= .venv/bin/slab
DBT     ?= .venv/bin/dbt
SF      ?= 1
MODEL   ?=
RUN     ?=
export SLAB_DB_PATH ?= $(CURDIR)/data/tpch.duckdb
SMOKE_IDS = sim001,sim007,mj001,mj004,tim001,tim018,bd001,bd003,ooc001,ooc013

.PHONY: install data semantic gold-check parity test test-fast smoke bench-ollama bench-claude report clean

install:            ## create venv and install (needs uv)
	uv venv -p 3.12 .venv
	uv pip install -p $(PY) -e ".[dev]"

data:               ## TPC-H -> DuckDB, then build the semantic layer models
	$(SLAB) data --sf $(SF)
	$(MAKE) semantic

semantic:           ## dbt build (views + time spine) and semantic manifest
	$(DBT) build --project-dir dbt --profiles-dir dbt --target local --quiet

gold-check:         ## validate gold set and its frozen hash
	$(SLAB) gold-check

parity:             ## semantic layer must reproduce every in-coverage reference result
	$(SLAB) parity

test:               ## full test suite (needs `make data`)
	$(PY) -m pytest -q

test-fast:          ## unit tests only, no database
	$(PY) -m pytest -q -m "not data and not semantic"

smoke:              ## scripted stub over stdio MCP, expects EX = 70% in every arm
	$(SLAB) bench --provider stub --ids $(SMOKE_IDS) --attempts 1 --run-id smoke --transport stdio
	$(SLAB) report smoke --split all

bench-ollama:       ## make bench-ollama MODEL=<ollama tag>
	$(SLAB) bench --provider ollama --model $(MODEL) --split holdout --attempts 3 $(if $(RUN),--run-id $(RUN))

bench-claude:       ## calibrate on dev first: see README
	$(SLAB) bench --provider anthropic $(if $(MODEL),--model $(MODEL)) --split holdout --attempts 3 --budget-usd $(BUDGET_USD) $(if $(RUN),--run-id $(RUN))

report:             ## make report RUN="run1 run2"
	$(SLAB) report $(RUN)

clean:
	rm -rf runs dbt/target dbt/logs .pytest_cache
