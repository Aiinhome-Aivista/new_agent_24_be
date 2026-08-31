"""Unit tests for Stage 5 Dynamic Codebase Grounding and Test Code Generation."""
import pytest
import os
import shutil
from pathlib import Path
from app.tools.repository.workspace import GitWorkspace
from app.agents.code_generator.agent import CodeGeneratorAgent


@pytest.fixture
def mock_java_repo(tmp_path):
    """Creates a temporary Java Spring Boot repository layout for testing."""
    repo_dir = tmp_path / "mock_java_project"
    app_dir = repo_dir / "src" / "main" / "java" / "com" / "poc" / "crud"
    service_dir = app_dir / "service"
    controller_dir = app_dir / "controller"
    
    service_dir.mkdir(parents=True, exist_ok=True)
    controller_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Spring Boot Application
    app_file = app_dir / "CrudPocApplication.java"
    app_file.write_text("package com.poc.crud;\n\npublic class CrudPocApplication {}\n", encoding="utf-8")
    
    # 2. AuthController
    ctrl_file = controller_dir / "AuthController.java"
    ctrl_file.write_text("package com.poc.crud.controller;\n\npublic class AuthController {}\n", encoding="utf-8")
    
    # 3. AuthService
    srv_file = service_dir / "AuthService.java"
    srv_file.write_text("package com.poc.crud.service;\n\npublic class AuthService {}\n", encoding="utf-8")
    
    # Initialize fake git directory so ws.exists is True
    git_dir = repo_dir / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    
    return repo_dir


def test_find_root_package_java(mock_java_repo):
    ws = GitWorkspace("test-uuid", "http://github.com/fake/repo.git")
    ws.workspace_path = mock_java_repo
    
    root_pkg = ws.find_root_package(lang="java")
    assert root_pkg == "com.poc.crud"


def test_resolve_imports_for_functions(mock_java_repo):
    ws = GitWorkspace("test-uuid", "http://github.com/fake/repo.git")
    ws.workspace_path = mock_java_repo
    
    resp_funcs = ["AuthController.changePassword", "AuthService.changePassword", "UnknownClass.method"]
    imports = ws.resolve_imports_for_functions(resp_funcs, lang="java")
    
    assert "import com.poc.crud.controller.AuthController;" in imports
    assert "import com.poc.crud.service.AuthService;" in imports
    assert len(imports) == 2


def test_assemble_test_file_dynamic_package_and_imports():
    agent = CodeGeneratorAgent()
    snippets = [
        ("TC-001", "Valid test", ["AuthController.changePassword"], "    @Test\n    void testValid() {}")
    ]
    custom_imports = [
        "import com.poc.crud.controller.AuthController;",
        "import com.poc.crud.service.AuthService;"
    ]
    
    code = agent._assemble_test_file(
        class_name="AuthControllerTest",
        test_code_snippets=snippets,
        lang="java",
        framework="junit5",
        package_name="com.poc.crud.controller",
        custom_imports=custom_imports
    )
    
    assert "package com.poc.crud.controller;" in code
    assert "import com.poc.crud.controller.AuthController;" in code
    assert "import com.poc.crud.service.AuthService;" in code
    assert "public class AuthControllerTest {" in code
    assert "void testValid() {}" in code


def test_write_test_files_creates_matching_package_directory(tmp_path, mock_java_repo):
    agent = CodeGeneratorAgent()
    snippets = [
        ("TC-001", "Valid test", ["AuthController.changePassword"], "    @Test\n    void testValid() {}")
    ]
    custom_imports = [
        "import com.poc.crud.controller.AuthController;"
    ]
    
    files_info = agent._write_test_files(
        workflow_id="wf-test-dyn",
        project={"name": "CrudPOC"},
        story={"title": "ChangePassword"},
        test_code_snippets=snippets,
        lang="java",
        framework="junit5",
        workspace_path=str(mock_java_repo),
        log_entries=[],
        package_name="com.poc.crud",
        custom_imports=custom_imports
    )
    
    assert len(files_info) == 2 # 1 in evidence_output, 1 in workspace
    ws_file = Path(mock_java_repo) / "src" / "test" / "java" / "com" / "poc" / "crud" / "ChangePasswordTest.java"
    assert ws_file.exists()
    
    content = ws_file.read_text(encoding="utf-8")
    assert "package com.poc.crud;" in content
    assert "import com.poc.crud.controller.AuthController;" in content


def test_zero_codebase_fallback():
    ws = GitWorkspace("nonexistent-uuid", "")
    root_pkg = ws.find_root_package(lang="java")
    assert root_pkg == "com.app.tests"
    
    agent = CodeGeneratorAgent()
    code = agent._assemble_test_file(
        class_name="AppTest",
        test_code_snippets=[("TC-001", "Test", [], "void test() {}")],
        lang="java",
        framework="junit5",
        package_name=root_pkg,
        custom_imports=[]
    )
    assert "package com.app.tests;" in code
