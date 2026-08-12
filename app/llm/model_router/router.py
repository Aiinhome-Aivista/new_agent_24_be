"""
ModelRouter: single abstraction between agents and the LLM provider.
Agents call generate_structured / generate_text / generate_code — never Gemini directly.
Per-task model config is read from the model_configurations table (falls back to defaults).
"""
from app.llm.client.gemini_client import build_client
from app.extensions.db import query

_DEFAULTS = {
    "requirement_analysis": ("gemini-1.5-pro", 0.2, 2048),
    "service_planning":     ("gemini-1.5-pro", 0.2, 2048),
    "test_generation":      ("gemini-1.5-pro", 0.3, 4096),
    "code_generation":      ("gemini-1.5-pro", 0.2, 4096),
    "evidence_narrative":   ("gemini-1.5-flash", 0.2, 2048),
    "explanation":          ("gemini-1.5-flash", 0.3, 1024),
}


class ModelRouter:
    def __init__(self):
        self._client = build_client()

    def _config(self, task_type):
        try:
            row = query("SELECT model_name, temperature, max_tokens FROM model_configurations WHERE task_type=%s AND is_active=1",
                        (task_type,), fetchone=True)
            if row:
                return row["model_name"], float(row["temperature"]), int(row["max_tokens"])
        except Exception:
            pass
        return _DEFAULTS.get(task_type, ("gemini-1.5-flash", 0.2, 2048))

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
