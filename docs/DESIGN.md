# Design decisions, trade-offs and scaling

## 1. The core idea: one engine, configuration per sector
The task asks for an agent that can be re-pointed at another domain **without code changes**. So everything that differs between sectors lives in `domains/<sector>/`:

| Varies per sector (config) | Shared (code) |
|---|---|
| system prompt, output labels, disclaimer | ReAct loop, structured output |
| refusal rules (regex + canned response) | guardrail machinery |
| similarity threshold, aliases (Arabic names → entities) | hybrid retrieval, citations |
| few-shot examples, enabled tools | confidence scoring, reviewer |
| knowledge files, evaluation cases | web UI, API, evaluation harness |

Adding a sixth sector = copy a folder, edit YAML, drop in markdown, run `scripts/build_index.py`. The five shipped sectors are the proof: Pharma, Medical, Finance, Marketing, Hospitality share 100% of the Python.

## 2. Key decisions and why

| Decision | Alternatives considered | Why this one |
|---|---|---|
| **Gemini as the default LLM**, provider-neutral adapter (`llm.py`) with OpenAI and Azure OpenAI | Hard-code one vendor | The brief mentions GPT/Azure; reviewers can paste *their* key in the UI. Swapping provider is a config value. |
| **Own hybrid retriever** (dense embeddings + BM25, fused with Reciprocal Rank Fusion) | Gemini File Search only; Chroma; Supabase pgvector | Pure-semantic search misses exact tokens (drug names, "FY2025", "PMID"); BM25 catches them. File Search has no keyword/rerank stage. It is kept as an alternative backend (`backend="file_search"`) and compared in `BONUS.md`. |
| **Entity-aware merge** in retrieval | Plain top-k | A question about *two* drugs/companies must retrieve from *both*; plain top-k often returns six chunks about one. |
| **Deterministic guardrails in Python** for refusal, coverage, citations, confidence | Ask the LLM to police itself | Cheap (0 LLM calls for refusals), testable, cannot be talked out of it. The LLM is used only where judgement is needed (reviewer). |
| **Confidence from measured signals** | LLM self-reported "confidence: 0.9" | Self-reported confidence is poorly calibrated. Ours = retrieval strength, evidence breadth, citation validity, text-to-source support. |
| **"No evidence found" as a first-class outcome** | Always answer | Required by the brief; also the single most important trust feature in medicine/finance. |
| **Real public data where it exists** (FDA, PubMed, MedlinePlus, SEC); **clearly labelled synthetic** data where it cannot (marketing campaigns, hotel reviews) | Scrape random sites | Real, citable sources are the point of RAG. Synthetic sets say so in the first line of every file and in the UI disclaimer; their statistics are *computed from the records*, so evaluation answers are checkable. |
| **No-build web UI** (vanilla JS) | React/Vite | Zero tooling for the reviewer: `uvicorn` and open the page. |
| **API key from the UI**, kept in `sessionStorage`, sent per request, never stored server-side | `.env` only | The brief wants anyone to run it with their own key. The key never reaches disk or logs. |
| **Model list fetched from the provider** (`POST /api/models`), filtered to chat models, cached 10 min | A hard-coded model name the user must type | Model names change monthly; a typo silently fails. The dropdown shows exactly what the user's key can call; a *Custom* entry remains for unlisted deployments. |
| **UI language switch (EN / Arabic)** with logical CSS properties, so RTL mirrors without a second stylesheet | Separate Arabic page | One code path. Sector names, tasks and disclaimers are configuration (`ui_ar:` in `domain.yaml`); documentation, sources and evaluation stay in English. |
| **Everything vendored** (Mermaid, Marked, IBM Plex fonts, icons) under `web/` | CDN links | Works offline and behind proxies; no third-party request leaks the page. Docs render Mermaid diagrams as real charts. |

## 3. Trade-offs we accepted (and what we'd do about them)

| Limitation | Impact | Mitigation / next step |
|---|---|---|
| **Latency 10–40 s** per answer (3–4 sequential LLM calls) | Slow for chat | Streaming trace makes progress visible; reviewer can be switched off; next: merge steps 2+4, cache frequent questions, use a faster model for the reviewer. |
| **Free-tier quotas** (Gemini daily requests *and* 1000 embeddings/day) | The agent can hit 429s | Fast model fallback (`llm.py`), query-embedding cache, **degraded keyword-only mode** if embeddings are unavailable (so refusals/no-evidence still work). Documented: use a billed key for production. |
| **Rule-based guardrails** can be bypassed by creative phrasing | Possible false negatives | Layer 2 (reviewer agent) and layer 3 (grounding check) still apply; next: add an LLM-based intent classifier as a second opinion. |
| **Small knowledge bases** (15 drugs, 15 conditions, 6 companies) | Narrow coverage | By design for a demo; unknown entities are *detected* and answered with "no evidence" rather than guessed. |
| **Arabic retrieval** against English sources scores lower | Arabic questions can be judged "not covered" | Domain `aliases` map Arabic names to entities; see `EVALUATION.md` for measured effect and the planned fix (translate-then-retrieve). |
| **Severity/summary produced by an LLM** | Could be mis-labelled | Reviewer checks; every finding carries its sources so a human can verify. |

## 4. Scaling plan

1. **Data size** — The numpy index is exact and fast up to ~100k chunks. Beyond that, swap `HybridRetriever` for a managed vector store (Postgres + pgvector / Supabase, or Gemini File Search). The `Retriever` interface (`search`, `stats`, `entities`) is the only seam, so the agent code does not change.
2. **Many tenants / sectors** — One process already serves all sectors (agents cached per `(domain, provider, model, key)`); put several uvicorn workers behind a load balancer. Sessions/memory move from process memory to Redis.
3. **Freshness** — Run the `scripts/fetch_*.py` jobs on a schedule; the index fingerprint triggers re-embedding only for changed files. PubMed is already queried live.
4. **Cost** — Refusals and "no evidence" cost 0–1 LLM calls. Add an answer cache keyed on (domain, normalised question, knowledge-version). Use a small model for the reviewer.
5. **Quality** — `eval/run_eval.py` is the regression gate: run on every change; track retrieval accuracy, answer accuracy, hallucination rate and refusal accuracy over time.
6. **Safety / compliance** — Add logging with PII scrubbing, rate limiting per key, and human escalation for high-severity answers (medical/finance).
7. **Observability** — The agent already emits a structured trace per question (step, tool, similarity, token usage); forward it to OpenTelemetry/Langfuse.

## 5. What this project deliberately does *not* do
It does not diagnose, prescribe doses, give investment advice, or predict prices; it does not use knowledge outside the retrieved sources; and it does not claim the synthetic sectors reflect real companies.
