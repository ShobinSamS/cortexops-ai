"""Create local credentials without printing them or replacing existing values."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    print("Existing .env preserved.")
else:
    content = (root / ".env.example").read_text(encoding="utf-8")
    content = content.replace("POSTGRES_PASSWORD=\n", f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n")
    content = content.replace("NEO4J_PASSWORD=\n", f"NEO4J_PASSWORD={secrets.token_urlsafe(32)}\n")
    content = content.replace("EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2", f"EMBEDDING_MODEL={root.as_posix()}/.cache/models/embedding")
    content = content.replace("RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L6-v2", f"RERANKER_MODEL={root.as_posix()}/.cache/models/reranker")
    target.write_text(content, encoding="utf-8")
    print("Created ignored local .env with generated database credentials.")
