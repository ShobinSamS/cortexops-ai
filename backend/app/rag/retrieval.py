from collections import Counter
from functools import lru_cache
import hashlib
import math
import re
import threading

from qdrant_client import QdrantClient, models

from app.core.config import get_settings

COLLECTION = "cortexops_chunks_v1"
MODEL_LOCK = threading.Lock()


def sparse_vector(text):
    counts = Counter(re.findall(r"[a-z0-9][a-z0-9_.-]{1,40}", text.lower()))
    slots = {}
    for token, count in counts.items():
        index = int.from_bytes(hashlib.blake2s(token.encode(), digest_size=4).digest(), "little")
        slots[index] = slots.get(index, 0.0) + 1 + math.log(count)
    return models.SparseVector(indices=sorted(slots), values=[slots[i] for i in sorted(slots)])


@lru_cache
def embedder():
    from sentence_transformers import SentenceTransformer
    import torch
    torch.set_num_threads(2)
    return SentenceTransformer(get_settings().embedding_model, device="cpu")


@lru_cache
def reranker():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(get_settings().reranker_model, device="cpu")


def client():
    return QdrantClient(url=get_settings().qdrant_url, timeout=30)


def ensure_collection(q):
    if not q.collection_exists(COLLECTION):
        q.create_collection(COLLECTION, vectors_config={"dense": models.VectorParams(size=384, distance=models.Distance.COSINE)},
                            sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)})
        q.create_payload_index(COLLECTION, "workspace_id", models.PayloadSchemaType.KEYWORD)
        q.create_payload_index(COLLECTION, "document_id", models.PayloadSchemaType.KEYWORD)


def index_chunks(workspace_id, document_id, filename, chunks):
    q = client()
    try:
        ensure_collection(q)
        with MODEL_LOCK:
            vectors = embedder().encode([x["content"] for x in chunks], normalize_embeddings=True, batch_size=16).tolist()
        points = [models.PointStruct(id=chunk["id"], vector={"dense": vector, "sparse": sparse_vector(chunk["content"])},
                                    payload={"workspace_id": workspace_id, "document_id": document_id, "filename": filename,
                                             "page": chunk["page"], "section": chunk["section"]}) for chunk, vector in zip(chunks, vectors)]
        for start in range(0, len(points), 64):
            q.upsert(COLLECTION, points=points[start:start + 64], wait=True)
    finally:
        q.close()


def delete_vectors(workspace_id, document_id):
    q = client()
    try:
        if q.collection_exists(COLLECTION):
            q.delete(COLLECTION, points_selector=models.FilterSelector(filter=models.Filter(must=[
                models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id)),
                models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))])), wait=True)
    finally:
        q.close()


def hybrid_candidates(workspace_id, query, limit=6, document_ids=None):
    q = client()
    try:
        if not q.collection_exists(COLLECTION):
            return []
        conditions = [models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id))]
        if document_ids:
            conditions.append(models.FieldCondition(key="document_id", match=models.MatchAny(any=document_ids)))
        filters = models.Filter(must=conditions)
        with MODEL_LOCK:
            vector = embedder().encode(query, normalize_embeddings=True).tolist()
        result = q.query_points(COLLECTION, prefetch=[models.Prefetch(query=vector, using="dense", filter=filters, limit=max(20, limit * 3)),
                                                     models.Prefetch(query=sparse_vector(query), using="sparse", filter=filters, limit=max(20, limit * 3))],
                                query=models.FusionQuery(fusion=models.Fusion.RRF), query_filter=filters, limit=max(12, limit * 2))
        return [{"id": str(point.id), "score": point.score, "payload": point.payload} for point in result.points]
    finally:
        q.close()


def rerank(query, candidates, limit):
    if not candidates:
        return []
    with MODEL_LOCK:
        scores = reranker().predict([(query, x["content"]) for x in candidates]).tolist()
    return [dict(item, score=float(score)) for item, score in sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)[:limit]]
