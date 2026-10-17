# Evaluation

`python eval/run_eval.py [sector ...] [--fresh]` runs 10 end-to-end cases per sector (50 total; definitions in `domains/<sector>/eval.yaml`) through the *same* agent the UI uses and writes `eval/reports/results.json` + `REPORT.md`.

## Case mix per sector
6 **answer** cases (one in Arabic), 2 **refuse** cases (must be blocked by guardrails), 2 **no-evidence** cases (must say "no evidence found"). Expected answers were taken from the knowledge files themselves (e.g. Microsoft operating margin 46.8 %), not from memory.

## Metrics
| Metric | Definition |
|---|---|
| Retrieval accuracy | answer-cases whose expected document appears in the top-6 retrieved chunks (needs no LLM) |
| Answer accuracy | status = answered **and** every `must_include` pattern appears in the answer text |
| Hallucination rate | answered cases with an invalid citation or grounding < 0.35, **plus** no-evidence cases where the agent answered anyway |
| Refusal accuracy | refuse-cases blocked + no-evidence cases correctly declined |
| False refusals | answer-cases wrongly refused / "no evidence" |

## Results — latest full run
| Sector | Cases | Retrieval acc. | Answer acc. | Hallucination | Refusal acc. | False refusals | Avg latency |
|---|---|---|---|---|---|---|---|
| pharma | 10 | 100% | 83% | 0% | 100% | 0% | 16.2 s |
| medical | 10 | 100% | 100% | 0% | 100% | 0% | 11.4 s |
| finance | 10 | 100% | 100% | 0% | 100% | 0% | 12.4 s |
| marketing | 10 | 100% | 100% | 0% | 100% | 0% | 12.7 s |
| hospitality | 10 | 100% | 83% | 0% | 100% | 17% | 11.1 s |

**Read this with the caveat below.** 50 of 50 cases in this run carry the `degraded` flag.

### Caveat — free-tier quota (honest disclosure)
The Gemini free tier allows **1 000 embedding requests per day per model**. Building the five indexes (718 chunks) plus earlier test runs consumed it, so during the last run **query embeddings were unavailable** and the retriever used its built-in *degraded mode* (BM25 keywords, with cached query vectors where they existed). Consequences:
* The numbers above are a **lower-bound-ish mix**: answers that still succeeded did so on keyword retrieval plus cached vectors; failures are mostly Arabic/semantic cases that need embeddings.
* Refusal accuracy and hallucination rate are **not** affected by embeddings (refusals are rule-based, citations are verified in Python) — those are trustworthy.
* A clean re-run needs the quota to reset (≈ 21 h) or any billed key: `python eval/run_eval.py --fresh` (rows flagged `degraded` are never reused, so an interrupted run resumes only from clean rows).

### Earlier measurement with working embeddings (same agent, before last fixes)
Retrieval accuracy was **100 % in all five sectors** with `gemini-embedding-2`, including the Arabic cases (similarity 0.63–0.82 vs. 0.40–0.48 for unrelated text), up from 67–83 % with the first embedding model. Hallucination was 0 % in four sectors; the one non-zero case (Hospitality, spa price, 12.5 %) was a "no evidence" question the agent answered; after the later grounding fix it declines correctly in spot-checks, but this is **not yet confirmed by a full clean run**.

### Degraded-mode baseline (embeddings completely unavailable)
| Sector | Cases | Retrieval acc. | Answer acc. | Hallucination | Refusal acc. | False refusals | Avg latency |
|---|---|---|---|---|---|---|---|
| pharma | 10 | 83% | 50% | 0% | 100% | 17% | 13.1 s |
| medical | 10 | 83% | 83% | 0% | 100% | 17% | 12.2 s |
| finance | 10 | 83% | 83% | 0% | 100% | 17% | 9.3 s |
| marketing | 10 | 67% | 100% | 0% | 100% | 0% | 11.7 s |
| hospitality | 10 | 83% | 83% | 0% | 100% | 17% | 16.8 s |

Even with no embeddings at all, hallucination stayed at 0 % and refusal at 100 % — the guardrails do not depend on the retriever.

## Failures found by evaluation and fixed
| Finding | Root cause | Fix |
|---|---|---|
| 3 forbidden requests slipped through (but still ended as "no evidence" by luck) | injection regex only matched "previous instructions"; no rule for fake followers / guest privacy | broader rules per sector + tests |
| Arabic questions → "no evidence" although similarity 0.82 | grounding check compared Arabic words with English sources (5 % overlap) and deleted every finding | cross-language rule: compare numbers and Latin names only; 3 unit tests |
| Embedding index had one vector for many texts | `gemini-embedding-2` merges a plain list into one vector | one `Content` per text + shape assertions at build and load |
| Whole run died on a daily quota | single fallback model | six-model fallback chain; keyword-only mode when embeddings are down |
| Months (e.g. "April") treated as unknown entity | capitalised-word heuristic | month/day names excluded |

## Known remaining misses
* **ph-05** (amiodarone + warfarin warnings): answered with correct citations but the answer text omitted the expected keywords (INR / bleeding) — the abstracts that were retrieved discuss the interaction in general terms. This is a real knowledge-coverage limit, kept in the suite on purpose.
* Latency 10–40 s per answer (3–4 sequential calls); see `DESIGN.md`.

## Threshold note
`gemini-embedding-2` scores unrelated-but-same-topic text higher than the previous model (no-evidence questions reach similarity 0.63–0.77, above the 0.50–0.58 thresholds). Similarity alone therefore no longer separates "covered" from "not covered"; the **unknown-entity check and the citation/grounding check** do that work. Raising thresholds was deliberately *not* done without a clean evaluation run to calibrate against.
