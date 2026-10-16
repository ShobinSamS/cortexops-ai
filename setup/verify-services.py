"""Verify real local service connections without persisting application data."""
import asyncio
import argparse
from pathlib import Path
import httpx
from dotenv import dotenv_values
import psycopg
from redis import Redis
from qdrant_client import QdrantClient

async def main(skip_inference=False):
    root = Path(__file__).resolve().parents[1]
    env = dotenv_values(root / ".env")
    with psycopg.connect(host="127.0.0.1", port=5432, user="cortexops", password=env["POSTGRES_PASSWORD"], dbname="cortexops", connect_timeout=10) as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)
    print("PASS PostgreSQL authenticated SELECT", flush=True)
    with Redis(host="127.0.0.1", port=6379, socket_connect_timeout=10) as redis:
        assert redis.ping()
    print("PASS Redis PING", flush=True)
    qdrant = QdrantClient(url="http://127.0.0.1:6333", timeout=10)
    try:
        qdrant.get_collections()
    finally:
        qdrant.close()
    print("PASS Qdrant server API", flush=True)
    if skip_inference:
        return
    async with httpx.AsyncClient(timeout=240) as client:
        response = await client.post("http://127.0.0.1:11434/api/chat", json={
            "model": env["OLLAMA_MODEL"], "stream": False,
            "messages": [{"role": "user", "content": "Reply with the word READY. /no_think"}],
            "think": False, "keep_alive": 0,
            "options": {"num_ctx": 2048, "num_predict": 16, "temperature": 0, "num_thread": 4}
        })
        response.raise_for_status()
        data = response.json()
        assert data.get("done") and data["message"]["content"].strip(), "No completed inference"
    print(f"PASS real Ollama inference: {env['OLLAMA_MODEL']}", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-inference", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.skip_inference))
