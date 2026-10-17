# Evaluation

`cases.json` includes the successful preprocessing regression, an ambiguous
source-mix question, irrelevant documents, a deliberately denied tool, and an
empty workspace with insufficient evidence. Labels are evaluation expectations,
never inputs that encode the diagnosis into the agent.

Run against a healthy local app with its workers and five MCP servers:

```powershell
.\backend\.venv\Scripts\python.exe evaluation/run.py
.\backend\.venv\Scripts\python.exe evaluation/run.py --case preprocessing-regression --investigate
.\backend\.venv\Scripts\python.exe evaluation/run.py --case denied-analytics --case empty-workspace --investigate
```

Use `--base-url http://127.0.0.1:8080` for Nginx/Compose. Each case creates its
own workspace with generated credentials, then uses real uploads, ingestion,
retrieval and optional model inference. Generated evaluation workspaces persist
for inspection. The output contains workspace/investigation/report IDs and scores,
never passwords, tokens, or source secrets. Results are written incrementally to
`results.json`; setup failures produce a nonzero exit code.

Measured fields:

- Document-level Recall@6 and precision among unique retrieved documents, using
  the labeled relevant-document set. These are not chunk-level metrics.
- Irrelevant-query abstention: whether retrieval returned zero records for a query
  labeled irrelevant. The baseline returned all available records for an unrelated
  query; a configurable top-logit floor now permits retrieval abstention. Calibrate
  `RETRIEVAL_MIN_SCORE` for a different cross-encoder or corpus. It is not a semantic
  safety guarantee, and relevant queries can still retrieve contextual noise.
- Citation-ID validity: fraction of cited supporting/contradictory IDs present in
  the report's recorded evidence. This checks referential integrity, not entailment.
- Expected-term matching on the successful incident, job/outcome expectations,
  and measured wall time. These are smoke-test metrics, not causal correctness.
  Failed explicit outcome/status/term expectations produce a nonzero exit code.

Use `--output evaluation/another-run.json` to preserve separate runs. Output files
must stay inside this project. `results.json` contains the initial full five-case
run; post-change checks are recorded separately with their scope made explicit.

The automated backend workflow test separately verifies real checkpoint resume
after a permission failure, single planner execution, numeric observations,
source-bound hypotheses and the incident's preprocessing explanation. Isolated
validation tests cover invented citations and honest insufficient-evidence output.
Never interpret a small synthetic set as an enterprise-wide model accuracy estimate.
