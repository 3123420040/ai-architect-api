from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["PUBLIC_BASE_URL"] = "http://localhost:3000"
os.environ["GPU_SERVICE_URL"] = "http://127.0.0.1:9"

from fastapi.testclient import TestClient
import pytest

from app.db import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def session_payload() -> dict:
    return {
        "email": "architect@test.com",
        "password": "supersecret123",
        "full_name": "Architect One",
        "organization_name": "Blackbird Studio",
    }


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
