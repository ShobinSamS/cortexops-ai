"""Download and exercise the CPU embedding and cross-encoder development models."""
import os
from pathlib import Path
import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np

root = Path(__file__).resolve().parents[1]
os.environ["HF_HOME"] = str(root / ".cache/huggingface")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
# Use standard HTTPS downloads on this Windows development machine.
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["OMP_NUM_THREADS"] = "2"
from sentence_transformers import SentenceTransformer, CrossEncoder
import torch
torch.set_num_threads(2)

def download_weights(url, target):
    """Use bounded ranges because unbounded CDN responses stall on this network."""
    chunk_size = 1024 * 1024
    def fetch_range(start, end):
        request = urllib.request.Request(f"{url}?download=true&offset={start}", headers={"Range": f"bytes={start}-{end}"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    content_range = response.headers.get("Content-Range", "")
                    if response.status != 206 or not content_range.startswith(f"bytes {start}-"):
                        raise RuntimeError("Model CDN did not honor the requested byte range")
                    total = int(content_range.split("/")[1])
                    block = response.read(end - start + 1)
                    if len(block) != min(end + 1, total) - start:
                        raise RuntimeError("Incomplete model range")
                    return start, block, total
            except Exception:
                if attempt == 2:
                    raise
    _, first, total = fetch_range(0, chunk_size - 1)
    with target.open("wb") as output, ThreadPoolExecutor(max_workers=4) as pool:
        output.truncate(total)
        output.write(first)
        completed = len(first)
        futures = [pool.submit(fetch_range, start, min(start + chunk_size, total) - 1) for start in range(chunk_size, total, chunk_size)]
        next_report = 16 * chunk_size
        for future in as_completed(futures):
            start, block, _ = future.result()
            output.seek(start)
            output.write(block)
            completed += len(block)
            if completed >= next_report or completed == total:
                print(f"Model weights: {completed}/{total} bytes", flush=True)
                next_report += 16 * chunk_size

def download_snapshot(repo, directory):
    """Fetch pinned official model files over standard HTTPS."""
    manifest_path = directory / "download-manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["repo"] != repo:
            raise ValueError("Cached model manifest belongs to a different repository")
        for item in manifest["files"]:
            path = directory / item["file"]
            with path.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != item["sha256"]:
                    raise ValueError("Cached model checksum mismatch; move the cache aside and download a fresh pinned snapshot")
        print(f"Verified cached pinned snapshot {repo}@{manifest['revision']}", flush=True)
        return str(directory)
    with urllib.request.urlopen(f"https://huggingface.co/api/models/{repo}", timeout=60) as response:
        metadata = json.load(response)
    revision = metadata["sha"]
    allowed = {"config.json", "config_sentence_transformers.json", "sentence_bert_config.json", "modules.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "vocab.txt", "1_Pooling/config.json"}
    directory.mkdir(parents=True, exist_ok=True)
    files = []
    for item in metadata["siblings"]:
        name = item["rfilename"]
        if name not in allowed:
            continue
        destination = directory / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            temporary = destination.with_suffix(destination.suffix + ".part")
            url = f"https://huggingface.co/{repo}/resolve/{revision}/{name}"
            if name == "model.safetensors":
                download_weights(url, temporary)
            else:
                with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as target:
                    while block := response.read(1024 * 1024):
                        target.write(block)
            temporary.replace(destination)
        with destination.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        files.append({"file": name, "sha256": digest, "bytes": destination.stat().st_size})
        print(f"Downloaded/verified {repo}/{name}", flush=True)
    (directory / "download-manifest.json").write_text(json.dumps({"repo": repo, "revision": revision, "files": files}, indent=2), encoding="utf-8")
    return str(directory)

embedding_path = download_snapshot("sentence-transformers/all-MiniLM-L6-v2", root / ".cache/models/embedding")
embedder = SentenceTransformer(embedding_path, device="cpu", local_files_only=True)
vectors = embedder.encode(["Document verification deployment", "Model accuracy investigation"], normalize_embeddings=True)
assert vectors.shape == (2, 384) and np.isfinite(vectors).all()
print("PASS embedding model download and inference: 384-dimensional vectors", flush=True)
del embedder
reranker_path = download_snapshot("cross-encoder/ms-marco-MiniLM-L6-v2", root / ".cache/models/reranker")
reranker = CrossEncoder(reranker_path, device="cpu", local_files_only=True)
scores = reranker.predict([("Why did accuracy drop?", "Deployment changed document preprocessing."), ("Why did accuracy drop?", "The cafeteria menu changed.")])
assert len(scores) == 2 and np.isfinite(scores).all()
print("PASS cross-encoder model download and inference", flush=True)
