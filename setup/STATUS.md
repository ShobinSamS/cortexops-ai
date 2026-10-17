# Verified environment — 16 October 2026

This is the initial prerequisite audit. The application has since been implemented;
the root README records current acceptance checks and deployment status.

| Requirement | Result |
| --- | --- |
| Python | Existing Python 3.12.10; isolated backend environment with 172 packages |
| Backend libraries | FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, Celery, LangGraph, LangChain, official MCP SDK, retrieval, auth, tracing and test dependencies installed |
| Node / frontend | Existing Node 24.16.0; 222 npm packages installed, including React 19, Vite 7, TypeScript 5, Tailwind 4 and Playwright |
| Docker / WSL | Docker Linux engine and Ubuntu WSL 2 verified; no BIOS change needed |
| Core services | PostgreSQL, Redis and Qdrant running on loopback with persistent volumes |
| Local LLM | Ollama 0.40.5 installed; Qwen3 1.7B downloaded and real CPU inference passed |
| Embeddings | all-MiniLM-L6-v2 downloaded; local 384-dimensional embedding inference passed |
| Reranking | ms-marco-MiniLM-L6-v2 downloaded; local cross-encoder inference passed |
| Browser | Project-cached Chromium installed; headless interaction passed |
| Existing tools | Git, uv and VS Code available |

Passed checks:

- `pip check`: no broken requirements.
- 22 Python dependency import checks.
- CPU tensor operation; FastAPI/Pydantic/HTTPX request.
- LangGraph execution and official MCP SDK tool registration.
- Qdrant local vector insert/query and Argon2 password hashing.
- Vite production bundle of frontend dependencies.
- Playwright Chromium launch and button interaction.
- Authenticated PostgreSQL SELECT, Redis PING, Qdrant server API.
- Real Qwen3 inference, embedding inference and reranker inference.
- npm installation audit: zero known vulnerabilities reported at installation.

These initial results verify the environment. See the root README for application
acceptance results and `SETUP.md` for license references and resource guidance.

Neo4j Community has since been downloaded and verified by integration tests.
shadcn/ui components, Nginx, Prometheus, Grafana OSS, OpenTelemetry Collector and
GitHub Actions configuration are implemented. The operations guide explains their
optional profiles and deployment boundaries.

Resolved package versions and licenses are recorded in `python-installed.json`,
`python-licenses.json`, `frontend-licenses.json` and the package lockfiles.
Model revisions/hashes are recorded in the local model download manifests and
`ollama-installed.json`. Core container images are pinned by digest.
