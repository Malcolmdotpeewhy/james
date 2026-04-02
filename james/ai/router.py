"""
JAMES Model Router — MoE-style intent-to-model mapping.

Routes requests to optimal model parameters based on task complexity:
  - Fast tier:     Simple queries, greetings, memory lookups (low tokens, low temp)
  - Balanced tier: Tool calls, commands, web searches (medium tokens)
  - Smart tier:    Reasoning, analysis, multi-step planning (high tokens, higher temp)
  - Code tier:     Code generation, debugging (high tokens, very low temp)

Phase 1: Single model, variable parameters (max_tokens, temperature).
Phase 2 (future): Multi-model with hot-swap or parallel llama-server instances.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("james.ai.router")


@dataclass
class RouteDecision:
    """Result of the model router's decision."""
    tier: str
    model_path: Optional[str]
    max_tokens: int
    temperature: float
    intent: str
    confidence: float


class ModelRouter:
    """
    Routes requests to the optimal model configuration based on intent.

    Phase 1 implementation: adjusts max_tokens and temperature per-tier
    while using the single active model. This alone saves significant
    inference time on trivial queries (512 vs 2048 tokens).
    """

    # Tier definitions: inference parameters per complexity class
    TIERS = {
        "fast": {
            "max_tokens": 512,
            "temperature": 0.2,
            "description": "Quick responses: greetings, memory lookups, simple facts",
            "model_keywords": ["smollm", "phi-2", "tinyllama", "qwen2-0.5b"],
        },
        "balanced": {
            "max_tokens": 1024,
            "temperature": 0.3,
            "description": "Standard tasks: tool calls, commands, web searches",
            "model_keywords": ["mistral", "llama-3", "phi-3", "qwen2.5-3b"],
        },
        "smart": {
            "max_tokens": 2048,
            "temperature": 0.4,
            "description": "Complex reasoning: analysis, multi-step planning, diagnosis",
            "model_keywords": ["qwen3-4b", "deepseek-r1", "command-r", "mixtral"],
        },
        "code": {
            "max_tokens": 2048,
            "temperature": 0.1,
            "description": "Code tasks: generation, debugging, refactoring",
            "model_keywords": ["codellama", "starcoder", "deepseek-coder", "codegemma"],
        },
    }

    # Intent → tier mapping (used by the classifier output)
    INTENT_TO_TIER = {
        # Fast tier
        "greeting": "fast",
        "farewell": "fast",
        "simple_question": "fast",
        "memory_query": "fast",
        "system_control": "fast",

        # Balanced tier
        "command": "balanced",
        "tool_use": "balanced",
        "web_search": "balanced",
        "memory_save": "balanced",
        "file_operation": "balanced",

        # Smart tier
        "reasoning": "smart",
        "analysis": "smart",
        "diagnosis": "smart",
        "planning": "smart",

        # Code tier
        "code_generation": "code",
        "debugging": "code",
        "code_review": "code",

        # Default
        "unknown": "balanced",
    }

    def __init__(self, available_models: Optional[list[dict]] = None):
        """
        Args:
            available_models: List of discovered models from local_llm.discover_models().
                Each dict has: name, filename, path, size_mb, directory.
        """
        self.models = available_models or []
        self._tier_model_map = self._build_tier_map()

    def _build_tier_map(self) -> dict[str, Optional[str]]:
        """Map each tier to the best available model path (if multiple models exist)."""
        tier_models: dict[str, Optional[str]] = {}

        for tier_name, tier_config in self.TIERS.items():
            best_match = None
            for model in self.models:
                model_name_lower = model.get("name", "").lower()
                # ⚡ Bolt: Avoid generator expression overhead
                match_found = False
                for kw in tier_config["model_keywords"]:
                    if kw in model_name_lower:
                        match_found = True
                        break
                if match_found:
                    best_match = model.get("path")
                    break

            tier_models[tier_name] = best_match
            if best_match:
                logger.debug(f"Router: tier '{tier_name}' → {best_match}")

        return tier_models

    def route(self, intent: str, confidence: float = 0.0,
              message: str = "") -> RouteDecision:
        """
        Select the optimal model configuration for a given intent.

        Args:
            intent: Classified intent string (from IntentClassifier).
            confidence: Classifier confidence score.
            message: Original user message (for length-based heuristics).

        Returns:
            RouteDecision with tier, model path, and inference parameters.
        """
        tier = self.INTENT_TO_TIER.get(intent, "balanced")

        # Length-based escalation: very long messages likely need more reasoning
        if len(message) > 200 and tier == "fast":
            tier = "balanced"
            logger.debug(f"Router: escalated from 'fast' to 'balanced' (message length={len(message)})")

        # Low-confidence escalation: if classifier is unsure, use smarter model
        if confidence < 0.5 and tier == "fast":
            tier = "balanced"
            logger.debug(f"Router: escalated from 'fast' to 'balanced' (confidence={confidence:.2f})")

        tier_config = self.TIERS.get(tier, self.TIERS["balanced"])
        model_path = self._tier_model_map.get(tier)

        decision = RouteDecision(
            tier=tier,
            model_path=model_path,
            max_tokens=tier_config["max_tokens"],
            temperature=tier_config["temperature"],
            intent=intent,
            confidence=confidence,
        )

        logger.info(
            f"Router: intent='{intent}' (conf={confidence:.2f}) → "
            f"tier='{tier}' (tokens={decision.max_tokens}, temp={decision.temperature})"
        )

        return decision

    def get_tier_info(self) -> dict:
        """Return tier configuration for display in dashboard/API."""
        info = {}
        for tier_name, config in self.TIERS.items():
            info[tier_name] = {
                "description": config["description"],
                "max_tokens": config["max_tokens"],
                "temperature": config["temperature"],
                "model": self._tier_model_map.get(tier_name, "default"),
            }
        return info
