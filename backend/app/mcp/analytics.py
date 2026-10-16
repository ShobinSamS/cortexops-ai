import math
import psycopg
from psycopg.rows import dict_row
from app.core.config import get_settings


async def query(sql: str, parameters: tuple):
    url = get_settings().analytics_database_url
    s = get_settings()
    if s.mcp_container_network and s.analytics_password:
        from urllib.parse import quote_plus
        url = f"postgresql://cortexops_analytics:{quote_plus(s.analytics_password)}@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}"
    if not url:
        raise ValueError("Read-only analytics connection is not configured; run python -m app.cli setup-analytics")
    async with await psycopg.AsyncConnection.connect(url, row_factory=dict_row, connect_timeout=5) as conn:
        await conn.execute("SET LOCAL statement_timeout = '10s'")
        cursor = await conn.execute(sql, parameters)
        return await cursor.fetchall()


async def metrics(workspace_id, version=None):
    return await query("""SELECT version, count(*)::int AS samples, sum(correct::int)::int AS correct,
        avg(correct::int)::float AS accuracy, avg(confidence)::float AS confidence,
        avg(latency_ms)::float AS latency_ms FROM analytics_model_observations
        WHERE workspace_id=%s AND (%s::text IS NULL OR version=%s) GROUP BY version ORDER BY version""", (workspace_id, version, version))


async def comparison(workspace_id, baseline, candidate):
    rows = await query("""SELECT version, category, count(*)::int AS samples,
        sum(correct::int)::int AS correct, avg(correct::int)::float AS accuracy
        FROM analytics_model_observations WHERE workspace_id=%s AND version IN (%s,%s)
        GROUP BY version,category ORDER BY version,category""", (workspace_id, baseline, candidate))
    result = []
    for category in sorted({row["category"] for row in rows}):
        old = next((r for r in rows if r["version"] == baseline and r["category"] == category), None)
        new = next((r for r in rows if r["version"] == candidate and r["category"] == category), None)
        if old and new:
            delta = new["accuracy"] - old["accuracy"]
            se = math.sqrt(old["accuracy"] * (1 - old["accuracy"]) / old["samples"] + new["accuracy"] * (1 - new["accuracy"]) / new["samples"])
            result.append({"category": category, "baseline": old, "candidate": new, "change_percentage_points": round(delta * 100, 3),
                           "approximate_95_percent_interval_pp": [round((delta - 1.96 * se) * 100, 3), round((delta + 1.96 * se) * 100, 3)]})
    return {"baseline": baseline, "candidate": candidate, "categories": result,
            "limitation": "Normal-approximation intervals describe association, not causation; small samples and dependent observations require additional analysis."}


async def failures(workspace_id, version):
    return await query("""SELECT category, count(*)::int AS samples,
        count(*) FILTER (WHERE NOT correct)::int AS failures FROM analytics_model_observations
        WHERE workspace_id=%s AND version=%s GROUP BY category ORDER BY failures DESC""", (workspace_id, version))


async def deployments(workspace_id):
    rows = await query("SELECT id,version,service,commit_sha,deployed_at,configuration FROM analytics_deployments WHERE workspace_id=%s ORDER BY deployed_at DESC LIMIT 30", (workspace_id,))
    for row in rows:
        row["deployed_at"] = row["deployed_at"].isoformat()
    return rows
