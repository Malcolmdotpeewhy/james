"""
JAMES RAG Pipeline — Full ingest + retrieve + inject pipeline.

Combines:
  - DocumentChunker: splits files into chunks
  - VectorStore: TF-IDF semantic indexing
  - Retriever: query-time search with relevance scoring

Usage:
    rag = RAGPipeline(db_dir="james/memory/rag")
    rag.ingest("C:/Projects/myapp")          # Index a directory
    rag.ingest_file("README.md")             # Index a single file
    results = rag.retrieve("login function")  # Semantic search
    context = rag.get_context("how does auth work?")  # For LLM injection
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from james.memory.vectors import VectorStore
from james.rag.chunker import DocumentChunker

logger = logging.getLogger("james.rag")


class RAGPipeline:
    """
    Retrieval-Augmented Generation pipeline.

    Handles the full lifecycle:
      1. Ingest: files/directories → chunks → vector index
      2. Retrieve: query → top-k relevant chunks
      3. Context: format retrieved chunks for LLM injection
    """

    def __init__(self, db_dir: str):
        self._db_dir = db_dir
        os.makedirs(db_dir, exist_ok=True)

        self._vector_store = VectorStore(db_dir)
        self._chunker = DocumentChunker(chunk_size=300, overlap=50)

        # Metadata: track ingested sources
        self._meta_path = os.path.join(db_dir, "rag_meta.json")
        self._sources: dict[str, dict] = {}  # source_path → {chunks, ingested_at, ...}
        self._load_meta()

    # ── Ingestion ────────────────────────────────────────────────

    def ingest(self, path: str, recursive: bool = True,
               max_files: int = 500) -> dict:
        """
        Ingest a file or directory into the RAG index.

        Args:
            path: File or directory path.
            recursive: Scan subdirectories (for directories).
            max_files: Maximum files to process.

        Returns:
            Summary dict: {files, chunks, duration_ms, errors}
        """
        start = time.time()
        path = os.path.abspath(path)
        errors = []

        if os.path.isfile(path):
            chunks = self._chunker.chunk_file(path)
            files_processed = 1 if chunks else 0
        elif os.path.isdir(path):
            chunks = self._chunker.chunk_directory(
                path, recursive=recursive, max_files=max_files
            )
            # Count unique source files
            files_processed = len(set(c["source"] for c in chunks))
        else:
            return {"error": f"Path not found: {path}"}

        # Index chunks
        chunk_count = 0
        for chunk in chunks:
            key = f"rag:{chunk['source']}:chunk{chunk['chunk_index']}"
            try:
                self._vector_store.add(key, chunk["text"])
                chunk_count += 1
            except Exception as e:
                errors.append(f"Failed to index chunk: {e}")

        # Save metadata
        self._sources[path] = {
            "chunks": chunk_count,
            "files": files_processed,
            "ingested_at": time.time(),
        }
        self._save_meta()
        self._vector_store.save()

        duration_ms = (time.time() - start) * 1000
        logger.info(
            f"RAG ingest: {files_processed} files → {chunk_count} chunks "
            f"from '{path}' ({duration_ms:.0f}ms)"
        )

        return {
            "status": "success",
            "path": path,
            "files": files_processed,
            "chunks": chunk_count,
            "duration_ms": round(duration_ms),
            "errors": errors[:10],
        }

    def ingest_file(self, path: str) -> dict:
        """Ingest a single file."""
        return self.ingest(path)

    # ── Retrieval ────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 5,
                 threshold: float = 0.1) -> list[dict]:
        """
        Retrieve relevant chunks for a query.

        Args:
            query: Search query.
            top_k: Maximum results.
            threshold: Minimum relevance score.

        Returns:
            List of {key, text, source, relevance} dicts.
        """
        results = self._vector_store.search(query, top_k=top_k, threshold=threshold)

        enriched = []
        for key, score in results:
            # Extract source file from key (format: "rag:filepath:chunkN")
            parts = key.split(":", 2)
            source = parts[1] if len(parts) > 1 else key
            text = self._vector_store._documents.get(key, "")

            # Remove the key prefix from text (it's the combined key+text)
            enriched.append({
                "key": key,
                "source": source,
                "text": text[:500],  # Cap display length
                "relevance": round(score, 3),
            })

        return enriched

    def get_context(self, query: str, top_k: int = 3,
                    max_chars: int = 2000) -> list[dict]:
        """
        Get formatted context for LLM injection.

        Returns a compact list suitable for adding to the AI context dict.
        """
        results = self.retrieve(query, top_k=top_k)

        context_items = []
        char_count = 0
        for r in results:
            text = r["text"]
            if char_count + len(text) > max_chars:
                text = text[:max_chars - char_count]
            context_items.append({
                "source": os.path.basename(r["source"]),
                "relevance": r["relevance"],
                "content": text,
            })
            char_count += len(text)
            if char_count >= max_chars:
                break

        return context_items

    # ── Management ───────────────────────────────────────────────

    def clear(self) -> dict:
        """Clear the entire RAG index."""
        count = self._vector_store.count
        self._vector_store._documents.clear()
        self._vector_store._dirty = True
        self._vector_store.save()
        self._sources.clear()
        self._save_meta()
        return {"status": "cleared", "removed_chunks": count}

    def remove_source(self, path: str) -> dict:
        """Remove all chunks from a specific source."""
        path = os.path.abspath(path)
        removed = 0
        keys_to_remove = [
            k for k in self._vector_store._documents
            if k.startswith(f"rag:{path}:")
        ]
        for key in keys_to_remove:
            self._vector_store.remove(key)
            removed += 1

        if path in self._sources:
            del self._sources[path]
            self._save_meta()
        self._vector_store.save()

        return {"status": "removed", "source": path, "chunks_removed": removed}

    def status(self) -> dict:
        """Get RAG pipeline status."""
        return {
            "total_chunks": self._vector_store.count,
            "sources": len(self._sources),
            "source_details": {
                path: {
                    "chunks": info["chunks"],
                    "files": info.get("files", 0),
                    "ingested_at": info.get("ingested_at", 0),
                }
                for path, info in self._sources.items()
            },
            "vector_store": self._vector_store.status(),
        }

    # ── Persistence ──────────────────────────────────────────────

    def _save_meta(self) -> None:
        try:
            with open(self._meta_path, "w", encoding="utf-8") as f:
                json.dump({"sources": self._sources}, f)
        except Exception as e:
            logger.error(f"Failed to save RAG metadata: {e}")

    def _load_meta(self) -> None:
        if os.path.exists(self._meta_path):
            try:
                with open(self._meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._sources = data.get("sources", {})
            except Exception as e:
                logger.error(f"Failed to load RAG metadata: {e}")
