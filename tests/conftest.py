import pytest
from app.config import Config
from app import create_app


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    """Ensure all tests run safely in deterministic mock mode."""
    monkeypatch.setattr(Config, "LLM_PROVIDER", "mock")
    monkeypatch.setattr(Config, "VECTOR_STORE", "mock")
    monkeypatch.setattr(Config, "API_RUNNER", "mock")
    monkeypatch.setattr(Config, "CODE_ANALYZER", "mock")
    monkeypatch.setattr(Config, "ALM_PROVIDER", "mock")


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()

