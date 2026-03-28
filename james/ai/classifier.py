"""
JAMES Intent Classifier — Fast, rule-based pre-classification.

Classifies user messages in <1ms to enable:
  - Short-circuiting the LLM for trivial messages (greetings, direct commands)
  - Providing intent hints to the LLM for better routing
  - Selecting optimal model tier via the Model Router (future)
"""

from __future__ import annotations

import re
from typing import Optional


class IntentClassifier:
    """
    Fast, rule-based intent classification.
    Returns (intent, confidence) in <1ms per call.
    """

    INTENTS = [
        "greeting",
        "farewell",
        "simple_question",
        "memory_query",
        "memory_save",
        "command",
        "web_search",
        "file_operation",
        "process_management",
        "code_generation",
        "analysis",
        "system_control",
        "time_query",
        "math",
        "unknown",
    ]

    # Rules evaluated in order — first match wins.
    # (pattern_type, pattern, intent, confidence)
    _RULES = [
        # ── Direct command prefixes (highest confidence) ──────
        ("prefix", "!", "command", 1.0),
        ("prefix", "$", "command", 1.0),
        ("prefix", "http://", "web_search", 0.95),
        ("prefix", "https://", "web_search", 0.95),

        # ── Greetings / Farewells ─────────────────────────────
        ("regex", r"^(hi|hello|hey|yo|sup|howdy|greetings|good\s+(morning|afternoon|evening))\b", "greeting", 0.92),
        ("regex", r"^(bye|goodbye|see\s+(ya|you)|later|good\s*night|cya|peace)\b", "farewell", 0.92),
        ("regex", r"^(thanks|thank\s+you|ty|thx|cheers)\b", "greeting", 0.85),

        # ── Time queries ──────────────────────────────────────
        ("regex", r"\b(what\s+time|current\s+time|what\'?s?\s+the\s+time|date\s+today)\b", "time_query", 0.90),

        # ── Memory queries (personal facts) ───────────────────
        ("keywords", {"my favorite", "my name", "my age", "do you remember", "remember me",
                      "what do you know about me", "my preference", "my email", "about me"}, "memory_query", 0.88),
        ("regex", r"\b(what\s+is\s+my|what\'?s?\s+my|do\s+you\s+know\s+my|tell\s+me\s+my)\b", "memory_query", 0.88),

        # ── Memory save ───────────────────────────────────────
        ("regex", r"^(remember|save|store|note|record)\b", "memory_save", 0.85),
        ("keywords", {"remember that", "save this", "note that", "store the fact"}, "memory_save", 0.85),

        # ── File operations ───────────────────────────────────
        ("keywords", {"read file", "write file", "create file", "delete file", "list files",
                      "show file", "open file", "edit file", "file contents", "cat ",
                      "search files", "find file", "copy file", "move file"}, "file_operation", 0.85),

        # ── Process management ────────────────────────────────
        ("keywords", {"list process", "running process", "kill process", "stop process",
                      "task manager", "tasklist", "taskkill", "running programs"}, "process_management", 0.85),

        # ── Web search ────────────────────────────────────────
        ("keywords", {"search for", "search the web", "google", "look up", "find online",
                      "browse to", "web search", "search online"}, "web_search", 0.82),

        # ── Code generation ───────────────────────────────────
        ("keywords", {"write code", "write a function", "write a script", "implement",
                      "code for", "generate code", "write python", "write javascript",
                      "create a class", "debug this"}, "code_generation", 0.80),

        # ── Analysis / Reasoning ──────────────────────────────
        ("keywords", {"analyze", "explain", "compare", "evaluate", "review",
                      "summarize", "what are the differences", "pros and cons"}, "analysis", 0.75),

        # ── System control ────────────────────────────────────
        ("keywords", {"shutdown", "restart", "reboot", "system info", "disk space",
                      "cpu usage", "ram usage", "uptime", "services"}, "system_control", 0.78),

        # ── Shell commands (lower confidence — let LLM decide) ─
        ("keywords", {"run", "execute", "start", "stop", "install",
                      "pip install", "npm install"}, "command", 0.65),

        # ── Simple questions (broad catch) ────────────────────
        ("regex", r"^(what|who|where|when|how|why|which|can\s+you|is\s+there)\b.*\?$", "simple_question", 0.55),

        # ── Math ──────────────────────────────────────────────
        ("regex", r"^\d+[\s]*[\+\-\*/\^%][\s]*\d+", "math", 0.90),
        ("keywords", {"calculate", "compute", "what is", "how much is"}, "math", 0.50),
    ]

    # Short-circuitable intents → direct response without LLM
    GREETING_RESPONSES = [
        "Hello! I'm JAMES, your autonomous system orchestrator. How can I help you today?",
        "Hey! What would you like me to do?",
        "Hi there! I'm ready to help. What's on your mind?",
    ]
    FAREWELL_RESPONSES = [
        "Goodbye! I'll be here when you need me.",
        "See you later! JAMES standing by.",
        "Take care! I'll keep running in the background.",
    ]

    def classify(self, message: str) -> tuple[str, float]:
        """
        Classify a message into an intent.

        Returns:
            (intent: str, confidence: float) — confidence 0.0 to 1.0
        """
        msg = message.strip()
        msg_lower = msg.lower()

        for rule_type, pattern, intent, confidence in self._RULES:
            if rule_type == "prefix":
                if msg_lower.startswith(pattern):
                    return intent, confidence

            elif rule_type == "regex":
                if re.search(pattern, msg_lower):
                    return intent, confidence

            elif rule_type == "keywords":
                for kw in pattern:
                    if kw in msg_lower:
                        return intent, confidence

        return "unknown", 0.0

    def get_short_circuit_response(self, intent: str, confidence: float) -> Optional[str]:
        """
        For high-confidence trivial intents, return a direct response
        without invoking the LLM at all.

        Returns None if the intent should go to the LLM.
        """
        if confidence < 0.85:
            return None

        if intent == "greeting":
            import random
            return random.choice(self.GREETING_RESPONSES)
        if intent == "farewell":
            import random
            return random.choice(self.FAREWELL_RESPONSES)

        return None

    def get_intent_hint(self, intent: str, confidence: float) -> str:
        """
        Generate a hint string to prepend to the LLM context,
        helping it route the request correctly.
        """
        if confidence < 0.4:
            return ""

        hints = {
            "memory_query": "The user is asking about personal information. Check long_term_memory first.",
            "memory_save": "The user wants to save information to memory. Use the memory_save tool.",
            "time_query": "The user is asking about the current time. Use the current_time tool.",
            "file_operation": "The user wants a file operation. Use file_read/file_write/file_list tools.",
            "process_management": "The user wants to manage processes. Use process_list/process_kill tools.",
            "web_search": "The user wants to search the web. Use the web_search tool.",
            "command": "The user wants to run a system command. Use command execution.",
            "system_control": "The user wants system information. Use system_info/disk_usage/cpu_info tools.",
            "code_generation": "The user wants code written. Respond with a chat message containing the code.",
            "analysis": "The user wants analysis. Respond with a detailed chat message.",
        }
        return hints.get(intent, "")
