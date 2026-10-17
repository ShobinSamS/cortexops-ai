# Resume checkpoint - 16 October 2026

**Superseded on 17 October 2026:** the remaining local implementation and acceptance
checks below have been completed. See `VERIFICATION.md` for 22 backend tests,
4 browser workflows, actual telemetry, evaluation results and successful GitHub CI.
The original pause notes are retained as development history, not a current to-do.

The user paused implementation to continue tomorrow and requested a new GitHub
repository containing the current project. Continue the original full application
objective next session; do not treat Phase 6 as complete.

## Verified

- Latest complete backend regression: **21 passed, 3 warnings in 436.98s**.
  Local log: `setup/backend-regression.log` (ignored by Git).
- Regression used ephemeral PostgreSQL data, real Redis/Qdrant, two actual Celery
  workers, five official MCP SDK servers, CPU embedding/reranking/Qwen3 inference,
  and Neo4j for the graph tests. It exercised pause, permission failure and resume.
- Individual graph/PDF/workspace run: **3 passed in 23.14s**.
- Focused evidence validation: **5 passed in 3.24s**.
- Frontend TypeScript/Vite build passed after graph/PDF/workspace UI changes
  (`setup/phase5-frontend-build.log`); page bundles split successfully.
  Small later changes to document filtering, tool activity and download refresh
  still need the next final frontend build.
- Earlier foundation and knowledge browser workflows passed. Tools browser test
  had a locator error that was corrected; it must be rerun. New real investigation
  Playwright test is authored but has not run.
- PDF sample `output/pdf/sample-investigation-report.pdf` was reopened, rendered
  with Poppler, and both pages visually inspected. It contains synthetic test data.

## Implementation landed

Authentication/refresh rotation, RBAC, workspaces/membership and switching,
investigation CRUD/control/history, durable ordered events/WebSocket replay,
bounded document parsing/upload, hybrid retrieval/reranking, MCP discovery/tools,
read-only analytics, approvals bound to both exact arguments and destination,
LangGraph checkpoints/budgets, verified numerical observations versus model
hypotheses, reports with PDF/Markdown, and a provenance-preserving graph with an
optional Neo4j projection. See architecture and operations docs for boundaries.

Qwen3's unconstrained free-text diagnosis originally hallucinated an unchanged
model-weight explanation. Closed-choice assessment now selects among actual
observed code changes; report wording derives from the selected recorded diff.
The real test retained its preprocessing-quality assertion and passed. A unit
test verifies selection of the second candidate rather than a hardcoded first.

## Next work, in order

1. Check `setup/docker-build.log` and `setup/observability-pull.log`. Downloads and
   image builds were in progress at the pause; determine their final status before
   restarting. Backend package download finished, image export was pending.
   Do not claim the full Compose deployment has run yet.
   Update verified on 17 October: both backend and frontend image builds completed
   successfully after the pause. Full Compose startup remains unverified; rebuild
   before verification to include the latest source changes.
2. Run one app stack at a time on this 16 GB CPU laptop. Native launcher was stopped
   to free memory for isolated tests/builds. Core database containers remain.
   Optional Neo4j was stopped after its integration tests due memory pressure.
   `setup/dev.ps1 -Action status` reports launcher-owned processes only.
3. Rebuild updated frontend/backend images as needed, verify full Compose startup
   (init migrations/read-only role, API, both workers, all five MCP containers and
   Nginx). Check host Ollama reachability from containers; see OPERATIONS.md.
   Native and container upload paths use separate storage and need care if
   switching existing workspaces across execution modes.
4. Verify optional Prometheus/Grafana/collector configuration and actual exported
   metrics/traces. Worker activity uses persisted database gauges. The collector
   debug exporter does not provide a trace search database.
5. Start native mode or use Nginx as E2E_BASE_URL, rerun browser suite serially.
   Run the real-model browser workflow with `E2E_LLM=1`; capture actual graph,
   execution, report and approval screenshots. The Tools test uses the select's
   explicit Server accessible name because workspace switching adds another select.
6. Run real HTTP evaluation and record measured results. Cases include successful,
   ambiguous, irrelevant, denied-tool and empty-workspace investigations. Ranking
   can return irrelevant documents; do not claim semantic abstention/entailment
   from citation integrity. CPU inference is slow; execute cases sequentially.
7. Review GitHub Actions by execution, final build, security/code review, API
   documentation, version/license inventory and README cleanup. Some older README
   sections/setup STATUS.md still describe earlier milestones; consolidate them.
   CI has been authored locally but is not yet claimed as passing on GitHub.

## Important implementation details

- Root config supports `CORTEXOPS_ROOT=/app` for containers; demo-data is mounted.
- MCP URLs always derive from operator configuration; sync display URLs using
  `python -m app.cli sync-endpoints` when switching modes.
- Analytics role setup supports `--no-write-env`; generated secrets stay in `.env`.
- Test rate-limit windows reset only the synthetic TestClient IP in reserved Redis
  database 15 between independent cases. Production limits remain enabled.
- Windows async Python tests require normal loopback access (the restricted shell
  can hang asyncio initialization); use the approved execution environment.
- No GitHub token, generated .env, local databases, uploads, model weights, caches,
  dependencies, logs or browser traces belong in the repository.
- Test workflows create only isolated local synthetic incidents; live GitHub writes
  require a configured workspace/repository and a single-use human approval.
- Keep README updated with actual checks and unresolved limitations. Do not present
  this local showcase as independently security-audited enterprise deployment.
