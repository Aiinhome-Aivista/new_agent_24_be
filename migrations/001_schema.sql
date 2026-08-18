-- =====================================================================
-- TDD Intelligence — Complete Relational Schema (MySQL 8)
-- AI-Assisted TDD Test Case Generator & Evidence Automation Platform
--
-- Design notes:
--   * Normalized relational entities. JSON columns are used ONLY for
--     genuinely flexible metadata (agent output payloads, request/response
--     captures, trace attributes) — the app is not a JSON database.
--   * Every consequential entity carries created_at / updated_at.
--   * Foreign keys enforce referential integrity; ON DELETE chosen per
--     relationship (CASCADE for owned children, RESTRICT for references).
-- =====================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ---------------------------------------------------------------------
-- IDENTITY, RBAC
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid            CHAR(36) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    is_active       TINYINT(1) NOT NULL DEFAULT 1,
    last_login_at   TIMESTAMP NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_users_uuid (uuid),
    UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS roles (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    code        VARCHAR(50) NOT NULL,          -- ADMIN, ARCHITECT, DEVELOPER, QA_ENGINEER, REVIEWER, PRODUCT_OWNER, AUDITOR
    name        VARCHAR(100) NOT NULL,
    description VARCHAR(255),
    UNIQUE KEY uq_roles_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS permissions (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    code        VARCHAR(100) NOT NULL,         -- e.g. workflow.create, evidence.approve, alm.write
    description VARCHAR(255),
    UNIQUE KEY uq_permissions_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id       BIGINT NOT NULL,
    permission_id BIGINT NOT NULL,
    PRIMARY KEY (role_id, permission_id),
    CONSTRAINT fk_rp_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
    CONSTRAINT fk_rp_perm FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_roles (
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    PRIMARY KEY (user_id, role_id),
    CONSTRAINT fk_ur_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_ur_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- WORKSPACES: PROJECTS, MEMBERSHIP
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS projects (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid          CHAR(36) NOT NULL,
    key_code      VARCHAR(30) NOT NULL,        -- short project key, e.g. PAY, ORD
    name          VARCHAR(255) NOT NULL,
    description   TEXT,
    target_language  VARCHAR(50)  DEFAULT 'java',
    target_framework VARCHAR(50)  DEFAULT 'junit5',
    coding_standard  VARCHAR(100) DEFAULT 'checkstyle-google',
    git_repo_url     VARCHAR(500),
    git_provider     VARCHAR(50)  DEFAULT 'github',
    git_branch       VARCHAR(100) DEFAULT 'main',
    base_branch      VARCHAR(100) DEFAULT 'main',
    tech_stack       VARCHAR(100),
    build_tool       VARCHAR(100),
    app_type         VARCHAR(100) DEFAULT 'REST API / Microservice',
    deployment_target VARCHAR(100),
    testing_framework VARCHAR(100),
    integration_test_framework VARCHAR(100),
    mocking_library  VARCHAR(100),
    target_coverage  VARCHAR(50)  DEFAULT '80%',
    frontend_framework VARCHAR(100),
    backend_framework VARCHAR(100),
    health        VARCHAR(20) NOT NULL DEFAULT 'green',   -- green | amber | red
    created_by    BIGINT,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_projects_uuid (uuid),
    UNIQUE KEY uq_projects_key (key_code),
    CONSTRAINT fk_projects_creator FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS project_members (
    project_id BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    role_code  VARCHAR(50) NOT NULL,           -- project-scoped role
    added_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project_id, user_id),
    CONSTRAINT fk_pm_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_pm_user    FOREIGN KEY (user_id)    REFERENCES users(id)    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- REQUIREMENTS DOMAIN: STORIES, ACCEPTANCE CRITERIA, REQUIREMENTS
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS stories (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid          CHAR(36) NOT NULL,
    project_id    BIGINT NOT NULL,
    external_key  VARCHAR(50),                 -- e.g. JIRA/ADO id
    title         VARCHAR(500) NOT NULL,
    description   TEXT,
    sprint        VARCHAR(50),
    status        VARCHAR(30) NOT NULL DEFAULT 'draft',  -- draft|ready|in_workflow|covered|blocked
    coverage_pct  DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    created_by    BIGINT,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_stories_uuid (uuid),
    KEY idx_stories_project (project_id),
    KEY idx_stories_status (status),
    CONSTRAINT fk_stories_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_stories_creator FOREIGN KEY (created_by) REFERENCES users(id)   ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS acceptance_criteria (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid        CHAR(36) NOT NULL,
    story_id    BIGINT NOT NULL,
    ac_key      VARCHAR(30) NOT NULL,          -- AC-1, AC-2 within the story
    text        TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_ac_uuid (uuid),
    KEY idx_ac_story (story_id),
    CONSTRAINT fk_ac_story FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS requirements (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid          CHAR(36) NOT NULL,
    story_id      BIGINT NOT NULL,
    req_key       VARCHAR(30) NOT NULL,        -- REQ-1
    kind          VARCHAR(30) NOT NULL DEFAULT 'business_rule', -- business_rule|functional|dependency|assumption
    text          TEXT NOT NULL,
    is_ambiguous  TINYINT(1) NOT NULL DEFAULT 0,
    source_ac_id  BIGINT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_req_uuid (uuid),
    KEY idx_req_story (story_id),
    CONSTRAINT fk_req_story FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE,
    CONSTRAINT fk_req_ac    FOREIGN KEY (source_ac_id) REFERENCES acceptance_criteria(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- SERVICES & CONTRACTS
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS services (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid        CHAR(36) NOT NULL,
    project_id  BIGINT NOT NULL,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_services_uuid (uuid),
    KEY idx_services_project (project_id),
    CONSTRAINT fk_services_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS api_contracts (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid         CHAR(36) NOT NULL,
    service_id   BIGINT NOT NULL,
    method       VARCHAR(10) NOT NULL,          -- GET|POST|PUT|PATCH|DELETE
    path         VARCHAR(500) NOT NULL,
    request_schema  JSON,
    response_schema JSON,
    version      VARCHAR(30) DEFAULT 'v1',
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_contracts_uuid (uuid),
    KEY idx_contracts_service (service_id),
    CONSTRAINT fk_contracts_service FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- WORKFLOW STATE MACHINE: RUNS, TASKS, AGENT RUNS
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS workflow_runs (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    workflow_id     CHAR(36) NOT NULL,          -- public id returned to clients
    project_id      BIGINT NOT NULL,
    story_id        BIGINT NOT NULL,
    status          VARCHAR(30) NOT NULL DEFAULT 'QUEUED',  -- see workflow state machine
    current_stage   VARCHAR(40) NOT NULL DEFAULT 'CREATED',
    current_agent   VARCHAR(60),
    capabilities    JSON,                       -- which stages were enabled in the wizard
    state_json      JSON,                       -- full serialized agent state
    started_by      BIGINT,
    error_code      VARCHAR(60),
    error_message   VARCHAR(1000),
    started_at      TIMESTAMP NULL,
    completed_at    TIMESTAMP NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_wf_workflow_id (workflow_id),
    KEY idx_wf_project (project_id),
    KEY idx_wf_story (story_id),
    KEY idx_wf_status (status),
    CONSTRAINT fk_wf_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_wf_story   FOREIGN KEY (story_id)   REFERENCES stories(id)  ON DELETE CASCADE,
    CONSTRAINT fk_wf_user    FOREIGN KEY (started_by) REFERENCES users(id)    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS workflow_tasks (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    task_id       CHAR(36) NOT NULL,            -- celery/task id
    workflow_id   CHAR(36) NOT NULL,
    agent         VARCHAR(60) NOT NULL,
    stage         VARCHAR(40) NOT NULL,
    status        VARCHAR(30) NOT NULL DEFAULT 'QUEUED',
    retry_count   INT NOT NULL DEFAULT 0,
    error_code    VARCHAR(60),
    error_message VARCHAR(1000),
    started_at    TIMESTAMP NULL,
    completed_at  TIMESTAMP NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_task_id (task_id),
    KEY idx_task_workflow (workflow_id),
    CONSTRAINT fk_task_wf FOREIGN KEY (workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_runs (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid          CHAR(36) NOT NULL,
    workflow_id   CHAR(36) NOT NULL,
    agent         VARCHAR(60) NOT NULL,
    agent_version VARCHAR(20) DEFAULT 'v1',
    task_type     VARCHAR(60),
    model_name    VARCHAR(80),
    tool_name     VARCHAR(80),
    status        VARCHAR(30) NOT NULL DEFAULT 'RUNNING',
    input_summary  JSON,
    output_summary JSON,
    token_usage   JSON,
    latency_ms    INT,
    retry_count   INT NOT NULL DEFAULT 0,
    trace_id      VARCHAR(64),
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_agentrun_uuid (uuid),
    KEY idx_agentrun_wf (workflow_id),
    KEY idx_agentrun_agent (agent),
    CONSTRAINT fk_agentrun_wf FOREIGN KEY (workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- TEST DOMAIN: PLANS, CASES, STEPS
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS test_plans (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid         CHAR(36) NOT NULL,
    workflow_id  CHAR(36) NOT NULL,
    story_id     BIGINT NOT NULL,
    summary      TEXT,
    sequencing   JSON,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_testplan_uuid (uuid),
    KEY idx_testplan_wf (workflow_id),
    CONSTRAINT fk_testplan_wf    FOREIGN KEY (workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE,
    CONSTRAINT fk_testplan_story FOREIGN KEY (story_id)    REFERENCES stories(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS test_cases (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid               CHAR(36) NOT NULL,
    test_plan_id       BIGINT NULL,
    workflow_id        CHAR(36) NOT NULL,
    story_id           BIGINT NOT NULL,
    service_id         BIGINT NULL,
    api_contract_id    BIGINT NULL,
    test_key           VARCHAR(40) NOT NULL,     -- TC-001
    scenario_type      VARCHAR(30) NOT NULL,     -- positive|negative|boundary|validation|error|security|integration
    title              VARCHAR(500) NOT NULL,
    description        TEXT,
    preconditions      TEXT,
    expected_result    TEXT,
    priority           VARCHAR(20) DEFAULT 'medium',
    risk               VARCHAR(20) DEFAULT 'medium',
    origin             VARCHAR(20) NOT NULL DEFAULT 'AI_GENERATED', -- AI_GENERATED|MODIFIED
    status             VARCHAR(30) NOT NULL DEFAULT 'AWAITING_REVIEW', -- AWAITING_REVIEW|APPROVED|REJECTED
    generated_code     MEDIUMTEXT,
    target_language    VARCHAR(50),
    framework          VARCHAR(50),
    version            INT NOT NULL DEFAULT 1,
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_testcase_uuid (uuid),
    KEY idx_testcase_wf (workflow_id),
    KEY idx_testcase_story (story_id),
    KEY idx_testcase_status (status),
    CONSTRAINT fk_tc_plan     FOREIGN KEY (test_plan_id)    REFERENCES test_plans(id)   ON DELETE SET NULL,
    CONSTRAINT fk_tc_wf       FOREIGN KEY (workflow_id)     REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE,
    CONSTRAINT fk_tc_story    FOREIGN KEY (story_id)        REFERENCES stories(id)      ON DELETE CASCADE,
    CONSTRAINT fk_tc_service  FOREIGN KEY (service_id)      REFERENCES services(id)     ON DELETE SET NULL,
    CONSTRAINT fk_tc_contract FOREIGN KEY (api_contract_id) REFERENCES api_contracts(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS test_steps (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    test_case_id BIGINT NOT NULL,
    step_no      INT NOT NULL,
    action       TEXT NOT NULL,
    expected     TEXT,
    KEY idx_step_tc (test_case_id),
    CONSTRAINT fk_step_tc FOREIGN KEY (test_case_id) REFERENCES test_cases(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- EXECUTION: RUNS, RESULTS, RAW API REQUEST/RESPONSE
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS execution_runs (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid          CHAR(36) NOT NULL,
    workflow_id   CHAR(36) NOT NULL,
    runner        VARCHAR(30) NOT NULL DEFAULT 'mock',  -- bruno|postman|mock
    environment   VARCHAR(80),
    collection    VARCHAR(255),
    status        VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    total         INT DEFAULT 0,
    passed        INT DEFAULT 0,
    failed        INT DEFAULT 0,
    is_mock       TINYINT(1) NOT NULL DEFAULT 0,
    started_at    TIMESTAMP NULL,
    completed_at  TIMESTAMP NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_execrun_uuid (uuid),
    KEY idx_execrun_wf (workflow_id),
    CONSTRAINT fk_execrun_wf FOREIGN KEY (workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS execution_results (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid           CHAR(36) NOT NULL,
    execution_run_id BIGINT NOT NULL,
    test_case_id   BIGINT NULL,
    status_code    INT,
    passed         TINYINT(1),
    duration_ms    INT,
    assertions     JSON,
    executed_at    TIMESTAMP NULL,
    is_mock        TINYINT(1) NOT NULL DEFAULT 0,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_execres_uuid (uuid),
    KEY idx_execres_run (execution_run_id),
    CONSTRAINT fk_execres_run FOREIGN KEY (execution_run_id) REFERENCES execution_runs(id) ON DELETE CASCADE,
    CONSTRAINT fk_execres_tc  FOREIGN KEY (test_case_id)     REFERENCES test_cases(id)     ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Raw request/response persisted separately so evidence is reproducible and
-- an LLM narrative can never overwrite the deterministic capture.
CREATE TABLE IF NOT EXISTS api_requests (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    execution_result_id BIGINT NOT NULL,
    method              VARCHAR(10),
    url                 VARCHAR(1000),
    headers             JSON,
    body                MEDIUMTEXT,
    CONSTRAINT fk_apireq_res FOREIGN KEY (execution_result_id) REFERENCES execution_results(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS api_responses (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    execution_result_id BIGINT NOT NULL,
    status_code         INT,
    headers             JSON,
    body                MEDIUMTEXT,
    raw_log_reference   VARCHAR(500),
    CONSTRAINT fk_apiresp_res FOREIGN KEY (execution_result_id) REFERENCES execution_results(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- CODE QUALITY
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS code_quality_runs (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid         CHAR(36) NOT NULL,
    workflow_id  CHAR(36) NOT NULL,
    analyzer     VARCHAR(40) NOT NULL DEFAULT 'mock',  -- sonarqube|checkstyle|pmd|spotbugs|mock
    score        DECIMAL(5,2),
    passed       TINYINT(1),
    is_mock      TINYINT(1) NOT NULL DEFAULT 0,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_cqrun_uuid (uuid),
    KEY idx_cqrun_wf (workflow_id),
    CONSTRAINT fk_cqrun_wf FOREIGN KEY (workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS code_quality_issues (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    code_quality_run_id BIGINT NOT NULL,
    severity           VARCHAR(20),          -- blocker|critical|major|minor|info
    rule               VARCHAR(120),
    file               VARCHAR(500),
    line               INT,
    description        TEXT,
    remediation        TEXT,
    KEY idx_cqissue_run (code_quality_run_id),
    CONSTRAINT fk_cqissue_run FOREIGN KEY (code_quality_run_id) REFERENCES code_quality_runs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- TRACEABILITY
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS traceability_links (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    workflow_id   CHAR(36) NOT NULL,
    from_type     VARCHAR(30) NOT NULL,   -- requirement|acceptance_criteria|scenario|test_case|api_test|execution|evidence
    from_id       VARCHAR(60) NOT NULL,
    to_type       VARCHAR(30) NOT NULL,
    to_id         VARCHAR(60) NOT NULL,
    relation      VARCHAR(30) NOT NULL DEFAULT 'covers',
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_trace_wf (workflow_id),
    KEY idx_trace_from (from_type, from_id),
    KEY idx_trace_to (to_type, to_id),
    CONSTRAINT fk_trace_wf FOREIGN KEY (workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- KNOWLEDGE / RAG
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid          CHAR(36) NOT NULL,
    project_id    BIGINT NOT NULL,
    title         VARCHAR(500) NOT NULL,
    doc_type      VARCHAR(50) NOT NULL,   -- user_story|acceptance_criteria|design|service_catalogue|api_contract|coding_standard|historical_evidence
    source        VARCHAR(255),
    version       VARCHAR(30) DEFAULT 'v1',
    index_status  VARCHAR(30) NOT NULL DEFAULT 'pending', -- pending|indexing|indexed|failed|archived
    freshness_at  TIMESTAMP NULL,
    chunk_count   INT NOT NULL DEFAULT 0,
    uploaded_by   BIGINT,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_kdoc_uuid (uuid),
    KEY idx_kdoc_project (project_id),
    CONSTRAINT fk_kdoc_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_kdoc_user    FOREIGN KEY (uploaded_by) REFERENCES users(id)   ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid          CHAR(36) NOT NULL,
    document_id   BIGINT NOT NULL,
    project_id    BIGINT NOT NULL,
    chunk_index   INT NOT NULL,
    content       MEDIUMTEXT NOT NULL,
    metadata      JSON,
    vector_ref    VARCHAR(120),           -- id in ChromaDB
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_kchunk_uuid (uuid),
    KEY idx_kchunk_doc (document_id),
    KEY idx_kchunk_project (project_id),
    CONSTRAINT fk_kchunk_doc     FOREIGN KEY (document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    CONSTRAINT fk_kchunk_project FOREIGN KEY (project_id)  REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- EVIDENCE
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS evidence_packages (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid            CHAR(36) NOT NULL,
    evidence_key    VARCHAR(50) NOT NULL,
    workflow_id     CHAR(36) NOT NULL,
    story_id        BIGINT NOT NULL,
    version         INT NOT NULL DEFAULT 1,
    format          VARCHAR(10) NOT NULL DEFAULT 'docx',
    file_path       VARCHAR(500),
    checksum        VARCHAR(128),
    source_execution_ids JSON,
    prompt_version  VARCHAR(30),
    model_info      JSON,
    narrative       MEDIUMTEXT,
    approval_status VARCHAR(20) NOT NULL DEFAULT 'PENDING', -- PENDING|APPROVED|REJECTED|ATTACHED
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_evid_uuid (uuid),
    UNIQUE KEY uq_evid_key (evidence_key),
    KEY idx_evid_wf (workflow_id),
    CONSTRAINT fk_evid_wf    FOREIGN KEY (workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE,
    CONSTRAINT fk_evid_story FOREIGN KEY (story_id)    REFERENCES stories(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- GOVERNANCE: APPROVALS, AUDIT, GUARDRAILS
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS approvals (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid          CHAR(36) NOT NULL,
    workflow_id   CHAR(36) NOT NULL,
    stage         VARCHAR(40) NOT NULL,      -- TEST_REVIEW|EVIDENCE_REVIEW|ALM_ATTACHMENT
    decision      VARCHAR(20) NOT NULL DEFAULT 'PENDING', -- PENDING|APPROVED|REJECTED|CHANGES_REQUESTED
    approver_id   BIGINT,
    comment       TEXT,
    requested_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at    TIMESTAMP NULL,
    UNIQUE KEY uq_approval_uuid (uuid),
    KEY idx_approval_wf (workflow_id),
    KEY idx_approval_decision (decision),
    CONSTRAINT fk_approval_wf   FOREIGN KEY (workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE,
    CONSTRAINT fk_approval_user FOREIGN KEY (approver_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS integrations (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid          CHAR(36) NOT NULL,
    project_id    BIGINT NOT NULL,
    kind          VARCHAR(30) NOT NULL,      -- alm|git|api_testing|code_quality
    provider      VARCHAR(40) NOT NULL,      -- azure_devops|jira|rally|github|bruno|postman|sonarqube|mock
    config        JSON,
    status        VARCHAR(20) NOT NULL DEFAULT 'connected', -- connected|degraded|disconnected|mock
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_integration_uuid (uuid),
    KEY idx_integration_project (project_id),
    CONSTRAINT fk_integration_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ALM write-back log (idempotent) — one row per attempted attach.
CREATE TABLE IF NOT EXISTS alm_writebacks (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid          CHAR(36) NOT NULL,
    integration_id BIGINT NULL,
    workflow_id   CHAR(36) NOT NULL,
    story_id      BIGINT NOT NULL,
    evidence_id   BIGINT NOT NULL,
    idempotency_key VARCHAR(120) NOT NULL,
    request_id    VARCHAR(120),
    external_ref  VARCHAR(255),
    status        VARCHAR(20) NOT NULL DEFAULT 'PENDING',  -- PENDING|SUCCESS|FAILED
    response      JSON,
    actor_id      BIGINT,
    is_mock       TINYINT(1) NOT NULL DEFAULT 0,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_alm_uuid (uuid),
    UNIQUE KEY uq_alm_idempotency (idempotency_key),
    KEY idx_alm_wf (workflow_id),
    CONSTRAINT fk_alm_wf    FOREIGN KEY (workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE,
    CONSTRAINT fk_alm_evid  FOREIGN KEY (evidence_id) REFERENCES evidence_packages(id) ON DELETE CASCADE,
    CONSTRAINT fk_alm_actor FOREIGN KEY (actor_id)    REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_events (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    event_id      CHAR(36) NOT NULL,
    timestamp     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id       BIGINT NULL,
    project_id    BIGINT NULL,
    story_id      BIGINT NULL,
    workflow_id   CHAR(36) NULL,
    agent         VARCHAR(60),
    tool          VARCHAR(60),
    event_type    VARCHAR(80) NOT NULL,
    status        VARCHAR(30),
    metadata      JSON,
    trace_id      VARCHAR(64),
    request_id    VARCHAR(64),
    UNIQUE KEY uq_audit_event (event_id),
    KEY idx_audit_wf (workflow_id),
    KEY idx_audit_type (event_type),
    KEY idx_audit_time (timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS guardrail_events (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid          CHAR(36) NOT NULL,
    workflow_id   CHAR(36) NULL,
    layer         VARCHAR(20) NOT NULL,       -- input|retrieval|execution|output|alm
    rule          VARCHAR(120) NOT NULL,
    passed        TINYINT(1) NOT NULL,
    detail        VARCHAR(1000),
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_grevent_uuid (uuid),
    KEY idx_grevent_wf (workflow_id),
    KEY idx_grevent_layer (layer)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- NOTIFICATIONS, SETTINGS
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS notifications (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid        CHAR(36) NOT NULL,
    user_id     BIGINT NOT NULL,
    kind        VARCHAR(40) NOT NULL,        -- approval_requested|workflow_failed|evidence_ready|...
    title       VARCHAR(255) NOT NULL,
    body        VARCHAR(1000),
    link        VARCHAR(500),
    is_read     TINYINT(1) NOT NULL DEFAULT 0,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_notif_uuid (uuid),
    KEY idx_notif_user (user_id),
    CONSTRAINT fk_notif_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS settings (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    scope       VARCHAR(20) NOT NULL DEFAULT 'global',  -- global|project|user
    scope_id    BIGINT NULL,
    key_name    VARCHAR(120) NOT NULL,
    value_json  JSON,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_setting (scope, scope_id, key_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- AI GOVERNANCE: PROMPT VERSIONS, TOOL SCHEMAS, MODEL CONFIG
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS prompt_versions (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid         CHAR(36) NOT NULL,
    prompt_name  VARCHAR(120) NOT NULL,
    version      VARCHAR(20) NOT NULL,
    agent        VARCHAR(60),
    task_type    VARCHAR(60),
    content      MEDIUMTEXT NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'DRAFT',  -- DRAFT|ACTIVE|DEPRECATED
    created_by   BIGINT,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    activated_at TIMESTAMP NULL,
    deprecated_at TIMESTAMP NULL,
    UNIQUE KEY uq_prompt_uuid (uuid),
    UNIQUE KEY uq_prompt_name_ver (prompt_name, version),
    KEY idx_prompt_status (status),
    CONSTRAINT fk_prompt_user FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tool_schemas (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid         CHAR(36) NOT NULL,
    tool_name    VARCHAR(120) NOT NULL,
    version      VARCHAR(20) NOT NULL,
    schema_json  JSON NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_tool_uuid (uuid),
    UNIQUE KEY uq_tool_name_ver (tool_name, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS model_configurations (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid         CHAR(36) NOT NULL,
    task_type    VARCHAR(60) NOT NULL,       -- requirement_analysis|service_planning|test_generation|code_generation|evidence_narrative|explanation
    provider     VARCHAR(40) NOT NULL DEFAULT 'gemini',
    model_name   VARCHAR(80) NOT NULL,
    temperature  DECIMAL(3,2) NOT NULL DEFAULT 0.20,
    max_tokens   INT NOT NULL DEFAULT 2048,
    timeout_s    INT NOT NULL DEFAULT 60,
    is_active    TINYINT(1) NOT NULL DEFAULT 1,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_modelcfg_uuid (uuid),
    UNIQUE KEY uq_modelcfg_task (task_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET FOREIGN_KEY_CHECKS = 1;
