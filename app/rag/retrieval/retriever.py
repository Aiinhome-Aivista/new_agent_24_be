import json
from app.config import Config
from app.guardrails.engine import check_retrieval
from app.extensions.db import query as db_query


class RetrievedChunk:
    def __init__(self, content, source, metadata):
        self.content = content
        self.source = source
        self.metadata = metadata


class DatabaseRetriever:
    """Project-isolated retrieval from MySQL knowledge_chunks table."""
    is_mock = False

    def retrieve(self, project_id, query, top_k=8, workflow_id=None):
        # Query chunks strictly belonging to project_id
        terms = [t for t in query.lower().split() if len(t) > 3][:4]
        if not terms:
            rows = db_query("""
                SELECT c.content, d.title AS source, c.metadata, c.project_id
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id=c.document_id
                WHERE c.project_id=%s
                LIMIT %s
            """, (project_id, top_k))
        else:
            like_clause = " OR ".join(["c.content LIKE %s" for _ in terms])
            params = [project_id] + [f"%{t}%" for t in terms] + [top_k]
            rows = db_query(f"""
                SELECT c.content, d.title AS source, c.metadata, c.project_id
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id=c.document_id
                WHERE c.project_id=%s AND ({like_clause})
                LIMIT %s
            """, tuple(params))

        chunks = []
        for r in rows:
            meta = r.get("metadata")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            ok, _ = check_retrieval(r.get("project_id"), project_id, workflow_id)
            if ok:
                chunks.append(RetrievedChunk(r["content"], r["source"], meta or {}))
        return chunks


class ChromaRetriever:
    is_mock = False

    def __init__(self):
        # pyrefly: ignore [missing-import]
        import chromadb  # type: ignore[import-untyped, import-not-found]
        # pyrefly: ignore [missing-import]
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped, import-not-found]
        self._client = chromadb.PersistentClient(path=Config.CHROMA_PATH)
        self._embedder = SentenceTransformer(Config.EMBEDDING_MODEL)

    def retrieve(self, project_id, query, top_k=8, workflow_id=None):
        try:
            collection = self._client.get_or_create_collection(f"project_{project_id}")
            emb = self._embedder.encode([query]).tolist()
            res = collection.query(query_embeddings=emb, n_results=top_k)
            chunks = []
            for doc, meta in zip(res.get("documents", [[]])[0], res.get("metadatas", [[]])[0]):
                ok, _ = check_retrieval(int(meta.get("project_id", project_id)), project_id, workflow_id)
                if ok:
                    chunks.append(RetrievedChunk(doc, meta.get("file_name") or meta.get("source"), meta))
            return chunks
        except Exception:
            # Fallback to DatabaseRetriever if Chroma query fails
            return DatabaseRetriever().retrieve(project_id, query, top_k, workflow_id)


def get_retriever():
    if Config.VECTOR_STORE == "chromadb":
        try:
            return ChromaRetriever()
        except Exception:
            return DatabaseRetriever()
    return DatabaseRetriever()

