"""Global tests for the Trixel Management Server app."""

from fastapi.testclient import TestClient

from trixelmanagementserver import app

client = TestClient(app)


def test_ping():
    """Test ping endpoint."""
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"ping": "pong"}


def test_version():
    """Test version endpoint."""
    response = client.get("/version")
    assert response.status_code == 200
    assert "version" in response.json()
