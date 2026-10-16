"""Provider-neutral LLM layer.

The agent only ever talks to ``LLM`` (chat / structured). Swapping Gemini for OpenAI or Azure OpenAI is a
configuration change (``LLMConfig.provider``), never a code change in the agent.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import GEMINI_FALLBACK_MODELS, LLMConfig


# ---------------------------------------------------------------- neutral message types
@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])


@dataclass
class Msg:
    role: str                              # user | assistant | tool
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_name: str | None = None           # for role == tool
    tool_call_id: str | None = None
    raw: Any = None                        # provider-native object (keeps Gemini thought signatures)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]             # JSON schema


@dataclass
class LLMResult:
    text: str
    tool_calls: list[ToolCall]
    raw: Any = None
    prompt_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class LLMError(RuntimeError):
    pass


def _retry(fn: Callable[[], Any], attempts: int = 4, base: float = 2.0) -> Any:
    """Retry transient errors (429 / 5xx / timeouts) with exponential backoff."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - provider SDKs raise many types
            msg = str(e)
            transient = any(t in msg for t in ("429", "500", "502", "503", "504", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "timed out", "Timeout", "overloaded"))
            if not transient or i == attempts - 1:
                raise
            last = e
            m = re.search(r"retry in ([0-9.]+)s", msg, re.I)   # honour the server's own hint (free-tier quotas)
            time.sleep(min(float(m.group(1)) + 1, 70) if m else base * (2 ** i))
    raise LLMError(str(last))


class LLM:
    """Interface. ``chat`` runs one model turn (optionally with tools); ``structured`` returns JSON text."""

    provider = "base"
    model = ""

    def chat(self, system: str, messages: list[Msg], tools: list[ToolSpec] | None = None,
             schema: dict | None = None, temperature: float = 0.0) -> LLMResult:
        raise NotImplementedError

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        raise NotImplementedError


# ---------------------------------------------------------------- Gemini
class GeminiLLM(LLM):
    provider = "gemini"
    EMBED_MODEL = "gemini-embedding-001"
    EMBED_DIM = 768

    def __init__(self, cfg: LLMConfig):
        from google import genai
        self._genai = genai
        self.client = genai.Client(api_key=cfg.api_key)
        self.model = cfg.model or "gemini-3.5-flash"
        self.default_temp = cfg.temperature

    # -- conversion --
    def _contents(self, messages: list[Msg]):
        from google.genai import types
        out: list[Any] = []
        pending_tool_parts: list[Any] = []

        def flush():
            nonlocal pending_tool_parts
            if pending_tool_parts:
                out.append(types.Content(role="user", parts=pending_tool_parts))
                pending_tool_parts = []

        for m in messages:
            if m.role == "tool":
                try:
                    payload = json.loads(m.text)
                    if not isinstance(payload, dict):
                        payload = {"result": payload}
                except (json.JSONDecodeError, TypeError):
                    payload = {"result": m.text}
                pending_tool_parts.append(types.Part.from_function_response(name=m.tool_name or "tool", response=payload))
                continue
            flush()
            if m.role == "assistant":
                out.append(m.raw if m.raw is not None else types.Content(role="model", parts=[types.Part(text=m.text or " ")]))
            else:
                out.append(types.Content(role="user", parts=[types.Part(text=m.text)]))
        flush()
        return out

    def _call(self, model: str, system: str, messages: list[Msg], tools, schema, temperature) -> LLMResult:
        from google.genai import types
        kwargs: dict[str, Any] = dict(system_instruction=system, temperature=temperature)
        if tools:
            kwargs["tools"] = [types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters) for t in tools])]
            kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
        if schema:
            kwargs["response_mime_type"] = "application/json"
            kwargs["response_json_schema"] = schema
        r = self.client.models.generate_content(model=model, contents=self._contents(messages), config=types.GenerateContentConfig(**kwargs))
        cand = r.candidates[0].content if r.candidates else None
        calls, text = [], ""
        for p in (cand.parts or []) if cand else []:
            if p.function_call:
                calls.append(ToolCall(name=p.function_call.name or "", args=dict(p.function_call.args or {})))
            elif p.text and not getattr(p, "thought", False):
                text += p.text
        u = r.usage_metadata
        return LLMResult(text=text, tool_calls=calls, raw=cand, model=model,
                         prompt_tokens=(u.prompt_token_count or 0) if u else 0, output_tokens=(u.candidates_token_count or 0) if u else 0)

    def chat(self, system, messages, tools=None, schema=None, temperature=0.0):
        models = [self.model] + [m for m in GEMINI_FALLBACK_MODELS if m != self.model]
        last: Exception | None = None
        for model in models:
            try:
                return _retry(lambda: self._call(model, system, messages, tools, schema, temperature), attempts=3)
            except Exception as e:  # noqa: BLE001
                last = e
                if not any(t in str(e) for t in ("429", "503", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                    break
        raise LLMError(f"Gemini request failed: {str(last)[:300]}")

    def embed(self, texts, kind="document"):
        from google.genai import types
        task = "RETRIEVAL_DOCUMENT" if kind == "document" else "RETRIEVAL_QUERY"
        vectors: list[list[float]] = []
        # Free tier = 100 embedded texts / minute: send 90 at a time and pause between batches.
        for i in range(0, len(texts), 90):
            if i and len(texts) > 90:
                time.sleep(61)
            batch = texts[i:i + 90]
            r = _retry(attempts=5, fn=lambda b=batch: self.client.models.embed_content(
                model=self.EMBED_MODEL, contents=b,
                config=types.EmbedContentConfig(task_type=task, output_dimensionality=self.EMBED_DIM)))
            vectors += [list(e.values or []) for e in (r.embeddings or [])]
        return vectors


# ---------------------------------------------------------------- OpenAI / Azure OpenAI
class OpenAILLM(LLM):
    provider = "openai"
    EMBED_MODEL = "text-embedding-3-small"

    def __init__(self, cfg: LLMConfig):
        import openai
        if cfg.provider == "azure":
            self.client = openai.AzureOpenAI(api_key=cfg.api_key, azure_endpoint=cfg.azure_endpoint, api_version=cfg.api_version)
            self.provider = "azure"
        else:
            self.client = openai.OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        self.model = cfg.model or "gpt-4o-mini"

    def _messages(self, system: str, messages: list[Msg]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "tool":
                out.append({"role": "tool", "tool_call_id": m.tool_call_id or "", "content": m.text})
            elif m.role == "assistant":
                d: dict[str, Any] = {"role": "assistant", "content": m.text or None}
                if m.tool_calls:
                    d["tool_calls"] = [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.args)}} for c in m.tool_calls]
                out.append(d)
            else:
                out.append({"role": "user", "content": m.text})
        return out

    def chat(self, system, messages, tools=None, schema=None, temperature=0.0):
        kwargs: dict[str, Any] = dict(model=self.model, messages=self._messages(system, messages), temperature=temperature)
        if tools:
            kwargs["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}} for t in tools]
        if schema:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema, "strict": False}}
        r = _retry(lambda: self.client.chat.completions.create(**kwargs))
        msg = r.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(name=tc.function.name, args=args, id=tc.id))
        u = r.usage
        return LLMResult(text=msg.content or "", tool_calls=calls, model=self.model,
                         prompt_tokens=getattr(u, "prompt_tokens", 0) or 0, output_tokens=getattr(u, "completion_tokens", 0) or 0)

    def embed(self, texts, kind="document"):
        model = self.model if self.provider == "azure" and "embedding" in self.model else self.EMBED_MODEL
        vectors: list[list[float]] = []
        for i in range(0, len(texts), 100):
            r = _retry(lambda b=texts[i:i + 100]: self.client.embeddings.create(model=model, input=b))
            vectors += [d.embedding for d in r.data]
        return vectors


def make_llm(cfg: LLMConfig | None = None) -> LLM:
    cfg = (cfg or LLMConfig()).resolved()
    if cfg.provider == "gemini":
        return GeminiLLM(cfg)
    if cfg.provider in ("openai", "azure"):
        return OpenAILLM(cfg)
    raise ValueError(f"Unknown provider '{cfg.provider}' (use gemini | openai | azure)")
