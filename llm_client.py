"""Unified LLM API client — supports OpenAI-compatible and Anthropic APIs."""

import json
import logging
import requests
from typing import Optional

logger = logging.getLogger("ghost.llm")


class LLMClient:
    """Thin wrapper that normalizes OpenAI-compatible and Anthropic chat APIs."""

    def __init__(self, config: dict):
        self.provider = config.get("provider", "openai")
        self.api_key = config["api_key"]
        self.base_url = config.get("base_url", "https://api.openai.com/v1").rstrip("/")
        self.model = config.get("model", "gpt-4o-mini")
        self.max_tokens = config.get("max_tokens", 4096)
        self.temperature = config.get("temperature", 0.3)

    # ── public ────────────────────────────────────────────

    def chat(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        """Send a chat completion and return the assistant's text."""
        if self.provider == "anthropic":
            return self._anthropic(messages, system, json_mode)
        return self._openai(messages, system, json_mode)

    # ── OpenAI-compatible (Groq, Together, Ollama, LM Studio, OpenAI) ─

    def _openai(self, messages, system, json_mode) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)

        payload = {
            "model": self.model,
            "messages": msgs,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        logger.debug("POST %s/chat/completions  model=%s  msgs=%d",
                      self.base_url, self.model, len(msgs))
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    # ── Anthropic ─────────────────────────────────────────

    def _anthropic(self, messages, system, json_mode) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": messages,
        }
        if system:
            payload["system"] = system

        logger.debug("POST anthropic  model=%s  msgs=%d", self.model, len(messages))
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]