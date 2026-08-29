"""
Knowledge Indexer & Vector Ingestion Service.
Handles document ingestion, relational persistence (knowledge_documents, knowledge_chunks),
and project-scoped vector indexing.
"""
import uuid
import json
from pathlib import Path
from app.extensions.db import execute, query
from app.rag.ingestion.parser import parse_document
from app.rag.chunking.chunker import chunk_text
from app.config import Config


def ingest_document(
    project_id: int,
    file_name: str,
    content_bytes: bytes,
    doc_type: str = "general",
    version: str = "v1",
    uploaded_by: int = None
) -> dict:
    """
    Ingests a document into the project's knowledge base.
    1. Parses document.
    2. Inserts record into knowledge_documents.
    3. Chunks text and inserts rows into knowledge_chunks.
    4. Indexes into ChromaDB project collection if enabled.
    """
    text, meta = parse_document(file_name, content_bytes, doc_type)
    doc_uuid = str(uuid.uuid4())

    # 1. Insert into knowledge_documents
    doc_id = execute("""
        INSERT INTO knowledge_documents
        (uuid, project_id, title, doc_type, source, version, index_status, freshness_at, chunk_count, uploaded_by)
        VALUES (%s, %s, %s, %s, %s, %s, 'indexed', NOW(), 0, %s)
    """, (doc_uuid, project_id, file_name, doc_type, file_name, version, uploaded_by), return_id=True)

    # 2. Chunk text
    base_meta = {
        "project_id": project_id,
        "doc_id": doc_id,
        "doc_uuid": doc_uuid,
        "doc_type": doc_type,
        "file_name": file_name,
        "version": version
    }
    chunk_sz = int(getattr(Config, "CHUNK_SIZE", 1000) or 1000)
    chunk_ovlp = int(getattr(Config, "CHUNK_OVERLAP", 200) or 200)
    chunks = chunk_text(text, chunk_size=chunk_sz, overlap=chunk_ovlp, base_metadata=base_meta)

    # 3. Store chunks in relational database
    vector_ids = []
    documents_for_vector = []
    metadatas_for_vector = []

    for c in chunks:
        chunk_uuid = str(uuid.uuid4())
        vector_ref = f"{doc_uuid}_{c['chunk_index']}"
        execute("""
            INSERT INTO knowledge_chunks
            (uuid, document_id, project_id, chunk_index, content, metadata, vector_ref)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (chunk_uuid, doc_id, project_id, c["chunk_index"], c["content"], json.dumps(c["metadata"], default=str), vector_ref))

        vector_ids.append(vector_ref)
        documents_for_vector.append(c["content"])
        metadatas_for_vector.append(c["metadata"])

    # Update chunk count
    execute("UPDATE knowledge_documents SET chunk_count=%s WHERE id=%s", (len(chunks), doc_id))

    # 4. Optional Vector Store Indexing (ChromaDB)
    if Config.VECTOR_STORE == "chromadb" and chunks:
        try:
            # pyrefly: ignore [missing-import]
            import chromadb  # type: ignore[import-untyped, import-not-found]
            # pyrefly: ignore [missing-import]
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped, import-not-found]
            client = chromadb.PersistentClient(path=Config.CHROMA_PATH)
            embedder = SentenceTransformer(Config.EMBEDDING_MODEL)
            collection = client.get_or_create_collection(f"project_{project_id}")
            embeddings = embedder.encode(documents_for_vector).tolist()
            collection.add(
                ids=vector_ids,
                documents=documents_for_vector,
                embeddings=embeddings,
                metadatas=[{k: str(v) for k, v in m.items()} for m in metadatas_for_vector]
            )
        except Exception as e:
            print(f"[Indexer] Vector store indexing error: {e}")

    return {
        "document_id": doc_id,
        "uuid": doc_uuid,
        "title": file_name,
        "doc_type": doc_type,
        "chunk_count": len(chunks),
        "status": "indexed"
    }


def delete_document(doc_uuid: str) -> bool:
    """Deletes a knowledge document and its chunks."""
    doc = query("SELECT id, project_id FROM knowledge_documents WHERE uuid=%s", (doc_uuid,), fetchone=True)
    if not doc:
        return False

    execute("DELETE FROM knowledge_chunks WHERE document_id=%s", (doc["id"],))
    execute("DELETE FROM knowledge_documents WHERE id=%s", (doc["id"],))

    if Config.VECTOR_STORE == "chromadb":
        try:
            # pyrefly: ignore [missing-import]
            import chromadb  # type: ignore[import-untyped, import-not-found]
            client = chromadb.PersistentClient(path=Config.CHROMA_PATH)
            collection = client.get_or_create_collection(f"project_{doc['project_id']}")
            # Delete where doc_uuid matches
            collection.delete(where={"doc_uuid": doc_uuid})
        except Exception:
            pass

    return True
