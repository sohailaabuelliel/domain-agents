"""Guardrails: input screening, prompt-injection defence, grounding verification and confidence scoring.

Everything here is deterministic Python (no LLM call), so it is cheap, testable and cannot be talked out of
its decisions by the user's text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import DomainConfig
from .retrieval import BM25, Hit, tokenize

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompt)",
    r"disregard (the )?(system|previous) (prompt|instructions)",
    r"(reveal|show|print|repeat) (your |the )?(system|hidden|initial) (prompt|instructions)",
    r"you are now (?:a |an )?(?!pharmac)",
    r"\bjailbreak\b|\bDAN mode\b|developer mode",
    r"تجاهل (كل )?(التعليمات|القواعد)|انس[ىي] (كل )?(التعليمات|القواعد)",
]


@dataclass
class InputVerdict:
    allowed: bool
    kind: str = "ok"            # ok | blocked_intent | prompt_injection | empty
    rule: str = ""
    message: str = ""


def check_input(question: str, domain: DomainConfig) -> InputVerdict:
    q = (question or "").strip()
    if not q:
        return InputVerdict(False, "empty", "empty", "Please type a question.")
    for pat in INJECTION_PATTERNS:
        if re.search(pat, q, re.I):
            return InputVerdict(False, "prompt_injection", "prompt_injection",
                                "I can't follow instructions that try to change my rules. Ask me a question about the domain instead.")
    for intent in domain.blocked_intents:
        for pat in intent.get("patterns", []):
            if re.search(pat, q, re.I):
                return InputVerdict(False, "blocked_intent", intent["id"], intent["response"].strip())
    return InputVerdict(True)


def uncovered_terms(question: str, bm25: BM25) -> list[str]:
    """Proper-noun-looking words in the question that appear NOWHERE in the knowledge base.

    Catches invented / unknown product names ("Zentrava") that a pure similarity score would let through,
    because "side effects of <anything>" is semantically close to every adverse-reaction passage.
    """
    out = []
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", question)
    for i, w in enumerate(words):
        starts_sentence = question.find(w) == 0
        if (w[0].isupper() and not starts_sentence) or (w[0].isupper() and w.lower() not in bm25.idf and not starts_sentence):
            if w.lower() not in bm25.idf and w.lower() not in {t.lower() for t in out}:
                out.append(w)
    return out


# ---------------------------------------------------------------- grounding / faithfulness
def _support(text: str, sources: list[str]) -> float:
    """Share of the claim's content words that occur in the cited source text (0..1)."""
    claim = set(tokenize(text))
    if not claim:
        return 1.0
    src = set()
    for s in sources:
        src.update(tokenize(s))
    return len(claim & src) / len(claim)


@dataclass
class Verification:
    valid_citations: bool
    unknown_ids: list[str] = field(default_factory=list)
    uncited_findings: int = 0
    weak_findings: list[int] = field(default_factory=list)   # indexes whose text is poorly supported
    support: float = 1.0
    cited_ids: list[str] = field(default_factory=list)


def verify_answer(answer: dict, evidence: dict[str, Hit], require_citations: bool = True) -> Verification:
    ids_re = re.compile(r"S\d+")
    cited: list[str] = []
    unknown: list[str] = []
    uncited = 0
    weak: list[int] = []
    supports: list[float] = []
    for i, f in enumerate(answer.get("findings", [])):
        ids = [s for s in f.get("sources", []) if ids_re.fullmatch(str(s))]
        ids += [s for s in ids_re.findall(f.get("detail", "")) if s not in ids]
        if not ids:
            uncited += 1
            continue
        known = [s for s in ids if s in evidence]
        unknown += [s for s in ids if s not in evidence]
        cited += known
        if known:
            sup = _support(f.get("detail", ""), [evidence[s].chunk.text for s in known])
            supports.append(sup)
            if sup < 0.35:
                weak.append(i)
    total = len(answer.get("findings", []))
    ok = not unknown and (uncited == 0 or not require_citations)
    return Verification(ok, sorted(set(unknown)), uncited, weak, sum(supports) / len(supports) if supports else (1.0 if not total else 0.0), sorted(set(cited)))


# ---------------------------------------------------------------- confidence
@dataclass
class Confidence:
    score: float
    level: str
    parts: dict[str, float]
    reasons: list[str]


def compute_confidence(hits: list[Hit], ver: Verification, n_findings: int, uncovered: list[str], min_score: float) -> Confidence:
    best = max((h.vector for h in hits), default=0.0)
    retrieval = max(0.0, min(1.0, (best - min_score) / (0.80 - min_score)))        # 0 at threshold, 1 at 0.80
    ncited = len(ver.cited_ids)
    breadth = min(1.0, ncited / 3)                                                  # 3+ distinct sources = full marks
    citation = 0.0 if n_findings == 0 else max(0.0, 1 - ver.uncited_findings / n_findings)
    grounding = ver.support
    score = 0.35 * retrieval + 0.20 * breadth + 0.20 * citation + 0.25 * grounding
    reasons = []
    if uncovered:
        score *= 0.4; reasons.append(f"Terms not found in the knowledge base: {', '.join(uncovered)}")
    if ver.unknown_ids:
        score *= 0.5; reasons.append("Answer cited sources that were not retrieved")
    if ver.weak_findings:
        score *= 0.85; reasons.append(f"{len(ver.weak_findings)} finding(s) only weakly supported by their sources")
    if ncited <= 1 and n_findings:
        reasons.append("Rests on a single source")
    score = round(max(0.0, min(1.0, score)), 2)
    level = "high" if score >= 0.75 else "medium" if score >= 0.5 else "low"
    return Confidence(score, level, {"retrieval": round(retrieval, 2), "breadth": round(breadth, 2), "citations": round(citation, 2), "grounding": round(grounding, 2)}, reasons)
