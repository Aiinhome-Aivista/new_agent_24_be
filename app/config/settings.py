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
    MYSQL_POOL_SIZE = int(os.getenv("MYSQL_POOL_SIZE", "25"))

    # Redis / Celery
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

    # CORS
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

    # LLM Provider Configuration (Cloud Gemini vs Local Ollama)
    USE_GEMINI = _bool("USE_GEMINI", "true")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    # Local LLM (Ollama / Custom Endpoint)
    LLM_API_URL = os.getenv("LLM_API_URL", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "")
    LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "300"))
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "")

    # RAG / Vector store & storage
    VECTOR_STORE = os.getenv("VECTOR_STORE", "chromadb")  # mock | chromadb
    CHROMA_PATH = os.getenv("CHROMA_PATH", "data/chroma_db")
    UPLOAD_PATH = os.getenv("UPLOAD_PATH", "data/uploads")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

    # Storage & AWS S3
    DEPLOY = _bool("deploy", "false")
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME", "")
    AWS_S3_BASE_FOLDER = os.getenv("AWS_S3_BASE_FOLDER", "Agents_Doc")
    AWS_S3_AGENT_FOLDER = os.getenv("AWS_S3_AGENT_FOLDER", "Agent_24")

    # RAG Chunking & Retrieval Parameters
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
    DENSE_TOP_K = int(os.getenv("DENSE_TOP_K", "10"))
    SPARSE_TOP_K = int(os.getenv("SPARSE_TOP_K", "10"))
    FUSION_TOP_K = int(os.getenv("FUSION_TOP_K", "10"))
    RRF_K = int(os.getenv("RRF_K", "60"))
    RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "8"))
    ENABLE_RERANKER = _bool("ENABLE_RERANKER", "true")
    RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

    # Context Window & Episodic Memory
    MAX_EPISODIC_EVENTS = int(os.getenv("MAX_EPISODIC_EVENTS", "20"))
    CONTEXT_COMPACTION_ENABLED = _bool("CONTEXT_COMPACTION_ENABLED", "true")
    CONTEXT_MAX_CHARACTERS = int(os.getenv("CONTEXT_MAX_CHARACTERS", "20000"))

    # Tools
    API_RUNNER = os.getenv("API_RUNNER", "newman")       # mock | newman | bruno
    CODE_ANALYZER = os.getenv("CODE_ANALYZER", "sonarqube")  # mock | sonarqube | checkstyle
    ALM_PROVIDER = os.getenv("ALM_PROVIDER", "jira")    # mock | azure_devops | jira | rally

    # Observability
    OTEL_EXPORTER = os.getenv("OTEL_EXPORTER", "console")
    OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "tdd-intelligence-backend")

    # Workflow
    WORKFLOW_MAX_RETRIES = int(os.getenv("WORKFLOW_MAX_RETRIES", "3"))

    # Git workspace
    GIT_WORKSPACE_ROOT = os.getenv("GIT_WORKSPACE_ROOT", "./workspaces")

