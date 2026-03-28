"""
JAMES Unit Tests — Security Layer
"""
import json
import os
import tempfile

import pytest
from james.security import (
    AuditEntry, AuditLog, OpClass, RestorePointManager, SecurityPolicy,
    EvolutionBoundary,
)


class TestSecurityPolicy:
    def test_classify_safe(self):
        policy = SecurityPolicy()
        assert policy.classify_operation("dir /b") == OpClass.SAFE

    def test_classify_destructive_rm(self):
        policy = SecurityPolicy()
        assert policy.classify_operation("rm -rf /tmp/stuff") == OpClass.DESTRUCTIVE

    def test_classify_destructive_del(self):
        policy = SecurityPolicy()
        assert policy.classify_operation("del /f /q myfile") == OpClass.DESTRUCTIVE

    def test_classify_system_level(self):
        policy = SecurityPolicy()
        assert policy.classify_operation("net stop SomeService") == OpClass.SYSTEM_LEVEL

    def test_classify_production(self):
        policy = SecurityPolicy()
        assert policy.classify_operation("docker push myimage:latest") == OpClass.PRODUCTION

    def test_requires_confirmation_destructive(self):
        policy = SecurityPolicy()
        # Default: destructive ops require confirmation
        assert policy.requires_confirmation(OpClass.DESTRUCTIVE) is True

    def test_requires_confirmation_safe(self):
        policy = SecurityPolicy()
        assert policy.requires_confirmation(OpClass.SAFE) is False

    def test_evolution_allowed(self):
        result = SecurityPolicy.classify_evolution("create new skill")
        assert result == EvolutionBoundary.ALLOWED

    def test_evolution_restricted_kernel(self):
        result = SecurityPolicy.classify_evolution("modify kernel driver")
        assert result == EvolutionBoundary.RESTRICTED

    def test_evolution_restricted_bypass(self):
        result = SecurityPolicy.classify_evolution("bypass security check")
        assert result == EvolutionBoundary.RESTRICTED


class TestAuditLog:
    def test_record_and_read(self):
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(os.path.join(td, "audit.jsonl"))
            log.record(AuditEntry(operation="test_op", classification=OpClass.SAFE, details="test details"))
            entries = log.read_recent(10)
            assert len(entries) == 1
            assert entries[0]["op"] == "test_op"
            assert entries[0]["class"] == "safe"

    def test_multiple_entries(self):
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(os.path.join(td, "audit.jsonl"))
            for i in range(5):
                log.record(AuditEntry(operation=f"op_{i}", classification=OpClass.SAFE))
            assert log.entry_count == 5
            entries = log.read_recent(3)
            assert len(entries) == 3

    def test_entry_count_empty(self):
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(os.path.join(td, "audit.jsonl"))
            assert log.entry_count == 0

    def test_approved_flag(self):
        with tempfile.TemporaryDirectory() as td:
            log = AuditLog(os.path.join(td, "audit.jsonl"))
            log.record(AuditEntry(operation="blocked", classification=OpClass.DESTRUCTIVE, approved=False))
            entries = log.read_recent()
            assert entries[0]["approved"] is False


class TestRestorePointManager:
    def test_create_and_restore(self):
        with tempfile.TemporaryDirectory() as td:
            rpm = RestorePointManager(os.path.join(td, "restore"))

            # Create source file
            src = os.path.join(td, "original.txt")
            with open(src, "w") as f:
                f.write("original content")

            # Create restore point
            rp_path = rpm.create_restore_point(src, label="test")
            assert rp_path is not None
            assert os.path.isfile(rp_path)

            # Modify original
            with open(src, "w") as f:
                f.write("modified content")

            # Restore
            assert rpm.restore(rp_path, src) is True
            with open(src) as f:
                assert f.read() == "original content"

    def test_create_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as td:
            rpm = RestorePointManager(os.path.join(td, "restore"))
            result = rpm.create_restore_point(os.path.join(td, "nope.txt"))
            assert result is None

    def test_list_restore_points(self):
        with tempfile.TemporaryDirectory() as td:
            rpm = RestorePointManager(os.path.join(td, "restore"))
            src = os.path.join(td, "file.txt")
            with open(src, "w") as f:
                f.write("test")
            rpm.create_restore_point(src, label="v1")
            rpm.create_restore_point(src, label="v2")
            points = rpm.list_restore_points()
            assert len(points) == 2
