"""Unified LLM API client — supports OpenAI-compatible and Anthropic APIs.
Includes retry with exponential backoff and rate-limit pacing."""

import json
import logging
import time
import requests
from typing import Optional

logger = logging.getLogger("ghost.llm")

# Minimum seconds between API calls (prevents burst-triggered 429s)
DEFAULT_MIN_INTERVAL = 3.0


class RateLimitError(Exception):
    """Raised when an LLM rate limit is hit and cannot be handled by simple retry."""
    def __init__(self, message: str, retry_after_seconds: float = 0):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LLMClient:
    """Thin wrapper that normalizes OpenAI-compatible and Anthropic chat APIs."""

    def __init__(self, config: dict):
        self.provider = config.get("provider", "openai")
        self.api_key = config["api_key"]
        self.base_url = config.get("base_url", "https://api.openai.com/v1").rstrip("/")
        self.model = config.get("model", "gpt-4o-mini")
        self.max_tokens = config.get("max_tokens", 4096)
        self.temperature = config.get("temperature", 0.3)
        self.min_interval = config.get("min_interval", DEFAULT_MIN_INTERVAL)
        self.json_mode_supported = config.get("json_mode_supported", True)
        self._last_call = 0.0

    def _pace(self):
        """Enforce minimum interval between calls."""
        now = time.time()
        elapsed = now - self._last_call
        if elapsed < self.min_interval:
            wait = self.min_interval - elapsed
            logger.debug("Pacing: waiting %.1fs before next call", wait)
            time.sleep(wait)
        self._last_call = time.time()

    def chat(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        json_mode: bool = False,
        max_retries: int = 4,
    ) -> str:
        """Send a chat completion and return the assistant's text.
        Retries on 429/5xx with exponential backoff.
        Raises RateLimitError if a long wait is required."""
        last_exc = None
        for attempt in range(max_retries):
            try:
                self._pace()
                if self.provider == "anthropic":
                    return self._anthropic(messages, system, json_mode)
                return self._openai(messages, system, json_mode)
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response else 0
                if status == 429:
                    # Parse retry-after from header or body
                    retry_after = self._parse_retry_after(exc.response)
                    if retry_after > 60:
                        # Too long to wait sync — raise for caller to pause
                        raise RateLimitError(
                            f"Rate limit exceeded (TPD/RPM). Retry after {retry_after}s.",
                            retry_after_seconds=retry_after
                        )
                    
                    wait = retry_after if retry_after > 0 else (2 ** attempt) * 3
                    logger.warning("HTTP 429 (Rate Limit), retrying in %ds…", wait)
                    time.sleep(wait)
                    last_exc = exc
                    continue

                if status in (500, 502, 503, 529) and attempt < max_retries - 1:
                    wait = (2 ** attempt) * 3  # 3s, 6s, 12s, 24s
                    logger.warning(
                        "HTTP %d on attempt %d/%d — retrying in %ds…",
                        status, attempt + 1, max_retries, wait,
                    )
                    time.sleep(wait)
                    last_exc = exc
                    continue
                raise
            except requests.exceptions.ConnectionError as exc:
                if attempt < max_retries - 1:
                    wait = (2 ** attempt) * 3
                    logger.warning("Connection error, retrying in %ds…", wait)
                    time.sleep(wait)
                    last_exc = exc
                    continue
                raise
        raise last_exc

    def _parse_retry_after(self, response) -> float:
        """Extract retry-after value from headers or body (Groq specific)."""
        # 1. Try standard header
        header = response.headers.get("Retry-After")
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        
        # 2. Try parsing Groq error body for "Please try again in XmYs"
        try:
            body = response.json()
            message = body.get("error", {}).get("message", "")
            if "Please try again in" in message:
                # Simple extraction for "XmYs.Z" or "Xs"
                import re
                m = re.search(r"try again in (?:(\d+)m)?(?:([\d.]+)s)?", message)
                if m:
                    minutes = float(m.group(1) or 0)
                    seconds = float(m.group(2) or 0)
                    return minutes * 60 + seconds
        except Exception:
            pass
            
        return 0.0

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
        if json_mode and self.json_mode_supported:
            payload["response_format"] = {"type": "json_object"}

        logger.debug("POST %s/chat/completions  model=%s  msgs=%d",
                      self.base_url, self.model, len(msgs))
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=180,
        )
        if not resp.ok:
            logger.error("HTTP %d from %s: %s", resp.status_code, self.model, resp.text[:800])
            print(f"[API error {resp.status_code}] {resp.text[:800]}", flush=True)
        resp.raise_for_status()
        self._last_call = time.time()
        return resp.json()["choices"][0]["message"]["content"]

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
        self._last_call = time.time()
        return resp.json()["content"][0]["text"]