"""
JAMES — Justified Autonomous Machine for Execution & Systems

A self-evolving execution engine with deterministic control,
layered authority, and continuous improvement.

Plan -> Validate -> Execute -> Verify -> Learn -> Improve -> Repeat
"""

__version__ = "1.0.0"
__codename__ = "JAMES"


def get_orchestrator(**kwargs):
    """Lazy factory to avoid circular/heavy imports at module level."""
    from james.orchestrator import Orchestrator
    return Orchestrator(**kwargs)


__all__ = ["get_orchestrator", "__version__", "__codename__"]
