"""Exercise actual dependency APIs without external services or model downloads."""
import asyncio
import importlib
from importlib.metadata import version
import json
from typing import TypedDict

def verify():
    imports = ["fastapi", "pydantic", "sqlalchemy", "alembic", "psycopg", "redis", "celery", "langgraph", "langchain", "langchain_ollama", "mcp.server.fastmcp", "sentence_transformers", "qdrant_client", "fastembed", "neo4j", "pypdf", "docx", "jwt", "pwdlib", "opentelemetry.sdk", "prometheus_client", "pytest"]
    for name in imports:
        importlib.import_module(name)
        print(f"PASS import {name}", flush=True)
    import torch
    assert torch.version.cuda is None, "Expected CPU-only PyTorch"
    assert torch.tensor([1., 2.]).sum().item() == 3
    print(f"PASS CPU tensor operation: torch {torch.__version__}", flush=True)

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from pydantic import BaseModel
    app = FastAPI()
    class Output(BaseModel):
        status: str
    @app.get("/health", response_model=Output)
    def health():
        return Output(status="ok")
    async def check_api():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
    asyncio.run(check_api())
    print("PASS FastAPI/Pydantic/HTTPX request", flush=True)

    from langgraph.graph import StateGraph, START, END
    class State(TypedDict):
        value: int
    graph = StateGraph(State)
    graph.add_node("increment", lambda state: {"value": state["value"] + 1})
    graph.add_edge(START, "increment")
    graph.add_edge("increment", END)
    assert graph.compile().invoke({"value": 1})["value"] == 2
    print("PASS LangGraph execution", flush=True)

    from mcp.server.fastmcp import FastMCP
    server = FastMCP("environment-check")
    @server.tool()
    def add(a: int, b: int) -> int:
        return a + b
    assert asyncio.run(server.list_tools())[0].name == "add"
    print("PASS official MCP SDK tool registration", flush=True)

    from qdrant_client import QdrantClient, models
    client = QdrantClient(":memory:")
    client.create_collection("check", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE))
    client.upsert("check", points=[models.PointStruct(id=1, vector=[1., 0.], payload={"source": "setup"})])
    assert client.query_points("check", query=[1., 0.], limit=1).points[0].id == 1
    client.close()
    print("PASS Qdrant local vector indexing/query", flush=True)

    from pwdlib import PasswordHash
    hasher = PasswordHash.recommended()
    hashed = hasher.hash("local-environment-check")
    assert hasher.verify("local-environment-check", hashed)
    print("PASS Argon2 hashing", flush=True)
    print(json.dumps({name: version(name) for name in ["fastapi", "pydantic", "sqlalchemy", "langgraph", "mcp", "sentence-transformers", "torch"]}, indent=2))

if __name__ == "__main__":
    verify()
