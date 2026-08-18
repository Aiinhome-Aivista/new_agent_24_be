"""
Centralized Gemini client with a safe MOCK adapter for development.

If LLM_PROVIDER=gemini and GEMINI_API_KEY is set, real calls are made via google-genai.
Otherwise a deterministic MOCK adapter is used and every output is tagged MOCK so it can
never be mistaken for a real model response.
"""
import json
import time
from app.config import Config


class LLMResult:
    def __init__(self, text, model, latency_ms, token_usage, is_mock):
        self.text = text
        self.model = model
        self.latency_ms = latency_ms
        self.token_usage = token_usage
        self.is_mock = is_mock


class MockGeminiClient:
    def generate(self, *, model, system, prompt, temperature, max_tokens, as_json=False):
        start = time.time()
        if as_json:
            text = json.dumps({"_mock": True, "note": "MOCK structured output — set GEMINI_API_KEY for real generation"})
        else:
            text = "[MOCK] Set GEMINI_API_KEY and LLM_PROVIDER=gemini for real model output."
        return LLMResult(text, f"MOCK::{model}", int((time.time() - start) * 1000),
                         {"prompt_tokens": len(prompt.split()), "completion_tokens": 0}, True)


MODEL_ALIASES = {
    "gemini-1.5-pro": "gemini-3.1-flash-lite",
    "gemini-1.5-flash": "gemini-3.1-flash-lite",
    "gemini-1.5-flash-latest": "gemini-3.1-flash-lite",
    "gemini-1.0-pro": "gemini-3.1-flash-lite",
    "gemini-2.5-pro": "gemini-3.1-flash-lite",
    "gemini-2.5-flash": "gemini-3.1-flash-lite",
}


class GeminiClient:
    def __init__(self, api_key):
        try:
            # pyrefly: ignore [missing-import]
            from google import genai  # imported lazily so mock mode needs no dependency
            self._client = genai.Client(api_key=api_key.strip() if api_key else "")
            self._mock = MockGeminiClient()
        except Exception as e:
            print(f"[GeminiClient] Failed to initialize Google GenAI SDK ({e}) — using Mock adapter.")
            self._client = None
            self._mock = MockGeminiClient()

    def generate(self, *, model, system, prompt, temperature, max_tokens, as_json=False):
        # Normalize model name if alias exists
        actual_model = MODEL_ALIASES.get(model, model)
        if actual_model.startswith("models/"):
            actual_model = actual_model.replace("models/", "")

        if self._client is None:
            return self._mock.generate(model=actual_model, system=system, prompt=prompt,
                                       temperature=temperature, max_tokens=max_tokens, as_json=as_json)

        try:
            start = time.time()
            contents = f"{system}\n\n{prompt}" if system else prompt
            config = {"temperature": temperature, "max_output_tokens": max_tokens}
            if as_json:
                config["response_mime_type"] = "application/json"
            resp = self._client.models.generate_content(model=actual_model, contents=contents, config=config)
            usage = getattr(resp, "usage_metadata", None)
            token_usage = {
                "prompt_tokens": getattr(usage, "prompt_token_count", None) if usage else None,
                "completion_tokens": getattr(usage, "candidates_token_count", None) if usage else None,
            }
            return LLMResult(resp.text, actual_model, int((time.time() - start) * 1000), token_usage, False)
        except Exception as e:
            print(f"[GeminiClient] Live call failed with model '{actual_model}' ({e}) — falling back to deterministic mock adapter.")
            return self._mock.generate(model=actual_model, system=system, prompt=prompt,
                                       temperature=temperature, max_tokens=max_tokens, as_json=as_json)



def build_client():
    if Config.LLM_PROVIDER == "gemini" and Config.GEMINI_API_KEY:
        return GeminiClient(Config.GEMINI_API_KEY)
    return MockGeminiClient()
