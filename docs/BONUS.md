# Bonus features

| Bonus | Status | Where | How it works |
|---|---|---|---|
| **Multi-agent** (analyst + safety reviewer) | done, all 5 sectors | `agent._review`, `domains/*/domain.yaml → reviewer` | A second LLM role with a different prompt audits the draft before the user sees it. Each sector has its own reviewer checklist (`reviewer_focus` in `domain.yaml`): Finance checks fiscal years and advice-like wording; Marketing checks for promised results and correlation-as-causation; Hospitality for guest identification; Medical for diagnoses and medication changes; Pharma uses the default dose/diagnosis checklist. Trace shows `reviewer: approved / objected`. |
| **Memory** | done | `domain_agent/memory.py`, `/api/memory/{session}` | Per-session preferences (language, length, role, format, name, explanation level) learned from plain sentences like "I'm a pharmacist, keep it short, answer in Arabic" and injected as a style note. Rule-based: free, deterministic, tested. Cannot loosen safety rules (note is appended after them; input screening runs first; names are validated). "Forget my preferences" clears it. UI shows what is remembered with a *forget* button. |
| **Live tool use (PubMed)** | done | `domain_agent/tools.py` | In Pharma/Medical the agent can call `pubmed_search` (NCBI E-utilities) when the local sources are not enough; results are cited like any other source. Finance, Marketing and Hospitality use only the local search tool: their ratios (margins, growth, ROAS) are pre-computed from the raw figures when the knowledge files are generated, and each is labelled "computed". |
| **Chat UI** | done | `web/`, `api/server.py` | Domain switcher, streaming trace, clickable citations, confidence, severity colours, example questions, settings drawer for provider/model/API key, Checklist & spec tab, evaluation tab. No build step. |
| **Bilingual Arabic/English** | partial | `aliases` in each `domain.yaml`, `memory.py`, UI `dir=auto` | Questions in Arabic are answered in Arabic; Arabic entity names map to English sources. Retrieval of Arabic questions against English sources scores lower — measured in `EVALUATION.md`. |
| **Swappable provider** | done | `domain_agent/llm.py` | Gemini (default), OpenAI, Azure OpenAI; chosen in the UI or via config. |
| **Evaluation harness** | done | `eval/run_eval.py` | See `EVALUATION.md`. |
| **Two retrieval backends** | done | `retrieval.py` | `hybrid` (default) and `file_search` (Gemini File Search) — selectable with `backend` in the API. |

## Using memory in the demo
1. "I'm a pharmacist. Keep answers short."  → chip *User role: pharmacist · Answer length: short*
2. Ask any question → shorter, professional wording.
3. "Answer in Arabic from now on." → Arabic replies, citations unchanged.
4. Click *forget* → back to defaults.

## Interface: live model list and Arabic UI
* **Settings → Model** is filled by the provider itself (`POST /api/models`): Gemini and OpenAI list the chat models the key can call (embedding, image, audio and TTS models are filtered out; newest first); Azure lists the resource's deployments. A *Custom* option stays for anything unlisted.
* **EN / عربي switch** translates every UI label and mirrors the layout right-to-left. Sector names, tasks and disclaimers come from each `domain.yaml` (`ui_ar:` block), so a new sector adds its Arabic text without code. Documentation stays in English.
* **Icons** for the five sectors and the logo were generated with OpenAI `gpt-image` and are stored as small PNGs in `web/icons/`.
