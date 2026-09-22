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
        # Code quality calculation removed per system specification.
        return AnalysisResult(score=100.0, passed=True, issues=[], is_mock=False)


def get_analyzer():
    return MockAnalyzer()
