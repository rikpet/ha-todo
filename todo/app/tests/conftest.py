import pytest
from fastapi.testclient import TestClient

from todo_app import db
from todo_app.main import create_app


@pytest.fixture
def conn():
    connection = db.connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def app(conn):
    application = create_app()
    application.state.db = conn
    return application


@pytest.fixture
def client_with_token(app, monkeypatch):
    """LAN-style client: not ingress, valid bearer token configured."""
    monkeypatch.setenv("TODO_API_TOKEN", "secret-token")
    return TestClient(app, headers={"Authorization": "Bearer secret-token"})


@pytest.fixture
def ingress_client(app, monkeypatch):
    """Ingress-style client: source host matches HA's ingress proxy."""
    from todo_app import auth

    monkeypatch.setattr(auth, "HA_INGRESS_IP", "testclient")
    monkeypatch.delenv("TODO_API_TOKEN", raising=False)
    return TestClient(app)
