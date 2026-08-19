"""Centralized, environment-driven configuration."""
import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# Search order: backend/.env -> project root .env -> standard dotenv search
backend_dir = Path(__file__).resolve().parent.parent.parent
env_backend = backend_dir / ".env"
env_root = backend_dir.parent / ".env"

if env_backend.exists():
    load_dotenv(dotenv_path=env_backend)
elif env_root.exists():
    load_dotenv(dotenv_path=env_root)
else:
    load_dotenv(find_dotenv())




def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes")


class Config:
    ENV = os.getenv("FLASK_ENV", "production")
    DEBUG = _bool("FLASK_DEBUG") and ENV == "development"
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    # Auth
    JWT_SECRET = os.getenv("JWT_SECRET", "dev-jwt-change-me")
    JWT_ACCESS_MINUTES = int(os.getenv("JWT_ACCESS_MINUTES", "60"))
    JWT_REFRESH_DAYS = int(os.getenv("JWT_REFRESH_DAYS", "7"))

    # MySQL
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "tdd_intelligence")
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_POOL_SIZE = int(os.getenv("MYSQL_POOL_SIZE", "5"))

    # Redis / Celery
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

    # CORS
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

    # LLM (Gemini)
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")  # mock | gemini
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    # RAG / Vector store & storage
    VECTOR_STORE = os.getenv("VECTOR_STORE", "mock")  # mock | chromadb
    CHROMA_PATH = os.getenv("CHROMA_PATH", "./.chroma")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    UPLOAD_PATH = os.getenv("UPLOAD_PATH", "data/uploads")

    # Tools
    API_RUNNER = os.getenv("API_RUNNER", "mock")       # mock | newman | bruno
    CODE_ANALYZER = os.getenv("CODE_ANALYZER", "mock")  # mock | sonarqube | checkstyle
    ALM_PROVIDER = os.getenv("ALM_PROVIDER", "mock")    # mock | azure_devops | jira | rally

    # Observability
    OTEL_EXPORTER = os.getenv("OTEL_EXPORTER", "console")
    OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "tdd-intelligence-backend")

    # Workflow
    WORKFLOW_MAX_RETRIES = int(os.getenv("WORKFLOW_MAX_RETRIES", "3"))

    # Git workspace
    GIT_WORKSPACE_ROOT = os.getenv("GIT_WORKSPACE_ROOT", "./workspaces")

