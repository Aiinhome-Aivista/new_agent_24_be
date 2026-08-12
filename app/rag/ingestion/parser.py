"""
Document parser for RAG ingestion.
Extracts clean text and metadata from TXT, MD, JSON, YAML, CSV, Postman, Bruno, and PDF files.
"""
import json
import os
from pathlib import Path


def parse_document(file_name: str, content_bytes: bytes, doc_type: str = "general") -> tuple[str, dict]:
    """
    Parses document bytes based on file extension and returns (text_content, metadata).
    """
    ext = Path(file_name).suffix.lower()
    meta = {
        "file_name": file_name,
        "doc_type": doc_type,
        "extension": ext,
        "size_bytes": len(content_bytes),
    }

    try:
        if ext in (".txt", ".md", ".markdown"):
            text = content_bytes.decode("utf-8", errors="replace")
            return text, meta

        elif ext in (".json", ".json5"):
            raw_text = content_bytes.decode("utf-8", errors="replace")
            try:
                data = json.loads(raw_text)
                # If it's a Postman Collection
                if "info" in data and ("_postman_id" in data["info"] or "schema" in data["info"]):
                    return _parse_postman_collection(data), {**meta, "doc_type": "postman_collection"}
                # If it's an OpenAPI / Swagger spec
                if "openapi" in data or "swagger" in data:
                    return _parse_openapi_spec(data), {**meta, "doc_type": "api_contract"}
                # Generic JSON: pretty print for clear chunking
                return json.dumps(data, indent=2), meta
            except Exception:
                return raw_text, meta

        elif ext in (".yaml", ".yml"):
            raw_text = content_bytes.decode("utf-8", errors="replace")
            return raw_text, meta

        elif ext in (".csv", ".tsv"):
            raw_text = content_bytes.decode("utf-8", errors="replace")
            return raw_text, meta

        elif ext == ".pdf":
            try:
                import pypdf
                import io
                reader = pypdf.PdfReader(io.BytesIO(content_bytes))
                text_pages = [page.extract_text() or "" for page in reader.pages]
                return "\n\n".join(text_pages), {**meta, "page_count": len(reader.pages)}
            except Exception:
                # Fallback if pypdf is not installed
                return f"[PDF Document: {file_name} ({len(content_bytes)} bytes)]", meta

        elif ext == ".docx":
            try:
                import docx
                import io
                doc = docx.Document(io.BytesIO(content_bytes))
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                return "\n\n".join(paragraphs), meta
            except Exception:
                return f"[DOCX Document: {file_name} ({len(content_bytes)} bytes)]", meta

        else:
            # Fallback text decoding
            text = content_bytes.decode("utf-8", errors="replace")
            return text, meta

    except Exception as e:
        return f"[Error parsing {file_name}: {str(e)}]", {**meta, "error": str(e)}


def _parse_postman_collection(data: dict) -> str:
    """Extracts human-readable endpoints and request/response specifications from Postman collection."""
    lines = [f"# Postman Collection: {data.get('info', {}).get('name', 'API Collection')}\n"]
    if data.get("info", {}).get("description"):
        lines.append(f"Description: {data['info']['description']}\n")

    def walk_items(items, prefix=""):
        for it in items:
            name = it.get("name", "Item")
            if "item" in it:
                walk_items(it["item"], prefix=f"{prefix}{name} > ")
            elif "request" in it:
                req = it["request"]
                method = req.get("method", "GET")
                url = req.get("url", {})
                raw_url = url.get("raw") if isinstance(url, dict) else str(url)
                lines.append(f"### Endpoint: {method} {raw_url}")
                lines.append(f"Name: {prefix}{name}")
                if req.get("description"):
                    lines.append(f"Description: {req['description']}")
                body = req.get("body", {})
                if body.get("raw"):
                    lines.append(f"Request Body:\n```json\n{body['raw']}\n```")
                lines.append("")

    if "item" in data:
        walk_items(data["item"])
    return "\n".join(lines)


def _parse_openapi_spec(data: dict) -> str:
    """Extracts human-readable API specs from OpenAPI / Swagger JSON."""
    lines = [f"# API Contract: {data.get('info', {}).get('title', 'API Spec')}\n"]
    paths = data.get("paths", {})
    for path, methods in paths.items():
        if isinstance(methods, dict):
            for method, details in methods.items():
                if method.lower() in ("get", "post", "put", "delete", "patch"):
                    lines.append(f"### {method.upper()} {path}")
                    if isinstance(details, dict):
                        if details.get("summary"):
                            lines.append(f"Summary: {details['summary']}")
                        if details.get("description"):
                            lines.append(f"Description: {details['description']}")
                    lines.append("")
    return "\n".join(lines)
