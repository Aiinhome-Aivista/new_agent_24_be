"""
Document chunker for RAG.
Segments text into sliding-window or paragraph-based chunks with overlap and rich metadata.
"""
from typing import List, Dict, Any


def chunk_text(
    text: str,
    chunk_size: int = 800,
    overlap: int = 150,
    base_metadata: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """
    Splits text into chunks of roughly `chunk_size` characters with `overlap`.
    Returns list of dicts with {"chunk_index": int, "content": str, "metadata": dict}.
    """
    if not text or not text.strip():
        return []

    base_metadata = base_metadata or {}
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = []
    current_length = 0
    chunk_idx = 0

    for para in paragraphs:
        para_clean = para.strip()
        if not para_clean:
            continue

        if current_length + len(para_clean) > chunk_size and current_chunk:
            chunk_str = "\n\n".join(current_chunk)
            chunks.append({
                "chunk_index": chunk_idx,
                "content": chunk_str,
                "metadata": {
                    **base_metadata,
                    "chunk_index": chunk_idx,
                    "char_count": len(chunk_str),
                }
            })
            chunk_idx += 1
            # Keep the last paragraph for overlap if it fits
            if len(para_clean) < chunk_size:
                current_chunk = [current_chunk[-1], para_clean] if len(current_chunk) > 1 else [para_clean]
                current_length = sum(len(p) for p in current_chunk) + len(current_chunk)
            else:
                current_chunk = [para_clean]
                current_length = len(para_clean)
        else:
            current_chunk.append(para_clean)
            current_length += len(para_clean) + 2

    if current_chunk:
        chunk_str = "\n\n".join(current_chunk)
        chunks.append({
            "chunk_index": chunk_idx,
            "content": chunk_str,
            "metadata": {
                **base_metadata,
                "chunk_index": chunk_idx,
                "char_count": len(chunk_str),
            }
        })

    return chunks
