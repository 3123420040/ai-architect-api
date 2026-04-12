from __future__ import annotations

import base64
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.db import SessionLocal
from app.models import Organization, User
from app.security import create_access_token, hash_password
from app.tasks.worker import ping_task


def _create_user(*, role: str, email: str) -> User:
    with SessionLocal() as db:
        organization = Organization(name=f"{role.title()} Org")
        db.add(organization)
        db.flush()
        user = User(
            organization_id=organization.id,
            email=email,
            password_hash=hash_password("supersecret123"),
            full_name=f"{role.title()} User",
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _token_for(user: User) -> str:
    return create_access_token(user.id, user.role)


def test_rbac_blocks_regular_user_from_project_creation(client):
    user = _create_user(role="user", email="user@test.com")
    token = _token_for(user)

    read_response = client.get(
        "/api/v1/organizations/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert read_response.status_code == 200
    assert read_response.json()["current_user_role"] == "user"

    write_response = client.post(
        "/api/v1/projects",
        json={"name": "Unauthorized project"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert write_response.status_code == 403


def test_rbac_allows_admin_route_only_for_admin(client):
    architect = _create_user(role="architect", email="architect-rbac@test.com")
    admin = _create_user(role="admin", email="admin@test.com")

    forbidden = client.get(
        "/api/v1/admin/audit-logs",
        headers={"Authorization": f"Bearer {_token_for(architect)}"},
    )
    assert forbidden.status_code == 403

    allowed = client.get(
        "/api/v1/admin/audit-logs",
        headers={"Authorization": f"Bearer {_token_for(admin)}"},
    )
    assert allowed.status_code == 200


def test_upload_presign_route_returns_contract(client, session_payload, monkeypatch):
    registered = client.post("/api/v1/auth/register", json=session_payload)
    assert registered.status_code == 201
    token = registered.json()["access_token"]

    monkeypatch.setattr(
        "app.api.v1.uploads.create_presigned_upload",
        lambda **_: {
            "object_key": "projects/demo-file.png",
            "upload_url": "http://minio.local/upload",
            "download_url": "http://minio.local/download",
            "expires_in": 900,
        },
    )

    response = client.post(
        "/api/v1/uploads/presign",
        json={
            "filename": "demo-file.png",
            "content_type": "image/png",
            "folder": "projects",
            "expires_in": 900,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    assert response.json()["object_key"] == "projects/demo-file.png"


def test_celery_ping_task_runs_synchronously():
    result = ping_task.apply(kwargs={"payload": {"hello": "world"}}).get()
    assert result["status"] == "completed"
    assert result["payload"]["hello"] == "world"


def test_alembic_upgrade_and_downgrade(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "alembic-test.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"

    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert upgrade.returncode == 0, upgrade.stderr

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "projects" in tables
    assert "design_versions" in tables

    downgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert downgrade.returncode == 0, downgrade.stderr


def test_generation_route_accepts_binary_gpu_payload(client, session_payload, monkeypatch):
    registered = client.post("/api/v1/auth/register", json=session_payload)
    assert registered.status_code == 201
    token = registered.json()["access_token"]

    project_response = client.post(
        "/api/v1/projects",
        json={"name": "Binary GPU Project"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    client.put(
        f"/api/v1/projects/{project_id}/brief",
        json={
            "brief_json": {
                "lot": {"width_m": 5, "depth_m": 20},
                "floors": 3,
                "style": "modern_minimalist",
            },
            "status": "confirmed",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    monkeypatch.setattr(
        "app.api.v1.generation.generate_floorplans",
        lambda *_args, **_kwargs: [
            {
                "label": "Option A",
                "description": "Raster option",
                "image_base64": base64.b64encode(b"fake-png").decode("utf-8"),
                "image_format": "png",
                "mime_type": "image/png",
                "pipeline": "raster-floorplan-v1",
                "seed": 1000,
                "duration_ms": 321,
                "generated_at": "2026-04-11T00:00:00Z",
            }
        ],
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/generate",
        json={"num_options": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["versions"][0]["thumbnail_url"].endswith(".svg")
