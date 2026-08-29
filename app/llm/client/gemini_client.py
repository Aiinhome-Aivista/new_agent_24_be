"""
Centralized LLM client supporting both Cloud Gemini and Local LLM (Ollama).

- Mode 1: Cloud Google Gemini (when USE_GEMINI=true and GEMINI_API_KEY is provided)
- Mode 2: Local LLM / Ollama (when USE_GEMINI=false or GEMINI_API_KEY is empty, using LLM_API_URL)
- Mode 3: Deterministic MOCK adapter (for offline unit tests)
"""
import json
import time
import requests
from app.config import Config


class LLMResult:
    def __init__(self, text, model, latency_ms, token_usage, is_mock):
        self.text = text
        self.model = model
        self.latency_ms = latency_ms
        self.token_usage = token_usage
        self.is_mock = is_mock


def _clean_json_text(text: str) -> str:
    """Helper to strip markdown code fences if the model wrapped the JSON response."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


class MockGeminiClient:
    def generate(self, *, model, system, prompt, temperature, max_tokens, as_json=False):
        start = time.time()
        if as_json:
            text = json.dumps({"_mock": True, "note": "MOCK structured output — configure GEMINI_API_KEY or LLM_API_URL for real generation"})
        else:
            text = "[MOCK] Configure GEMINI_API_KEY or LLM_API_URL for real model output."
        return LLMResult(text, f"MOCK::{model}", int((time.time() - start) * 1000),
                         {"prompt_tokens": len(prompt.split()), "completion_tokens": 0}, True)


class LocalLLMClient:
    """Client for local Ollama / OpenAI-compatible LLM endpoints."""
    def __init__(self, api_url: str = None, default_model: str = None, timeout: int = None):
        self.api_url = (api_url or getattr(Config, "LLM_API_URL", "") or "").strip()
        self.default_model = (default_model or getattr(Config, "LLM_MODEL", "") or "").strip()
        self.timeout = int(timeout or getattr(Config, "LLM_TIMEOUT", 300) or 300)
        self._mock = MockGeminiClient()

    def generate(self, *, model, system, prompt, temperature, max_tokens, as_json=False):
        actual_model = (model or self.default_model or getattr(Config, "LLM_MODEL", "") or "").strip()
        start = time.time()
        try:
            target_url = self.api_url
            if not target_url.endswith("/generate") and not target_url.endswith("/completions"):
                target_url = f"{target_url.rstrip('/')}/api/generate"

            payload = {
                "model": actual_model,
                "prompt": f"{system}\n\n{prompt}" if system else prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }
            if as_json:
                payload["format"] = "json"

            resp = requests.post(target_url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()

            raw_text = data.get("response") or data.get("message", {}).get("content") or ""
            text = _clean_json_text(raw_text) if as_json else raw_text

            prompt_tokens = data.get("prompt_eval_count", len(prompt.split()))
            completion_tokens = data.get("eval_count", len(text.split()))

            return LLMResult(
                text=text,
                model=f"local::{actual_model}",
                latency_ms=int((time.time() - start) * 1000),
                token_usage={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
                is_mock=False
            )
        except Exception as e:
            print(f"[LocalLLMClient] Call to {self.api_url} failed ({e}) — falling back to deterministic mock adapter.")
            return self._mock.generate(model=actual_model, system=system, prompt=prompt,
                                       temperature=temperature, max_tokens=max_tokens, as_json=as_json)


try:
    # pyrefly: ignore [missing-import]
    from google import genai  # type: ignore[import-untyped, import-not-found]
    # pyrefly: ignore [missing-import]
    from google.genai import types  # type: ignore[import-untyped, import-not-found]
    HAS_GENAI = True
except (ImportError, ModuleNotFoundError, Exception):
    genai = None  # type: ignore
    types = None  # type: ignore
    HAS_GENAI = False


class GeminiClient:
    """Client for Google Cloud Gemini API."""
    def __init__(self, api_key: str = None):
        key = (api_key or getattr(Config, "GEMINI_API_KEY", "") or "").strip()
        if not HAS_GENAI or not genai:
            print("[GeminiClient] Google GenAI SDK (google-genai) not available — using Mock adapter.")
            self._client = None
            self._mock = MockGeminiClient()
            return

        try:
            self._client = genai.Client(api_key=key)
            self._mock = MockGeminiClient()
        except Exception as e:
            print(f"[GeminiClient] Failed to initialize Google GenAI SDK ({e}) — using Mock adapter.")
            self._client = None
            self._mock = MockGeminiClient()

    def generate(self, *, model, system, prompt, temperature, max_tokens, as_json=False):
        # Use exact model from argument or Config.GEMINI_MODEL from .env
        actual_model = (model or getattr(Config, "GEMINI_MODEL", "") or "").strip()
        if actual_model.startswith("models/"):
            actual_model = actual_model.replace("models/", "")

        if self._client is None:
            return self._mock.generate(model=actual_model, system=system, prompt=prompt,
                                       temperature=temperature, max_tokens=max_tokens, as_json=as_json)

        try:
            start = time.time()

            if types:
                config = types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    system_instruction=system.strip() if system else None,
                    response_mime_type="application/json" if as_json else None,
                )
            else:
                config = {
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                }
                if system:
                    config["system_instruction"] = system.strip()
                if as_json:
                    config["response_mime_type"] = "application/json"

            resp = self._client.models.generate_content(
                model=actual_model,
                contents=prompt,
                config=config,
            )

            raw_text = resp.text or ""
            text = _clean_json_text(raw_text) if as_json else raw_text

            usage = getattr(resp, "usage_metadata", None)
            token_usage = {
                "prompt_tokens": getattr(usage, "prompt_token_count", None) if usage else None,
                "completion_tokens": getattr(usage, "candidates_token_count", None) if usage else None,
            }
            return LLMResult(text, actual_model, int((time.time() - start) * 1000), token_usage, False)
        except Exception as e:
            print(f"[GeminiClient] Live call failed with model '{actual_model}' ({e}) — falling back to deterministic mock adapter.")
            return self._mock.generate(model=actual_model, system=system, prompt=prompt,
                                       temperature=temperature, max_tokens=max_tokens, as_json=as_json)


def build_client():
    """
    Factory: Selects Cloud Gemini, Local Ollama LLM, or Mock strictly based on .env / Config.
    1. If USE_GEMINI=true AND GEMINI_API_KEY is non-empty -> Cloud Gemini
    2. If Local LLM is configured (LLM_API_URL) -> Local Ollama
    3. Fallback -> Mock Adapter
    """
    use_gemini = getattr(Config, "USE_GEMINI", True) or Config.LLM_PROVIDER == "gemini"
    gemini_key = getattr(Config, "GEMINI_API_KEY", "").strip()

    # Explicit mock check
    if Config.LLM_PROVIDER == "mock":
        return MockGeminiClient()

    # 1. Use Cloud Gemini if enabled and key is present in .env
    if use_gemini and gemini_key:
        print(f"[LLM] Active Mode: CLOUD GEMINI (Model: {Config.GEMINI_MODEL})")
        return GeminiClient(gemini_key)

    # 2. Use Local LLM if URL configured in .env
    local_url = getattr(Config, "LLM_API_URL", "").strip()
    if local_url:
        print(f"[LLM] Active Mode: LOCAL OLLAMA (Endpoint: {local_url}, Model: {Config.LLM_MODEL})")
        return LocalLLMClient(local_url, Config.LLM_MODEL, Config.LLM_TIMEOUT)

    # 3. Fallback to mock
    print("[LLM] Active Mode: MOCK ADAPTER (No valid Gemini key or Local URL found in .env)")
    return MockGeminiClient()
