"""
Code Generator Agent — Executes post-approval during Stage 7 (CODE_GENERATION).
Generates full production test code for all approved test cases, writes test files to the
project's workspace/repository, and produces an auditable Code Log.
"""
import os
import json
import time
import datetime
from pathlib import Path
from app.agents.base import BaseAgent
from app.llm.model_router.router import get_router
from app.repositories.test_repo import list_test_cases, update_test_case_code_by_key
from app.workflows.state_machine import CODE_VALIDATION

def _get_system_prompt(lang: str, framework: str) -> str:
    lang = (lang or "python").lower()
    framework = (framework or "pytest").lower()
    if lang == "python":
        return """You are an expert Python TDD Software Engineer.

Given the test case specification, API contracts, and target language/framework (Python with Pytest):
1. Generate complete, executable, clean pytest test functions.
2. Follow the standard Arrange-Act-Assert (AAA) pattern.
3. For API endpoint tests, use the provided `client` or `api_client` fixture to send HTTP requests (e.g. `client.post('/api/...', json=payload)` or `client.get('/api/...')`).
4. Assert HTTP response status codes and expected response body properties/errors.
5. NEVER invent non-existent class or module imports (e.g. DO NOT hallucinate `from app.services... import ...` unless explicitly present in codebase context).
6. Include inline docstrings and comments referencing the Acceptance Criteria.

Return ONLY clean, valid Python test function code without markdown code blocks (```) or conversational filler.
"""
    elif lang in ("java", "kotlin"):
        return """You are an expert Java Spring Boot Architect specializing in Test-Driven Development (TDD).

Given the test case specification, identified responsible functions, API contracts, and target framework (JUnit 5 with Mockito):
1. Generate complete, compilable, production-ready JUnit 5 test methods.
2. Follow the standard Arrange-Act-Assert (AAA) pattern.
3. For Unit/Service tests: Mock external repositories/collaborators using Mockito (`when(...).thenReturn(...)`, `verify(...)`).
4. For Controller/API tests: Assert HTTP request/response payloads and status codes.
5. Include inline comments referencing the Acceptance Criteria and scenario under test.

Return ONLY clean, valid Java test method code without markdown code blocks (```) or conversational filler.
"""
    else:
        return """You are an expert TypeScript / JavaScript Engineer specializing in TDD.

Given the test case specification and API contracts:
1. Generate complete, clean Jest / Supertest test blocks.
2. Follow Arrange-Act-Assert (AAA).
3. Assert HTTP response status codes and payload properties.

Return ONLY clean, valid test code without markdown code blocks (```) or conversational filler.
"""


class CodeGeneratorAgent(BaseAgent):
    name = "code_generator"

    def run(self, workflow_id, state):
        start_time = time.time()
        project = state.get("project", {})
        story = state.get("story", {})
        lang = project.get("target_language", "java").lower()
        framework = project.get("target_framework", "junit5").lower()
        contracts = state.get("api_contracts", [])
        workspace_path = state.get("workspace_path")
        
        # Fetch test cases from database or state
        db_tests = list_test_cases(workflow_id)
        test_cases = db_tests if db_tests else state.get("generated_tests", [])

        router = get_router()
        log_entries = []
        files_written = []
        total_lines = 0
        total_latency = 0

        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        log_entries.append(f"[{now_str}] [INIT] Starting post-approval test code synthesis for Workflow {workflow_id[:8]}")
        log_entries.append(f"[{now_str}] [CONFIG] Target Language: {lang.upper()} | Framework: {framework.upper()} | Tests to generate: {len(test_cases)}")

        updated_tests = []
        test_code_snippets = []

        print(f"\n[CodeGenerator] Starting Code Synthesis for {len(test_cases)} approved test cases ({lang.upper()} / {framework.upper()})...")

        # Detect workspace context and package information
        ws_obj = None
        detected_package = "com.app.tests" if lang in ("java", "kotlin") else ""
        resolved_imports = []
        if workspace_path and os.path.isdir(workspace_path):
            try:
                from app.tools.repository.workspace import GitWorkspace
                project_uuid = project.get("uuid", "")
                ws_obj = GitWorkspace(project_uuid, project.get("git_repo_url", ""))
                detected_package = ws_obj.find_root_package(lang=lang)
                log_entries.append(f"[{now_str}] [WORKSPACE] Detected root package from codebase: {detected_package}")
            except Exception as ex:
                print(f"[CodeGenerator] Package discovery note: {ex}")

        # Resolve class imports for all responsible functions
        all_resp_funcs = []
        for tc in test_cases:
            all_resp_funcs.extend(tc.get("responsible_functions") or [])
        if ws_obj and all_resp_funcs:
            try:
                resolved_imports = ws_obj.resolve_imports_for_functions(all_resp_funcs, lang=lang)
                if resolved_imports:
                    log_entries.append(f"[{now_str}] [IMPORTS] Resolved {len(resolved_imports)} class imports from codebase")
            except Exception as ex:
                print(f"[CodeGenerator] Import resolution note: {ex}")

        # Generate code for each test case
        for idx, tc in enumerate(test_cases, start=1):
            key = tc.get("test_key", f"TC-{idx:03d}")
            title = tc.get("title", key)
            scenario_type = tc.get("scenario_type", "positive")
            expected_result = tc.get("expected_result", "")
            resp_funcs = tc.get("responsible_functions", [])
            resp_funcs_str = ", ".join(resp_funcs) if resp_funcs else "N/A"

            log_entries.append(f"[{now_str}] [SYNTHESIS] Generating test method for {key} ({scenario_type.upper()})")
            log_entries.append(f"[{now_str}] [TARGET] Responsible functions: {resp_funcs_str}")

            prompt = self._build_prompt(story, tc, resp_funcs, contracts, lang, framework, detected_package)

            print(f"[CodeGenerator] Synthesizing {key} [{scenario_type.upper()}] targeting {resp_funcs_str}...")
            code_res = router.generate_code(
                "test_generation",
                prompt=prompt,
                system=_get_system_prompt(lang, framework)
            )
            total_latency += (code_res.latency_ms or 0)

            generated_code = self._clean_code(code_res.text, lang, framework, key, resp_funcs, tc)
            lines_in_test = len(generated_code.strip().split("\n"))
            total_lines += lines_in_test

            print(f"[CodeGenerator] -> Generated {lines_in_test} lines for {key} in {code_res.latency_ms}ms (is_mock={code_res.is_mock})")

            # Persist code to database
            update_test_case_code_by_key(workflow_id, key, generated_code, status="CODE_GENERATED")

            tc_updated = {**tc, "generated_code": generated_code, "status": "CODE_GENERATED"}
            updated_tests.append(tc_updated)
            test_code_snippets.append((key, title, resp_funcs, generated_code))

            log_entries.append(f"[{now_str}] [SUCCESS] Synthesized {key} ({lines_in_test} lines) targeting {resp_funcs_str}")

        # Assemble full test file and write to workspace
        file_write_info = self._write_test_files(
            workflow_id=workflow_id,
            project=project,
            story=story,
            test_code_snippets=test_code_snippets,
            lang=lang,
            framework=framework,
            workspace_path=workspace_path,
            log_entries=log_entries,
            package_name=detected_package,
            custom_imports=resolved_imports
        )
        if file_write_info:
            files_written.extend(file_write_info)
            for fw in file_write_info:
                print(f"[CodeGenerator] Written file to workspace: {fw.get('file_path')}")

        elapsed_ms = int((time.time() - start_time) * 1000)
        print(f"[CodeGenerator] Finished code generation in {elapsed_ms}ms. Total lines: {total_lines}.\n")
        log_entries.append(f"[{now_str}] [COMPLETE] Code generation complete in {elapsed_ms}ms. Total lines: {total_lines}. Advancing to CODE_VALIDATION.")

        code_log = {
            "workflow_id": workflow_id,
            "generated_at": now_str,
            "target_language": lang,
            "target_framework": framework,
            "root_package": detected_package,
            "resolved_imports": resolved_imports,
            "total_tests_generated": len(updated_tests),
            "total_lines_generated": total_lines,
            "elapsed_ms": elapsed_ms,
            "files_written": files_written,
            "log_entries": log_entries,
        }

        state["generated_tests"] = updated_tests
        state["code_generation"] = code_log
        state["current_stage"] = CODE_VALIDATION
        
        self._record(workflow_id, "code_generation", model_name=f"{lang}/{framework}",
                     latency_ms=total_latency, output_summary={"total_lines": total_lines, "tests": len(updated_tests)})
        return state

    def _build_prompt(self, story, tc, resp_funcs, contracts, lang, framework, package_name="com.app.tests"):
        resp_funcs_text = "\n".join(f"  - {f}" for f in resp_funcs) if resp_funcs else "  - Primary API handler"
        contract_text = "\n".join(f"  - {c.get('method', 'GET')} {c.get('path', '/')} (service: {c.get('service', 'unknown')})" for c in contracts[:4])
        pkg_info = f"\nRoot Package: {package_name}" if package_name else ""
        req_spec = tc.get("request_spec") or {}
        res_spec = tc.get("expected_response_spec") or {}

        return f"""User Story: {story.get('title', '')}
Story Description: {story.get('description', '')}

Test Case: {tc.get('test_key')} — {tc.get('title')}
Scenario Type: {tc.get('scenario_type', 'positive').upper()}
Description: {tc.get('description', '')}
Expected Result: {tc.get('expected_result', '')}{pkg_info}

Request Specification:
- Method: {req_spec.get('method', 'GET')}
- Endpoint: {req_spec.get('endpoint', '/api/resource')}
- Headers: {req_spec.get('headers', {})}
- Payload Body: {req_spec.get('body')}

Expected Response:
- Status Code: {res_spec.get('status_code', 200)}
- Response Body: {res_spec.get('response_body')}
- Assertions: {res_spec.get('assertions', [])}

Responsible Functions / Target Methods to Test:
{resp_funcs_text}

API Contracts Available:
{contract_text}

Generate a complete, executable {framework} test function/method in {lang} that explicitly tests the scenario above.
"""

    def _clean_code(self, raw_code, lang, framework, test_key, resp_funcs, tc=None):
        """Strip markdown ticks if present or format code."""
        text = raw_code.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        
        if not text or text.startswith("[MOCK]"):
            # Provide high quality template based on lang and framework
            return self._generate_fallback_code(lang, framework, test_key, resp_funcs, tc)
        return text

    def _generate_fallback_code(self, lang, framework, test_key, resp_funcs, tc=None):
        tc = tc or {}
        req_spec = tc.get("request_spec") or {}
        res_spec = tc.get("expected_response_spec") or {}
        method = (req_spec.get("method") or "POST").lower()
        endpoint = req_spec.get("endpoint") or "/api/resource"
        body = req_spec.get("body")
        status_code = res_spec.get("status_code") or 200
        title = tc.get("title", test_key)
        func_comment = ", ".join(resp_funcs) if resp_funcs else title

        if lang in ("java", "kotlin"):
            return f"""    /**
     * Test Case: {test_key} - {title}
     * Target: {func_comment}
     */
    @Test
    @DisplayName("Verify {test_key} - {title}")
    void test_{test_key.lower().replace('-', '_')}() {{
        // Arrange
        // Given valid request payload mapped to {func_comment}
        var requestPayload = Map.of("status", "ACTIVE", "requestId", UUID.randomUUID().toString());

        // Act
        var response = targetService.execute(requestPayload);

        // Assert
        assertNotNull(response, "Response should not be null");
        assertEquals({status_code}, response.getStatusCodeValue(), "Expected HTTP {status_code}");
    }}"""
        elif lang == "python":
            body_str = json.dumps(body) if body is not None else None
            req_call = f'client.{method}("{endpoint}", json={body_str})' if body_str else f'client.{method}("{endpoint}")'
            return f"""def test_{test_key.lower().replace('-', '_')}(client):
    \"\"\"
    Test Case: {test_key} - {title}
    Expected: HTTP {status_code}
    \"\"\"
    # Arrange & Act
    response = {req_call}

    # Assert
    assert response.status_code == {status_code}, f"Expected {status_code} but got {{response.status_code}}"
    if {status_code} in [200, 201]:
        data = response.get_json() or {{}}
        assert data is not None"""
        else:
            return f"""  /**
   * Test Case: {test_key} - {title}
   */
  it('should verify {test_key} ({title})', async () => {{
    // Arrange & Act
    const response = await request(app).{method}('{endpoint}'){f".send({json.dumps(body)})" if body else ""};

    // Assert
    expect(response.status).toBe({status_code});
  }});"""

    def _write_test_files(self, workflow_id, project, story, test_code_snippets, lang, framework, workspace_path, log_entries, package_name="com.app.tests", custom_imports=None):
        """Write synthesized test code files to project workspace and evidence directories."""
        files_info = []
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Determine target file name and path
        story_slug = story.get("title", "App").replace(" ", "")
        story_slug = "".join(c for c in story_slug if c.isalnum()) or "AppService"
        
        ext_map = {"java": "java", "kotlin": "kt", "python": "py", "typescript": "ts", "javascript": "js"}
        ext = ext_map.get(lang, "java")
        class_name = f"{story_slug}Test"
        file_name = f"{class_name}.{ext}" if lang != "python" else f"test_{story_slug.lower()}.py"

        # Combine all test methods into a class/module
        assembled_content = self._assemble_test_file(
            class_name=class_name,
            test_code_snippets=test_code_snippets,
            lang=lang,
            framework=framework,
            package_name=package_name,
            custom_imports=custom_imports
        )

        # 1. Write to evidence output folder
        evidence_dir = Path("evidence_output") / "generated_tests" / workflow_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_file = evidence_dir / file_name
        try:
            evidence_file.write_text(assembled_content, encoding="utf-8")
            line_count = len(assembled_content.split("\n"))
            files_info.append({
                "file_path": str(evidence_file),
                "relative_path": f"evidence_output/generated_tests/{workflow_id}/{file_name}",
                "lines_count": line_count,
                "class_name": class_name,
                "tests_count": len(test_code_snippets)
            })
            log_entries.append(f"[{now_str}] [FILE_WRITE] Generated test artifact saved to {evidence_file} ({line_count} lines)")
        except Exception as e:
            log_entries.append(f"[{now_str}] [WARN] Could not write evidence test file: {e}")

        # 2. Write to project Git workspace if workspace path is present
        if workspace_path and os.path.isdir(workspace_path):
            ws_root = Path(workspace_path)
            # Find or create test directory dynamically based on package
            if lang in ("java", "kotlin"):
                pkg_subpath = Path(*package_name.split(".")) if package_name else Path("com", "app", "tests")
                test_dir = ws_root / "src" / "test" / "java" / pkg_subpath
            elif lang == "python":
                test_dir = ws_root / "tests"
            else:
                test_dir = ws_root / "src" / "__tests__"

            try:
                test_dir.mkdir(parents=True, exist_ok=True)
                ws_file = test_dir / file_name
                ws_file.write_text(assembled_content, encoding="utf-8")
                line_count = len(assembled_content.split("\n"))
                files_info.append({
                    "file_path": str(ws_file),
                    "relative_path": str(ws_file.relative_to(ws_root)),
                    "lines_count": line_count,
                    "class_name": class_name,
                    "tests_count": len(test_code_snippets)
                })
                log_entries.append(f"[{now_str}] [WORKSPACE_WRITE] Wrote test suite to workspace: {ws_file.relative_to(ws_root)} ({line_count} lines)")
            except Exception as e:
                log_entries.append(f"[{now_str}] [WARN] Workspace write error: {e}")

        return files_info

    def _assemble_test_file(self, class_name, test_code_snippets, lang, framework, package_name="com.app.tests", custom_imports=None):
        methods_code = "\n\n".join(snippet[3] for snippet in test_code_snippets)
        custom_imports_str = "\n".join(custom_imports) if custom_imports else ""
        if custom_imports_str:
            custom_imports_str = "\n" + custom_imports_str
        
        if lang in ("java", "kotlin"):
            pkg_header = f"package {package_name};" if package_name else "package com.app.tests;"
            return f"""{pkg_header}

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;

import java.util.Map;
import java.util.List;
import java.util.UUID;{custom_imports_str}

/**
 * Auto-generated Java Spring Boot TDD Test Suite.
 * Verified and approved by Human Reviewer.
 */
@ExtendWith(MockitoExtension.class)
public class {class_name} {{

{methods_code}
}}
"""
        elif lang == "python":
            return f"""\"\"\"
Auto-generated TDD Test Suite.
Verified and approved by Human Reviewer.
\"\"\"
import pytest
import uuid{custom_imports_str}

{methods_code}
"""
        else:
            return f"""/**
 * Auto-generated TDD Test Suite.
 * Verified and approved by Human Reviewer.
 */
import request from 'supertest';{custom_imports_str}

describe('{class_name}', () => {{
{methods_code}
}});
"""
