"""Tools the agent can call. Tools are generic; a domain enables the ones it needs via ``tools:`` in domain.yaml."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

import httpx

from .llm import ToolSpec
from .retrieval import Hit, Retriever, find_entities

SPECS: dict[str, ToolSpec] = {
    "search_knowledge": ToolSpec(
        "search_knowledge",
        "Search the domain knowledge base (official documents). Call it for every factual question; "
        "you may call it several times with different queries, e.g. once per drug/entity being compared.",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "Search query in English (translate the user's question if needed)."},
            "entity": {"type": "string", "description": "Optional: restrict to one entity (e.g. a drug name) from the knowledge base."}},
         "required": ["query"]}),
    "pubmed_search": ToolSpec(
        "pubmed_search",
        "LIVE search of PubMed for recent published abstracts. Use when the knowledge base lacks evidence or the user asks for studies / recent evidence.",
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
}


@dataclass
class ToolContext:
    retriever: Retriever
    aliases: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, Hit] = field(default_factory=dict)     # S1.. -> hit
    _seen: dict[str, str] = field(default_factory=dict)        # chunk id -> S id

    def register(self, hit: Hit) -> str:
        sid = self._seen.get(hit.chunk.id)
        if not sid:
            sid = f"S{len(self.evidence) + 1}"
            self._seen[hit.chunk.id] = sid
            self.evidence[sid] = hit
        return sid


def run_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> str:
    """Return a compact text observation for the model (and register sources)."""
    if name == "search_knowledge":
        q = str(args.get("query", ""))
        ents = find_entities(q, ctx.retriever.entities, ctx.aliases)
        if args.get("entity") and args["entity"] in ctx.retriever.entities and args["entity"] not in ents:
            ents.append(args["entity"])
        hits = ctx.retriever.search(q, k=6, entities=ents)
        if not hits:
            return "No results."
        lines = []
        for h in hits:
            sid = ctx.register(h)
            lines.append(f"[{sid}] {h.chunk.label} (relevance {h.vector:.2f})\n{h.chunk.text[:900]}")
        return "\n\n".join(lines)
    if name == "pubmed_search":
        return _pubmed(str(args.get("query", "")), ctx)
    return f"Unknown tool '{name}'."


def _pubmed(query: str, ctx: ToolContext, n: int = 3) -> str:
    from .retrieval import Chunk
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": "domain-agent/1.0"}) as c:
            ids = c.get(f"{base}/esearch.fcgi", params={"db": "pubmed", "term": query + " AND hasabstract", "retmax": n, "sort": "relevance", "retmode": "json"}).json()["esearchresult"]["idlist"]
            if not ids:
                return "PubMed returned no abstracts for this query."
            root = ET.fromstring(c.get(f"{base}/efetch.fcgi", params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}).text)
    except Exception as e:  # noqa: BLE001
        return f"PubMed is unreachable right now ({type(e).__name__})."
    out = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID") or ""
        t_el = art.find(".//ArticleTitle")
        title = "".join(t_el.itertext()) if t_el is not None else ""
        year = art.findtext(".//PubDate/Year") or ""
        abstract = " ".join("".join(a.itertext()) for a in art.findall(".//Abstract/AbstractText"))
        ch = Chunk(id=f"pubmed-live::{pmid}", text=f"[PubMed live | PMID {pmid}]\n{title}. {abstract}", doc_id=f"pmid{pmid}",
                   title=f"PubMed PMID {pmid}", entity="pubmed-live", doc_type="pubmed_live", section=title[:80],
                   source="PubMed E-utilities (live)", url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
        sid = ctx.register(Hit(ch, score=1.0, vector=0.7, via="pubmed_live"))
        out.append(f"[{sid}] PubMed PMID {pmid} ({year}) — {title}\n{abstract[:800]}")
    return "\n\n".join(out) or "PubMed returned no abstracts."
