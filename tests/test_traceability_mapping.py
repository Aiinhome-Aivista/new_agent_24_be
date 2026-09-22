"""
Unit tests for TraceabilityMapper (AC -> API -> Code Traceability Engine).
Validates that:
1. All Acceptance Criteria are preserved without elimination (Section 2 of prompt.md)
2. ACs map to endpoints, call chains, and responsible source files
3. Statuses (SUPPORTED, PARTIALLY_SUPPORTED, NOT_IMPLEMENTED) are correctly assigned
"""
import pytest
from app.tools.traceability.mapper import TraceabilityMapper


def test_mapper_preserves_all_acs_without_elimination():
    """Validates that EVERY AC is preserved in the mapping and none is deleted."""
    mapper = TraceabilityMapper()
    acs = [
        {"ac_key": "AC-01", "text": "Valid user login returns HTTP 200 and JWT token."},
        {"ac_key": "AC-02", "text": "Duplicate email registration must be rejected with HTTP 409."},
        {"ac_key": "AC-03", "text": "Support ticket creation via POST /api/tickets returns HTTP 201."},
        {"ac_key": "AC-04", "text": "Feature X not present anywhere in the codebase."},
    ]

    extracted_apis = [
        {"method": "POST", "path": "/api/login", "service": "AuthService"},
        {"method": "POST", "path": "/api/tickets", "service": "TicketService"},
    ]

    records = mapper.map(acs=acs, extracted_apis=extracted_apis)

    assert len(records) == 4
    ac_keys = [r["ac_key"] for r in records]
    assert ac_keys == ["AC-01", "AC-02", "AC-03", "AC-04"]

    # AC-04 must NOT be eliminated, but flagged as NOT_IMPLEMENTED
    ac_04 = next(r for r in records if r["ac_key"] == "AC-04")
    assert ac_04["implementation_status"] == "NOT_IMPLEMENTED"
    assert len(ac_04["mapped_apis"]) == 0


def test_mapper_explicit_endpoint_and_codebase_context():
    """Validates call-chain discovery when codebase context snippets are provided."""
    mapper = TraceabilityMapper()
    acs = [
        "AC-01: Create support ticket via POST /api/tickets should return 201 Created",
    ]
    extracted_apis = [
        {"method": "POST", "path": "/api/tickets", "service": "TicketService"},
    ]
    codebase_context = """
    --- routes/ticket_controller.py ---
    @app.route('/api/tickets', methods=['POST'])
    def create_ticket():
        return ticket_service.create()

    --- services/ticket_service.py ---
    class TicketService:
        def create(self):
            return ticket_repo.save()

    --- repositories/ticket_repository.py ---
    class TicketRepository:
        def save(self):
            pass
    """

    records = mapper.map(
        acs=acs,
        extracted_apis=extracted_apis,
        codebase_context=codebase_context,
    )

    assert len(records) == 1
    rec = records[0]
    assert rec["ac_key"] == "AC-01"
    assert len(rec["mapped_apis"]) >= 1
    assert rec["mapped_apis"][0]["path"] == "/api/tickets"

    # Verify call chain was detected
    layers = [n["layer"] for n in rec["mapped_code"]]
    assert "controller" in layers
    assert "service" in layers
    assert "repository" in layers

    # Responsible files for scoped coverage
    assert len(rec["responsible_files"]) >= 2
    assert any("ticket_controller.py" in f for f in rec["responsible_files"])


def test_mapper_identifies_partially_supported_error_conditions():
    """Validation or negative requirements on existing endpoints get PARTIALLY_SUPPORTED."""
    mapper = TraceabilityMapper()
    acs = [
        {"ac_key": "AC-02", "text": "POST /api/tickets with duplicate email must fail and return HTTP 400 with error message."},
    ]
    extracted_apis = [
        {"method": "POST", "path": "/api/tickets", "service": "TicketService"},
    ]

    records = mapper.map(acs=acs, extracted_apis=extracted_apis)
    assert len(records) == 1
    rec = records[0]
    assert rec["implementation_status"] == "PARTIALLY_SUPPORTED"
    assert "error condition" in rec["implementation_notes"].lower() or "validation" in rec["implementation_notes"].lower()
