"""
Deterministic code quality analyzer. Static tools are authoritative; the LLM may only
explain findings. Real adapters (SonarQube/Checkstyle/PMD/SpotBugs) plug in here; a
labeled MOCK analyzer is used otherwise.
"""
import random
from app.config import Config


class AnalysisResult:
    def __init__(self, score, passed, issues, is_mock):
        self.score = score
        self.passed = passed
        self.issues = issues
        self.is_mock = is_mock


class MockAnalyzer:
    def analyze(self, code_units):
        rng = random.Random(len(code_units or []))
        issues = []
        if rng.random() > 0.6:
            issues.append({"severity": "minor", "rule": "UnusedImport",
                           "file": "GeneratedTest.java", "line": 3,
                           "description": "Unused import statement (MOCK finding).",
                           "remediation": "Remove the unused import."})
        score = 92.0 - 5 * len(issues)
        return AnalysisResult(score, score >= 80, issues, is_mock=True)


class SonarQubeAnalyzer:
    """Real SonarQube analyzer wrapper."""
    def analyze(self, code_units):
        import os, tempfile, subprocess, time, requests, json
        
        # SonarQube connection config
        sonar_url = os.getenv("SONARQUBE_URL", "http://localhost:9000")
        sonar_token = os.getenv("SONARQUBE_TOKEN", "")
        project_key = "agent24-generated-tests"
        
        issues = []
        score = 100.0
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # 1. Write code units to disk
            for i, code in enumerate(code_units or []):
                with open(os.path.join(temp_dir, f"TestSnippet{i}.java"), "w") as f:
                    f.write(code)
            
            # 2. Write sonar-project.properties
            props_path = os.path.join(temp_dir, "sonar-project.properties")
            with open(props_path, "w") as f:
                f.write(f"sonar.projectKey={project_key}\n")
                f.write("sonar.sources=.\n")
                f.write(f"sonar.host.url={sonar_url}\n")
                if sonar_token:
                    f.write(f"sonar.token={sonar_token}\n")

            # 3. Run sonar-scanner
            try:
                import shutil
                cmd = "sonar-scanner"
                which_sonar = shutil.which("sonar-scanner")
                fallback_sonar = r"C:\Program Files\sonar-scanner-cli-8.1.0.6389-windows-x64\sonar-scanner-8.1.0.6389-windows-x64\bin\sonar-scanner.bat"
                
                if which_sonar:
                    cmd = f'"{which_sonar}"'
                elif os.path.exists(fallback_sonar):
                    cmd = f'"{fallback_sonar}"'

                proc = subprocess.run(cmd, cwd=temp_dir, shell=True, capture_output=True, text=True, timeout=120)
                if proc.returncode != 0:
                    err_msg = proc.stderr if proc.stderr else proc.stdout
                    print("Sonar-scanner failed:", err_msg)
                    return AnalysisResult(0, False, [{"severity": "major", "rule": "ScannerError", "file": "Unknown", "line": 0, "description": f"sonar-scanner execution failed: {err_msg[:200]}", "remediation": "Check scanner logs"}], is_mock=False)
                
                # 4. Fetch results from SonarQube Web API (wait a bit for processing)
                time.sleep(5) 
                auth = (sonar_token, "") if sonar_token else None
                res = requests.get(f"{sonar_url}/api/issues/search?componentKeys={project_key}", auth=auth, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    for issue in data.get("issues", []):
                        issues.append({
                            "severity": issue.get("severity", "minor").lower(),
                            "rule": issue.get("rule", "Unknown"),
                            "file": issue.get("component", "Unknown").split(":")[-1],
                            "line": issue.get("line", 1),
                            "description": issue.get("message", ""),
                            "remediation": "Check SonarQube for remediation"
                        })
                    score = max(0, 100.0 - 5 * len(issues))
                else:
                    print("SonarQube API fetch failed:", res.status_code)
            except Exception as e:
                print("SonarQube error:", str(e))
                return AnalysisResult(0, False, [{"severity": "major", "rule": "ScannerError", "file": "Unknown", "line": 0, "description": str(e), "remediation": "Install sonar-scanner and start server"}], is_mock=False)
                
        return AnalysisResult(score, score >= 80, issues, is_mock=False)


def get_analyzer():
    # Real analyzers registered here when configured; MOCK by default.
    analyzer_type = Config.CODE_ANALYZER.lower()
    if analyzer_type == "sonarqube":
        return SonarQubeAnalyzer()
    return MockAnalyzer()
