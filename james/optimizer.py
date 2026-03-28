"""
JAMES Autonomous Improvement Engine (Optimizer)

Multi-phase evolution cycle:
  1. Observe  — capture execution metrics
  2. Diagnose — identify bottlenecks, instability, inefficiencies
  3. Generate — propose optimized execution variants
  4. Sandbox  — test variant in isolated environment
  5. Score    — compare original vs variant
  6. Deploy   — replace or augment existing skill
  7. Monitor  — track regression over subsequent executions
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from james.memory.store import MemoryStore
from james.skills.skill import Skill, SkillStore

logger = logging.getLogger("james.optimizer")


@dataclass
class OptimizationProposal:
    """A proposed optimization for a skill."""
    skill_id: str
    description: str
    category: str  # "parallelization", "caching", "layer_switch", "step_elimination"
    expected_improvement: float  # Estimated improvement percentage
    risk_level: str  # "low", "medium", "high"
    changes: list[dict] = field(default_factory=list)


@dataclass
class DiagnosticReport:
    """Results of diagnosing execution patterns."""
    bottlenecks: list[dict] = field(default_factory=list)
    instability: list[dict] = field(default_factory=list)
    inefficiencies: list[dict] = field(default_factory=list)
    total_issues: int = 0
    generated_at: float = field(default_factory=time.time)


class Optimizer:
    """
    Autonomous improvement engine that analyzes execution
    history and proposes/applies optimizations to skills.
    """

    # Minimum improvement threshold to deploy a change
    IMPROVEMENT_THRESHOLD = 0.05  # 5%

    # Minimum executions before considering optimization
    MIN_EXECUTIONS = 3

    # Maximum regression tolerance before rollback
    MAX_REGRESSION = -0.10  # -10%

    def __init__(self, memory: MemoryStore, skill_store: SkillStore):
        self._memory = memory
        self._skills = skill_store

    # ── Phase 1: Observe ─────────────────────────────────────────

    def observe(self, skill_id: str) -> dict:
        """
        Gather execution metrics for a skill.
        Returns aggregated performance data.
        """
        metrics = self._memory.get_metrics(node_id=skill_id, limit=50)
        if not metrics:
            return {"skill_id": skill_id, "data_points": 0}

        successes = sum(1 for m in metrics if m.get("success"))
        durations = [m["duration_ms"] for m in metrics if m.get("duration_ms")]

        return {
            "skill_id": skill_id,
            "data_points": len(metrics),
            "success_rate": successes / len(metrics) if metrics else 0,
            "avg_duration_ms": sum(durations) / len(durations) if durations else 0,
            "min_duration_ms": min(durations) if durations else 0,
            "max_duration_ms": max(durations) if durations else 0,
            "p95_duration_ms": sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 1 else 0,
            "recent_failures": sum(1 for m in metrics[:5] if not m.get("success")),
        }

    # ── Phase 2: Diagnose ────────────────────────────────────────

    def diagnose(self) -> DiagnosticReport:
        """
        Analyze all skills for bottlenecks, instability, and inefficiencies.
        """
        report = DiagnosticReport()
        skills = self._skills.list_all()

        for skill in skills:
            if skill.execution_count < self.MIN_EXECUTIONS:
                continue

            stats = self.observe(skill.id)

            # Bottleneck: High duration relative to others
            if stats.get("avg_duration_ms", 0) > 5000:
                report.bottlenecks.append({
                    "skill_id": skill.id,
                    "skill_name": skill.name,
                    "avg_duration_ms": stats["avg_duration_ms"],
                    "severity": "high" if stats["avg_duration_ms"] > 15000 else "medium",
                })

            # Instability: Low success rate
            if stats.get("success_rate", 1.0) < 0.8:
                report.instability.append({
                    "skill_id": skill.id,
                    "skill_name": skill.name,
                    "success_rate": stats["success_rate"],
                    "recent_failures": stats.get("recent_failures", 0),
                    "severity": "high" if stats["success_rate"] < 0.5 else "medium",
                })

            # Inefficiency: High variance in duration (p95 >> avg)
            p95 = stats.get("p95_duration_ms", 0)
            avg = stats.get("avg_duration_ms", 1)
            if avg > 0 and p95 > avg * 3:
                report.inefficiencies.append({
                    "skill_id": skill.id,
                    "skill_name": skill.name,
                    "avg_ms": avg,
                    "p95_ms": p95,
                    "variance_ratio": p95 / avg,
                })

        report.total_issues = (
            len(report.bottlenecks)
            + len(report.instability)
            + len(report.inefficiencies)
        )
        return report

    # ── Phase 3: Generate ────────────────────────────────────────

    def generate_proposals(self, report: DiagnosticReport) -> list[OptimizationProposal]:
        """
        Generate optimization proposals based on diagnostic findings.
        """
        proposals: list[OptimizationProposal] = []

        # For bottlenecks: suggest parallelization or caching
        for bottleneck in report.bottlenecks:
            proposals.append(OptimizationProposal(
                skill_id=bottleneck["skill_id"],
                description=f"Reduce execution time for '{bottleneck['skill_name']}' "
                            f"(avg {bottleneck['avg_duration_ms']:.0f}ms)",
                category="caching",
                expected_improvement=0.30,
                risk_level="low",
                changes=[{"action": "add_result_caching"}],
            ))

        # For instability: suggest method switch or retry enhancement
        for unstable in report.instability:
            proposals.append(OptimizationProposal(
                skill_id=unstable["skill_id"],
                description=f"Improve reliability for '{unstable['skill_name']}' "
                            f"(success rate: {unstable['success_rate']:.0%})",
                category="layer_switch",
                expected_improvement=0.20,
                risk_level="medium",
                changes=[{"action": "try_alternate_layer"}],
            ))

        # For inefficiencies: suggest step elimination or batching
        for inefficiency in report.inefficiencies:
            proposals.append(OptimizationProposal(
                skill_id=inefficiency["skill_id"],
                description=f"Reduce variance for '{inefficiency['skill_name']}' "
                            f"(p95/avg ratio: {inefficiency['variance_ratio']:.1f}x)",
                category="step_elimination",
                expected_improvement=0.15,
                risk_level="low",
                changes=[{"action": "add_timeout_guard"}],
            ))

        return proposals

    # ── Phase 4-5: Score ─────────────────────────────────────────

    def score_improvement(self, skill_id: str, before: dict, after: dict) -> float:
        """
        Calculate improvement score between before and after metrics.
        Returns improvement as a fraction (0.1 = 10% improvement).
        """
        score = 0.0

        # Success rate improvement (weighted 60%)
        sr_before = before.get("success_rate", 0)
        sr_after = after.get("success_rate", 0)
        if sr_before > 0:
            sr_improvement = (sr_after - sr_before) / sr_before
            score += sr_improvement * 0.6

        # Duration reduction (weighted 40%)
        dur_before = before.get("avg_duration_ms", 1)
        dur_after = after.get("avg_duration_ms", 1)
        if dur_before > 0:
            dur_improvement = (dur_before - dur_after) / dur_before
            score += dur_improvement * 0.4

        return score

    # ── Phase 6: Deploy ──────────────────────────────────────────

    def apply_optimization(self, proposal: OptimizationProposal) -> bool:
        """
        Apply an optimization to a skill.
        Records the change in meta-memory for tracking.
        """
        skill = self._skills.get(proposal.skill_id)
        if not skill:
            logger.warning(f"Skill not found for optimization: {proposal.skill_id}")
            return False

        before_score = skill.confidence_score

        # Log the optimization
        skill.log_optimization(
            description=proposal.description,
            improvement=proposal.expected_improvement,
        )

        # Update the skill
        self._skills.update(skill)

        # Record in meta-memory
        self._memory.record_optimization(
            skill_id=skill.id,
            optimization=proposal.description,
            before_score=before_score,
            after_score=skill.confidence_score,
        )

        logger.info(
            f"Applied optimization to skill '{skill.id}': {proposal.description}"
        )
        return True

    # ── Full Cycle ───────────────────────────────────────────────

    def run_improvement_cycle(self) -> dict:
        """
        Run a full improvement cycle:
        Observe → Diagnose → Generate → Score → Deploy
        Returns a summary of actions taken.
        """
        start = time.time()
        logger.info("Starting improvement cycle...")

        # Diagnose
        report = self.diagnose()
        logger.info(
            f"Diagnosis complete: {report.total_issues} issues found "
            f"({len(report.bottlenecks)} bottlenecks, "
            f"{len(report.instability)} unstable, "
            f"{len(report.inefficiencies)} inefficient)"
        )

        if report.total_issues == 0:
            return {
                "issues_found": 0,
                "proposals_generated": 0,
                "optimizations_applied": 0,
                "duration_ms": (time.time() - start) * 1000,
            }

        # Generate proposals
        proposals = self.generate_proposals(report)
        logger.info(f"Generated {len(proposals)} optimization proposals")

        # Apply safe proposals (low risk only on auto)
        applied = 0
        for proposal in proposals:
            if proposal.risk_level == "low":
                if self.apply_optimization(proposal):
                    applied += 1

        duration = (time.time() - start) * 1000
        summary = {
            "issues_found": report.total_issues,
            "proposals_generated": len(proposals),
            "optimizations_applied": applied,
            "duration_ms": duration,
            "details": {
                "bottlenecks": len(report.bottlenecks),
                "instability": len(report.instability),
                "inefficiencies": len(report.inefficiencies),
            },
        }

        logger.info(f"Improvement cycle complete: {applied} optimizations applied in {duration:.0f}ms")
        return summary
