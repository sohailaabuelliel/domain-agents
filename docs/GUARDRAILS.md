# Guardrails, hallucination control and confidence

Four layers. The first three are plain Python (no LLM call), so they are fast, free, deterministic and unit-tested (`tests/test_offline.py`).

| Layer | Where | Catches | Result for the user |
|---|---|---|---|
| **1. Input screening** | `guardrails.check_input` | Out-of-scope intent per sector (diagnosis, individual dosing, investment advice, price prediction, fake reviews, guaranteed ROI, guest privacy, self-harm…) and prompt-injection ("ignore your rules", "reveal system prompt", Arabic variants) | Instant refusal with a helpful alternative; **0 LLM calls** |
| **2. Coverage check** | `agent.ask`, `guardrails.uncovered_terms` | Best similarity below the sector threshold (`min_retrieval_score`), or a named entity (drug/company/channel) that is not in the knowledge base | **"No evidence found"** — the model is never asked to improvise |
| **3. Grounding check** | `guardrails.verify_answer` | A citation id that was never retrieved; a finding with no citation; a finding whose words are not supported by the text it cites | One automatic repair attempt, then "no evidence" if still uncited |
| **4. Safety reviewer** | `agent._review` (second LLM role) | Individual dose/treatment advice, advice phrased as a personal instruction, claims beyond the sources | Answer withheld/replaced; the reviewer's note is shown in the UI |

## Why this prevents hallucination
* The model only sees retrieved passages, labelled `[S1]…[Sn]`, and the system prompt forbids outside knowledge.
* An answer without valid citations is **not shown as an answer**.
* Every finding lists its sources; the UI makes them clickable (title, section, URL, similarity).
* Unknown names are detected *before* generation, which is the most common hallucination trigger ("side effects of Zentrava").

## Confidence score (0–1)
`score = 0.35·retrieval + 0.20·breadth + 0.20·citations + 0.25·grounding`

| Signal | Measured as |
|---|---|
| retrieval | mean cosine similarity of the cited passages, rescaled between the sector threshold and 1 |
| breadth | how many distinct sources back the answer (saturates at 3) |
| citations | share of findings that carry a valid citation |
| grounding | lexical/numeric overlap between each finding and the passage it cites |

Levels: **high ≥ 0.75**, **medium ≥ 0.55**, otherwise **low**. Each score ships with its `reasons` (e.g. "only one source", "unrecognised term: …"), shown in the UI. Confidence is *measured*, not asked from the model.

## What is deliberately blocked, per sector

| Sector | Refused | Always added |
|---|---|---|
| Pharma | patient-specific dose, "ignore the rules" | not-medical-advice disclaimer |
| Medical | diagnosing the user, stopping/changing own medication, self-harm (→ crisis message) | disclaimer, "see a clinician" |
| Finance | buy/sell/hold advice, price targets, guaranteed returns | not-investment-advice; fiscal years always named |
| Marketing | guaranteed results, fake engagement, deceptive tactics | sample-data label |
| Hospitality | fake reviews, guest personal data, defamation | sample-data label |

## Known limits
Rules are pattern-based: a very creative paraphrase can slip past layer 1, but still has to pass layers 2–4, which are independent of the user's wording. Adding an LLM intent classifier as a second opinion is the planned hardening step (see `DESIGN.md`).

## Credentials
API keys are typed in the UI, kept in the browser's `sessionStorage`, sent with each request and used in memory only. They are never written to disk, logged or committed (`.gitignore` blocks `.env*`, `data/`, keys).
