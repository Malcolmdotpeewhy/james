"""
JAMES Vector Store — Lightweight semantic search using TF-IDF + cosine similarity.

Zero external dependencies beyond numpy (already installed).
Provides semantic memory search that works without sentence-transformers/FAISS.

Architecture:
  - TF-IDF vectorization of memory keys + values
  - Cosine similarity for semantic matching
  - NumPy-based matrix operations (fast, CPU-only)
  - Persistent index via JSON serialization
  - Drop-in upgrade path to sentence-transformers when available

Usage:
    vs = VectorStore(db_dir="james/memory")
    vs.add("fav_car", "My favorite vehicle is a Tesla Model 3")
    results = vs.search("what car do I drive?", top_k=5)
    # → [("fav_car", 0.72), ...]
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from collections import Counter
from typing import Optional

import numpy as np

logger = logging.getLogger("james.memory.vectors")


class VectorStore:
    """
    Lightweight vector store using TF-IDF + cosine similarity.

    No FAISS, no torch, no sentence-transformers required.
    Uses numpy for fast matrix operations on the TF-IDF vectors.
    """

    def __init__(self, db_dir: str):
        self._db_dir = db_dir
        self._index_path = os.path.join(db_dir, "vectors.json")

        # In-memory state
        self._documents: dict[str, str] = {}   # key → text
        self._vocabulary: dict[str, int] = {}   # word → index
        self._idf: Optional[np.ndarray] = None  # inverse doc frequency
        self._tfidf_matrix: Optional[np.ndarray] = None  # docs × vocab
        self._key_order: list[str] = []          # ordered list of keys

        self._dirty = False
        self._load()

    # ── Public API ───────────────────────────────────────────────

    def add(self, key: str, text: str) -> None:
        """Add or update a document in the vector store."""
        # Normalize text
        combined = f"{key} {text}".strip()
        if not combined:
            return

        self._documents[key] = combined
        self._dirty = True

    def remove(self, key: str) -> bool:
        """Remove a document from the index."""
        if key in self._documents:
            del self._documents[key]
            self._dirty = True
            return True
        return False

    def search(self, query: str, top_k: int = 5,
               threshold: float = 0.1) -> list[tuple[str, float]]:
        """
        Search for documents similar to the query.

        Args:
            query: Search query string.
            top_k: Maximum number of results.
            threshold: Minimum similarity score (0-1).

        Returns:
            List of (key, score) tuples sorted by relevance.
        """
        if not self._documents:
            return []

        # Rebuild index if dirty
        if self._dirty or self._tfidf_matrix is None:
            self._rebuild_index()

        # Vectorize the query
        query_vec = self._vectorize_query(query)
        if query_vec is None or np.linalg.norm(query_vec) == 0:
            return []

        # Cosine similarity against all documents
        norms = np.linalg.norm(self._tfidf_matrix, axis=1)
        norms[norms == 0] = 1  # avoid division by zero
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []

        similarities = self._tfidf_matrix.dot(query_vec) / (norms * query_norm)

        # Get top-k results above threshold
        results = []
        top_indices = np.argsort(similarities)[::-1][:top_k]
        for idx in top_indices:
            score = float(similarities[idx])
            if score >= threshold:
                results.append((self._key_order[idx], score))

        return results

    @property
    def count(self) -> int:
        return len(self._documents)

    def rebuild(self) -> None:
        """Force a full index rebuild."""
        self._dirty = True
        self._rebuild_index()

    def save(self) -> None:
        """Persist the index to disk."""
        self._save()

    # ── Index Construction ───────────────────────────────────────

    def _rebuild_index(self) -> None:
        """Rebuild the TF-IDF matrix from all documents."""
        if not self._documents:
            self._tfidf_matrix = None
            self._dirty = False
            return

        self._key_order = list(self._documents.keys())
        texts = [self._documents[k] for k in self._key_order]

        # Tokenize all documents
        tokenized = [self._tokenize(t) for t in texts]

        # Build vocabulary from all tokens
        vocab = set()
        for tokens in tokenized:
            vocab.update(tokens)
        self._vocabulary = {word: idx for idx, word in enumerate(sorted(vocab))}
        vocab_size = len(self._vocabulary)

        if vocab_size == 0:
            self._tfidf_matrix = None
            self._dirty = False
            return

        n_docs = len(tokenized)

        # Term frequency (TF) matrix: docs × vocab
        tf_matrix = np.zeros((n_docs, vocab_size), dtype=np.float32)
        for doc_idx, tokens in enumerate(tokenized):
            counts = Counter(tokens)
            max_count = max(counts.values()) if counts else 1
            for word, count in counts.items():
                if word in self._vocabulary:
                    word_idx = self._vocabulary[word]
                    # Augmented TF to prevent bias toward longer documents
                    tf_matrix[doc_idx, word_idx] = 0.5 + 0.5 * (count / max_count)

        # Inverse Document Frequency (IDF)
        doc_freq = np.sum(tf_matrix > 0, axis=0)
        self._idf = np.log((n_docs + 1) / (doc_freq + 1)) + 1  # smoothed IDF

        # TF-IDF matrix
        self._tfidf_matrix = tf_matrix * self._idf

        self._dirty = False
        self._save()
        logger.debug(f"Vector index rebuilt: {n_docs} docs, {vocab_size} terms")

    def _vectorize_query(self, query: str) -> Optional[np.ndarray]:
        """Convert a query string to a TF-IDF vector."""
        if not self._vocabulary or self._idf is None:
            return None

        tokens = self._tokenize(query)
        if not tokens:
            return None

        vec = np.zeros(len(self._vocabulary), dtype=np.float32)
        counts = Counter(tokens)
        max_count = max(counts.values()) if counts else 1

        for word, count in counts.items():
            if word in self._vocabulary:
                word_idx = self._vocabulary[word]
                tf = 0.5 + 0.5 * (count / max_count)
                vec[word_idx] = tf * self._idf[word_idx]

        return vec

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text into lowercase words, removing punctuation."""
        text = text.lower()
        # Split on non-alphanumeric, keep meaningful tokens
        tokens = re.findall(r'[a-z0-9]+', text)
        # Remove very short tokens and stop words
        stop_words = {
            'a', 'an', 'the', 'is', 'it', 'in', 'on', 'at', 'to', 'for',
            'of', 'and', 'or', 'but', 'not', 'this', 'that', 'with', 'from',
            'by', 'as', 'be', 'was', 'were', 'been', 'are', 'am', 'has',
            'had', 'have', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'can', 'i', 'my', 'me', 'we', 'you',
        }
        return [t for t in tokens if len(t) > 1 and t not in stop_words]

    # ── Persistence ──────────────────────────────────────────────

    def _save(self) -> None:
        """Save documents to disk. The TF-IDF index is rebuilt on load."""
        os.makedirs(self._db_dir, exist_ok=True)
        data = {"documents": self._documents}
        try:
            with open(self._index_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save vector index: {e}")

    def _load(self) -> None:
        """Load documents from disk and rebuild the index."""
        if not os.path.exists(self._index_path):
            return
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._documents = data.get("documents", {})
            if self._documents:
                self._dirty = True
                self._rebuild_index()
            logger.debug(f"Vector index loaded: {len(self._documents)} docs")
        except Exception as e:
            logger.error(f"Failed to load vector index: {e}")

    def status(self) -> dict:
        """Return index status information."""
        return {
            "documents": len(self._documents),
            "vocabulary_size": len(self._vocabulary),
            "index_built": self._tfidf_matrix is not None,
            "index_path": self._index_path,
        }
