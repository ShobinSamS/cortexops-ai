"""Record direct dependency metadata from official package registries."""
import concurrent.futures
import json
from pathlib import Path
import tomllib
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
data = tomllib.loads((ROOT / "backend/pyproject.toml").read_text(encoding="utf-8"))
import re
python_names = [re.split(r"[\[<>=!~; ]", s)[0] for s in data["project"]["dependencies"] + data["dependency-groups"]["dev"]]
frontend = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
npm_names = list(frontend["dependencies"]) + list(frontend["devDependencies"])

def fetch(item):
    ecosystem, name = item
    url = f"https://pypi.org/pypi/{name}/json" if ecosystem == "python" else f"https://registry.npmjs.org/{name}/latest"
    with urllib.request.urlopen(url, timeout=60) as response:
        metadata = json.load(response)
    metadata = metadata["info"] if ecosystem == "python" else metadata
    license_value = metadata.get("license_expression") or metadata.get("license")
    if not license_value:
        license_value = [v for v in metadata.get("classifiers", []) if v.startswith("License ::")]
    return {"ecosystem": ecosystem, "name": name, "latest_version": metadata["version"], "license": license_value, "requires": metadata.get("requires_python") or metadata.get("engines"), "source": url}

if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(fetch, [("python", n) for n in python_names] + [("npm", n) for n in npm_names]))
    output = ROOT / "setup/registry-metadata.json"
    output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    for entry in results:
        license_value = str(entry["license"])
        print(entry["ecosystem"], entry["name"], entry["latest_version"], license_value[:180], entry["requires"])
