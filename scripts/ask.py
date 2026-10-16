"""Quick CLI: python scripts/ask.py <domain> "question" [--no-review]"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain_agent.agent import build_agent  # noqa: E402
from domain_agent.config import load_domain  # noqa: E402

domain, question = sys.argv[1], sys.argv[2]
agent = build_agent(load_domain(domain))
res = agent.ask(question, review="--no-review" not in sys.argv, emit=lambda e: print("  ·", e["t"], e["type"], {k: v for k, v in e.items() if k not in ("type", "t")}))
d = res.to_dict()
print("\nSTATUS:", d["status"], "| elapsed", d["elapsed"], "s | usage", d["usage"])
if d["answer"]:
    print(json.dumps(d["answer"], ensure_ascii=False, indent=2))
print("MESSAGE:", d["message"][:300])
print("CONFIDENCE:", d["confidence"])
print("SOURCES:", [(s["id"], s["entity"], s["section"][:30], s["similarity"]) for s in d["sources"]])
