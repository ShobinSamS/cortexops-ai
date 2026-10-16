"""Integration tests use an ephemeral PostgreSQL database, never application data."""
import os
from pathlib import Path
import subprocess
import sys
import secrets
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
import pytest

ROOT = Path(__file__).resolve().parents[2]
env = dotenv_values(ROOT / ".env")
DATABASE_NAME = "cortexops_test_" + uuid4().hex[:12]
ADMIN = make_conninfo(host=env.get("POSTGRES_HOST", "127.0.0.1"), port=env.get("POSTGRES_PORT", 5432), dbname="postgres", user=env.get("POSTGRES_USER", "cortexops"), password=env["POSTGRES_PASSWORD"], connect_timeout=5)
from urllib.parse import quote_plus
os.environ["DATABASE_URL"] = f"postgresql+psycopg://{env.get('POSTGRES_USER','cortexops')}:{quote_plus(env['POSTGRES_PASSWORD'])}@{env.get('POSTGRES_HOST','127.0.0.1')}:{env.get('POSTGRES_PORT',5432)}/{DATABASE_NAME}"
os.environ["APP_ENV"] = "test"
os.environ["ACCESS_TOKEN_MINUTES"] = "30"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/15"
os.environ["CELERY_QUEUE"] = DATABASE_NAME
os.environ["UPLOAD_DIR"] = str(ROOT / ".data/test-uploads" / DATABASE_NAME)
ANALYTICS_ROLE = DATABASE_NAME + "_ro"
ANALYTICS_SECRET = secrets.token_urlsafe(24)
os.environ["ANALYTICS_DATABASE_URL"] = f"postgresql://{ANALYTICS_ROLE}:{ANALYTICS_SECRET}@{env.get('POSTGRES_HOST','127.0.0.1')}:{env.get('POSTGRES_PORT',5432)}/{DATABASE_NAME}"
os.environ["MCP_PORT_OFFSET"] = "1000"
if os.environ.get("CORTEXOPS_TEST_NEO4J"):
    os.environ["NEO4J_URI"] = "bolt://127.0.0.1:7687"


@pytest.fixture(autouse=True)
def isolated_test_client_rate_window():
    # Independent cases represent different users, but TestClient gives every
    # request the same synthetic IP. Reset only that IP in the reserved test DB;
    # rate limits still apply within each case and production DB 0 is untouched.
    from redis import Redis
    with Redis.from_url(os.environ["REDIS_URL"]) as cache:
        keys = list(cache.scan_iter(match="rate:*:testclient:*"))
        if keys:
            cache.delete(*keys)


@pytest.fixture(scope="session")
def client():
    with psycopg.connect(ADMIN, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE_NAME)))
    try:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "backend", env=os.environ.copy(), check=True, capture_output=True)
        with psycopg.connect(ADMIN, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}").format(sql.Identifier(ANALYTICS_ROLE), sql.Literal(ANALYTICS_SECRET)))
            connection.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only=on").format(sql.Identifier(ANALYTICS_ROLE)))
        with psycopg.connect(make_conninfo(ADMIN, dbname=DATABASE_NAME), autocommit=True) as connection:
            connection.execute("CREATE VIEW analytics_model_observations AS SELECT id,workspace_id,version,category,correct,confidence,latency_ms,observed_at FROM model_observations")
            connection.execute("CREATE VIEW analytics_deployments AS SELECT id,workspace_id,version,service,commit_sha,deployed_at,configuration FROM deployments")
            connection.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(ANALYTICS_ROLE)))
            connection.execute(sql.SQL("GRANT SELECT ON analytics_model_observations,analytics_deployments TO {}").format(sql.Identifier(ANALYTICS_ROLE)))
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as test_client:
            yield test_client
    finally:
        with psycopg.connect(ADMIN, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(DATABASE_NAME)))
            connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(ANALYTICS_ROLE)))


def account(client):
    email = f"user-{uuid4().hex[:10]}@example.test"
    response = client.post("/api/v1/auth/register", json={"email": email, "password": "a-strong-local-test-password", "name": "Test Analyst", "workspace_name": "Isolated test workspace"})
    assert response.status_code == 201, response.text
    return response.json(), {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="session")
def worker(client):
    output = (ROOT / "setup/phase2-test-worker.log").open("w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "celery", "-A", "app.workers.celery_app:celery", "worker", "--pool=solo", "--concurrency=1", "--loglevel=info", "--without-gossip", "--without-mingle", "--without-heartbeat"], cwd=ROOT / "backend", env=os.environ.copy(), stdout=output, stderr=subprocess.STDOUT)
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    output.close()


@pytest.fixture(scope="session")
def mcp_servers(client):
    import socket
    import time
    processes = []
    try:
        for i, kind in enumerate(["github", "analytics", "knowledge", "monitoring", "incidents"]):
            log = (ROOT / f"setup/mcp-test-{kind}.log").open("w", encoding="utf-8")
            proc = subprocess.Popen([sys.executable, "-m", "app.mcp.server", "--kind", kind], cwd=ROOT / "backend", env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT)
            processes.append((proc, log))
        deadline = time.monotonic() + 45
        for i, kind in enumerate(["github", "analytics", "knowledge", "monitoring", "incidents"]):
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", 9101 + i), timeout=1):
                        break
                except OSError:
                    if time.monotonic() > deadline:
                        raise AssertionError(f"MCP {kind} failed to start; inspect setup/mcp-test-{kind}.log")
                    time.sleep(.3)
        yield
    finally:
        for proc, log in processes:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.close()


@pytest.fixture(scope="session")
def investigation_worker(worker):
    output = (ROOT / "setup/phase4-test-worker.log").open("w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "celery", "-A", "app.workers.celery_app:celery", "worker", "--pool=solo", "--concurrency=1", "--loglevel=info", "-Q", DATABASE_NAME + ".investigations", "--without-gossip", "--without-mingle", "--without-heartbeat"], cwd=ROOT / "backend", env=os.environ.copy(), stdout=output, stderr=subprocess.STDOUT)
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    output.close()
