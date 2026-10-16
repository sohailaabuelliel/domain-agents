"""Settings, provider credentials and domain configuration loading.

Credentials are resolved in this order (first hit wins):
  1. per-request ``LLMConfig`` (what the web UI "API settings" panel sends)
  2. process environment / ``.env`` file in the project root
They are never written to disk or logged by this project.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOMAINS_DIR = ROOT / "domains"
DATA_DIR = ROOT / "data"

DEFAULT_MODELS = {
    "gemini": "gemini-3.5-flash",
    "openai": "gpt-4o-mini",
    "azure": "gpt-4o-mini",  # for Azure this is the *deployment name*
}
GEMINI_FALLBACK_MODELS = ["gemini-2.5-flash"]  # used only when the primary returns 429/503


def load_dotenv(path: Path | None = None) -> None:
    """Tiny .env loader (no extra dependency). Does not override real environment variables."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$", line)
        if m and not line.lstrip().startswith("#"):
            os.environ.setdefault(m.group(1), m.group(2).strip().strip("\"'"))


@dataclass
class LLMConfig:
    """Which model backend to use and how to authenticate to it."""

    provider: str = "gemini"            # gemini | openai | azure
    api_key: str | None = None
    model: str | None = None            # azure: deployment name
    azure_endpoint: str | None = None   # https://<resource>.openai.azure.com
    api_version: str = "2024-10-21"
    base_url: str | None = None         # any OpenAI-compatible server (optional)
    temperature: float = 0.0

    def resolved(self) -> "LLMConfig":
        """Fill gaps from the environment; raise a clear error if no key is available."""
        load_dotenv()
        p = (self.provider or "gemini").lower()
        env_key = {
            "gemini": os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
            "openai": os.environ.get("OPENAI_API_KEY"),
            "azure": os.environ.get("AZURE_OPENAI_API_KEY"),
        }.get(p)
        cfg = LLMConfig(
            provider=p,
            api_key=self.api_key or env_key,
            model=self.model or os.environ.get(f"{p.upper()}_MODEL") or DEFAULT_MODELS.get(p),
            azure_endpoint=self.azure_endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT"),
            api_version=self.api_version or os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            base_url=self.base_url or os.environ.get("OPENAI_BASE_URL"),
            temperature=self.temperature,
        )
        if not cfg.api_key:
            raise MissingCredentials(
                f"No API key for provider '{p}'. Paste one in the UI (⚙ API settings) or set it in .env."
            )
        if p == "azure" and not cfg.azure_endpoint:
            raise MissingCredentials("Azure OpenAI needs an endpoint (https://<resource>.openai.azure.com).")
        return cfg

    def public(self) -> dict[str, Any]:
        """Safe-to-return description (never includes the key)."""
        return {"provider": self.provider, "model": self.model, "has_key": bool(self.api_key)}


class MissingCredentials(RuntimeError):
    pass


# --------------------------------------------------------------------------- domains
@dataclass
class DomainConfig:
    """Everything that differs between industries. The engine code never mentions a domain by name."""

    id: str
    display_name: str
    use_case: str
    tasks: list[str]
    system_prompt: str
    few_shots: list[dict[str, str]]
    answer_labels: dict[str, str]
    knowledge_dir: Path
    collection: str
    tools: list[str]
    guardrails: dict[str, Any]
    entities: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    example_questions: list[str] = field(default_factory=list)
    disclaimer: str = ""
    languages: list[str] = field(default_factory=lambda: ["en", "ar"])
    accent: str = "#0d7a6f"
    icon: str = "🧪"

    @property
    def min_score(self) -> float:
        return float(self.guardrails.get("min_retrieval_score", 0.55))

    @property
    def blocked_intents(self) -> list[dict[str, str]]:
        return self.guardrails.get("blocked_intents", [])


def load_domain(domain_id: str) -> DomainConfig:
    folder = DOMAINS_DIR / domain_id
    raw = yaml.safe_load((folder / "domain.yaml").read_text(encoding="utf-8"))
    shots_path = folder / "few_shots.yaml"
    shots = yaml.safe_load(shots_path.read_text(encoding="utf-8")) if shots_path.exists() else []
    return DomainConfig(
        id=domain_id,
        display_name=raw["display_name"],
        use_case=raw["use_case"],
        tasks=raw["tasks"],
        system_prompt=raw["system_prompt"].strip(),
        few_shots=shots or [],
        answer_labels=raw.get("answer_labels", {}),
        knowledge_dir=folder / "knowledge",
        collection=raw.get("collection", domain_id),
        tools=raw.get("tools", []),
        guardrails=raw.get("guardrails", {}),
        entities=raw.get("entities", []),
        aliases=raw.get("aliases", {}),
        example_questions=raw.get("example_questions", []),
        disclaimer=raw.get("disclaimer", "").strip(),
        languages=raw.get("languages", ["en", "ar"]),
        accent=raw.get("accent", "#0d7a6f"),
        icon=raw.get("icon", "🧪"),
    )


def list_domains() -> list[str]:
    return sorted(p.name for p in DOMAINS_DIR.iterdir() if (p / "domain.yaml").exists())
