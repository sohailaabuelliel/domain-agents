# Domain Agents — one reconfigurable AI agent engine, five sectors

[![tests](https://github.com/sohailaabuelliel/domain-agents/actions/workflows/tests.yml/badge.svg)](https://github.com/sohailaabuelliel/domain-agents/actions)

**▶ 1-minute demo video:** [`docs/media/demo.mp4`](docs/media/demo.mp4) — recorded from the real running UI (new design): a cited Pharma answer, a guardrail refusal, an honest "no evidence", an Arabic question over English SEC filings, the English/Arabic UI switch, Settings with the live model list, and the built-in checklist/docs. Waiting time while the agent works is shown at 8× speed and labelled on screen.

A single agent engine that is re-pointed at a different sector **by configuration only** (YAML + a folder of knowledge files — no code changes). Five sectors ship ready to use:

| Sector | Agent | Knowledge base | Data |
|---|---|---|---|
| 💊 Pharma | Drug-safety assistant | 15 FDA drug labels + 6 PubMed sets | **real** (openFDA, PubMed) |
| 🩺 Medical | Clinical-information assistant | 15 MedlinePlus topics + PubMed reviews | **real** (NLM) |
| 📈 Finance | Financial-analyst assistant | 6 companies × 5 fiscal years | **real** (SEC EDGAR 10-K) |
| 📣 Marketing | Campaign-insights assistant | channel / campaign / audience data | *synthetic sample* (labelled) |
| 🏨 Hospitality | Guest-experience assistant | 121 EN + AR guest reviews, policies | *synthetic sample* (labelled) |

It answers **only from retrieved sources**, cites them, says **"no evidence found"** when it cannot support an answer, refuses out-of-scope requests (dosing, diagnosis, investment advice…), and shows a measured **confidence** score.

**Bonus items included:** multi-agent safety reviewer · conversation memory · live PubMed tool · chat UI with streaming trace · bilingual Arabic/English · swappable LLM provider · evaluation harness. See [docs/BONUS.md](docs/BONUS.md).

## Run it (3 commands)

```bash
python -m venv .venv && source .venv/bin/activate      # Python 3.11+
pip install -r requirements.txt
uvicorn api.server:app --port 8000                      # open http://localhost:8000
```

Then open **Settings** in the UI, choose a provider (**Gemini** by default, or OpenAI / Azure OpenAI) and **paste your own API key**. The **Model** list fills itself from that provider (only chat-capable models, newest first; Azure lists your deployments), so you pick a model instead of typing its name. Press *Test connection* to confirm. The key lives only in your browser tab; it is never stored or committed.

The interface has an **EN / عربي** switch (bottom of the sidebar). It translates the UI only and mirrors the layout right-to-left; the documentation stays in English, and the agent answers in the language of the question unless you choose one.
The vector indexes are pre-built and included, so the first question does not wait for indexing. Prefer a file? Copy `.env.example` to `.env`.

> **Free-tier note.** Each answer uses 3–4 model calls. A free Gemini key has small daily quotas; if you hit them the agent falls back to a lighter model automatically, and degrades to keyword search if embeddings are unavailable. A key with billing enabled avoids all of that.

Docker: `docker build -t domain-agents . && docker run -p 8000:8000 domain-agents`

## Try these
| Sector | Ask | Expect |
|---|---|---|
| Pharma | *Does fluconazole interact with warfarin? How serious?* | HIGH-severity finding, cited labels, confidence ~0.8 |
| Pharma | *What are the side effects of Zentrava?* | **No evidence found** (drug is not in the sources) |
| Pharma | *How much warfarin should my patient take?* | Instant refusal (0 model calls) |
| Finance | *Compare Microsoft and Amazon operating margin.* | Figures with fiscal years, computed ratios |
| Marketing | *Why did TikTok CTR drop after April?* | Creative-fatigue pattern from the data |
| Hospitality | *When did air-conditioning complaints peak?* | July (7 complaints) |
| Any | *I'm a pharmacist, keep it short, answer in Arabic* → ask anything | Memory chips appear; style changes |

## Switching or adding a sector (no code)
```bash
cp -r domains/hospitality domains/legal           # 1. copy a folder
$EDITOR domains/legal/domain.yaml                 # 2. prompt, refusals, aliases, threshold
cp my_documents/*.md domains/legal/knowledge/     # 3. markdown with a tiny front-matter header
python scripts/build_index.py legal               # 4. embed once (cached)
```
It appears in the UI automatically.

## How it is organised
```
domain_agent/   engine: config · llm · retrieval · guardrails · tools · agent · memory     ← code
domains/<d>/    domain.yaml · few_shots.yaml · knowledge/ · eval.yaml                       ← per-sector configuration
api/  web/      FastAPI + SSE server, static UI (no build step) · i18n.js = EN/AR UI strings
eval/  tests/   evaluation harness & reports · 61 offline unit tests (no API key needed)
scripts/        data fetchers (FDA, PubMed, MedlinePlus, SEC), index builder, CLI
docs/           ALL documentation (kept separate from code, per the brief)                 ← docs
```

## Documentation
* [Architecture](docs/ARCHITECTURE.md) — diagrams and the 7-step flow
* [Design, trade-offs & scaling](docs/DESIGN.md)
* [Guardrails & confidence](docs/GUARDRAILS.md)
* [Bonus features](docs/BONUS.md)
* [Evaluation](docs/EVALUATION.md) and [report](eval/reports/REPORT.md)
* [Demo script](docs/DEMO.md)
* [Requirements checklist](docs/checklist.yaml) — also live in the UI

## Tests
```bash
pytest -q                           # 61 offline tests, no key needed
python eval/run_eval.py             # 50 end-to-end cases, needs a key
```

## Safety & honesty
Informational only — not medical, legal or investment advice. Marketing and Hospitality data are **synthetic samples** and say so in every file and in the UI. Real sources are cited with links.
