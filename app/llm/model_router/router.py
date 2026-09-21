"""
ModelRouter: single abstraction between agents and the LLM provider.
Agents call generate_structured / generate_text / generate_code — never Gemini directly.
Per-task model config is read from the model_configurations table (falls back to defaults).

LangChain Integration:
    When langchain-google-genai is installed, get_langchain_llm() returns a
    ChatGoogleGenerativeAI instance for use with LangGraph nodes that need
    LangChain's structured output / tool-calling abstractions.
    All existing generate_* methods remain unchanged.
"""
from app.config import Config
from app.llm.client.gemini_client import build_client
from app.extensions.db import query

_DEFAULT_MODEL = getattr(Config, "GEMINI_MODEL", "gemini-3.1-flash-lite") or "gemini-3.1-flash-lite"

_DEFAULTS = {
    "requirement_analysis": (_DEFAULT_MODEL, 0.2, 8192),
    "service_planning":     (_DEFAULT_MODEL, 0.2, 8192),
    "test_generation":      (_DEFAULT_MODEL, 0.3, 16384),
    "code_generation":      (_DEFAULT_MODEL, 0.2, 16384),
    "evidence_narrative":   (_DEFAULT_MODEL, 0.2, 4096),
    "explanation":          (_DEFAULT_MODEL, 0.3, 2048),
}

# ── LangChain integration (optional — imported lazily) ────────────────────────
_langchain_llm = None
_langchain_available: bool | None = None


def get_langchain_llm(temperature: float = 0.2, max_output_tokens: int = 8192):
    """
    Return a LangChain ChatGoogleGenerativeAI instance for use with LangGraph nodes
    that require LangChain's tool-calling or structured output interface.

    Returns None if langchain-google-genai is not installed or GEMINI_API_KEY is absent.
    Callers must handle None gracefully and fall back to the native GeminiClient.
    """
    global _langchain_llm, _langchain_available

    if _langchain_available is False:
        return None

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore[import-untyped]
        api_key = getattr(Config, "GEMINI_API_KEY", "").strip()
        model = _DEFAULT_MODEL

        if not api_key:
            _langchain_available = False
            print("[ModelRouter] LangChain: GEMINI_API_KEY not set — LangChain LLM unavailable.")
            return None

        if _langchain_llm is None:
            _langchain_llm = ChatGoogleGenerativeAI(
                model=model,
                google_api_key=api_key,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                convert_system_message_to_human=True,
            )
            _langchain_available = True
            print(f"[ModelRouter] LangChain ChatGoogleGenerativeAI initialized (model={model})")

        return _langchain_llm
    except ImportError:
        _langchain_available = False
        print("[ModelRouter] langchain-google-genai not installed. LangChain LLM unavailable.")
        return None
    except Exception as e:
        _langchain_available = False
        print(f"[ModelRouter] LangChain LLM init failed: {e}")
        return None


class ModelRouter:
    def __init__(self):
        self._client = build_client()

    def _config(self, task_type):
        env_model = getattr(Config, "GEMINI_MODEL", "").strip()
        try:
            row = query("SELECT model_name, temperature, max_tokens FROM model_configurations WHERE task_type=%s AND is_active=1",
                        (task_type,), fetchone=True)
            if row:
                model_name = env_model or row["model_name"]
                return model_name, float(row["temperature"]), int(row["max_tokens"])
        except Exception:
            pass
        return _DEFAULTS.get(task_type, (env_model or _DEFAULT_MODEL, 0.2, 2048))

    def generate_text(self, task_type, prompt, system=""):
        model, temp, max_tokens = self._config(task_type)
        return self._client.generate(model=model, system=system, prompt=prompt,
                                      temperature=temp, max_tokens=max_tokens, as_json=False)

    def generate_structured(self, task_type, prompt, system=""):
        model, temp, max_tokens = self._config(task_type)
        return self._client.generate(model=model, system=system, prompt=prompt,
                                      temperature=temp, max_tokens=max_tokens, as_json=True)

    def generate_code(self, task_type, prompt, system=""):
        model, temp, max_tokens = self._config(task_type)
        return self._client.generate(model=model, system=system, prompt=prompt,
                                      temperature=temp, max_tokens=max_tokens, as_json=False)

    def get_langchain_llm(self, temperature: float = 0.2, max_output_tokens: int = 8192):
        """Convenience accessor on the router instance."""
        return get_langchain_llm(temperature=temperature, max_output_tokens=max_output_tokens)


_router = None


def get_router():
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router

