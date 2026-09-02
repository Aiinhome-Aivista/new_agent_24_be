import json
import os
import re

class ApiExtractor:
    """
    Extracts API endpoints from code or collections.
    """
    
    def parse_collection(self, file_path):
        """
        Parses a Postman or Bruno collection JSON file and returns a list of API endpoints.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Collection file not found: {file_path}")
            
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        endpoints = []
        
        def _extract_items(items):
            for item in items:
                if "item" in item:
                    _extract_items(item["item"])
                elif "request" in item:
                    req = item["request"]
                    
                    method = req.get("method", "GET")
                    url = req.get("url", "")
                    
                    # Postman URL can be a dict or string
                    url_str = url.get("raw", "") if isinstance(url, dict) else str(url)
                    
                    endpoints.append({
                        "name": item.get("name", "Unnamed Request"),
                        "method": method,
                        "url": url_str,
                        "body": req.get("body", {}).get("raw", ""),
                        "headers": req.get("header", [])
                    })
                    
        if "item" in data:
            _extract_items(data["item"])
            
        return endpoints

    def extract_from_code(self, source_path):
        """
        Statically parses a source file to find simple API definitions (e.g. FastAPI / Flask style decorators)
        """
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source file not found: {source_path}")
            
        endpoints = []
        with open(source_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Very basic regex to catch Python route decorators like @app.get("/users") or @router.post("/items")
        pattern = re.compile(r'@\w+\.(get|post|put|delete|patch)\([\'"]([^\'"]+)[\'"]')
        
        matches = pattern.finditer(content)
        for match in matches:
            method = match.group(1).upper()
            route = match.group(2)
            endpoints.append({
                "name": f"{method} {route}",
                "method": method,
                "url": route,
                "body": "",
                "headers": []
            })
            
        return endpoints
