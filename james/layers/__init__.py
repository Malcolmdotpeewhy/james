"""
JAMES Authority Layer System

Abstract base class for all 5 control layers,
plus the layer registry for dynamic selection.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Optional

logger = logging.getLogger("james.layers")


class LayerLevel(IntEnum):
    """Authority layer levels, ordered by reliability."""
    NATIVE = 1           # Direct OS interaction
    APPLICATION = 2      # Software ecosystem integration
    UI_COGNITIVE = 3     # Visual interpretation + input simulation
    SYNTHETIC = 4        # Custom control mechanism engineering
    ENVIRONMENTAL = 5    # System environment modification


@dataclass
class LayerResult:
    """Result from a layer execution."""
    success: bool
    output: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0


class ControlLayer(ABC):
    """
    Abstract base class for all authority layers.
    Each layer implements execute() with its own control strategy.
    """

    level: LayerLevel = LayerLevel.NATIVE
    name: str = "base"
    description: str = ""

    @abstractmethod
    def execute(self, action: dict) -> LayerResult:
        """
        Execute an action using this layer's control strategy.

        Args:
            action: Dict with at minimum:
                - "type": action type (e.g., "command", "api_call", "click")
                - "target": what to act on
                - Additional keys depend on the action type.

        Returns:
            LayerResult with success status, output, and timing.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this layer's dependencies are satisfied."""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} L{self.level.value}: {self.name}>"


class LayerRegistry:
    """
    Registry of all available control layers.
    Supports dynamic layer selection based on reliability and availability.
    """

    def __init__(self):
        self._layers: dict[LayerLevel, ControlLayer] = {}

    def register(self, layer: ControlLayer) -> None:
        """Register a control layer."""
        self._layers[layer.level] = layer
        logger.info(f"Registered layer: {layer}")

    def get(self, level: LayerLevel) -> Optional[ControlLayer]:
        """Get a specific layer by level."""
        return self._layers.get(level)

    def get_available(self) -> list[ControlLayer]:
        """Get all available layers, ordered by level (most reliable first)."""
        available = []
        for level in sorted(self._layers.keys()):
            layer = self._layers[level]
            try:
                if layer.is_available():
                    available.append(layer)
            except Exception as e:
                logger.warning(f"Layer availability check failed for {layer}: {e}")
        return available

    def select_best(self, preferred: Optional[LayerLevel] = None) -> Optional[ControlLayer]:
        """
        Select the best available layer.
        Prefers the specified level if available, otherwise falls back
        to the most reliable available layer (lowest level number).
        """
        available = self.get_available()
        if not available:
            return None

        if preferred:
            for layer in available:
                if layer.level == preferred:
                    return layer

        return available[0]  # Most reliable available

    def escalate(self, current_level: LayerLevel) -> Optional[ControlLayer]:
        """
        Get the next available layer above the current one.
        Used for failure recovery via layer escalation.
        """
        available = self.get_available()
        for layer in available:
            if layer.level > current_level:
                return layer
        return None

    @property
    def registered_count(self) -> int:
        return len(self._layers)

    @property
    def available_count(self) -> int:
        return len(self.get_available())
