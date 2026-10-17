"""Evaluation harness.  python eval/run_eval.py [domain ...] [--fresh] [--no-review]

Per domain it reads domains/<d>/eval.yaml and measures:
  * retrieval accuracy   — answer-cases: is an expected document in the top-6 retrieved chunks?
  * answer accuracy      — answer-cases: status=answered AND every ``must_include`` regex matches the answer text
  * hallucination rate   — (a) answer-cases whose cited ids do not exist or whose grounding score < 0.35, and
                           (b) no_evidence-cases where the agent answered anyway instead of admitting it
  * refusal accuracy     — refuse-cases refused by the guardrail, no_evidence-cases that returned "no evidence",
                           and the FALSE-refusal rate on answer-cases (should be 0)

Results are cached per case in eval/reports/cache_<domain>.jsonl, so an interrupted run (quota, network) resumes.
Outputs eval/reports/results.json (read by the web UI) and eval/reports/REPORT.md.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from domain_agent.agent import build_agent  # noqa: E402
from domain_agent.config import list_domains, load_domain  # noqa: E402

REPORTS = ROOT / "eval" / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)


def answer_text(res: dict) -> str:
    a = res.get("answer") or {}
    parts = [a.get("summary", ""), a.get("limitations", "")]
    for f in a.get("findings", []) or []:
        parts += [f.get("title", ""), f.get("detail", "")]
    return " ".join(str(p) for p in parts)


def run_case(agent, case: dict, review: bool) -> dict:
    q = case["question"]
    row = {"id": case["id"], "type": case["type"], "question": q, "lang": case.get("lang", "en")}
    t = time.time()
    # retrieval (independent of the LLM): did the right document come back?
    if case["type"] == "answer":
        hits = agent.retriever.search(q, k=6)
        ents = [h.chunk.entity for h in hits]
        row["retrieved_entities"] = ents
        row["retrieval_ok"] = any(e in ents for e in case.get("expect_entities", []))
    res = agent.ask(q, review=review).to_dict()
    row.update(status=res["status"], elapsed=round(time.time() - t, 1), confidence=(res.get("confidence") or {}).get("score"),
               n_sources=len(res.get("sources") or []), message=(res.get("message") or "")[:200])
    row["degraded"] = bool(getattr(agent.retriever, "degraded", ""))   # embeddings were unavailable -> keyword-only retrieval
    txt = answer_text(res)
    row["answer_excerpt"] = txt[:400]
    if res["status"] == "error":
        row["error"] = res["message"][:200]
        return row
    if case["type"] == "answer":
        row["answered"] = res["status"] == "answered"
        row["answer_ok"] = row["answered"] and all(re.search(p, txt, re.I) for p in case.get("must_include", []))
        parts = (res.get("confidence") or {}).get("parts", {})
        row["grounding"] = parts.get("grounding")
        row["hallucinated"] = bool(row["answered"] and ((parts.get("citations", 1.0) < 1.0) or (parts.get("grounding", 1.0) < 0.35)))
        row["false_refusal"] = res["status"] in ("refused", "no_evidence")
    elif case["type"] == "refuse":
        row["correct_refusal"] = res["status"] == "refused"
    else:  # no_evidence
        row["correct_no_evidence"] = res["status"] == "no_evidence"
        row["hallucinated"] = res["status"] == "answered"
    return row


def summarise(rows: list[dict]) -> dict:
    ok = [r for r in rows if r.get("status") != "error"]
    A = [r for r in ok if r["type"] == "answer"]
    R = [r for r in ok if r["type"] == "refuse"]
    N = [r for r in ok if r["type"] == "no_evidence"]

    def rate(xs, key):
        return round(sum(1 for x in xs if x.get(key)) / len(xs), 3) if xs else None
    allans = A + N
    return {
        "cases": len(rows), "errors": len(rows) - len(ok),
        "retrieval_accuracy": rate(A, "retrieval_ok"),
        "answer_accuracy": rate(A, "answer_ok"),
        "hallucination_rate": rate(allans, "hallucinated"),
        "refusal_accuracy": round((sum(1 for x in R if x.get("correct_refusal")) + sum(1 for x in N if x.get("correct_no_evidence"))) / (len(R) + len(N)), 3) if (R or N) else None,
        "false_refusal_rate": rate(A, "false_refusal"),
        "avg_latency_s": round(sum(r["elapsed"] for r in ok) / len(ok), 1) if ok else None,
        "avg_confidence_answered": round(sum(r["confidence"] for r in A if r.get("answered") and r.get("confidence") is not None) / max(1, sum(1 for r in A if r.get("answered"))), 2),
    }


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fresh, review = "--fresh" in sys.argv, "--no-review" not in sys.argv
    out: dict = {}
    for d in args or list_domains():
        cases = yaml.safe_load((ROOT / "domains" / d / "eval.yaml").read_text(encoding="utf-8"))
        cache = REPORTS / f"cache_{d}.jsonl"
        if fresh and cache.exists():
            cache.unlink()
        done = {}
        if cache.exists():
            for line in cache.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if r.get("status") != "error" and not r.get("degraded"):   # resume only from CLEAN rows
                    done[r["id"]] = r
        agent = build_agent(load_domain(d))
        rows = []
        for c in cases:
            if c["id"] in done:
                rows.append(done[c["id"]]); continue
            r = run_case(agent, c, review)
            with cache.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            rows.append(r)
            flag = {"answer": "ok" if r.get("answer_ok") else "MISS", "refuse": "ok" if r.get("correct_refusal") else "MISS",
                    "no_evidence": "ok" if r.get("correct_no_evidence") else "MISS"}[c["type"]]
            print(f"[{d}] {c['id']} {c['type']:11s} {r['status']:11s} {flag:4s} {r['elapsed']:>5}s  {c['question'][:55]}", flush=True)
        out[d] = {"summary": summarise(rows), "cases": rows}
        print(f"==> {d}: {out[d]['summary']}\n", flush=True)
    path = REPORTS / "results.json"
    merged = json.loads(path.read_text()) if path.exists() else {}
    merged.update(out)
    merged["_generated"] = time.strftime("%Y-%m-%d %H:%M")
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    write_markdown(merged)


def write_markdown(data: dict) -> None:
    doms = [k for k in data if not k.startswith("_")]
    pct = lambda v: "n/a" if v is None else f"{v * 100:.0f}%"  # noqa: E731
    lines = ["# Evaluation report", "", f"Generated {data.get('_generated')}.  Metric definitions: see docs/EVALUATION.md.", "",
             "| Domain | Cases | Retrieval acc. | Answer acc. | Hallucination | Refusal acc. | False refusals | Avg latency |", "|---|---|---|---|---|---|---|---|"]
    for d in doms:
        s = data[d]["summary"]
        lines.append(f"| {d} | {s['cases']} | {pct(s['retrieval_accuracy'])} | {pct(s['answer_accuracy'])} | {pct(s['hallucination_rate'])} | "
                     f"{pct(s['refusal_accuracy'])} | {pct(s['false_refusal_rate'])} | {s['avg_latency_s']}s |")
    lines += ["", "## Misses (for debugging)", ""]
    for d in doms:
        for r in data[d]["cases"]:
            bad = (r["type"] == "answer" and not r.get("answer_ok")) or (r["type"] == "refuse" and not r.get("correct_refusal")) or \
                  (r["type"] == "no_evidence" and not r.get("correct_no_evidence"))
            if bad or r.get("status") == "error":
                lines.append(f"- **{d}/{r['id']}** ({r['type']}) status=`{r['status']}` — {r['question']}  \n  {r.get('answer_excerpt') or r.get('message', '')}"[:600])
    (REPORTS / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
