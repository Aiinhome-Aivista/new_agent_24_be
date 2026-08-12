# TDD Intelligence — Backend

Flask (Python 3.12) API + agentic core for the TDD Intelligence platform.

## Run locally
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
mysql -u root -p tdd_intelligence < migrations/001_schema.sql
mysql -u root -p tdd_intelligence < migrations/002_seed.sql
cp ../.env.example .env   # set MYSQL_HOST=localhost
python wsgi.py            # http://localhost:5000/api/v1/health
celery -A app.tasks.celery_app worker --loglevel=info   # optional async worker
```

## Layout
```
app/
  config/ extensions/ middleware/ errors/     # foundation
  auth/                                        # JWT + bcrypt + RBAC
  repositories/                                # data access (all SQL lives here)
  routes/                                      # /api/v1 blueprints
  workflows/state_machine.py                   # explicit stages + statuses
  agents/orchestrator + 7 specialists          # agentic core
  llm/{client,model_router}                    # Gemini + MockGemini + ModelRouter
  tools/{api_runner,code_analysis,document_generator,alm}   # deterministic tools
  rag/                                         # Docling→Chroma retrieval (+ mock)
  guardrails/engine.py                         # input/retrieval/execution/output/ALM
  observability/tracing.py                     # OpenTelemetry + redaction
  audit/audit_log.py                           # audit + guardrail events
  tasks/                                        # Celery app + workflow tasks
migrations/                                     # 001_schema.sql, 002_seed.sql
tests/                                          # pytest
```

## Tests
```bash
pytest -q
```
