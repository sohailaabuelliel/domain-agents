"""FastAPI server: serves the web UI and streams agent traces as Server-Sent Events.

Run:  uvicorn api.server:app --port 8000
API keys arrive per request from the UI (never stored); falls back to .env / environment variables.
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from domain_agent.agent import DomainAgent, build_agent
from domain_agent.config import ROOT, LLMConfig, MissingCredentials, list_domains, load_domain
from domain_agent.llm import list_models, make_llm
from domain_agent.memory import MemoryStore

app = FastAPI(title="Domain Agents", version="1.0")
WEB = ROOT / "web"
_agents: dict[tuple, DomainAgent] = {}
_lock = threading.Lock()
MEMORY = MemoryStore()


class LLMSettings(BaseModel):
    provider: str = "gemini"
    api_key: Optional[str] = None
    model: Optional[str] = None
    azure_endpoint: Optional[str] = None


class AskBody(BaseModel):
    domain: str
    question: str
    language: str = "auto"
    review: bool = True
    backend: str = "hybrid"
    llm: LLMSettings = LLMSettings()
    history: list[dict[str, Any]] = []
    session_id: str = "anon"


def _cfg(s: LLMSettings) -> LLMConfig:
    return LLMConfig(provider=s.provider, api_key=s.api_key or None, model=s.model or None, azure_endpoint=s.azure_endpoint or None)


def get_agent(body: AskBody) -> DomainAgent:
    cfg = _cfg(body.llm).resolved()
    key = (body.domain, cfg.provider, cfg.model, hash(cfg.api_key), body.backend)
    with _lock:
        if key not in _agents:
            _agents[key] = build_agent(load_domain(body.domain), _cfg(body.llm), body.backend)
        return _agents[key]


# ------------------------------------------------------------------ catalogue
@app.get("/api/domains")
def domains():
    out = []
    for d in list_domains():
        c = load_domain(d)
        n_docs = len(list(c.knowledge_dir.glob("*.md")))
        out.append({"id": c.id, "name": c.display_name, "icon": c.icon, "accent": c.accent, "use_case": c.use_case.strip(),
                    "tasks": c.tasks, "tools": c.tools, "examples": c.example_questions, "disclaimer": c.disclaimer,
                    "documents": n_docs, "min_score": c.min_score,
                    "ar": c.ui_ar,
                    "blocked_intents": [{"id": b["id"], "description": b.get("description", "")} for b in c.blocked_intents]})
    return out


@app.get("/api/checklist")
def checklist():
    return yaml.safe_load((ROOT / "docs" / "checklist.yaml").read_text(encoding="utf-8"))


@app.get("/api/docs")
def docs_index():
    return [{"file": p.name, "title": (p.read_text(encoding="utf-8").splitlines() or [p.stem])[0].lstrip("# ").strip()}
            for p in sorted((ROOT / "docs").glob("*.md"))]


@app.get("/api/docs/{name}")
def doc(name: str):
    p = ROOT / "docs" / Path(name).name
    if not p.exists() or p.suffix != ".md":
        raise HTTPException(404, "no such document")
    return {"file": p.name, "markdown": p.read_text(encoding="utf-8")}


@app.post("/api/test-key")
def test_key(s: LLMSettings):
    try:
        llm = make_llm(_cfg(s))
        r = llm.chat("Reply with the single word OK.", [__import__("domain_agent.llm", fromlist=["Msg"]).Msg("user", "ping")])
        return {"ok": True, "provider": llm.provider, "model": llm.model, "reply": r.text.strip()[:20]}
    except MissingCredentials as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300]}


_model_cache: dict[tuple, tuple[float, list[str]]] = {}


@app.post("/api/models")
def models(s: LLMSettings):
    """List the chat models the user's key can use, so the settings dropdown fills itself."""
    import time
    try:
        cfg = _cfg(s).resolved()
    except MissingCredentials as e:
        return {"ok": False, "error": str(e), "models": []}
    key = (cfg.provider, hash(cfg.api_key), cfg.azure_endpoint)
    hit = _model_cache.get(key)
    if hit and time.time() - hit[0] < 600:
        return {"ok": True, "provider": cfg.provider, "models": hit[1], "default": cfg.model}
    try:
        ids = list_models(cfg)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:240]}", "models": []}
    _model_cache[key] = (time.time(), ids)
    return {"ok": True, "provider": cfg.provider, "models": ids, "default": cfg.model}


# ------------------------------------------------------------------ ask (SSE)
@app.post("/api/ask")
async def ask(body: AskBody):
    q: queue.Queue = queue.Queue()

    def worker():
        try:
            agent = get_agent(body)
            mem = MEMORY.get(body.session_id)
            learned = mem.learn(body.question)
            if learned:
                q.put(("trace", {"t": 0, "type": "memory_learned", "items": learned}))
            q.put(("start", {"domain": body.domain, "provider": agent.llm.provider, "model": agent.llm.model}))
            res = agent.ask(body.question, body.language, body.history, body.review, emit=lambda e: q.put(("trace", e)), memory_note=mem.note())
            out = res.to_dict(); out["memory"] = mem.public()
            q.put(("result", out))
        except MissingCredentials as e:
            q.put(("fatal", {"code": "missing_key", "message": str(e)}))
        except Exception as e:  # noqa: BLE001
            q.put(("fatal", {"code": "error", "message": f"{type(e).__name__}: {str(e)[:300]}"}))
        q.put(("end", {}))

    threading.Thread(target=worker, daemon=True).start()

    async def stream():
        loop = asyncio.get_running_loop()
        while True:
            kind, data = await loop.run_in_executor(None, q.get)
            yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            if kind == "end":
                break

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/memory/{session_id}")
def get_memory(session_id: str):
    return {"preferences": MEMORY.get(session_id).public()}


@app.delete("/api/memory/{session_id}")
def clear_memory(session_id: str):
    MEMORY.clear(session_id)
    return {"preferences": []}


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")
app.mount("/docs-media", StaticFiles(directory=ROOT / "docs" / "media", check_dir=False), name="docs-media")
