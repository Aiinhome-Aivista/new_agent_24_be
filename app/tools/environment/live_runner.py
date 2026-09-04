import os
import subprocess
import threading
import time
import socket

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

class LiveEnvironmentManager:
    """
    Manages the lifecycle of a locally cloned git repository to expose it as a live server
    for API testing. Supports Node.js, Python, and Java (Spring Boot) projects based on heuristics.
    """
    def __init__(self, workspace_path, port=8080):
        self.workspace_path = workspace_path
        self.process = None
        self.port = port

    def detect_project_type(self):
        if os.path.exists(os.path.join(self.workspace_path, "package.json")):
            return "nodejs"
        elif os.path.exists(os.path.join(self.workspace_path, "requirements.txt")) or os.path.exists(os.path.join(self.workspace_path, "Pipfile")):
            return "python"
        elif os.path.exists(os.path.join(self.workspace_path, "pom.xml")) or os.path.exists(os.path.join(self.workspace_path, "build.gradle")):
            return "java"
        return "unknown"

    def start_server(self):
        if is_port_in_use(self.port):
            print(f"[LiveEnvironment] Port {self.port} is already in use. Assuming server is already running.")
            return True

        project_type = self.detect_project_type()
        print(f"[LiveEnvironment] Detected project type: {project_type}")
        
        command = []
        if project_type == "nodejs":
            command = ["npm", "start"]
        elif project_type == "python":
            if os.path.exists(os.path.join(self.workspace_path, "run.py")):
                command = ["python", "run.py"]
            elif os.path.exists(os.path.join(self.workspace_path, "main.py")):
                command = ["python", "main.py"]
                # Try to guess uvicorn if FastAPI
                with open(os.path.join(self.workspace_path, "main.py"), "r", encoding="utf-8") as f:
                    content = f.read()
                    if "FastAPI" in content and "uvicorn.run" not in content:
                        command = ["uvicorn", "main:app", "--port", str(self.port)]
            elif os.path.exists(os.path.join(self.workspace_path, "manage.py")):
                command = ["python", "manage.py", "runserver", str(self.port)]
            else:
                command = ["python", "app.py"]
        elif project_type == "java":
            if os.path.exists(os.path.join(self.workspace_path, "pom.xml")):
                command = ["mvn", "spring-boot:run"]
            else:
                command = ["./gradlew", "bootRun"]
        else:
            print("[LiveEnvironment] Unknown project type. Cannot start local server.")
            return False

        print(f"[LiveEnvironment] Starting server with command: {' '.join(command)}")
        # Start as background process
        try:
            self.process = subprocess.Popen(
                command, 
                cwd=self.workspace_path, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL,
                shell=True
            )
            # Give it time to boot up
            time.sleep(5)
            print("[LiveEnvironment] Server is assumed to be running.")
            return True
        except Exception as e:
            print(f"[LiveEnvironment] Failed to start server: {e}")
            return False

    def stop_server(self):
        if self.process:
            print("[LiveEnvironment] Stopping live server...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def get_base_url(self):
        return f"http://localhost:{self.port}"
