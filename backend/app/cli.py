"""Explicit operator commands; never invoked from an LLM or public API."""
import argparse
import asyncio
from pathlib import Path
import secrets
from urllib.parse import quote_plus

import psycopg
from psycopg import sql
from app.core.config import ROOT, get_settings


def setup_analytics(write_env=True):
    settings = get_settings()
    env_path = ROOT / ".env"
    from dotenv import dotenv_values
    values = dotenv_values(env_path)
    password = settings.analytics_password or values.get("ANALYTICS_PASSWORD") or secrets.token_urlsafe(32)
    if not write_env and not settings.analytics_password:
        raise ValueError("ANALYTICS_PASSWORD is required when --no-write-env is set")
    with psycopg.connect(settings.psycopg_url, autocommit=True, connect_timeout=5) as conn:
        if conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", ("cortexops_analytics",)).fetchone() is None:
            conn.execute(sql.SQL("CREATE ROLE cortexops_analytics LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}").format(sql.Literal(password)))
        else:
            conn.execute(sql.SQL("ALTER ROLE cortexops_analytics PASSWORD {}").format(sql.Literal(password)))
        conn.execute("ALTER ROLE cortexops_analytics SET default_transaction_read_only=on")
        conn.execute("CREATE OR REPLACE VIEW analytics_model_observations AS SELECT id,workspace_id,version,category,correct,confidence,latency_ms,observed_at FROM model_observations")
        conn.execute("CREATE OR REPLACE VIEW analytics_deployments AS SELECT id,workspace_id,version,service,commit_sha,deployed_at,configuration FROM deployments")
        conn.execute("GRANT USAGE ON SCHEMA public TO cortexops_analytics")
        conn.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM cortexops_analytics")
        conn.execute("GRANT SELECT ON analytics_model_observations,analytics_deployments TO cortexops_analytics")
    url = f"postgresql://cortexops_analytics:{quote_plus(password)}@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    if not write_env:
        print("Read-only analytics role and approved views configured from operator environment.")
        return
    content = env_path.read_text(encoding="utf-8")
    import re
    for name, value in {"ANALYTICS_PASSWORD": password, "ANALYTICS_DATABASE_URL": url}.items():
        if re.search(rf"^{name}=", content, re.MULTILINE):
            content = re.sub(rf"^{name}=.*$", f"{name}={value}", content, flags=re.MULTILINE)
        else:
            content += f"\n{name}={value}\n"
    env_path.write_text(content, encoding="utf-8")
    print("Read-only analytics role and approved views configured; credentials saved to ignored .env.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["setup-analytics", "sync-endpoints"])
    parser.add_argument("--no-write-env", action="store_true")
    args = parser.parse_args()
    if args.command == "setup-analytics":
        setup_analytics(write_env=not args.no_write_env)
    elif args.command == "sync-endpoints":
        from app.services.auth import SERVER_PORTS, mcp_endpoint
        with psycopg.connect(get_settings().psycopg_url, autocommit=True) as conn:
            for kind in SERVER_PORTS:
                conn.execute("UPDATE mcp_servers SET url=%s WHERE kind=%s", (mcp_endpoint(kind), kind))
        print("Configured MCP endpoints synchronized.")
