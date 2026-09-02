import sys
import os

# Ensure paths are correct for local imports if needed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from app.tools.api_extractor.extractor import ApiExtractor
from app.workflows.api_tester.analyzer import LlmTestAnalyzer
from app.tools.api_runner.runner import get_runner

class ApiTesterWorkflow:
    def __init__(self):
        self.extractor = ApiExtractor()
        self.analyzer = LlmTestAnalyzer()
        
    def run_workflow(self, target_path, is_collection=False, acceptance_criteria=None):
        """
        Orchestrates the entire automated API testing flow.
        """
        print(f"Starting API Testing Workflow for: {target_path}")
        
        # 1. Extract APIs
        if is_collection:
            apis = self.extractor.parse_collection(target_path)
        else:
            apis = self.extractor.extract_from_code(target_path)
            
        print(f"Extracted {len(apis)} API endpoints.")
        
        # 2. LLM Analyzes and builds test cases
        test_cases = self.analyzer.analyze_apis(apis)
        print(f"LLM generated {len(test_cases)} test cases.")
        
        # 3. Execute using the runner
        runner = get_runner()
        # The runner.py has a MockApiRunner if not configured for newman
        # Our mock runner supports passing 'test_cases' directly.
        run_results = runner.run(collection_path=target_path, environment="local", test_cases=test_cases)
        print(f"Execution completed. (Mock={run_results.is_mock})")
        
        # 4. LLM analyzes results and formats the final JSON report for the UI
        ac = acceptance_criteria or [{"key": "AC-01", "requirement": "Ensure basic functionality works"}]
        report_json = self.analyzer.generate_report(run_results, ac)
        
        print("Generated Test Report successfully.")
        return report_json

# Example usage:
if __name__ == "__main__":
    workflow = ApiTesterWorkflow()
    # Let's create a dummy file to test
    dummy_code_path = "dummy_api.py"
    with open(dummy_code_path, "w") as f:
        f.write("@app.get('/health')\\n@app.post('/users')")
        
    report = workflow.run_workflow(dummy_code_path, is_collection=False)
    print("\n--- FINAL REPORT ---")
    print(report)
    
    os.remove(dummy_code_path)
