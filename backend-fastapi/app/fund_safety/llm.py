from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import (
    LLM_CONFIG,
    LLM_ENABLED,
    LLM_PROVIDERS_CONFIG,
    DISCOVERY_PROVIDER,
    DISCOVERY_MODEL,
    ASSESSMENT_PROVIDER,
    ASSESSMENT_MODEL,
)
from .models import Finding, Severity

SYSTEM_REVIEW = """You are a fintech fund-safety code reviewer. Review ONLY the provided evidence. Return compact JSON with: confirmed:boolean, confidence:0..1, explanation:string, recommended_fix:string. Do not invent code not present in evidence."""

SYSTEM_AGENT = """You are an autonomous fintech fund-safety agent.
You must be conservative and evidence-first.
Only reason from the provided index, targets, snippets, and assessment criteria.
Do not invent source code or call paths that are not present.
Prefer structured JSON output when requested.
"""


def should_review(f: Finding) -> bool:
    return f.severity in {Severity.HIGH, Severity.CRITICAL}


@dataclass
class StageLLMConfig:
    """Provider config for one pipeline stage.

    Stages are intentionally independent:
    - discovery: claude_code | anthropic_api | ollama | mock
    - assessment: junie | claude_code | anthropic_api | openai | ollama | mock
    """

    stage: str = "assessment"
    provider: str = "mock"
    model: str = "claude-sonnet-4-5"
    timeout_seconds: int = 600
    max_chars: int = 120_000
    provider_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def for_stage(cls, stage: str) -> "StageLLMConfig":
        stage = stage.strip().lower()
        stage_cfg = LLM_CONFIG.get(stage, {}) or {}
        if not isinstance(stage_cfg, dict):
            stage_cfg = {}
        default_provider = DISCOVERY_PROVIDER if stage == "discovery" else ASSESSMENT_PROVIDER
        default_model = DISCOVERY_MODEL if stage == "discovery" else ASSESSMENT_MODEL
        env_prefix = stage.upper()

        provider = os.getenv(f"{env_prefix}_PROVIDER", str(stage_cfg.get("provider", default_provider))).strip().lower()
        # Priority: env var > stage config > provider config > default
        env_model = os.getenv(f"{env_prefix}_MODEL")
        stage_model = stage_cfg.get("model")
        if env_model:
            model = str(env_model)
        elif stage_model:
            model = str(stage_model)
        else:
            model = str(default_model)

        if not LLM_ENABLED and not os.getenv("LLM_ENABLED"):
            provider = "mock"

        providers = LLM_PROVIDERS_CONFIG if isinstance(LLM_PROVIDERS_CONFIG, dict) else {}
        provider_cfg = providers.get(provider, {}) or {}
        if not isinstance(provider_cfg, dict):
            provider_cfg = {}

        # Provider-specific model fallback (only if not explicitly set via env or stage config).
        if not env_model and not stage_model:
            if provider == "ollama":
                model = str(provider_cfg.get("model", model))
            elif provider == "openai":
                model = str(provider_cfg.get("model", model))

        return cls(
            stage=stage,
            provider=provider,
            model=model,
            timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", str(LLM_CONFIG.get("timeout_seconds", 600)))),
            max_chars=int(os.getenv("LLM_MAX_CHARS", str(LLM_CONFIG.get("max_chars", 120000)))),
            provider_config=provider_cfg,
        )


# Backward-compatible alias used by older code paths.
@dataclass
class LLMConfig(StageLLMConfig):
    @classmethod
    def from_config(cls) -> "LLMConfig":
        base = StageLLMConfig.for_stage("assessment")
        return cls(**base.__dict__)

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls.from_config()


class LLMUnavailable(RuntimeError):
    pass


class LLMClient:
    """Stage-aware provider abstraction.

    Python owns orchestration and artifacts. Providers only perform bounded
    reasoning on supplied evidence. They never freely scan the repository.
    """

    def __init__(self, config: StageLLMConfig | None = None):
        self.config = config or StageLLMConfig.for_stage("assessment")

    @classmethod
    def for_stage(cls, stage: str) -> "LLMClient":
        return cls(StageLLMConfig.for_stage(stage))

    @property
    def enabled(self) -> bool:
        return self.config.provider not in {"", "mock", "none", "off"}

    def generate(self, prompt: str, system: str = SYSTEM_AGENT, cwd: str | None = None) -> str:
        provider = self.config.provider
        prompt = prompt[: self.config.max_chars]
        if provider in {"", "mock", "none", "off"}:
            raise LLMUnavailable(f"{self.config.stage} provider is mock/off")
        if provider == "claude_code":
            return self._generate_cli(prompt, system=system, cwd=cwd, default_binary="claude")
        if provider == "junie":
            return self._generate_cli(prompt, system=system, cwd=cwd, default_binary="junie")
        if provider == "anthropic_api":
            return self._generate_anthropic_api(prompt, system=system)
        if provider == "openai":
            return self._generate_openai_compatible(prompt, system=system)
        if provider == "ollama":
            return self._generate_ollama(prompt, system=system)
        raise LLMUnavailable(f"Unsupported {self.config.stage} provider={provider!r}")

    def _generate_cli(self, prompt: str, system: str, cwd: str | None = None, default_binary: str = "claude") -> str:
        cfg = self.config.provider_config
        binary = os.getenv(f"{self.config.provider.upper()}_BIN", str(cfg.get("binary", default_binary)))
        args = cfg.get("args", ["-p"])
        if isinstance(args, str):
            args = [args]
        if not isinstance(args, list):
            args = ["-p"]
        full_prompt = f"{system}\n\n{prompt}"
        result = subprocess.run(
            [binary, *[str(x) for x in args], full_prompt],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=self.config.timeout_seconds,
        )
        if result.returncode != 0:
            raise LLMUnavailable(result.stderr.strip() or f"{binary} exited with {result.returncode}")
        return result.stdout.strip()

    def _generate_anthropic_api(self, prompt: str, system: str) -> str:
        cfg = self.config.provider_config
        api_key_env = str(cfg.get("api_key_env", "ANTHROPIC_API_KEY"))
        api_key = os.getenv(api_key_env, str(cfg.get("api_key", "") or ""))
        if not api_key:
            raise LLMUnavailable(f"{api_key_env} is not configured")
        base_url = str(cfg.get("base_url", "https://api.anthropic.com")).rstrip("/")
        version = str(cfg.get("version", "2023-06-01"))
        headers = {"x-api-key": api_key, "anthropic-version": version, "content-type": "application/json"}
        payload = {
            "model": self.config.model,
            "max_tokens": 12000,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            r = client.post(base_url + "/v1/messages", headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        blocks = data.get("content", [])
        return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()

    def _generate_openai_compatible(self, prompt: str, system: str) -> str:
        cfg = self.config.provider_config
        api_key_env = str(cfg.get("api_key_env", "OPENAI_API_KEY"))
        api_key = os.getenv(api_key_env, str(cfg.get("api_key", "") or ""))
        if not api_key:
            raise LLMUnavailable(f"{api_key_env} is not configured")
        base_url = str(cfg.get("base_url", "https://api.openai.com/v1")).rstrip("/")
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        headers = {"authorization": f"Bearer {api_key}", "content-type": "application/json"}
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            r = client.post(base_url + "/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

    def _generate_ollama(self, prompt: str, system: str) -> str:
        cfg = self.config.provider_config
        model = self.config.model or str(cfg.get("model", "qwen2.5-coder:14b"))
        base_url = str(cfg.get("base_url", "http://localhost:11434")).rstrip("/")
        payload = {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            r = client.post(base_url + "/api/chat", json=payload)
            r.raise_for_status()
            return r.json().get("message", {}).get("content", "").strip()


def extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


def extract_json_array(text: str) -> list[Any] | None:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


async def review_with_ollama(finding: Finding, model: str | None = None, base_url: str | None = None) -> dict:
    cfg = StageLLMConfig.for_stage("assessment")
    provider_cfg = cfg.provider_config or {}
    model = model or cfg.model or str(provider_cfg.get("model", "qwen2.5-coder:14b"))
    base_url = base_url or str(provider_cfg.get("base_url", "http://localhost:11434"))
    prompt = {
        "finding": finding.model_dump(exclude={"llm_review", "autofix_patch"}),
        "instruction": "Validate whether this is a real fintech fund-loss risk. Be conservative.",
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{base_url.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": SYSTEM_REVIEW},
                        {"role": "user", "content": json.dumps(prompt)[:12000]},
                    ],
                },
            )
            r.raise_for_status()
            content = r.json().get("message", {}).get("content", "{}")
            parsed = extract_json_object(content)
            if parsed:
                return parsed
            return {"confirmed": True, "confidence": finding.confidence, "explanation": content[:500], "recommended_fix": finding.remediation}
    except Exception as e:
        return {"confirmed": None, "confidence": finding.confidence, "explanation": f"LLM review unavailable: {e}", "recommended_fix": finding.remediation}
