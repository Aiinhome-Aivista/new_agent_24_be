"""OpenTelemetry setup with configurable exporter + safe-logging redaction."""
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource
from app.config import Config

_REDACT = {"password", "password_hash", "token", "jwt", "authorization",
           "api_key", "gemini_api_key", "secret"}

_initialized = False


def init_tracing(app):
    global _initialized
    if _initialized:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": Config.OTEL_SERVICE_NAME}))
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _initialized = True


def get_tracer():
    return trace.get_tracer(Config.OTEL_SERVICE_NAME)


def redact(payload):
    """Never log secrets. Shallow redaction for dicts headed to logs/spans/audit."""
    if not isinstance(payload, dict):
        return payload
    return {k: ("***REDACTED***" if k.lower() in _REDACT else v) for k, v in payload.items()}
