from conftest import account


def test_health_and_auth_required(client):
    assert client.get("/health/live").json()["status"] == "ok"
    assert client.get("/health/ready").json()["status"] == "ready"
    assert client.get("/api/v1/investigations").status_code == 401


def test_registration_login_and_cookie_rotation(client):
    data, headers = account(client)
    assert data["user"]["role"] == "owner"
    assert "password" not in str(data)
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["id"] == data["user"]["id"]
    first = client.cookies.get("cortexops_refresh")
    refreshed = client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    second = client.cookies.get("cortexops_refresh")
    assert second != first
    replay = client.post("/api/v1/auth/refresh", headers={"Cookie": f"cortexops_refresh={first}"})
    assert replay.status_code == 401
    invalidated = client.post("/api/v1/auth/refresh", headers={"Cookie": f"cortexops_refresh={second}"})
    assert invalidated.status_code == 401


def test_investigation_workspace_isolation_and_audit(client):
    a, headers_a = account(client)
    b, headers_b = account(client)
    created = client.post("/api/v1/investigations", headers=headers_a, json={"title": "Regression analysis", "question": "Why did model accuracy decrease after deployment?"})
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["status"] == "draft"
    assert client.get(f"/api/v1/investigations/{item['id']}", headers=headers_b).status_code == 404
    assert client.get("/api/v1/investigations", headers=headers_b).json() == []
    dashboard = client.get("/api/v1/dashboard", headers=headers_a)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["total"] == 1
    assert any(x["action"] == "investigation.create" for x in client.get("/api/v1/audit", headers=headers_a).json())


def test_validation_does_not_leak_passwords(client):
    response = client.post("/api/v1/auth/register", json={"email": "wrong", "password": "private-short", "name": "x"})
    assert response.status_code == 422
    assert "private-short" not in response.text
    assert client.post("/api/v1/auth/login", json={"email": "unknown@example.test", "password": "secret"}).status_code == 401


def test_viewer_cannot_create_or_change_model(client):
    owner, owner_headers = account(client)
    member, member_headers = account(client)
    add = client.post("/api/v1/members", headers=owner_headers, json={"email": member["user"]["email"], "role": "viewer"})
    assert add.status_code == 201, add.text
    from app.core.security import issue_token, Principal
    viewer_token = issue_token(Principal(member["user"]["id"], owner["user"]["workspace_id"], "viewer"))
    headers = {"Authorization": f"Bearer {viewer_token}"}
    assert client.get("/api/v1/investigations", headers=headers).status_code == 200
    assert client.post("/api/v1/investigations", headers=headers, json={"title": "Unauthorized request", "question": "This action must require analyst permission."}).status_code == 403
    assert client.get("/api/v1/settings/model", headers=headers).status_code == 403
    assert client.get("/api/v1/audit", headers=headers).status_code == 403


def test_refresh_origin_and_logout(client):
    _, headers = account(client)
    assert client.post("/api/v1/auth/refresh", headers={"Origin": "https://untrusted.invalid"}).status_code == 403
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.post("/api/v1/auth/refresh").status_code == 401
