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
def client(app):
    return TestClient(app)
