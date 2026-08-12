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


def get_analyzer():
    # Real analyzers registered here when configured; MOCK by default.
    return MockAnalyzer()
