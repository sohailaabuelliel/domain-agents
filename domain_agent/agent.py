"""The agent: one engine for every domain.

Flow (each numbered step is emitted as a trace event the UI can display):
  1 input guardrails -> 2 ReAct tool loop (think/search) -> 3 coverage check -> 4 structured answer
  -> 5 citation/grounding verification (+1 repair try) -> 6 safety-reviewer agent -> 7 confidence score
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field

from .config import DomainConfig, LLMConfig
from .guardrails import check_input, compute_confidence, uncovered_terms, verify_answer
from .llm import LLM, LLMError, Msg, make_llm
from .retrieval import Retriever, find_entities, make_retriever
from .tools import SPECS, ToolContext, run_tool

MAX_STEPS = 3


# ---------------------------------------------------------------- output schema (the fixed response format)
class Finding(BaseModel):
    title: str
    detail: str = Field(description="1-3 sentences, every claim followed by a source id like [S1]")
    severity: Optional[Literal["high", "moderate", "low", "info"]] = None
    sources: list[str] = Field(default_factory=list)


class Answer(BaseModel):
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    limitations: str = ""


class Review(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list)


Emit = Callable[[dict], None]


@dataclass
class AgentResult:
    status: str                      # answered | refused | no_evidence | error
    answer: dict | None = None
    message: str = ""
    sources: list[dict] = field(default_factory=list)
    confidence: dict | None = None
    review: dict | None = None
    trace: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    elapsed: float = 0.0

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class DomainAgent:
    def __init__(self, domain: DomainConfig, llm: LLM, retriever: Retriever):
        self.domain, self.llm, self.retriever = domain, llm, retriever
        self.tool_specs = [SPECS[t] for t in domain.tools if t in SPECS]

    # ------------------------------------------------------------ prompts
    def _system(self, lang: str) -> str:
        d = self.domain
        parts = [d.system_prompt]
        parts.append(f"\nAnswer language: {'Arabic (العربية الفصحى المبسطة); keep drug names in English in brackets' if lang == 'ar' else 'English'}. "
                     "Search queries must always be in English.")
        if d.few_shots:
            ex = "\n".join(f"Q: {s['question']}\nA: {s['answer'].strip()}" for s in d.few_shots)
            parts.append("\nEXAMPLES of the required JSON answer style:\n" + ex)
        return "\n".join(parts)

    @staticmethod
    def detect_language(text: str) -> str:
        arabic = sum("\u0600" <= c <= "\u06FF" for c in text)
        return "ar" if arabic > max(3, len(text) * 0.3) else "en"

    # ------------------------------------------------------------ main
    def ask(self, question: str, language: str = "auto", history: list[dict] | None = None,
            review: bool = True, emit: Emit | None = None, memory_note: str = "") -> AgentResult:
        t0 = time.time()
        trace: list[dict] = []
        usage = {"prompt_tokens": 0, "output_tokens": 0, "llm_calls": 0}

        def ev(kind: str, **kw):
            e = {"type": kind, "t": round(time.time() - t0, 2), **kw}
            trace.append(e)
            if emit:
                emit(e)

        def add_usage(r):
            usage["prompt_tokens"] += r.prompt_tokens; usage["output_tokens"] += r.output_tokens; usage["llm_calls"] += 1

        lang = self.detect_language(question) if language == "auto" else language
        verdict = check_input(question, self.domain)
        ev("guard_input", ok=verdict.allowed, rule=verdict.rule or "pass")
        if not verdict.allowed:
            return AgentResult("refused", message=verdict.message, trace=trace, elapsed=round(time.time() - t0, 2),
                               confidence={"score": 0.0, "level": "n/a", "parts": {}, "reasons": [f"Blocked by guardrail: {verdict.rule}"]})

        ctx = ToolContext(self.retriever, self.domain.aliases)
        system = self._system(lang)
        if memory_note:
            system += f"\n\nUser preferences to respect: {memory_note}"
        msgs: list[Msg] = []
        for h in (history or [])[-6:]:
            msgs.append(Msg(h["role"] if h["role"] in ("user", "assistant") else "user", h.get("text", "")))
        msgs.append(Msg("user", question))

        try:
            # ---- 2. ReAct loop
            for step in range(MAX_STEPS):
                r = self.llm.chat(system + "\nFirst gather evidence with your tools: ONE well-aimed search per entity is usually enough, do not repeat similar searches. When you have enough, reply with the single word DONE.",
                                  msgs, tools=self.tool_specs)
                add_usage(r)
                if not r.tool_calls:
                    ev("thought", text=(r.text or "").strip()[:200] or "Enough evidence gathered.")
                    break
                msgs.append(Msg("assistant", r.text, tool_calls=r.tool_calls, raw=r.raw))
                for call in r.tool_calls:
                    ev("action", tool=call.name, args=call.args)
                    obs = run_tool(call.name, call.args, ctx)
                    ev("observation", tool=call.name, n_sources=len(ctx.evidence), preview=obs[:160].replace("\n", " "))
                    msgs.append(Msg("tool", obs, tool_name=call.name, tool_call_id=call.id))
            hits = list(ctx.evidence.values())

            # ---- 3. coverage check ("no evidence found" instead of guessing)
            unknown = uncovered_terms(question, getattr(self.retriever, "bm25", None)) if hasattr(self.retriever, "bm25") else []
            best = max((h.vector for h in hits if h.via != "pubmed_live"), default=0.0)
            if hits and any(h.via == "pubmed_live" for h in hits):
                best = max(best, 0.6)
            covered = bool(hits) and best >= self.domain.min_score and not unknown
            ev("coverage", best_similarity=round(best, 3), threshold=self.domain.min_score, unknown_terms=unknown, covered=covered)
            if not covered:
                why = (f"I found no information about “{', '.join(unknown)}” in the knowledge base." if unknown
                       else "The knowledge base has no passage relevant enough to answer this reliably.")
                msg = why + " I won't guess — no evidence found. " + ("Try rephrasing, or ask about a topic covered by the documents." )
                return AgentResult("no_evidence", message=msg, trace=trace, usage=usage, elapsed=round(time.time() - t0, 2),
                                   sources=[],
                                   confidence={"score": 0.0, "level": "n/a", "parts": {"retrieval": 0.0}, "reasons": ["No evidence found in the knowledge base"]})

            # ---- 4. structured answer
            evidence_block = "\n\n".join(f"[{sid}] {h.chunk.label}\n{h.chunk.text[:1100]}" for sid, h in ctx.evidence.items())
            final_msgs = ([Msg("user", f"QUESTION: {question}\n\nSOURCES (the only facts you may use):\n{evidence_block}\n\nReturn the JSON answer.")])
            ans, ver = self._answer_and_verify(system, final_msgs, ctx, ev, add_usage)

            # ---- 5b. an answer that cites nothing is not an answer: say "no evidence" instead of showing filler
            if self.domain.guardrails.get("require_citations", True) and not ver.cited_ids:
                ev("no_evidence", reason="answer cited no source")
                return AgentResult("no_evidence", message="I couldn't find this in the knowledge base, so I won't guess — no evidence found. Try rephrasing, or ask about a topic covered by the documents.",
                                   trace=trace, usage=usage, elapsed=round(time.time() - t0, 2),
                                   confidence={"score": 0.0, "level": "n/a", "parts": {}, "reasons": ["Answer contained no cited evidence"]})

            # ---- 6. safety reviewer (second agent)
            rev_out = None
            if review:
                rev_out = self._review(ans, ctx, ev, add_usage)
                if rev_out and not rev_out["approved"]:
                    note = "Reviewer flagged: " + "; ".join(rev_out["issues"][:3])
                    ans["limitations"] = (ans.get("limitations", "") + " " + note).strip()

            # ---- 7. confidence
            conf = compute_confidence(hits, ver, len(ans.get("findings", [])), unknown, self.domain.min_score)
            if rev_out and not rev_out["approved"]:
                conf.score = round(conf.score * 0.8, 2); conf.reasons.append("Safety reviewer raised issues")
                conf.level = "high" if conf.score >= 0.75 else "medium" if conf.score >= 0.5 else "low"
            ev("confidence", score=conf.score, level=conf.level)

            return AgentResult("answered", answer=ans, sources=self._sources(ctx, ver.cited_ids), review=rev_out,
                               confidence={"score": conf.score, "level": conf.level, "parts": conf.parts, "reasons": conf.reasons},
                               trace=trace, usage=usage, elapsed=round(time.time() - t0, 2),
                               message=self.domain.disclaimer)
        except LLMError as e:
            ev("error", text=str(e))
            return AgentResult("error", message=f"The model service is unavailable right now: {e}", trace=trace, usage=usage, elapsed=round(time.time() - t0, 2))

    # ------------------------------------------------------------ helpers
    def _answer_and_verify(self, system, msgs, ctx, ev, add_usage):
        schema = Answer.model_json_schema()
        attempt_msgs = list(msgs)
        ans: dict = {}
        ver = None
        for attempt in range(2):
            r = self.llm.chat(system, attempt_msgs, schema=schema)
            add_usage(r)
            try:
                ans = Answer.model_validate_json(r.text).model_dump()
            except Exception:  # noqa: BLE001
                ans = {"summary": r.text[:400], "findings": [], "limitations": "The model returned an invalid format."}
            ver = verify_answer(ans, ctx.evidence, self.domain.guardrails.get("require_citations", True))
            ev("verify", attempt=attempt + 1, valid=ver.valid_citations, unknown_ids=ver.unknown_ids, uncited=ver.uncited_findings,
               weak=len(ver.weak_findings), support=round(ver.support, 2))
            if ver.valid_citations and not ver.weak_findings:
                break
            problems = []
            if ver.unknown_ids: problems.append(f"you cited non-existent sources {ver.unknown_ids}")
            if ver.uncited_findings: problems.append(f"{ver.uncited_findings} finding(s) have no source ids")
            if ver.weak_findings: problems.append(f"findings #{[i + 1 for i in ver.weak_findings]} contain statements not found in their sources")
            attempt_msgs = msgs + [Msg("assistant", r.text), Msg("user", "Fix these problems and return the corrected JSON: " + "; ".join(problems) +
                                                                " Use only the provided sources and cite each finding.")]
        # final safety net: drop findings that are still uncited / unsupported rather than show them
        assert ver is not None
        if not ver.valid_citations or ver.weak_findings:
            keep = []
            for i, f in enumerate(ans.get("findings", [])):
                ids = [s for s in f.get("sources", []) if s in ctx.evidence]
                if ids and i not in ver.weak_findings:
                    f["sources"] = ids; keep.append(f)
            dropped = len(ans.get("findings", [])) - len(keep)
            if dropped:
                ans["findings"] = keep
                ans["limitations"] = (ans.get("limitations", "") + f" {dropped} statement(s) removed because they could not be verified against the sources.").strip()
            ver = verify_answer(ans, ctx.evidence)
            ev("verify_pruned", dropped=dropped)
        for f in ans.get("findings", []):  # normalise: sources = ids actually cited
            f["sources"] = sorted({s for s in f.get("sources", []) if s in ctx.evidence})
        return ans, ver

    def _review(self, ans: dict, ctx: ToolContext, ev, add_usage) -> dict | None:
        focus = self.domain.reviewer_focus or ("(a) an individual dose/therapy recommendation, (b) a diagnosis, (c) severity stated without support, "
                                               "(d) claims not in the sources, (e) overconfident wording")
        prompt = ("You are an independent SAFETY REVIEWER for the " + self.domain.display_name + ". Check the draft answer against the sources for: " + focus +
                  ". Return approved=true only if none apply; otherwise list short issues.")
        src = "\n".join(f"[{k}] {h.chunk.text[:1100]}" for k, h in ctx.evidence.items())
        try:
            r = self.llm.chat(prompt, [Msg("user", f"DRAFT:\n{json.dumps(ans, ensure_ascii=False)}\n\nSOURCES:\n{src}")], schema=Review.model_json_schema())
            add_usage(r)
            out = Review.model_validate_json(r.text).model_dump()
        except Exception as e:  # noqa: BLE001
            ev("review", approved=True, issues=[f"reviewer unavailable ({type(e).__name__})"])
            return None
        ev("review", approved=out["approved"], issues=out["issues"])
        return out

    @staticmethod
    def _sources(ctx: ToolContext, only: list[str] | None = None) -> list[dict]:
        out = []
        for sid, h in ctx.evidence.items():
            if only is not None and sid not in only:
                continue
            c = h.chunk
            out.append({"id": sid, "title": c.title, "section": c.section, "doc_type": c.doc_type, "entity": c.entity,
                        "source": c.source, "url": c.url, "similarity": round(h.vector, 3), "excerpt": c.text[:420]})
        return out


def build_agent(domain: DomainConfig, llm_cfg: LLMConfig | None = None, backend: str = "hybrid") -> DomainAgent:
    llm = make_llm(llm_cfg)
    return DomainAgent(domain, llm, make_retriever(domain, llm, backend))
