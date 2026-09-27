import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHEALTH_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("MYHEALTH_DISABLE_SCHEDULER", "1")
    from app.main import app

    with TestClient(app) as c:
        yield c
