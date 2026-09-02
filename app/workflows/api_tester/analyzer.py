import json
import uuid

class LlmTestAnalyzer:
    """
    Simulates sending extracted APIs and test results to an LLM to generate
    test cases and produce the final JSON structure for the TDD Intelligence Dashboard.
    """

    def analyze_apis(self, apis):
        """
        Takes extracted APIs and asks the LLM to generate test plans/cases.
        For now, this is a mock implementation that builds the structure.
        """
        # In a real system, we'd send a prompt to the LLM client here.
        # client.generate(prompt=f"Analyze these APIs: {apis}")
        
        test_cases = []
        for idx, api in enumerate(apis):
            test_cases.append({
                "id": str(uuid.uuid4()),
                "test_key": f"TC-HI101-{idx+1:03d}",
                "request_spec": {
                    "method": api["method"],
                    "endpoint": api["url"]
                },
                "expected_response_spec": {
                    "status_code": 200,
                    "assertions": [
                        "Response should return 200 OK",
                        "Content-Type should be application/json"
                    ]
                }
            })
        return test_cases

    def generate_report(self, run_results, acceptance_criteria):
        """
        Takes the raw runner execution results and formats them into
        the JSON structure expected by the frontend TDD Dashboard.
        """
        
        # We assume run_results is an ApiRunResult object as returned by ApiRunner
        executions = run_results.results if hasattr(run_results, 'results') else []
        
        # Build the Acceptance Criteria Coverage Matrix
        ac_matrix = []
        for idx, ac in enumerate(acceptance_criteria):
            # For demonstration, randomly associate some test cases
            mapped_tc = None
            covered = False
            
            if executions and idx < len(executions):
                mapped_tc = executions[idx].get("test_key", f"TC-HI101-00{idx+1}")
                covered = executions[idx].get("passed", False)
                
            ac_matrix.append({
                "ac_key": ac.get("key", f"AC-{idx+1:02d}"),
                "requirement": ac.get("requirement", "Requirement description"),
                "covered": covered,
                "mapped_test_cases": mapped_tc
            })
            
        covered_count = sum(1 for item in ac_matrix if item["covered"])
        total_ac = len(ac_matrix)
        
        report = {
            "dashboard_data": {
                "summary": {
                    "total_tests": len(executions),
                    "ac_coverage": f"{covered_count}/{total_ac}",
                    "ac_coverage_percent": round((covered_count / total_ac * 100) if total_ac else 0, 1),
                    "contract_gaps": 2 # Simulated
                },
                "acceptance_criteria_matrix": ac_matrix,
                "generated_tests": executions
            }
        }
        
        return json.dumps(report, indent=2)
