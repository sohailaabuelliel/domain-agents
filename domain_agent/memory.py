"""Conversation memory (Bonus): remembers user preferences within a session and feeds them to the agent.

Deliberately rule-based (no extra LLM call): it is free, instant, deterministic and unit-testable. Each rule maps a
phrase the user types ("answer in Arabic", "keep it short", "I'm a pharmacist") to a stored preference. Preferences
are injected into the agent's system prompt as ``memory_note``; they can never loosen guardrails because the note is
appended AFTER the domain rules and input screening happens before the agent ever sees it.

Storage is in-process per ``session_id`` (a random id the browser creates); nothing is written to disk.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

# (key, regex, value-or-callable, human label)
RULES: list[tuple[str, str, object, str]] = [
    ("language", r"\b(answer|reply|respond|write)\b.{0,20}\b(in )?arabic\b|بالعربي|رد (عليا )?بالعربي", "Arabic", "Reply language"),
    ("language", r"\b(answer|reply|respond|write)\b.{0,20}\b(in )?english\b|بالانجليزي|بالإنجليزي", "English", "Reply language"),
    ("length", r"\b(keep it|be)\b.{0,12}\b(short|brief|concise)\b|\bshort answers?\b|باختصار|اختصر", "short", "Answer length"),
    ("length", r"\b(more detail|in detail|detailed|elaborate)\b|بالتفصيل|اشرح أكتر", "detailed", "Answer length"),
    ("audience", r"\bi(?:'| a)?m an? (pharmacist|doctor|physician|nurse|student|manager|analyst|investor|marketer)\b|\bi am an? (pharmacist|doctor|physician|nurse|student|manager|analyst|investor|marketer)\b",
     lambda m: next(g for g in m.groups() if g), "User role"),
    ("audience", r"أنا (صيدلي|صيدلانية|دكتور|دكتورة|طبيب|ممرض|طالب|طالبة)", lambda m: m.group(1), "User role"),
    ("format", r"\b(use|give me|show)\b.{0,12}\b(bullet|bullets|bullet points|a list)\b|نقاط", "bullet points", "Format"),
    ("format", r"\b(use|give me|show)\b.{0,12}\b(a )?table\b|في جدول", "a table where useful", "Format"),
    ("name", r"\bcall me ([A-Z][a-zA-Z]{1,20})\b|\bmy name is ([A-Z][a-zA-Z]{1,20})\b", lambda m: next(g for g in m.groups() if g), "Name"),
    ("expertise", r"\b(explain|explained)\b.{0,15}\b(simply|like i'?m (5|five)|in simple terms|for a layperson)\b|ببساطة", "plain language", "Explanation level"),
    ("expertise", r"\b(technical|expert level|advanced)\b.{0,10}\b(language|terms|answer|detail)\b", "technical", "Explanation level"),
]
FORGET = re.compile(r"\b(forget (my )?(preferences|everything)|clear (my )?memory|reset (my )?preferences)\b|انسى (كل حاجة|تفضيلاتي)", re.I)


@dataclass
class Memory:
    prefs: dict[str, dict] = field(default_factory=dict)   # key -> {value, label}
    updated: float = field(default_factory=time.time)

    def learn(self, text: str) -> list[str]:
        """Update from a user message; returns human-readable descriptions of what changed."""
        if FORGET.search(text or ""):
            changed = [f"forgot {len(self.prefs)} preference(s)"] if self.prefs else []
            self.prefs.clear()
            return changed
        changed = []
        for key, pat, val, label in RULES:
            m = re.search(pat, text or "", re.I)
            if not m:
                continue
            v = val(m) if callable(val) else val
            if self.prefs.get(key, {}).get("value") != v:
                self.prefs[key] = {"value": v, "label": label}
                changed.append(f"{label}: {v}")
        if changed:
            self.updated = time.time()
        return changed

    def note(self) -> str:
        """Text for the agent's system prompt."""
        p = {k: v["value"] for k, v in self.prefs.items()}
        bits = []
        if "language" in p: bits.append(f"reply in {p['language']}")
        if p.get("length") == "short": bits.append("keep the answer short (summary plus at most 3 findings)")
        if p.get("length") == "detailed": bits.append("give more detail in the findings")
        if "audience" in p: bits.append(f"the user is a {p['audience']}; adapt the vocabulary accordingly")
        if "format" in p: bits.append(f"prefer {p['format']}")
        if "expertise" in p: bits.append(f"explain in {p['expertise']}")
        if "name" in p: bits.append(f"address the user as {p['name']}")
        if not bits:
            return ""
        return ("; ".join(bits) + ". These are style preferences only — they never override the safety rules, the source-only rule, or citations.")

    def public(self) -> list[dict]:
        return [{"key": k, **v} for k, v in self.prefs.items()]


class MemoryStore:
    """Per-session memory with a size cap and 6-hour expiry."""

    def __init__(self, max_sessions: int = 500, ttl: float = 6 * 3600):
        self._d: dict[str, Memory] = {}
        self._lock = threading.Lock()
        self.max, self.ttl = max_sessions, ttl

    def get(self, session_id: str) -> Memory:
        sid = (session_id or "anon")[:64]
        with self._lock:
            now = time.time()
            for k in [k for k, m in self._d.items() if now - m.updated > self.ttl]:
                del self._d[k]
            if sid not in self._d:
                if len(self._d) >= self.max:
                    del self._d[min(self._d, key=lambda k: self._d[k].updated)]
                self._d[sid] = Memory()
            return self._d[sid]

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._d.pop((session_id or "anon")[:64], None)
