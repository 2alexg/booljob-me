from fastapi.testclient import TestClient

from bool_api.config import Settings
from bool_api.worker import create_app as create_worker_app
from tests.conftest import headers


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_without_database(client: TestClient) -> None:
    response = client.get("/ready", headers=headers())
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "not_configured"}


def test_no_public_docs_outside_local(settings: Settings) -> None:
    from bool_api.main import create_app

    app = create_app(settings.model_copy(update={"environment": "staging"}))
    client = TestClient(app)
    assert client.get("/docs", headers=headers()).status_code == 404
    assert client.get("/openapi.json", headers=headers()).status_code == 404


def test_worker_health(settings: Settings) -> None:
    response = TestClient(create_worker_app(settings)).get("/health")
    assert response.status_code == 200
