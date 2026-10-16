# Operations and deployment

## Execution modes

The lightweight mode runs Python/Vite natively and PostgreSQL, Redis and Qdrant
in Docker. Two solo Celery workers prevent investigation-to-retrieval deadlock.
Five separately authenticated MCP HTTP servers run on ports 8101–8105.
The full application Compose deployment runs these application processes in
Linux containers behind Nginx; Ollama remains a host process to reuse the model.
Neo4j (`full`) and monitoring (`observability`) are optional profiles.

Avoid running native and container application stacks together: port 8000 and
their queues/database are shared. The 16 GB laptop should run one stack and one
CPU investigation at a time. Optional services add memory pressure. Stop the
native launcher before container deployment; preserve infrastructure volumes.

## First container run

From the repository root, after dependency/model setup in the README:

```powershell
.\setup\dev.ps1 -Action stop
python setup/configure-app.py
docker compose build
docker compose up -d --wait
docker compose ps
```

The one-shot `init` service runs Alembic, provisions the read-only analytics role
from the generated environment secret, and synchronizes the displayed MCP URLs.
The API initializes LangGraph's SDK-owned checkpoint tables before workers start.
Open http://127.0.0.1:8080. Every MCP destination is derived from operator settings;
stored display URLs are never followed as arbitrary network targets.

Windows Ollama normally listens only on loopback. For container access, quit the
tray Ollama process, set `OLLAMA_HOST=0.0.0.0:11434` in its operator environment,
and relaunch Ollama. Restrict port 11434 to your Docker/local host with Windows
Firewall; do not expose unauthenticated inference to the public network. A
dedicated Linux deployment can use an Ollama container on the private network and
set `OLLAMA_BASE_URL=http://ollama:11434` instead.

The upload volume is separate from native `.data/uploads`. Use one mode for an
existing workspace's documents or migrate its files and `storage_path` values
together. Database/Redis/Qdrant volumes are shared between these Compose files.

## Optional services

```powershell
# Neo4j projection; set before recreating app/worker containers:
$env:CONTAINER_NEO4J_URI='bolt://neo4j:7687'
docker compose --profile full up -d --wait
# Select Knowledge graph > Rebuild & sync in the UI.

# Local telemetry and metrics dashboard:
$env:CONTAINER_OTEL_ENDPOINT='http://otel-collector:4318'
docker compose --profile observability up -d --wait
```

Native mode can set `NEO4J_URI=bolt://127.0.0.1:7687` and
`OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318` in `.env`, then restart the
launcher. Start the optional services using the corresponding Compose profile.

Prometheus is at http://127.0.0.1:9090. Grafana OSS is at
http://127.0.0.1:3000 with user `cortexops` and the generated `GRAFANA_PASSWORD`
in your ignored `.env`. Its Prometheus datasource and CortexOps Operations
dashboard are provisioned automatically. Collector health is at
http://127.0.0.1:13133; traces are exported to collector logs using the debug
exporter. This configuration verifies the trace pipeline; it does not include a
long-term trace database or trace search UI.

Prometheus scrapes bounded route/status HTTP counters and latency histograms.
Database-derived gauges include investigation status, worker LLM calls, tokens,
and tool outcomes across both queues. No email, question, document text, token,
workspace label, or arbitrary URL becomes a metric label. Application request/job
events use JSON logs. Operational failures include request IDs and retain detailed
server diagnostics. SQL parameter logging is disabled.

Image/version and license references:

- Prometheus v3.5.0: [Docker installation](https://prometheus.io/docs/prometheus/latest/installation/), [Apache 2.0](https://github.com/prometheus/prometheus/blob/main/LICENSE).
- Grafana OSS 12.2.0: [Docker installation](https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/), [AGPLv3](https://github.com/grafana/grafana/blob/main/LICENSE).
- OpenTelemetry Collector Contrib 0.162.0: [Docker installation](https://opentelemetry.io/docs/collector/install/docker/), [configuration](https://opentelemetry.io/docs/collector/configuration/), [Apache 2.0](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/LICENSE).

These are explicit deployment versions, not a claim that they are the newest
security releases. Review image advisories before deploying to an organization.

## Health, logs and shutdown

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
docker compose logs --tail 100 api worker investigation-worker
docker compose logs --tail 50 mcp-analytics otel-collector
docker compose stop
```

`stop` preserves named volumes; routine shutdown never requires `down --volumes`.
The native launcher writes process IDs and creation times in
`.data/dev-services.json`; its stop action only terminates those owned process
trees. Logs are under `setup/dev-*.log`. Never paste `.env` or connection strings
into issues, model prompts, frontend configuration, or screenshots.

## Recovery and persistence

Investigations, steps, tool/agent attempts, reports, events, approvals and
LangGraph checkpoints persist in PostgreSQL. Redis is a queue/notification/cache;
the event table is authoritative for replay. Qdrant stores dense/sparse vectors;
canonical chunk text/ownership/status remains in PostgreSQL. Neo4j is a rebuildable
projection; a failed projection falls back to the canonical PostgreSQL graph.

After a worker interruption, inspect the job and investigation status. A failed
investigation can resume from its checkpoint. If the process died before recording
failure, the operator should confirm no owned worker is executing it, mark the
abandoned job failed and investigation failed in an audited maintenance procedure,
then use Resume. There is no automatic zombie-job sweeper. Session advisory locks
release on lost connections and prevent simultaneous duplicate execution.

An approved external write is consumed before execution. If the GitHub request
times out after it may have been accepted, verify the destination and its approval
marker before requesting a new action. The app deliberately does not retry an
ambiguous external write automatically.

Back up PostgreSQL, Qdrant snapshots and upload storage as a consistent set.
Keep environment secrets separately in protected operator storage. Test restores
before upgrades. Neo4j can be rebuilt from canonical records. Do not copy live
PostgreSQL data directories as an ad-hoc backup.

## Deployment boundary

This is a verified local engineering showcase with production-oriented boundaries.
Before serving organizational data, configure TLS, secure cookies, exact origins,
`APP_ENV=production`, `ENABLE_DEMO=false`, private networks, backups and a dedicated
least-privilege application DB role separate from the migration owner. Restrict
self-registration at the reverse proxy or add an organization identity provider.
The sample deployment intentionally binds published ports to loopback. It does
not include SSO, organization provisioning, antivirus/OCR, HA, disaster-recovery
automation, a penetration test, or an independent security audit.
