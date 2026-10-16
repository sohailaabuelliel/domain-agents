# Demo script (about 8 minutes)

Goal: show that **one engine** serves several sectors, stays grounded, refuses what it should, and is measurable.

## Before you start
1. `uvicorn api.server:app --port 8000` → open http://localhost:8000
2. **Settings** → provider *Gemini* → paste your key → *Test connection* (green tick).

## 1. The idea in one sentence (30 s)
"One engine, five sectors. A sector is a YAML file plus a folder of documents — no code changes. Pharma, Medical and Finance use real public data; Marketing and Hospitality use labelled synthetic samples."
Click through the five agents in the left menu: same screen, different icon, prompt, examples and rules.

## 2. A grounded answer (Pharma, 90 s)
Ask: **Does fluconazole interact with warfarin? How serious is it?**
Point at: the live **trace** (search → coverage → answer → verification → reviewer) · the **HIGH** severity badge · the clickable **[S1] sources** with section and link · the **confidence** and its reasons.

## 3. It says "I don't know" (60 s)
Ask: **What are the side effects of Zentrava?** (invented drug)
→ *No evidence found.* "A model would happily invent side effects; ours detects an unknown name before generating."

## 4. It refuses (45 s)
Ask: **How much warfarin should my patient take every day?** → refused instantly (0 model calls, see the trace).
Then in Finance: **Should I buy Tesla stock?** → refused with an alternative.

## 5. Another sector, zero code (90 s)
Finance → **Compare Microsoft and Amazon operating margin.** → numbers carry their fiscal year; ratios are labelled *computed*.
Marketing → **Why did TikTok CTR drop after April?** → the creative-fatigue pattern, from the data.
Hospitality → **When did air-conditioning complaints peak?** → July.

## 6. Memory and Arabic (60 s)
Type: **I'm a pharmacist. Keep it short and answer in Arabic.** → chips appear under the header.
Ask any Pharma question → short Arabic answer, citations unchanged. Click *forget*.

## 7. Swap the model (30 s)
Settings → switch provider to OpenAI or Azure, paste a key → same agent, same guardrails. "The LLM is a config value."

## 8. Measured, not claimed (60 s)
Open **Checklist & spec** (requirement → where it is implemented) and the evaluation report: retrieval accuracy, answer accuracy, hallucination rate, refusal accuracy per sector.

## 9. Close (30 s)
"Everything is in the repo: code in `domain_agent/`, configuration in `domains/`, documentation separately in `docs/`, 49 offline tests, and a Dockerfile."

## If something goes wrong
| Symptom | Cause | Fix |
|---|---|---|
| "quota" / 429 message | Free-tier daily limit | Paste a billed key; the agent already falls back to a lighter model |
| Very slow first answer | Cold start / model queue | Wait; the trace shows progress |
| Arabic question → "no evidence" | Arabic vs English similarity under threshold | Rephrase with the English term, or see `EVALUATION.md` |
