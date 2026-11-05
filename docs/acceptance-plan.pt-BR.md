# Plano de aceite

[English](acceptance-plan.md)

Status em 2026-11-05. Todo item marcado tem saída que o comprova no README ou no CI.

## Build e corretude

- [x] `make data gold-check parity test smoke` passa a partir de um checkout limpo (2 min 28 s, 4 vCPU)
- [x] `gold-check` OK e hash igual ao `gold/HASH` congelado (`2b8663f4…`)
- [x] `parity`: 130/130 perguntas dentro da cobertura batem
- [x] A suíte de guards cobre acesso a arquivo, configurações, DDL/DML, ATTACH/COPY/PRAGMA/INSTALL/LOAD/CALL, funções de tabela, escape de schema, timeouts
- [x] Testes baseados em propriedades do comparador: invariância a permutação de linhas e colunas, detecção de perturbações
- [x] Kill -9 no meio da execução e depois retomada: sem duplicatas, sem lacunas
- [x] O `trace_id` de toda linha de resultado existe no arquivo de traces
- [x] Smoke sobre MCP via stdio: EX exatamente 70% em cada braço (com script)
- [ ] `docker compose run --rm bench smoke` em uma máquina com Docker (não disponível no ambiente de build)
- [ ] CI verde no GitHub Actions (workflow escrito, repositório ainda não enviado)

## Resultados (aguardando execuções com modelos)

- [ ] Um modelo local via Ollama: holdout, 3 braços, 3 tentativas
- [ ] Claude: calibração no dev com 1 tentativa, depois holdout com 3 tentativas dentro do orçamento
- [ ] Teste A/A em um braço: não significativo
- [ ] Relatório: EX com IC de 95%, pares McNemar, parcela da documentação com IC, por categoria, tabela operacional
- [ ] Taxonomia de erros a partir de ~30 falhas revisadas manualmente (join errado, filtro errado, definição de métrica errada, granularidade de tempo errada, coluna alucinada, erro de protocolo de tool, recusa errada)
- [ ] README atualizado com os resultados reais e com o que eles não mostram

## Documentação

- [x] Business case, requisitos, arquitetura com ADRs, plano de aceite (EN)
- [x] Os mesmos documentos em PT-BR
- [x] README em EN e PT-BR com saída real
