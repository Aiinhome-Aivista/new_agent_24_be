"""
ModelRouter: single abstraction between agents and the LLM provider.
Agents call generate_structured / generate_text / generate_code — never Gemini directly.
Per-task model config is read from the model_configurations table (falls back to defaults).
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


_router = None


def get_router():
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
