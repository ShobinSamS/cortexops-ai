# Verification - 17 October 2026

All results below were observed, not inferred from generated code. Local logs
remain under ignored `setup/*.log`; the repository contains reproducible tests,
synthetic evaluation output, screenshots and a sample real investigation export.

## Application acceptance

| Area | Evidence |
| --- | --- |
| Backend regression | **22 passed in 195.35s**; `setup/final-backend-tests.log` |
| Real model | Qwen3 1.7B through Ollama; actual planner/diagnosis inference and token accounting |
| Recovery | Pause, permission denial, failed-node resume from PostgreSQL checkpoints; planner executed once |
| Tool protocol | Five actual MCP SDK HTTP servers; discovery/read/write authorization and restricted SQL role |
| Documents | Real parsing, CPU embedding, Qdrant dense/sparse fusion, graph expansion and reranking |
| Query abstention | Real cross-encoder rejects an unrelated query when its top score is below the configured floor |
| Graph | Separate actual Neo4j synchronization/provenance/isolation test run: **3 passed in 23.14s** with PDF/workspace tests |
| Docker | Init, API, both Celery queues, all five MCP servers and Nginx started; host Ollama access returned HTTP 200 |
| Browser | **4 passed in 3.0 minutes** through Nginx; `setup/final-browser-combined.log` |
| Report | Real model selected the observed bicubic-to-nearest preprocessing change; numerical results computed from source rows |
| PDF | Downloaded via browser, reopened with pypdf, rendered with Poppler and visually inspected; seven pages |
| Telemetry | Actual API spans received by collector debug exporter; Prometheus worker-derived gauges; Grafana dashboard provisioned |
| Static check | Ruff `F,E9` passed; TypeScript/Vite production build passed |
| GitHub CI | [Successful run on c29e78b](https://github.com/ShobinSamS/cortexops-ai/actions/runs/38998911293), including Linux non-LLM integration and 3 browser checks |

The three backend warnings come from the MCP SDK's deprecated transport wrapper
in a direct negative-test helper. Application clients use the supported transport.
The CI job's optional real-model input was not enabled; real inference was verified
locally in both the backend regression and complete browser workflow.

## Evaluation scope and results

`evaluation/results.json` preserves the initial real five-case run. Each case
created an isolated workspace and used actual workers/tools/models. Relevant
document labels are small synthetic sets; Recall@6 is document-level, and precision
is calculated among unique retrieved documents, not chunks.

| Baseline case | Measured behavior |
| --- | --- |
| Successful preprocessing regression | Recall@6 1.0; document precision 0.333; citation-ID validity 1.0; expected root-cause terms matched; 123.39s |
| Ambiguous source-mix question | Recall@6 1.0; precision 0.333; citation-ID validity 1.0; explicitly a hypothesis report; 68.39s |
| Unrelated astronomy query | Returned unrelated ranked context; abstention false; demonstrated that valid IDs alone do not establish relevance; 64.12s |
| Deliberately denied analytics | Failed with the expected permission boundary; 17.72s |
| Empty workspace | Completed with insufficient evidence and no invented cause; 15.03s |

The unrelated-query result prompted two changes: a configurable top-logit floor
for retrieval and an empty-findings option for unsupported diagnosis. The separate
post-change run, `evaluation/abstention-results.json`, returned **zero retrieved
documents** for the unrelated search and **no supported hypothesis** for its
investigation in 64.97s. The final 22-test suite and four browser workflows ran
with these changes, preserving the successful regression explanation.

These measurements do not establish general enterprise accuracy, semantic
entailment or causal correctness. The floor is a development calibration for
the selected cross-encoder; evaluate it again for a different corpus/model.

## Fixes discovered through verification

- Initialized SDK checkpoint tables before workers held execution leases, removing
  an index-creation/open-transaction deadlock.
- Separated investigation and ingestion/search workers to prevent solo-worker
  retrieval deadlock.
- Bound approvals to exact arguments and destination, invalidating mode/repository
  changes and replay; ambiguity after a possible external write is not retried.
- Used actual model selection among recorded diffs after unconstrained small-model
  prose invented an unchanged weight explanation. The quality assertion remained.
- Committed API transactions before sending HTTP responses, eliminating an actual
  discovery/refetch race and allowing commit failures to return errors properly.
- Derived report coverage/caveats from recorded execution rather than accepting
  model caveats that contradicted measured observations.
- Corrected CI's backend working directory and its install/test browser-cache path.

## Practical limits

This verifies a complete local demonstration, not an independent production audit.
Only GitHub has a live external adapter; other operational tools read persisted
workspace records. OCR, SSO, HA, zombie-job sweeping and long-term trace search are
outside this implementation. TLS, protected identity/registration, production DB
roles, private networks and tested backups are operator deployment work described
in the operations guide. No real GitHub issue was created by the test/evaluation
workflows; approved write tests created only isolated local incidents.
