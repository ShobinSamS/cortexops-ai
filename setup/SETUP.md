# CortexOps AI prerequisite setup

This folder prepares the environment from the supplied project prompt. Application
implementation, migrations, authentication, agents, and UI pages come afterwards.

## Machine and development profile

Audited on 16 October 2026: Windows 11 Home 25H2, HP Pavilion 15-cs1xxx,
Intel i5-8265U (4 cores / 8 threads), 15.9 GB RAM, Intel UHD 620 graphics.
Use CPU inference. No CUDA toolkit or NVIDIA driver is needed.

Existing tools: Python 3.12.10, Node 24.16.0, npm 11.4.1, Git 2.47.0,
uv 0.7.12, Docker Engine 29.8.0, Compose 5.5.1, WSL 3.0.1.0, Ubuntu WSL 2,
and VS Code. WSL successfully booted and Docker's Linux engine responded.
Do not change BIOS settings based solely on the CPU CIM virtualization field:
the Windows hypervisor is already present and both runtimes work.

Project dependencies live in `backend/.venv` and `frontend/node_modules`.
The existing system Python has no pip; pip is installed inside the project
environment. Use uv to manage that environment. No activation or PowerShell
execution-policy change is necessary.

The lightweight profile runs PostgreSQL, Redis, and Qdrant. Start Neo4j only
when graph development requires it. Avoid running a larger LLM, embedding jobs,
Neo4j, and the complete monitoring stack simultaneously on this laptop.
Disk C had approximately 27.6 GB free before setup; monitor remaining space.

## Repeat the setup

Run from the `cortexops-ai` directory in PowerShell:

```powershell
python .\setup\init-environment.py
Push-Location backend
uv sync --locked --group dev
Pop-Location
Push-Location frontend
npm.cmd ci --no-fund
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Split-Path -Parent (Get-Location).Path) '.cache\ms-playwright'
node .\node_modules\playwright\cli.js install chromium
Pop-Location
docker compose -f compose.prerequisites.yml up -d --wait
ollama pull qwen3:1.7b
.\backend\.venv\Scripts\python.exe .\setup\cache-models.py
```

Ollama is installed with the official Windows installer through winget:

```powershell
winget install --id Ollama.Ollama --exact --source winget --scope user
```

Open a fresh terminal after installing Ollama so PATH refreshes. In an existing
terminal use `& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"`.
The Ollama Windows app provides the server; if it is not running, use `ollama serve`.

## Verify

```powershell
.\backend\.venv\Scripts\python.exe -m pip check
.\backend\.venv\Scripts\python.exe .\setup\verify-python.py
node .\setup\verify-frontend.mjs
.\backend\.venv\Scripts\python.exe .\setup\verify-services.py
docker compose -f compose.prerequisites.yml ps
```

These are environment smoke checks. They are not tests of the unimplemented
CortexOps application. `verify-services.py` performs a real Ollama inference
and unloads the model afterwards to release memory.

The embedding and reranker weights are stored under `.cache/models/embedding`
and `.cache/models/reranker`. `cache-models.py` fetches the official model revision,
uses bounded HTTPS ranges for this network, records each file's SHA-256 and the
upstream commit in `download-manifest.json`, and verifies local CPU inference.
Use these local directories when configuring offline application inference.
The generated local `.env` selects their absolute paths. `.env.example` retains
the upstream identifiers for portable deployments.

## Services

| Component | Local address | Profile |
| --- | --- | --- |
| PostgreSQL | 127.0.0.1:5432, database/user `cortexops` | Default |
| Redis | 127.0.0.1:6379 | Default |
| Qdrant | http://127.0.0.1:6333 | Default |
| Ollama | http://127.0.0.1:11434 | Native Windows |
| Neo4j browser / Bolt | http://127.0.0.1:7474 / 127.0.0.1:7687 | `full` |

Passwords are randomly generated into ignored `.env`; they are not committed.
This Compose file is for local development. Its services bind to loopback.
Application roles, read-only analytics permissions, and service authentication
must be added during implementation before deployment.

```powershell
# Add Neo4j when needed:
docker compose -f compose.prerequisites.yml --profile full up -d neo4j
# Stop local services and preserve data:
docker compose -f compose.prerequisites.yml --profile full stop
# Start them again:
docker compose -f compose.prerequisites.yml up -d --wait
```

Celery is installed for imports and development; run its workers in Linux
containers/WSL. Windows workers are not officially supported. No host PostgreSQL,
Redis, Qdrant, Java, or Neo4j installation is necessary.

## Versioning and licenses

`backend/uv.lock` and `frontend/package-lock.json` record the resolved versions.
The three installed container images are pinned to their downloaded digests in
`compose.prerequisites.yml`; optional Neo4j is selected from the 5.26 Community line.
The Python project restricts Python to 3.12 for the initial reproducible setup,
uses Pydantic 2, SQLAlchemy 2, LangGraph 1, and the official MCP Python SDK 1.
These stable major versions are deliberate; later major upgrades require testing.
PyTorch comes from its explicit CPU wheel index, so CUDA packages are not needed.

Direct dependency metadata from the official registries is saved in
`registry-metadata.json`. This file describes latest registry metadata at audit
time; installed-version license reports should be used for the actual environment.
`python-licenses.json` and `frontend-licenses.json` contain installed-version
metadata. `py_rust_stemmers` 0.1.8 reports UNKNOWN in its package metadata; its
installed `dist-info/licenses/LICENSE` explicitly identifies the MIT license.

Python/frontend dependencies use open-source licenses including MIT, Apache 2.0,
BSD, ISC, and LGPL (psycopg). Service/model license references:

- [PostgreSQL license](https://www.postgresql.org/about/licence/)
- [Redis licensing](https://redis.io/legal/licenses/): Redis 8 offers AGPLv3 as an open-source license option.
- [Qdrant Apache 2.0 license](https://github.com/qdrant/qdrant/blob/master/LICENSE)
- [Neo4j Community GPLv3](https://github.com/neo4j/neo4j/blob/5.26/LICENSE.txt)
- [Ollama MIT license](https://github.com/ollama/ollama/blob/main/LICENSE)
- [Qwen3 1.7B model card](https://huggingface.co/Qwen/Qwen3-1.7B): Apache 2.0.
- [Embedding model](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2): Apache 2.0.
- [Reranker model](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2): Apache 2.0.
- [Docker Desktop license](https://docs.docker.com/subscription-billing/desktop-license/):
  Docker Desktop is proprietary development tooling already installed on this PC.
  Personal/educational/noncommercial open-source use qualifies for its free tier.
  Deployment can use open-source Docker Engine and Compose on Linux.

## Added during application implementation

shadcn/ui components are generated into frontend source when the UI is initialized;
the Radix Slot, styling utilities, Tailwind, and icon prerequisites are installed.
Nginx, Prometheus, Grafana OSS, and the OpenTelemetry Collector will be configured
as Docker services when application endpoints and telemetry exist. The Python
OpenTelemetry SDK/exporter/instrumentation and Prometheus client are installed.
GitHub Actions is repository CI configuration, not a local program to install.
An optional GitHub personal access token will only be needed for real GitHub
integration; synthetic local investigation development does not require one.
