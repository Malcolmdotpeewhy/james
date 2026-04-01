"""
JAMES RAG Chunker — Split documents into overlapping chunks for indexing.

Supports: .py, .js, .ts, .md, .txt, .json, .yaml, .yml, .csv, .html, .xml, .cfg, .ini, .bat, .ps1
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("james.rag.chunker")

# File extensions we can ingest
SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt",
    ".md", ".txt", ".rst", ".log",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env",
    ".csv", ".xml", ".html", ".css", ".scss",
    ".bat", ".ps1", ".sh", ".bash",
    ".sql", ".dockerfile",
}


class DocumentChunker:
    """
    Split documents into overlapping chunks for vector indexing.

    Uses word-level chunking with configurable overlap to preserve
    context across chunk boundaries.
    """

    def __init__(self, chunk_size: int = 300, overlap: int = 50):
        """
        Args:
            chunk_size: Target words per chunk.
            overlap: Word overlap between consecutive chunks.
        """
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_text(self, text: str, source: str = "<string>") -> list[dict]:
        """
        Split text into overlapping chunks.

        Returns:
            List of chunk dicts: {text, source, chunk_index, start_word, end_word}
        """
        words = text.split()
        if not words:
            return []

        chunks = []
        step = max(1, self.chunk_size - self.overlap)

        for i in range(0, len(words), step):
            chunk_words = words[i:i + self.chunk_size]
            if len(chunk_words) < 10:  # skip tiny trailing chunks
                break
            chunks.append({
                "text": " ".join(chunk_words),
                "source": source,
                "chunk_index": len(chunks),
                "start_word": i,
                "end_word": i + len(chunk_words),
                "total_words": len(words),
            })

        return chunks

    def chunk_file(self, path: str) -> list[dict]:
        """
        Read and chunk a single file.

        Returns empty list for unsupported or unreadable files.
        """
        p = Path(path)
        ext = p.suffix.lower()

        if ext not in SUPPORTED_EXTENSIONS:
            return []

        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"Cannot read {path}: {e}")
            return []

        if not text.strip():
            return []

        # For code files, preserve structure by chunking on function/class boundaries
        if ext in (".py", ".js", ".ts", ".java", ".go", ".rs"):
            return self._chunk_code(text, str(path))

        return self.chunk_text(text, source=str(path))

    def chunk_directory(self, directory: str,
                        recursive: bool = True,
                        max_files: int = 500) -> list[dict]:
        """
        Chunk all supported files in a directory.

        Args:
            directory: Root directory to scan.
            recursive: Whether to scan subdirectories.
            max_files: Maximum files to process.

        Returns:
            List of all chunks across all files.
        """
        dir_path = Path(directory)
        if not dir_path.is_dir():
            logger.warning(f"Not a directory: {directory}")
            return []

        all_chunks = []
        file_count = 0
        glob_fn = dir_path.rglob if recursive else dir_path.glob

        # Skip common non-source directories
        skip_dirs = {
            ".git", "__pycache__", "node_modules", ".venv", "venv",
            ".env", "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
            "egg-info", ".eggs",
        }

        for p in sorted(glob_fn("*")):
            if file_count >= max_files:
                break
            if not p.is_file():
                continue

            # Skip files in excluded directories
            parts = set(p.parts)
            if parts & skip_dirs:
                continue

            chunks = self.chunk_file(str(p))
            if chunks:
                all_chunks.extend(chunks)
                file_count += 1

        logger.info(f"Chunked {file_count} files → {len(all_chunks)} chunks from {directory}")
        return all_chunks

    def _chunk_code(self, text: str, source: str) -> list[dict]:
        """
        Smart chunking for code: split on function/class boundaries.
        Falls back to word-level chunking if no boundaries found.
        """
        import re

        # Split on common code boundaries
        patterns = [
            r'\n(?=def\s)',           # Python functions
            r'\n(?=class\s)',          # Python classes
            r'\n(?=function\s)',       # JS functions
            r'\n(?=export\s)',         # JS/TS exports
            r'\n(?=const\s\w+\s*=)',   # JS const assignments
            r'\n(?=public\s)',         # Java/C# methods
            r'\n(?=func\s)',           # Go functions
        ]

        combined_pattern = "|".join(patterns)
        blocks = re.split(combined_pattern, text)

        if len(blocks) <= 1:
            # No code boundaries found, use word-level chunking
            return self.chunk_text(text, source=source)

        chunks = []
        current_block = ""

        for block in blocks:
            if not block.strip():
                continue

            # If adding this block would exceed chunk size, flush
            combined = current_block + "\n" + block if current_block else block
            if len(combined.split()) > self.chunk_size and current_block:
                chunks.append({
                    "text": current_block.strip(),
                    "source": source,
                    "chunk_index": len(chunks),
                    "start_word": 0,
                    "end_word": len(current_block.split()),
                    "total_words": len(text.split()),
                })
                current_block = block
            else:
                current_block = combined

        # Flush remaining
        if current_block.strip():
            chunks.append({
                "text": current_block.strip(),
                "source": source,
                "chunk_index": len(chunks),
                "start_word": 0,
                "end_word": len(current_block.split()),
                "total_words": len(text.split()),
            })

        return chunks
