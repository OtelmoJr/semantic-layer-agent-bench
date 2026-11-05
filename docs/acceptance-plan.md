# Acceptance plan

[Português](acceptance-plan.pt-BR.md)

Status as of 2026-11-05. Every checked item has output behind it in the README or in CI.

## Build and correctness

- [x] `make data gold-check parity test smoke` passes from a clean checkout (2 min 29 s, 4 vCPU)
- [x] `gold-check` OK and hash equals the frozen `gold/HASH` (`2b8663f4…`)
- [x] `parity`: 130/130 in-coverage questions match
- [x] Guard suite covers file access, settings, DDL/DML, ATTACH/COPY/PRAGMA/INSTALL/LOAD/CALL, table functions, schema escape, timeouts
- [x] Comparator property tests: row and column permutation invariance, perturbation detection
- [x] Kill -9 mid-run then resume: no duplicates, no gaps
- [x] Every result row's `trace_id` exists in the trace file
- [x] Smoke over stdio MCP: EX exactly 70% in each arm (scripted)
- [ ] `docker compose run --rm bench smoke` on a machine with Docker (not available in the build environment)
- [ ] CI green on GitHub Actions (workflow written, repository not pushed yet)

## Results (pending model runs)

- [ ] One local model via Ollama: holdout, 3 arms, 3 attempts
- [ ] Claude: dev calibration with 1 attempt, then holdout with 3 attempts within budget
- [ ] A/A test on one arm: not significant
- [ ] Report: EX with 95% CI, McNemar pairs, documentation share with CI, per category, operational table
- [ ] Error taxonomy from ~30 manually reviewed failures (wrong join, wrong filter, wrong metric definition, wrong time grain, hallucinated column, tool protocol error, wrong refusal)
- [ ] README updated with the real results and what they do not show

## Documentation

- [x] Business case, requirements, architecture with ADRs, acceptance plan (EN)
- [x] Same documents in PT-BR
- [x] README EN and PT-BR with real output
