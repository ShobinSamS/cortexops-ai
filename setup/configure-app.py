"""Add application secrets to an existing .env without printing or replacing them."""
from pathlib import Path
import secrets
import re

root = Path(__file__).resolve().parents[1]
path = root / ".env"
if not path.exists():
    raise SystemExit("Run python setup/init-environment.py first")
content = path.read_text(encoding="utf-8")
keys = {line.split("=", 1)[0]: line.split("=", 1)[1].strip() for line in content.splitlines() if "=" in line and not line.startswith("#")}
for key, value in {"JWT_SECRET": secrets.token_urlsafe(48), "ANALYTICS_PASSWORD": secrets.token_urlsafe(32), "GRAFANA_PASSWORD": secrets.token_urlsafe(24), "ENABLE_DEMO": "true", "COOKIE_SECURE": "false"}.items():
    if key not in keys:
        content += f"\n{key}={value}\n"
    elif not keys[key]:
        content = re.sub(rf"^{key}=\s*$", f"{key}={value}", content, flags=re.MULTILINE)
path.write_text(content, encoding="utf-8")
print("Application configuration ready; existing secrets preserved.")
