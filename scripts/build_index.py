"""Pre-build the vector index for one or all domains: python scripts/build_index.py [domain ...] [--rebuild]"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain_agent.config import LLMConfig, list_domains, load_domain
from domain_agent.llm import make_llm
from domain_agent.retrieval import make_retriever

args = [a for a in sys.argv[1:] if not a.startswith("--")]
llm = make_llm(LLMConfig())
for d in args or list_domains():
    t = time.time()
    r = make_retriever(load_domain(d), llm, rebuild="--rebuild" in sys.argv)
    print(f"[{d}] {r.stats()}  {time.time() - t:.0f}s", flush=True)
