"""
Tests for Phase 3: Vector Store, RAG Pipeline, and Capability Expander.
"""

import os
import sys
import tempfile
import unittest
import unittest.mock

# Gracefully mock missing numpy dependency
sys.modules['numpy'] = unittest.mock.MagicMock()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))  # noqa: E402


class TestVectorStore(unittest.TestCase):
    """Test TF-IDF vector store."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from james.memory.vectors import VectorStore
        self.vs = VectorStore(db_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_and_search(self):
        self.vs.add("fav_car", "My favorite car is a Tesla Model 3")
        self.vs.add("fav_color", "My favorite color is deep ocean blue")
        self.vs.add("fav_food", "I love eating sushi and ramen")
        results = self.vs.search("what car do I drive?")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0][0], "fav_car")

    def test_search_relevance_order(self):
        self.vs.add("python", "Python is a programming language")
        self.vs.add("java", "Java is another programming language")
        self.vs.add("recipe", "How to bake chocolate cake")
        results = self.vs.search("programming language")
        self.assertTrue(len(results) >= 2)
        # Both programming entries should rank above recipe
        keys = [r[0] for r in results]
        self.assertIn("python", keys[:2])
        self.assertIn("java", keys[:2])

    def test_empty_store_search(self):
        results = self.vs.search("anything")
        self.assertEqual(results, [])

    def test_remove(self):
        self.vs.add("key1", "value one")
        self.assertTrue(self.vs.remove("key1"))
        self.assertFalse(self.vs.remove("nonexistent"))
        self.assertEqual(self.vs.count, 0)

    def test_count(self):
        self.assertEqual(self.vs.count, 0)
        self.vs.add("a", "document a")
        self.vs.add("b", "document b")
        self.assertEqual(self.vs.count, 2)

    def test_persistence(self):
        self.vs.add("persist", "this should be saved to disk")
        self.vs.save()
        # Create a new instance pointing at same dir
        from james.memory.vectors import VectorStore
        vs2 = VectorStore(db_dir=self.tmpdir)
        self.assertEqual(vs2.count, 1)
        results = vs2.search("saved to disk")
        self.assertTrue(len(results) > 0)

    def test_rebuild(self):
        self.vs.add("doc1", "alpha bravo charlie")
        self.vs.rebuild()
        self.assertEqual(self.vs.count, 1)

    def test_status(self):
        self.vs.add("x", "test doc for status")
        self.vs.rebuild()
        status = self.vs.status()
        self.assertEqual(status["documents"], 1)
        self.assertTrue(status["index_built"])
        self.assertTrue(status["vocabulary_size"] > 0)

    def test_threshold_filtering(self):
        self.vs.add("math", "calculus derivatives integrals")
        self.vs.add("cooking", "pasta sauce tomatoes garlic oil")
        results = self.vs.search("calculus math", threshold=0.5)
        # Only highly relevant result should pass
        for key, score in results:
            self.assertGreaterEqual(score, 0.5)

    def test_top_k_limit(self):
        for i in range(20):
            self.vs.add(f"doc{i}", f"document number {i} about topic")
        results = self.vs.search("document number", top_k=3)
        self.assertLessEqual(len(results), 3)


class TestDocumentChunker(unittest.TestCase):
    """Test the RAG document chunker."""

    def setUp(self):
        from james.rag.chunker import DocumentChunker
        self.chunker = DocumentChunker(chunk_size=50, overlap=10)

    def test_chunk_text(self):
        text = " ".join(f"word{i}" for i in range(100))
        chunks = self.chunker.chunk_text(text, source="test.txt")
        self.assertTrue(len(chunks) > 1)
        self.assertEqual(chunks[0]["source"], "test.txt")

    def test_chunk_empty_text(self):
        chunks = self.chunker.chunk_text("")
        self.assertEqual(chunks, [])

    def test_chunk_short_text(self):
        chunks = self.chunker.chunk_text("short text", source="small.txt")
        # Very short text may be skipped (< 10 words)
        self.assertTrue(len(chunks) <= 1)

    def test_chunk_file(self):
        tmpdir = tempfile.mkdtemp()
        test_file = os.path.join(tmpdir, "test.py")
        with open(test_file, "w") as f:
            f.write("def hello():\n    print('hello world')\n\n" * 30)
        chunks = self.chunker.chunk_file(test_file)
        self.assertTrue(len(chunks) > 0)
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_unsupported_extension(self):
        tmpdir = tempfile.mkdtemp()
        test_file = os.path.join(tmpdir, "test.exe")
        with open(test_file, "w") as f:
            f.write("binary content")
        chunks = self.chunker.chunk_file(test_file)
        self.assertEqual(chunks, [])
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chunk_directory(self):
        tmpdir = tempfile.mkdtemp()
        for i in range(3):
            with open(os.path.join(tmpdir, f"file{i}.txt"), "w") as f:
                f.write(f"This is file {i} with lots of content about testing. " * 20)
        chunks = self.chunker.chunk_directory(tmpdir)
        self.assertTrue(len(chunks) > 0)
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestRAGPipeline(unittest.TestCase):
    """Test the full RAG pipeline."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rag_dir = os.path.join(self.tmpdir, "rag")
        from james.rag.pipeline import RAGPipeline
        self.rag = RAGPipeline(db_dir=self.rag_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ingest_file(self):
        # Create a test file
        test_file = os.path.join(self.tmpdir, "readme.md")
        with open(test_file, "w") as f:
            f.write("# Project README\n\nThis is a project about machine learning.\n" * 10)
        result = self.rag.ingest_file(test_file)
        self.assertEqual(result["status"], "success")
        self.assertGreater(result["chunks"], 0)

    def test_ingest_directory(self):
        src_dir = os.path.join(self.tmpdir, "src")
        os.makedirs(src_dir)
        for i in range(3):
            with open(os.path.join(src_dir, f"module{i}.py"), "w") as f:
                f.write(f"def function_{i}():\n    return {i}\n" * 20)
        result = self.rag.ingest(src_dir)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["files"], 3)

    def test_retrieve(self):
        # Ingest diverse content for meaningful TF-IDF
        auth_file = os.path.join(self.tmpdir, "auth.py")
        with open(auth_file, "w") as f:
            f.write(
                "def authenticate(username, password):\n"
                "    '''Verify login credentials against the database.'''\n"
                "    user = db.find_user(username)\n"
                "    if user and check_password(password, user.hash):\n"
                "        return create_session(user)\n"
                "    raise AuthenticationError('Invalid credentials')\n"
            )
        other_file = os.path.join(self.tmpdir, "math.py")
        with open(other_file, "w") as f:
            f.write(
                "def calculate_area(radius):\n"
                "    '''Compute circle area from radius.'''\n"
                "    return 3.14159 * radius * radius\n"
            )
        self.rag.ingest(self.tmpdir)
        results = self.rag.retrieve("authentication login credentials")
        self.assertTrue(len(results) > 0)

    def test_get_context(self):
        test_file = os.path.join(self.tmpdir, "data.txt")
        with open(test_file, "w") as f:
            f.write("The database connection string is postgres://localhost:5432/mydb. " * 20)
        self.rag.ingest_file(test_file)
        context = self.rag.get_context("database connection")
        self.assertTrue(len(context) > 0)
        self.assertIn("content", context[0])

    def test_status(self):
        status = self.rag.status()
        self.assertIn("total_chunks", status)
        self.assertIn("sources", status)

    def test_clear(self):
        test_file = os.path.join(self.tmpdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("content " * 100)
        self.rag.ingest_file(test_file)
        self.assertGreater(self.rag._vector_store.count, 0)
        result = self.rag.clear()
        self.assertEqual(result["status"], "cleared")
        self.assertEqual(self.rag._vector_store.count, 0)

    def test_remove_source(self):
        test_file = os.path.join(self.tmpdir, "removeme.txt")
        with open(test_file, "w") as f:
            f.write("content to be removed " * 50)
        self.rag.ingest_file(test_file)
        initial = self.rag._vector_store.count
        self.assertGreater(initial, 0)
        result = self.rag.remove_source(test_file)
        self.assertEqual(result["status"], "removed")

    def test_nonexistent_path(self):
        result = self.rag.ingest("/nonexistent/path")
        self.assertIn("error", result)


class TestCapabilityExpander(unittest.TestCase):
    """Test the autonomous capability expansion engine."""

    def setUp(self):
        from james.evolution.expander import CapabilityExpander
        self.expander = CapabilityExpander()

    def test_analyze_missing_tool(self):
        gap = self.expander.analyze_failure(
            error="Unknown tool: super_scanner",
            task="scan network",
        )
        self.assertEqual(gap.gap_type, "missing_tool")
        self.assertIn("super_scanner", gap.details.get("missing_tool", ""))

    def test_analyze_missing_package(self):
        gap = self.expander.analyze_failure(
            error="No module named 'pandas'",
            task="analyze csv data",
        )
        self.assertEqual(gap.gap_type, "missing_package")
        self.assertEqual(gap.details["missing_package"], "pandas")

    def test_analyze_missing_command(self):
        gap = self.expander.analyze_failure(
            error="'docker' is not recognized as an internal or external command",
            task="start containers",
        )
        self.assertEqual(gap.gap_type, "missing_command")

    def test_analyze_permission_error(self):
        gap = self.expander.analyze_failure(
            error="Access denied: cannot write to C:\\Windows\\System32",
            task="modify system file",
        )
        self.assertEqual(gap.gap_type, "permission_error")

    def test_analyze_unknown_error(self):
        gap = self.expander.analyze_failure(
            error="Something weird happened",
            task="do something",
        )
        self.assertEqual(gap.gap_type, "unknown")

    def test_gap_to_dict(self):
        gap = self.expander.analyze_failure(
            error="test error", task="test task",
        )
        d = gap.to_dict()
        self.assertIn("task", d)
        self.assertIn("error", d)
        self.assertIn("gap_type", d)
        self.assertIn("timestamp", d)

    def test_attempt_recovery_unknown(self):
        result = self.expander.attempt_recovery(
            task="mystery task",
            error="Completely unknown error type",
        )
        self.assertFalse(result["recovered"])
        self.assertEqual(result["action"], "no_auto_recovery")

    def test_expansion_history(self):
        self.assertEqual(self.expander.expansion_count, 0)
        self.expander.attempt_recovery("t1", "Unknown tool: abc")
        self.expander.attempt_recovery("t2", "No module named 'xyz'")
        self.assertEqual(self.expander.expansion_count, 2)
        history = self.expander.get_history()
        self.assertEqual(len(history), 2)

    def test_status(self):
        self.expander.attempt_recovery("test", "Unknown tool: test_tool")
        status = self.expander.status()
        self.assertEqual(status["total_expansions"], 1)
        self.assertIn("missing_tool", status["gap_types"])


class TestToolSandbox(unittest.TestCase):
    """Test the code sandbox."""

    def setUp(self):
        from james.evolution.expander import ToolSandbox
        self.sandbox = ToolSandbox()

    def test_safe_code_execution(self):
        code = "def my_tool():\n    return {'result': 42}\n"
        result = self.sandbox.test_tool(code, "my_tool")
        self.assertTrue(result["success"])
        self.assertEqual(result["output"]["result"], 42)

    def test_failing_code(self):
        code = "def bad_tool():\n    raise ValueError('broken')\n"
        result = self.sandbox.test_tool(code, "bad_tool")
        self.assertFalse(result["success"])
        self.assertIn("ValueError", result["error"])

    def test_missing_function(self):
        code = "x = 42\n"
        result = self.sandbox.test_tool(code, "nonexistent")
        self.assertFalse(result["success"])

    def test_validate_safe_code(self):
        result = self.sandbox.validate_code_safety(
            "def tool():\n    return {'msg': 'safe'}\n"
        )
        self.assertTrue(result["safe"])
        self.assertEqual(len(result["violations"]), 0)

    def test_validate_dangerous_code(self):
        result = self.sandbox.validate_code_safety(
            "import os\nos.system('rm -rf /')\n"
        )
        self.assertFalse(result["safe"])
        self.assertTrue(len(result["violations"]) > 0)

    def test_validate_network_code(self):
        result = self.sandbox.validate_code_safety(
            "import requests\nrequests.get('http://evil.com')\n"
        )
        self.assertFalse(result["safe"])


class TestRAGTools(unittest.TestCase):
    """Test RAG tool functions."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from james.rag.pipeline import RAGPipeline
        from james.memory.vectors import VectorStore
        from james.tools.registry import set_rag, set_vectors
        self.rag = RAGPipeline(db_dir=os.path.join(self.tmpdir, "rag"))
        self.vectors = VectorStore(db_dir=os.path.join(self.tmpdir, "vec"))
        set_rag(self.rag)
        set_vectors(self.vectors)

    def tearDown(self):
        from james.tools.registry import set_rag, set_vectors
        set_rag(None)
        set_vectors(None)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_tool_rag_ingest(self):
        from james.tools.registry import _tool_rag_ingest
        test_file = os.path.join(self.tmpdir, "doc.txt")
        with open(test_file, "w") as f:
            f.write("test document content about programming " * 20)
        result = _tool_rag_ingest(path=test_file)
        self.assertEqual(result["status"], "success")

    def test_tool_rag_search(self):
        from james.tools.registry import _tool_rag_ingest, _tool_rag_search
        test_file = os.path.join(self.tmpdir, "searchable.txt")
        with open(test_file, "w") as f:
            f.write("machine learning neural networks deep learning " * 20)
        _tool_rag_ingest(path=test_file)
        result = _tool_rag_search(query="neural networks")
        self.assertIn("results", result)

    def test_tool_rag_status(self):
        from james.tools.registry import _tool_rag_status
        result = _tool_rag_status()
        self.assertIn("total_chunks", result)

    def test_tool_vector_search(self):
        from james.tools.registry import _tool_vector_search
        self.vectors.add("test_key", "test document about weather")
        result = _tool_vector_search(query="weather")
        self.assertIn("results", result)

    def test_no_query_error(self):
        from james.tools.registry import _tool_rag_search
        result = _tool_rag_search()
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
