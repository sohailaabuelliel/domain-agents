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

## Results — clean full run (embeddings available, 0 of 50 cases degraded)
| Sector | Cases | Retrieval acc. | Answer acc. | Hallucination | Refusal acc. | False refusals | Avg latency |
|---|---|---|---|---|---|---|---|
| pharma | 10 | 100% | 83% | 0% | 100% | 0% | 11.7 s |
| medical | 10 | 100% | 100% | 0% | 100% | 0% | 12.7 s |
| finance | 10 | 100% | 100% | 0% | 100% | 0% | 21.8 s |
| marketing | 10 | 100% | 100% | 0% | 100% | 0% | 11.7 s |
| hospitality | 10 | 100% | 83% | 0% | 100% | 0% | 12.4 s |

All 50 cases ran with real semantic retrieval (no `degraded` flag), after the cross-language grounding fix. **Hallucination 0 % and refusal 100 % in every sector; retrieval 100 % in every sector; 28 of 30 answer-cases pass.**

### The two answer misses (kept in the suite on purpose)
| Case | What happened | Verdict |
|---|---|---|
| **ph-05** amiodarone + warfarin warnings | Agent answered with a citation but said the sources "do not specify the mechanism or magnitude". The expected keywords (INR / bleeding / prothrombin) are not in the retrieved abstracts. | **Real knowledge-coverage limit**: the agent is honest instead of inventing. Fix = ingest the FDA warfarin label section on interactions. |
| **hs-05** what do guests praise most | Answer was correct and cited ("friendly front-desk team, breakfast buffet, spotless rooms, beach access") but the test requires the literal word `staff`, and the model wrote "front-desk team". | **Test strictness, not a wrong answer.** Left unchanged so the score is not inflated; a looser pattern would be `staff|front-desk|team`. |

### How the numbers moved across runs (same 50 cases)
| Run | Condition | Retrieval | Answer-cases passed |
|---|---|---|---|
| Keyword-only (no embeddings, quota out) | first embedding model unavailable | 67–83 % | 24 of 30 (Arabic: 1 of 5) |
| Previous run | `embedding-2`, quota out again → degraded | 100 % | 28 of 30 (Arabic: 5 of 5; cached query vectors) |
| **This run** | `embedding-2`, clean | **100 %** | **28 of 30** (Arabic: 5 of 5) |

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
