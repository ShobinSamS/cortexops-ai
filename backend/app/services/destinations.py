import json
from app.core.config import get_settings
from app.core.security import hash_token


def write_target(workspace_id, server, tool):
    s = get_settings()
    if server == "github" and tool == "create_issue" and s.github_token and s.github_repository and s.github_workspace_id == workspace_id:
        return {"mode": "live", "provider": "github", "repository": s.github_repository, "workspace_id": workspace_id}
    return {"mode": "local", "provider": "incident_store", "workspace_id": workspace_id}


def authorization_hash(payload, target):
    return hash_token(json.dumps({"arguments": payload, "target": target}, sort_keys=True, separators=(",", ":")))
