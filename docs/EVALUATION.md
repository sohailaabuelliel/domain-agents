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

## Results — final clean run (0 of 50 cases degraded)
| Sector | Cases | Retrieval acc. | Answer acc. | Hallucination | Refusal acc. | False refusals | Avg latency |
|---|---|---|---|---|---|---|---|
| pharma | 10 | 100% | 100% | 0% | 100% | 0% | 9.4 s |
| medical | 10 | 100% | 100% | 0% | 100% | 0% | 9.0 s |
| finance | 10 | 100% | 100% | 0% | 100% | 0% | 8.4 s |
| marketing | 10 | 100% | 100% | 0% | 100% | 0% | 8.7 s |
| hospitality | 10 | 100% | 100% | 0% | 100% | 0% | 11.6 s |

Retrieval 100 %, hallucination 0 %, refusal 100 %, **30 of 30 answer-cases** in this run. Zero cases ran in degraded mode and zero errored.

### Read this before trusting the 30/30
The model is non-deterministic, so the same question can pass in one run and fail in the next. Three clean runs of the identical 50 cases:

| Run | Answer-cases passed | Misses |
|---|---|---|
| Run A (clean) | 28 / 30 | ph-05, hs-05 |
| Run B (clean, same code + per-drug search rule) | 27 / 30 | ph-05, fn-06, hs-05 |
| Run C — final (clean, + per-entity search, + 90 s timeout) | 30 / 30 | none |

* The stable result across all three runs is the **safety side**: hallucination 0 %, refusal 100 %, retrieval 100 %. Those did not move.
* The **answer side varies by 0–3 cases per run** (90–100 %). A realistic reading is "about 27–30 of 30", not a guaranteed 30.
* What changed between runs, honestly:
  * **ph-05** (amiodarone + warfarin) failed in A and B, passes in C. Cause: the agent searched the two drugs only together and got a generic literature summary. Fix: for questions naming 2+ entities the agent now also retrieves each entity's own documents (`agent.py`, step 3b), and the pharma prompt asks for one search per drug. Verified 3/3 on repeated manual runs, not just once.
  * **hs-05** (what guests praise) failed in A–B because the test requires the literal word "staff" while the model sometimes writes "front-desk team". Passing in C is wording luck, not a fix. The test was left unchanged.
  * **fn-06** (Arabic NVIDIA revenue trend) failed once with "no evidence" in B and passed on every manual retry and in C. The cause of the single failure was **not identified** (a 504 timeout was seen in a manual retry, but the eval case itself returned a normal `no_evidence`, not an error), so it should be treated as an occasional flaky case.
* A hung model call once froze a run for ~90 minutes. All model calls now have a 90 s timeout.

### History: the earlier measurement with working embeddings (before the last fixes)
Retrieval accuracy was **100 % in all five sectors** with `gemini-embedding-2`, including the Arabic cases (similarity 0.63–0.82 vs. 0.40–0.48 for unrelated text), up from 67–83 % with the first embedding model. Hallucination was 0 % in four sectors; the one non-zero case (Hospitality, spa price, 12.5 %) was a "no evidence" question the agent answered; after the later grounding fix it declines correctly in spot-checks, but this is **not yet confirmed by a full clean run**.

### Degraded-mode baseline (embeddings completely unavailable) — still valid as a robustness result
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
* ph-05 and hs-05 — see the table above.
* Latency ≈ 12 s average, up to 40 s on slow turns (3–4 sequential calls); see `DESIGN.md`.

## Threshold note
`gemini-embedding-2` scores unrelated-but-same-topic text higher than the previous model (no-evidence questions reach similarity 0.63–0.77, above the 0.50–0.58 thresholds). Similarity alone therefore no longer separates "covered" from "not covered"; the **unknown-entity check and the citation/grounding check** do that work. Raising thresholds was deliberately *not* done without a clean evaluation run to calibrate against.
