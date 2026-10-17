"""RAG: loading, section-aware chunking, hybrid retrieval (semantic + BM25 + RRF), entity-aware merge.

Two interchangeable backends behind ``Retriever``:
  * ``HybridRetriever``      – local index (Gemini/OpenAI embeddings + BM25), exposes real scores  [default]
  * ``FileSearchRetriever``  – Gemini File Search managed RAG store (semantic only, no scores)
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .config import DATA_DIR, DomainConfig
from .llm import LLM

INDEX_DIR = DATA_DIR / "index"
CHUNK_CHARS = 1100
CHUNK_OVERLAP = 160


# ------------------------------------------------------------------ documents & chunks
@dataclass
class Chunk:
    id: str
    text: str                       # text shown to the model / user
    doc_id: str
    title: str
    entity: str
    doc_type: str
    section: str
    source: str
    url: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """Human-readable citation label."""
        return f"{self.title} › {self.section}" if self.section else self.title


@dataclass
class Hit:
    chunk: Chunk
    score: float                    # final ranking score (RRF + boosts)
    vector: float = 0.0             # cosine similarity (0 when not available)
    bm25: float = 0.0               # normalised 0..1 within the result set
    via: str = "hybrid"


_FRONT = re.compile(r"^---\n(.*?)\n---\n", re.S)


def parse_document(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_text(encoding="utf-8")
    m = _FRONT.match(raw)
    meta = yaml.safe_load(m.group(1)) if m else {}
    return meta or {}, raw[m.end():] if m else raw


def _split_long(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):  # prefer to cut on a sentence boundary
            cut = max(text.rfind(". ", start + size // 2, end), text.rfind("\n", start + size // 2, end))
            end = cut + 1 if cut > 0 else end
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return out


def chunk_document(path: Path, root: Path) -> list[Chunk]:
    meta, body = parse_document(path)
    doc_id = path.stem
    title = str(meta.get("title") or doc_id)
    entity = str(meta.get("entity") or doc_id)
    sections = re.split(r"^##\s+", body, flags=re.M)
    chunks: list[Chunk] = []
    pre = sections[0].strip()
    blocks = ([("Overview", re.sub(r"^#\s+.*\n", "", pre).strip())] if pre and len(pre) > 60 else [])
    for s in sections[1:]:
        head, _, rest = s.partition("\n")
        blocks.append((head.strip(), rest.strip()))
    for sec, content in blocks:
        for i, piece in enumerate(_split_long(content)):
            header = f"[{entity} | {meta.get('doc_type', 'doc')} | {sec}]"
            chunks.append(Chunk(
                id=f"{doc_id}::{len(chunks)}", text=f"{header}\n{piece}", doc_id=doc_id, title=title, entity=entity,
                doc_type=str(meta.get("doc_type", "doc")), section=sec, source=str(meta.get("source", "")),
                url=str(meta.get("url", "")), extra={"part": i}))
    return chunks


def load_chunks(knowledge_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for p in sorted(knowledge_dir.glob("**/*")):
        if p.suffix.lower() in (".md", ".txt"):
            chunks += chunk_document(p, knowledge_dir)
    return chunks


# ------------------------------------------------------------------ BM25
_TOKEN = re.compile(r"[A-Za-z0-9\u0600-\u06FF][A-Za-z0-9\u0600-\u06FF\-']*")
_STOP = set("a an the of and or to in on for with is are was were be by as at from that this these those it its not no can may will should use used using".split())


def tokenize(text: str) -> list[str]:
    return [t for t in (w.lower().strip("-'") for w in _TOKEN.findall(text)) if t and t not in _STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.N = len(docs)
        self.tf = [Counter(d) for d in docs]
        self.len = np.array([len(d) for d in docs], dtype=float)
        self.avg = float(self.len.mean()) if self.N else 1.0
        df: Counter[str] = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        s = np.zeros(self.N)
        for t in set(query):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(t, 0)
                if f:
                    s[i] += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
        return s


# ------------------------------------------------------------------ retriever interface
class Retriever:
    name = "base"

    def search(self, query: str, k: int = 6, entities: list[str] | None = None) -> list[Hit]:
        raise NotImplementedError

    @property
    def entities(self) -> list[str]:
        return []

    def stats(self) -> dict[str, Any]:
        return {}


def _fingerprint(chunks: list[Chunk], embed_id: str) -> str:
    h = hashlib.sha256(embed_id.encode())
    for c in chunks:
        h.update(c.id.encode()); h.update(c.text.encode())
    return h.hexdigest()[:16]


class HybridRetriever(Retriever):
    name = "hybrid"

    def __init__(self, domain: DomainConfig, llm: LLM, rebuild: bool = False):
        self.domain, self.llm = domain, llm
        self.degraded = ""
        self.chunks = load_chunks(domain.knowledge_dir)
        if not self.chunks:
            raise RuntimeError(f"No knowledge files found in {domain.knowledge_dir}")
        self.bm25 = BM25([tokenize(c.text) for c in self.chunks])
        self._entities = sorted({c.entity for c in self.chunks})
        self.matrix = self._load_or_build(rebuild)

    # -- index persistence --
    def _load_or_build(self, rebuild: bool) -> np.ndarray:
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        embed_id = f"{self.llm.provider}:{getattr(self.llm, 'EMBED_MODEL', '')}:{getattr(self.llm, 'EMBED_DIM', '')}"
        fp = _fingerprint(self.chunks, embed_id)
        npz = INDEX_DIR / f"{self.domain.collection}.npz"
        meta = INDEX_DIR / f"{self.domain.collection}.json"
        if npz.exists() and meta.exists() and not rebuild:
            if json.loads(meta.read_text()).get("fingerprint") == fp:
                m = np.load(npz)["m"]
                if m.shape[0] == len(self.chunks):
                    return m
        vecs = np.array(self.llm.embed([c.text for c in self.chunks], kind="document"), dtype=np.float32)
        assert vecs.shape[0] == len(self.chunks), f"index shape {vecs.shape} != {len(self.chunks)} chunks"
        vecs /= np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)
        np.savez_compressed(npz, m=vecs)
        meta.write_text(json.dumps({"fingerprint": fp, "chunks": len(self.chunks), "embed": embed_id}))
        return vecs

    @property
    def entities(self) -> list[str]:
        return self._entities

    def stats(self) -> dict[str, Any]:
        types = Counter(c.doc_type for c in self.chunks)
        return {"backend": self.name, "chunks": len(self.chunks), "documents": len({c.doc_id for c in self.chunks}),
                "entities": len(self._entities), "doc_types": dict(types), "embedding_dim": int(self.matrix.shape[1])}

    # -- search --
    def _query_vector(self, query: str) -> np.ndarray | None:
        """Query embedding with an on-disk cache (repeat questions cost no API quota).
        Returns None when the embedding service is unavailable (daily quota, outage) -> caller degrades to BM25."""
        cache_file = INDEX_DIR / f"{self.domain.collection}.queries.json"
        key = hashlib.sha1(query.strip().lower().encode()).hexdigest()
        try:
            cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        except Exception:  # noqa: BLE001
            cache = {}
        if key in cache:
            self.degraded = ""
            return np.array(cache[key], dtype=np.float32)
        try:
            v = self.llm.embed([query], kind="query")[0]
        except Exception as e:  # noqa: BLE001
            self.degraded = f"{type(e).__name__}: {str(e)[:120]}"
            return None
        self.degraded = ""
        cache[key] = [round(float(x), 6) for x in v]
        cache_file.write_text(json.dumps(cache))
        return np.array(v, dtype=np.float32)

    def _rank(self, query: str, pool: np.ndarray) -> list[Hit]:
        q = self._query_vector(query)
        bm = self.bm25.scores(tokenize(query))
        bm_n = bm / bm.max() if bm.max() > 0 else bm
        if q is None:   # DEGRADED MODE: keyword-only. cosine is replaced by a conservative proxy so guardrails still work.
            cos = 0.35 + 0.45 * bm_n
        else:
            q = q / max(float(np.linalg.norm(q)), 1e-9)
            cos = self.matrix @ q
        idx = np.where(pool)[0]
        v_rank = {int(i): r for r, i in enumerate(idx[np.argsort(-cos[idx])])}
        b_rank = {int(i): r for r, i in enumerate(idx[np.argsort(-bm[idx])])}
        hits = []
        for i in idx:
            i = int(i)
            rrf = 1 / (60 + v_rank[i]) + (1 / (60 + b_rank[i]) if bm[i] > 0 else 0)
            hits.append(Hit(self.chunks[i], score=rrf, vector=float(cos[i]), bm25=float(bm_n[i])))
        hits.sort(key=lambda h: -h.score)
        return hits

    def search(self, query: str, k: int = 6, entities: list[str] | None = None) -> list[Hit]:
        everything = np.ones(len(self.chunks), dtype=bool)
        hits = self._rank(query, everything)
        # entity-aware merge: make sure every entity the query is about is represented
        wanted = [e for e in (entities or []) if e in self._entities]
        if wanted:
            per = max(2, k // max(len(wanted), 1))
            chosen: list[Hit] = []
            for e in wanted:
                pool = np.array([c.entity == e or c.entity.startswith(e + "-") or e in c.entity.split("-") for c in self.chunks])
                if pool.any():
                    chosen += self._rank(query, pool)[:per]
            seen = {h.chunk.id for h in chosen}
            chosen += [h for h in hits if h.chunk.id not in seen]
            hits = chosen
        out, seen = [], set()
        for h in hits:
            if h.chunk.id in seen:
                continue
            seen.add(h.chunk.id); out.append(h)
            if len(out) >= k:
                break
        return out


# ------------------------------------------------------------------ Gemini File Search backend
class FileSearchRetriever(Retriever):
    """Managed RAG: Gemini indexes and searches the files; we read the grounding chunks it used.

    Trade-off documented in docs/DESIGN.md: simplest to operate, but semantic-only, no scores, and every
    retrieval costs one model call. Used as an alternative backend and in the evaluation comparison.
    """
    name = "gemini_file_search"

    def __init__(self, domain: DomainConfig, llm: LLM, rebuild: bool = False):
        from google.genai import types
        self._types = types
        if getattr(llm, "provider", "") != "gemini":
            raise RuntimeError("Gemini File Search needs the Gemini provider.")
        self.domain, self.llm, self.client = domain, llm, llm.client  # type: ignore[attr-defined]
        self.chunks = load_chunks(domain.knowledge_dir)
        self._entities = sorted({c.entity for c in self.chunks})
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        self.state_path = INDEX_DIR / f"{domain.collection}.filesearch.json"
        self.store = self._ensure_store(rebuild)

    @property
    def entities(self) -> list[str]:
        return self._entities

    def _ensure_store(self, rebuild: bool) -> str:
        import time
        files = [p for p in sorted(self.domain.knowledge_dir.glob("**/*")) if p.suffix.lower() in (".md", ".txt")]
        fp = hashlib.sha256("".join(p.name + str(p.stat().st_size) for p in files).encode()).hexdigest()[:16]
        if self.state_path.exists() and not rebuild:
            st = json.loads(self.state_path.read_text())
            if st.get("fingerprint") == fp:
                try:
                    self.client.file_search_stores.get(name=st["store"])
                    return st["store"]
                except Exception:  # noqa: BLE001 - store was deleted remotely
                    pass
        store = self.client.file_search_stores.create(config={"display_name": f"{self.domain.collection}-kb", "embedding_model": "models/gemini-embedding-2"})
        for p in files:
            meta, _ = parse_document(p)
            op = self.client.file_search_stores.upload_to_file_search_store(
                file=str(p), file_search_store_name=store.name,
                config={"display_name": p.stem, "mime_type": "text/markdown",
                        "custom_metadata": [{"key": "entity", "string_value": str(meta.get("entity", p.stem))},
                                            {"key": "doc_type", "string_value": str(meta.get("doc_type", "doc"))}],
                        "chunking_config": {"white_space_config": {"max_tokens_per_chunk": 250, "max_overlap_tokens": 30}}})
            while not op.done:
                time.sleep(3); op = self.client.operations.get(op)
        self.state_path.write_text(json.dumps({"store": store.name, "fingerprint": fp}))
        return store.name or ""

    def stats(self):
        return {"backend": self.name, "store": self.store, "documents": len({c.doc_id for c in self.chunks}), "entities": len(self._entities)}

    def search(self, query: str, k: int = 6, entities: list[str] | None = None) -> list[Hit]:
        t = self._types
        flt = None
        if entities and len(entities) == 1 and entities[0] in self._entities:
            flt = f'entity="{entities[0]}"'
        tool = t.Tool(file_search=t.FileSearch(file_search_store_names=[self.store], metadata_filter=flt) if flt
                      else t.FileSearch(file_search_store_names=[self.store]))
        r = self.client.models.generate_content(
            model=self.llm.model, contents=f"Retrieve passages relevant to: {query}",
            config=t.GenerateContentConfig(temperature=0, tools=[tool]))
        gm = r.candidates[0].grounding_metadata if r.candidates else None
        hits: list[Hit] = []
        for rank, gc in enumerate((gm.grounding_chunks or []) if gm else []):
            rc = gc.retrieved_context
            if not rc or not rc.text:
                continue
            title = rc.title or "document"
            md = {m.key: (m.string_value or m.numeric_value) for m in (rc.custom_metadata or [])}
            ch = Chunk(id=f"fs::{title}::{rank}", text=rc.text, doc_id=title, title=title, entity=str(md.get("entity", title)),
                       doc_type=str(md.get("doc_type", "doc")), section="", source="Gemini File Search")
            hits.append(Hit(ch, score=1 / (rank + 1), vector=0.0, via="file_search"))
        return hits[:k]


def make_retriever(domain: DomainConfig, llm: LLM, backend: str = "hybrid", rebuild: bool = False) -> Retriever:
    if backend in ("file_search", "gemini_file_search"):
        return FileSearchRetriever(domain, llm, rebuild)
    return HybridRetriever(domain, llm, rebuild)


def find_entities(text: str, known: list[str], aliases: dict[str, str] | None = None) -> list[str]:
    """Which known entities does the text mention? (word-boundary, case-insensitive; handles slug entities + aliases)."""
    low = text.lower()
    found = []
    for alias, target in (aliases or {}).items():
        if alias.lower() in low and target in known and target not in found:
            found.append(target)
    for e in known:
        parts = [e.lower()] + ([p for p in e.lower().split("-") if len(p) > 3] if "-" in e else [])
        if any(re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", low) for p in parts):
            found.append(e)
    return found
