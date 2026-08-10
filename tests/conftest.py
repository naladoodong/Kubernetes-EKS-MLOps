import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://argmax:argmax-local-only@db:5432/argmax")

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_dataset_data():
    with SessionLocal() as session:
        session.execute(text("DELETE FROM audit_logs"))
        session.execute(text("DELETE FROM dataset_versions"))
        session.execute(text("DELETE FROM datasets"))
        session.execute(text("DELETE FROM users WHERE id <> '00000000-0000-4000-8000-000000000001'"))
        session.commit()
    yield


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def create_dataset(client):
    def create(name="dataset", description="description"):
        response = client.post("/api/v1/datasets", json={"name": name, "description": description})
        assert response.status_code == 201
        return response
    return create
