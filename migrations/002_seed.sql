-- =====================================================================
-- TDD Intelligence — Seed Data
--
-- Provides a runnable demo dataset: RBAC catalog, seven demo users (one per
-- role), a sample project with stories / acceptance criteria / services /
-- API contracts, default AI model configuration, and an ACTIVE prompt set.
--
-- Demo password for every seeded user is: Passw0rd!  (bcrypt hash below)
-- The hash is a valid bcrypt of "Passw0rd!" — safe for local/demo use only.
-- =====================================================================

SET NAMES utf8mb4;

-- ---------- Roles ----------
INSERT INTO roles (code, name, description) VALUES
  ('ADMIN',        'Administrator',   'Full platform administration'),
  ('ARCHITECT',    'Architect',       'Solution and test architecture'),
  ('DEVELOPER',    'Developer',       'Generates and reviews tests and code'),
  ('QA_ENGINEER',  'QA Engineer',     'Owns test quality and execution'),
  ('REVIEWER',     'Reviewer',        'Reviews and approves generated artifacts'),
  ('PRODUCT_OWNER','Product Owner',   'Owns requirements and acceptance criteria'),
  ('AUDITOR',      'Auditor',         'Read-only access to audit and evidence')
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- ---------- Permissions ----------
INSERT INTO permissions (code, description) VALUES
  ('project.read',      'View projects'),
  ('project.write',     'Create/update projects'),
  ('story.read',        'View user stories'),
  ('story.write',       'Create/update user stories'),
  ('workflow.create',   'Start TDD workflows'),
  ('workflow.read',     'View workflows'),
  ('test.review',       'Approve or reject generated tests'),
  ('evidence.review',   'Approve or reject evidence'),
  ('alm.write',         'Trigger ALM write-back'),
  ('knowledge.write',   'Upload/manage knowledge documents'),
  ('audit.read',        'View audit trail'),
  ('admin.manage',      'Manage users, roles and settings')
ON DUPLICATE KEY UPDATE description = VALUES(description);

-- ---------- Role → Permission grants ----------
-- ADMIN: everything
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p ON r.code = 'ADMIN';

-- DEVELOPER
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p
  ON r.code = 'DEVELOPER' AND p.code IN
  ('project.read','project.write','story.read','story.write','workflow.create','workflow.read','test.review','knowledge.write');

-- REVIEWER
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p
  ON r.code = 'REVIEWER' AND p.code IN
  ('project.read','story.read','workflow.read','test.review','evidence.review');

-- PRODUCT_OWNER
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p
  ON r.code = 'PRODUCT_OWNER' AND p.code IN
  ('project.read','project.write','story.read','story.write','workflow.read','evidence.review','alm.write');

-- QA_ENGINEER
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p
  ON r.code = 'QA_ENGINEER' AND p.code IN
  ('project.read','project.write','story.read','workflow.create','workflow.read','test.review');

-- ARCHITECT
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p
  ON r.code = 'ARCHITECT' AND p.code IN
  ('project.read','project.write','story.read','workflow.read','knowledge.write');

-- AUDITOR: read-only + audit
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r JOIN permissions p
  ON r.code = 'AUDITOR' AND p.code IN
  ('project.read','story.read','workflow.read','audit.read');

-- ---------- Demo users (password = Passw0rd!) ----------
-- bcrypt hash generated with bcrypt.hashpw("Passw0rd!", gensalt(rounds=12))
SET @pw = '$2b$12$Egnpr9NHZuqplJLYG82jpuZSCTd6vbVNEW5LfqoXgcqEuRw1AA86G';


INSERT INTO users (uuid, name, email, password_hash, is_active) VALUES
  (UUID(), 'Ada Admin',      'admin@tdd.local',     @pw, 1),
  (UUID(), 'Arun Architect', 'architect@tdd.local', @pw, 1),
  (UUID(), 'Dev Developer',  'developer@tdd.local', @pw, 1),
  (UUID(), 'Quinn QA',       'qa@tdd.local',        @pw, 1),
  (UUID(), 'Rhea Reviewer',  'reviewer@tdd.local',  @pw, 1),
  (UUID(), 'Priya PO',       'po@tdd.local',        @pw, 1),
  (UUID(), 'Alex Auditor',   'auditor@tdd.local',   @pw, 1)
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- Map each demo user to their role
INSERT IGNORE INTO user_roles (user_id, role_id)
SELECT u.id, r.id FROM users u JOIN roles r ON
  (u.email='admin@tdd.local'     AND r.code='ADMIN') OR
  (u.email='architect@tdd.local' AND r.code='ARCHITECT') OR
  (u.email='developer@tdd.local' AND r.code='DEVELOPER') OR
  (u.email='qa@tdd.local'        AND r.code='QA_ENGINEER') OR
  (u.email='reviewer@tdd.local'  AND r.code='REVIEWER') OR
  (u.email='po@tdd.local'        AND r.code='PRODUCT_OWNER') OR
  (u.email='auditor@tdd.local'   AND r.code='AUDITOR');

-- ---------- Sample project ----------
INSERT INTO projects (uuid, key_code, name, description, target_language, target_framework, coding_standard, health, created_by)
SELECT UUID(), 'PAY', 'Payments Platform',
       'Core payments service — authorization, capture, refunds.',
       'java', 'junit5', 'checkstyle-google', 'green', u.id
FROM users u WHERE u.email = 'architect@tdd.local'
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- Project membership
INSERT IGNORE INTO project_members (project_id, user_id, role_code)
SELECT p.id, u.id, 
  CASE u.email
    WHEN 'architect@tdd.local' THEN 'ARCHITECT'
    WHEN 'developer@tdd.local' THEN 'DEVELOPER'
    WHEN 'reviewer@tdd.local'  THEN 'REVIEWER'
    WHEN 'po@tdd.local'        THEN 'PRODUCT_OWNER'
    WHEN 'qa@tdd.local'        THEN 'QA_ENGINEER'
  END
FROM projects p JOIN users u ON p.key_code = 'PAY'
WHERE u.email IN ('architect@tdd.local','developer@tdd.local','reviewer@tdd.local','po@tdd.local','qa@tdd.local');

-- ---------- Stories ----------
INSERT INTO stories (uuid, project_id, external_key, title, description, sprint, status, coverage_pct, created_by)
SELECT UUID(), p.id, 'PAY-101',
       'Authorize a card payment',
       'As a merchant, I want to authorize a card payment so that funds are reserved before capture.',
       'Sprint 12', 'ready', 0.00, u.id
FROM projects p JOIN users u ON u.email='po@tdd.local' WHERE p.key_code='PAY';

INSERT INTO stories (uuid, project_id, external_key, title, description, sprint, status, coverage_pct, created_by)
SELECT UUID(), p.id, 'PAY-102',
       'Refund a captured payment',
       'As a merchant, I want to refund a captured payment so that a customer receives their money back.',
       'Sprint 12', 'draft', 0.00, u.id
FROM projects p JOIN users u ON u.email='po@tdd.local' WHERE p.key_code='PAY';

-- ---------- Acceptance criteria for PAY-101 ----------
INSERT INTO acceptance_criteria (uuid, story_id, ac_key, text)
SELECT UUID(), s.id, 'AC-1', 'Given a valid card and sufficient limit, when authorization is requested, then a hold is placed and an auth code is returned.'
FROM stories s WHERE s.external_key='PAY-101';

INSERT INTO acceptance_criteria (uuid, story_id, ac_key, text)
SELECT UUID(), s.id, 'AC-2', 'Given an expired card, when authorization is requested, then the request is rejected with a validation error.'
FROM stories s WHERE s.external_key='PAY-101';

INSERT INTO acceptance_criteria (uuid, story_id, ac_key, text)
SELECT UUID(), s.id, 'AC-3', 'Given an amount above the card limit, when authorization is requested, then the request is declined.'
FROM stories s WHERE s.external_key='PAY-101';

-- ---------- Services & contracts ----------
INSERT INTO services (uuid, project_id, name, description)
SELECT UUID(), p.id, 'AuthorizationService', 'Handles card authorization holds.'
FROM projects p WHERE p.key_code='PAY';

INSERT INTO api_contracts (uuid, service_id, method, path, request_schema, response_schema, version)
SELECT UUID(), sv.id, 'POST', '/api/payments/authorize',
       JSON_OBJECT('card', 'string', 'amount', 'number', 'currency', 'string'),
       JSON_OBJECT('authCode', 'string', 'status', 'string'),
       'v1'
FROM services sv WHERE sv.name='AuthorizationService';

-- ---------- Default model configuration (Gemini) ----------
INSERT INTO model_configurations (uuid, task_type, provider, model_name, temperature, max_tokens, timeout_s, is_active) VALUES
  (UUID(), 'requirement_analysis', 'gemini', 'gemini-3.1-flash-lite', 0.20, 2048, 60, 1),
  (UUID(), 'service_planning',     'gemini', 'gemini-3.1-flash-lite', 0.20, 2048, 60, 1),
  (UUID(), 'test_generation',      'gemini', 'gemini-3.1-flash-lite', 0.30, 4096, 90, 1),
  (UUID(), 'code_generation',      'gemini', 'gemini-3.1-flash-lite', 0.20, 4096, 90, 1),
  (UUID(), 'evidence_narrative',   'gemini', 'gemini-3.1-flash-lite', 0.20, 2048, 60, 1),
  (UUID(), 'explanation',          'gemini', 'gemini-3.1-flash-lite', 0.30, 1024, 45, 1)
ON DUPLICATE KEY UPDATE model_name = VALUES(model_name);

-- ---------- Active prompt set ----------
INSERT INTO prompt_versions (uuid, prompt_name, version, agent, task_type, content, status, activated_at) VALUES
  (UUID(), 'requirement_analysis', 'v1', 'requirement_analyzer', 'requirement_analysis',
   'Decompose the user story and acceptance criteria into business rules and positive, negative, boundary, validation and error scenarios. Flag ambiguities; never invent missing rules. Return structured JSON only.', 'ACTIVE', NOW()),
  (UUID(), 'service_planning', 'v1', 'service_planner', 'service_planning',
   'Given services and API contracts, identify impacted services, dependencies and a service-by-service test plan. Flag missing or contradictory contracts as planning exceptions. Return structured JSON only.', 'ACTIVE', NOW()),
  (UUID(), 'test_generation', 'v1', 'test_generator', 'test_generation',
   'Generate structured, traceable test cases for the given scenarios and contracts in the configured language and framework. Each case must map to a requirement and acceptance criterion. Return structured JSON only.', 'ACTIVE', NOW()),
  (UUID(), 'evidence_narrative', 'v1', 'evidence_generator', 'evidence_narrative',
   'Summarize execution and validation results into an evidence narrative. Never alter or invent execution values. Return concise prose.', 'ACTIVE', NOW())
ON DUPLICATE KEY UPDATE status = VALUES(status);

-- ---------- Default guardrail-friendly settings ----------
INSERT INTO settings (scope, scope_id, key_name, value_json) VALUES
  ('global', NULL, 'workflow.max_retries', JSON_OBJECT('value', 3)),
  ('global', NULL, 'rag.top_k', JSON_OBJECT('value', 8)),
  ('global', NULL, 'evidence.default_format', JSON_OBJECT('value', 'docx'))
ON DUPLICATE KEY UPDATE value_json = VALUES(value_json);
