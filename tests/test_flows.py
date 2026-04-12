from __future__ import annotations

def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register(client, payload):
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def create_project(client, token: str):
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "Nha pho Tan Binh",
            "client_name": "Anh Minh",
            "client_phone": "0901234567",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "api"


def test_auth_register_login_refresh(client, session_payload):
    registered = register(client, session_payload)
    assert registered["user"]["role"] == "architect"

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": session_payload["email"], "password": session_payload["password"]},
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]
    assert access_token

    refresh_response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_response.json()["refresh_token"]},
    )
    assert refresh_response.status_code == 200
    assert refresh_response.json()["access_token"]


def test_project_brief_chat_flow(client, session_payload):
    session = register(client, session_payload)
    token = session["access_token"]
    project = create_project(client, token)

    list_response = client.get("/api/v1/projects", headers=auth_headers(token))
    assert list_response.status_code == 200
    assert list_response.json()["pagination"]["total"] == 1

    brief_response = client.put(
        f"/api/v1/projects/{project['id']}/brief",
        json={"brief_json": {"style": "modern"}, "status": "confirmed"},
        headers=auth_headers(token),
    )
    assert brief_response.status_code == 200
    assert brief_response.json()["brief_json"]["style"] == "modern"

    chat_response = client.post(
        f"/api/v1/projects/{project['id']}/chat",
        json={"message": "Toi muon nha 5x20m, 4 tang, co gara, phong cach toi gian"},
        headers=auth_headers(token),
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["brief_json"]["lot"]["width_m"] == 5
    assert payload["brief_json"]["floors"] == 4
    assert "source" in payload
    assert isinstance(payload["follow_up_topics"], list)
    assert payload["clarification_state"]["total_sections"] >= 6
    assert "Thông tin khu đất" in (
        payload["clarification_state"]["blocking_missing"]
        + payload["clarification_state"]["advisory_missing"]
        + [section["label"] for section in payload["clarification_state"]["sections"]]
    )

    history_response = client.get(
        f"/api/v1/projects/{project['id']}/chat/history",
        headers=auth_headers(token),
    )
    assert history_response.status_code == 200
    assert len(history_response.json()["messages"]) == 2


def test_chat_websocket_stream_persists_turn(client, session_payload):
    session = register(client, session_payload)
    token = session["access_token"]
    project = create_project(client, token)

    with client.websocket_connect(f"/api/v1/projects/{project['id']}/chat/stream?token={token}") as websocket:
        ready = websocket.receive_json()
        assert ready["event"] == "chat:ready"

        websocket.send_json(
            {
                "message": "Toi muon nha 6x18m, 3 tang, phong cach modern va co gara.",
            }
        )

        streamed_chunks: list[str] = []
        done_payload = None
        for _ in range(20):
            event = websocket.receive_json()
            if event["event"] == "chat:chunk":
                streamed_chunks.append(event["content"])
                continue
            if event["event"] == "chat:done":
                done_payload = event
                break

    assert streamed_chunks
    assert done_payload is not None
    assert done_payload["brief_json"]["lot"]["width_m"] == 6
    assert done_payload["brief_json"]["floors"] == 3
    assert done_payload["clarification_state"]["total_sections"] >= 6

    history_response = client.get(
        f"/api/v1/projects/{project['id']}/chat/history",
        headers=auth_headers(token),
    )
    assert history_response.status_code == 200
    assert len(history_response.json()["messages"]) == 2


def test_generation_review_share_revision_export_and_3d(client, session_payload):
    session = register(client, session_payload)
    token = session["access_token"]
    project = create_project(client, token)
    project_id = project["id"]

    client.put(
        f"/api/v1/projects/{project_id}/brief",
        json={
            "brief_json": {
                "lot": {"width_m": 5, "depth_m": 20, "orientation": "south"},
                "floors": 4,
                "style": "modern_minimalist",
            },
            "status": "confirmed",
        },
        headers=auth_headers(token),
    )

    generation = client.post(
        f"/api/v1/projects/{project_id}/generate",
        json={"num_options": 3},
        headers=auth_headers(token),
    )
    assert generation.status_code == 201, generation.text
    versions = generation.json()["versions"]
    assert len(versions) == 3

    generated_project = client.get(
        f"/api/v1/projects/{project_id}",
        headers=auth_headers(token),
    )
    assert generated_project.status_code == 200
    assert generated_project.json()["versions"][0]["generation_metadata"]["geometry_schema"] == "ai-architect-geometry-v2"

    selected_version_id = versions[0]["id"]
    select_response = client.post(
        f"/api/v1/versions/{selected_version_id}/select",
        json={"comment": "Best option"},
        headers=auth_headers(token),
    )
    assert select_response.status_code == 200
    assert select_response.json()["status"] == "under_review"

    annotation_response = client.post(
        f"/api/v1/versions/{selected_version_id}/annotations",
        json={"x": 0.5, "y": 0.3, "comment": "Bo sung cua so"},
        headers=auth_headers(token),
    )
    assert annotation_response.status_code == 201

    approve_response = client.post(
        f"/api/v1/reviews/{selected_version_id}/approve",
        json={"comment": "Ready to lock"},
        headers=auth_headers(token),
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "locked"

    share_response = client.post(
        f"/api/v1/projects/{project_id}/share-links",
        headers=auth_headers(token),
    )
    assert share_response.status_code == 201
    share_token = share_response.json()["token"]
    assert share_response.json()["url"].startswith("http://localhost:3000/share/")

    public_response = client.get(f"/api/v1/share/{share_token}")
    assert public_response.status_code == 200

    feedback_response = client.post(
        f"/api/v1/share/{share_token}/feedback",
        json={"content": "Can rong hon khu bep"},
    )
    assert feedback_response.status_code == 201
    assert feedback_response.json()["status"] == "submitted"

    revision_response = client.post(
        f"/api/v1/reviews/{selected_version_id}/revise",
        json={"comment": "Can rong hon khu bep"},
        headers=auth_headers(token),
    )
    assert revision_response.status_code == 200
    assert revision_response.json()["parent_version_id"] == selected_version_id

    export_response = client.post(
        f"/api/v1/versions/{selected_version_id}/exports",
        headers=auth_headers(token),
    )
    assert export_response.status_code == 200, export_response.text
    assert export_response.json()["export_urls"]["pdf"].startswith("/media/projects/")
    assert export_response.json()["export_urls"]["svg"].startswith("/media/projects/")
    assert export_response.json()["export_urls"]["dxf"].startswith("/media/projects/")
    assert export_response.json()["export_urls"]["ifc"].startswith("/media/projects/")
    assert export_response.json()["export_urls"]["manifest"].startswith("/media/projects/")
    assert export_response.json()["export_urls"]["door_csv"].endswith(".csv")
    assert export_response.json()["export_urls"]["window_csv"].endswith(".csv")
    assert export_response.json()["export_urls"]["room_csv"].endswith(".csv")
    package_id = export_response.json()["package"]["id"]
    assert export_response.json()["package"]["status"] == "review"
    assert export_response.json()["package"]["quality_status"] == "pass"

    packages_response = client.get(
        f"/api/v1/projects/{project_id}/packages",
        headers=auth_headers(token),
    )
    assert packages_response.status_code == 200
    assert packages_response.json()["data"][0]["id"] == package_id

    issue_response = client.post(
        f"/api/v1/packages/{package_id}/issue",
        json={"note": "Phase 3 issue gate approved"},
        headers=auth_headers(token),
    )
    assert issue_response.status_code == 200, issue_response.text
    assert issue_response.json()["package"]["status"] == "issued"
    assert issue_response.json()["version_status"] == "handoff_ready"

    derive_response = client.post(
        f"/api/v1/versions/{selected_version_id}/derive-3d",
        headers=auth_headers(token),
    )
    assert derive_response.status_code == 200
    assert derive_response.json()["model_url"].startswith("/media/projects/")
    assert len(derive_response.json()["render_urls"]) >= 1

    handoff_response = client.post(
        f"/api/v1/versions/{selected_version_id}/handoff",
        headers=auth_headers(token),
    )
    assert handoff_response.status_code == 200, handoff_response.text
    assert handoff_response.json()["status"] == "handoff_ready"
    assert any(item["type"] == "gltf" for item in handoff_response.json()["files_manifest"])
    assert any(item["type"] == "dxf" for item in handoff_response.json()["files_manifest"])
    assert any(item["type"] == "ifc" for item in handoff_response.json()["files_manifest"])
    assert any(item["type"] == "csv" for item in handoff_response.json()["files_manifest"])

    bundles_response = client.get(
        f"/api/v1/projects/{project_id}/handoffs",
        headers=auth_headers(token),
    )
    assert bundles_response.status_code == 200
    assert bundles_response.json()["data"][0]["is_current"] is True

    notifications = client.get("/api/v1/notifications", headers=auth_headers(token))
    assert notifications.status_code == 200
    assert len(notifications.json()["data"]) >= 3


def test_project_current_version_ignores_superseded_versions(client, session_payload):
    session = register(client, session_payload)
    token = session["access_token"]
    project = create_project(client, token)
    project_id = project["id"]

    client.put(
        f"/api/v1/projects/{project_id}/brief",
        json={
            "brief_json": {
                "lot": {"width_m": 5, "depth_m": 20, "orientation": "south"},
                "floors": 4,
                "style": "modern_minimalist",
            },
            "status": "confirmed",
        },
        headers=auth_headers(token),
    )

    generation = client.post(
        f"/api/v1/projects/{project_id}/generate",
        json={"num_options": 3},
        headers=auth_headers(token),
    )
    assert generation.status_code == 201, generation.text
    versions = generation.json()["versions"]
    selected_version_id = versions[0]["id"]

    selected_project = client.get(
        f"/api/v1/projects/{project_id}",
        headers=auth_headers(token),
    )
    assert selected_project.status_code == 200
    assert selected_project.json()["current_version_status"] == "generated"
    assert selected_project.json()["current_version_number"] == 3

    select_response = client.post(
        f"/api/v1/versions/{selected_version_id}/select",
        json={"comment": "Best option"},
        headers=auth_headers(token),
    )
    assert select_response.status_code == 200

    reviewing_project = client.get(
        f"/api/v1/projects/{project_id}",
        headers=auth_headers(token),
    )
    assert reviewing_project.status_code == 200
    assert reviewing_project.json()["current_version_status"] == "under_review"
    assert reviewing_project.json()["current_version_number"] == 1

    approve_response = client.post(
        f"/api/v1/reviews/{selected_version_id}/approve",
        json={"comment": "Ready to lock"},
        headers=auth_headers(token),
    )
    assert approve_response.status_code == 200

    locked_project = client.get(
        f"/api/v1/projects/{project_id}",
        headers=auth_headers(token),
    )
    assert locked_project.status_code == 200
    assert locked_project.json()["current_version_status"] == "locked"
    assert locked_project.json()["current_version_number"] == 1

    revision_response = client.post(
        f"/api/v1/reviews/{selected_version_id}/revise",
        json={"comment": "Them gieng troi"},
        headers=auth_headers(token),
    )
    assert revision_response.status_code == 200

    revision_project = client.get(
        f"/api/v1/projects/{project_id}",
        headers=auth_headers(token),
    )
    assert revision_project.status_code == 200
    assert revision_project.json()["current_version_status"] == "generated"
    assert revision_project.json()["current_version_number"] == 4


def test_generation_websocket_stream_returns_progress(client, session_payload):
    session = register(client, session_payload)
    token = session["access_token"]
    project = create_project(client, token)
    project_id = project["id"]

    client.put(
        f"/api/v1/projects/{project_id}/brief",
        json={
            "brief_json": {
                "lot": {"width_m": 6, "depth_m": 18, "orientation": "east"},
                "floors": 3,
                "style": "modern_minimalist",
            },
            "status": "confirmed",
        },
        headers=auth_headers(token),
    )

    with client.websocket_connect(f"/api/v1/projects/{project_id}/generate/stream?token={token}") as websocket:
        ready = websocket.receive_json()
        assert ready["event"] == "generation:ready"

        websocket.send_json({"num_options": 2})

        progress_events: list[dict] = []
        done_payload = None
        for _ in range(20):
            event = websocket.receive_json()
            if event["event"] == "generation:progress":
                progress_events.append(event)
                continue
            if event["event"] == "generation:done":
                done_payload = event
                break

    assert len(progress_events) >= 3
    assert done_payload is not None
    assert done_payload["source"] in {"remote_gpu", "fallback"}
    assert len(done_payload["versions"]) == 2
