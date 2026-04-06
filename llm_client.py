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


class _ProviderConfig:
    """Settings for a single LLM provider endpoint."""

    def __init__(self, config: dict):
        self.provider = config.get("provider", "openai")
        self.api_key = config.get("api_key", "")
        self.base_url = config.get("base_url", "https://api.openai.com/v1").rstrip("/")
        self.model = config.get("model", "gpt-4o-mini")
        self.max_tokens = config.get("max_tokens", 4096)
        self.temperature = config.get("temperature", 0.3)
        self.min_interval = config.get("min_interval", DEFAULT_MIN_INTERVAL)
        self.json_mode_supported = config.get("json_mode_supported", True)
        # Ignore shell-level proxy env vars by default so a broken desktop/app
        # proxy does not make every provider appear unreachable.
        self.trust_env = config.get("trust_env", False)


class LLMClient:
    """Thin wrapper that normalizes OpenAI-compatible and Anthropic chat APIs.

    Supports provider cascade: if config contains a `providers` list, tries each
    in order, falling back on connection errors or 5xx. Single-provider config
    (no `providers` key) still works as before.
    """

    def __init__(self, config: dict):
        # Support both single-provider and cascade configs
        if "providers" in config:
            self._providers = [_ProviderConfig(p) for p in config["providers"]]
        else:
            self._providers = [_ProviderConfig(config)]

        # Expose primary provider's settings for backward compat (ping, etc.)
        p = self._providers[0]
        self.provider = p.provider
        self.api_key = p.api_key
        self.base_url = p.base_url
        self.model = p.model
        self.max_tokens = p.max_tokens
        self.temperature = p.temperature
        self.min_interval = p.min_interval
        self.json_mode_supported = p.json_mode_supported
        self._last_call = 0.0

    def _pace(self, min_interval: float):
        """Enforce minimum interval between calls."""
        now = time.time()
        elapsed = now - self._last_call
        if elapsed < min_interval:
            wait = min_interval - elapsed
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

        With provider cascade: tries each provider in order. Falls back to next
        provider on connection error or 5xx. Rate limits (429) are retried within
        the current provider before cascading.

        Raises RateLimitError if all providers are exhausted or a long wait is required.
        """
        cascade_exc = None

        for pi, prov in enumerate(self._providers):
            prov_label = f"{prov.model}@{prov.base_url.split('//')[1][:30] if '//' in prov.base_url else prov.base_url[:30]}"
            last_exc = None
            
            print(f"  [Attempt] Trying provider {pi+1}/{len(self._providers)}: {prov_label}", flush=True)

            for attempt in range(max_retries):
                try:
                    self._pace(prov.min_interval)
                    if prov.provider == "anthropic":
                        result = self._anthropic(messages, system, json_mode, prov)
                    else:
                        result = self._openai(messages, system, json_mode, prov)
                    
                    # Success — expose selected provider's info
                    self.model = prov.model
                    self.provider = prov.provider
                    return result

                except requests.exceptions.HTTPError as exc:
                    status = exc.response.status_code if exc.response is not None else 0
                    last_exc = exc

                    # 1. IMMEDIATE CASCADE for auth errors or forbidden
                    if status in (401, 403):
                        if pi < len(self._providers) - 1:
                            logger.warning("Auth error %d on %s, cascading…", status, prov_label)
                            print(f"[Cascade] Provider {prov_label} unauthorized ({status}), trying next...", flush=True)
                            break # Go to next provider
                        raise # Last provider, just fail

                    # 2. RETRY THEN CASCADE for 429 (Rate Limit)
                    if status == 429:
                        retry_after = self._parse_retry_after(exc.response)
                        if retry_after > 120: # 2 minute limit for retry
                            if pi < len(self._providers) - 1:
                                logger.warning("Provider %s rate-limited (long wait), cascading…", prov_label)
                                break
                            raise RateLimitError(f"Rate limit exceeded on all providers. Retry after {retry_after}s.", retry_after)
                        
                        if attempt < max_retries - 1:
                            wait = retry_after if retry_after > 0 else (2 ** attempt) * 5
                            logger.warning("HTTP 429 on %s, retrying in %ds…", prov_label, wait)
                            print(f"[Retry] Provider {prov_label} rate-limited. Retrying in {wait}s...", flush=True)
                            time.sleep(wait)
                            continue
                        
                        if pi < len(self._providers) - 1:
                            logger.warning("Provider %s rate-limit retries exhausted, cascading…", prov_label)
                            print(f"[Cascade] Provider {prov_label} exhausted retries. Cascading to next...", flush=True)
                            break
                        raise

                    # 3. RETRY THEN CASCADE for 5xx (Server Errors)
                    if status in (500, 502, 503, 529):
                        if attempt < max_retries - 1:
                            wait = (2 ** attempt) * 3
                            print(f"[Retry] Provider {prov_label} server error ({status}). Retrying in {wait}s...", flush=True)
                            time.sleep(wait)
                            continue
                        if pi < len(self._providers) - 1:
                            logger.warning("Provider %s server errors exhausted, cascading…", prov_label)
                            print(f"[Cascade] Provider {prov_label} server errors. Cascading to next...", flush=True)
                            break
                        raise

                    # 4. IMMEDIATE CASCADE for 4xx (Bad Request, Payload Too Large)
                    if status in (400, 413):
                        if pi < len(self._providers) - 1:
                            logger.warning("Provider %s rejected request (%d), cascading…", prov_label, status)
                            print(f"[Cascade] Provider {prov_label} rejected request ({status}). Cascading to next...", flush=True)
                            break
                        raise

                    # 5. FATAL
                    raise

                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                    last_exc = exc
                    if pi < len(self._providers) - 1:
                        logger.warning("Provider %s unreachable, cascading…", prov_label)
                        break
                    
                    if attempt < max_retries - 1:
                        wait = (2 ** attempt) * 3
                        time.sleep(wait)
                        continue
                    raise
            
            # If we reached here normally (no return in the attempt loop), it means
            # we either broke (cascading) or finished retries (cascading).
            # The for pi loop will continue to the next provider.
            cascade_exc = last_exc

        # All providers exhausted
        if cascade_exc:
            raise cascade_exc
        raise RuntimeError("No LLM providers configured")

    def _parse_retry_after(self, response) -> float:
        """Extract retry-after value from headers or body (Groq/Gemini specific)."""
        # 1. Try standard header
        header = response.headers.get("Retry-After")
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        
        # 2. Try parsing error body for timing hints
        try:
            body = response.json()
            # Handle list-wrapped responses (some Gemini endpoints)
            if isinstance(body, list) and len(body) > 0:
                body = body[0]
            
            message = body.get("error", {}).get("message", "") if isinstance(body, dict) else ""
            if "retry in" in message.lower() or "try again in" in message.lower():
                # Simple extraction for "XmYs.Z" or "Xs"
                import re
                m = re.search(r"(?:retry in|try again in) (?:(\d+)m)?(?:([\d.]+)s)?", message, re.I)
                if m:
                    minutes = float(m.group(1) or 0)
                    seconds = float(m.group(2) or 0)
                    return minutes * 60 + seconds
        except Exception:
            pass
            
        return 0.0

    def _openai(self, messages, system, json_mode, prov: _ProviderConfig) -> str:
        headers = {
            "Authorization": f"Bearer {prov.api_key}",
            "Content-Type": "application/json",
        }
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)

        payload = {
            "model": prov.model,
            "messages": msgs,
            "max_tokens": prov.max_tokens,
            "temperature": prov.temperature,
        }
        if json_mode and prov.json_mode_supported:
            payload["response_format"] = {"type": "json_object"}

        logger.debug("POST %s/chat/completions  model=%s  msgs=%d",
                      prov.base_url, prov.model, len(msgs))
        session = requests.Session()
        session.trust_env = prov.trust_env
        resp = session.post(
            f"{prov.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=180,
        )
        if not resp.ok:
            logger.error("HTTP %d from %s: %s", resp.status_code, prov.model, resp.text[:800])
            print(f"[API error {resp.status_code}] {resp.text[:800]}", flush=True)
        resp.raise_for_status()
        self._last_call = time.time()
        return resp.json()["choices"][0]["message"]["content"]

    def _anthropic(self, messages, system, json_mode, prov: _ProviderConfig) -> str:
        headers = {
            "x-api-key": prov.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": prov.model,
            "max_tokens": prov.max_tokens,
            "temperature": prov.temperature,
            "messages": messages,
        }
        if system:
            payload["system"] = system

        logger.debug("POST anthropic  model=%s  msgs=%d", prov.model, len(messages))
        session = requests.Session()
        session.trust_env = prov.trust_env
        resp = session.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        self._last_call = time.time()
        return resp.json()["content"][0]["text"]
