"""Application factory — wires config, CORS, middleware, tracing, error handlers, blueprints."""
from flask import Flask
from flask_cors import CORS
from app.config import Config
from app.errors.handlers import register_error_handlers
from app.middleware.request_context import register_request_context
from app.observability.tracing import init_tracing

from app.routes.health_routes import health_bp
from app.routes.auth_routes import auth_bp
from app.routes.project_routes import project_bp
from app.routes.workflow_routes import workflow_bp
from app.routes.test_routes import test_bp
from app.routes.approval_routes import approval_bp
from app.routes.agent_routes import agent_bp
from app.routes.governance_routes import governance_bp
from app.routes.dashboard_routes import dashboard_bp

API_PREFIX = "/api/v1"


def create_app(config=Config):
    app = Flask(__name__)
    app.config.from_object(config)

    CORS(app, origins=config.CORS_ORIGINS, supports_credentials=True)
    init_tracing(app)
    register_request_context(app)
    register_error_handlers(app)

    for bp in (health_bp, auth_bp, project_bp, workflow_bp, test_bp,
               approval_bp, agent_bp, governance_bp, dashboard_bp):
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    return app
