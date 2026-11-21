from fastapi.testclient import TestClient

from pebbo import __version__
from pebbo.app import create_app


def test_health_reports_status_and_version() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_api_docs_that_load_cdn_assets_are_disabled() -> None:
    client = TestClient(create_app())

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
