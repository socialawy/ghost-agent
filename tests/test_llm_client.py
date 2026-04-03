"""Tests for LLM client with provider cascade (llm_client.py)."""

import json
from unittest.mock import patch, MagicMock

import pytest
import requests

from llm_client import LLMClient, RateLimitError, _ProviderConfig


class TestProviderConfig:
    def test_defaults(self):
        pc = _ProviderConfig({})
        assert pc.provider == "openai"
        assert pc.model == "gpt-4o-mini"
        assert pc.max_tokens == 4096
        assert pc.temperature == 0.3
        assert pc.json_mode_supported is True

    def test_custom_values(self):
        pc = _ProviderConfig({
            "provider": "anthropic",
            "model": "claude-3",
            "api_key": "sk-test",
            "base_url": "https://api.anthropic.com/v1",
            "max_tokens": 8192,
            "temperature": 0.1,
            "min_interval": 5.0,
            "json_mode_supported": False,
        })
        assert pc.provider == "anthropic"
        assert pc.model == "claude-3"
        assert pc.api_key == "sk-test"
        assert pc.max_tokens == 8192
        assert pc.min_interval == 5.0
        assert pc.json_mode_supported is False

    def test_strips_trailing_slash(self):
        pc = _ProviderConfig({"base_url": "https://api.example.com/v1/"})
        assert pc.base_url == "https://api.example.com/v1"


class TestLLMClientInit:
    def test_single_provider(self, mock_config):
        client = LLMClient(mock_config)
        assert len(client._providers) == 1
        assert client.model == "test-model"
        assert client.api_key == "test-key-123"

    def test_cascade_providers(self, cascade_config):
        client = LLMClient(cascade_config)
        assert len(client._providers) == 2
        # Exposes primary provider's settings
        assert client.model == "model-1"
        assert client.api_key == "key-1"


class TestParseRetryAfter:
    def setup_method(self):
        self.client = LLMClient({
            "provider": "openai",
            "api_key": "test",
            "base_url": "https://test.com/v1",
            "model": "test",
            "min_interval": 0,
        })

    def test_standard_header(self):
        resp = MagicMock()
        resp.headers = {"Retry-After": "30"}
        resp.json.side_effect = Exception("no body")
        assert self.client._parse_retry_after(resp) == 30.0

    def test_no_header_no_body(self):
        resp = MagicMock()
        resp.headers = {}
        resp.json.side_effect = Exception("no body")
        assert self.client._parse_retry_after(resp) == 0.0

    def test_gemini_list_wrapped_body(self):
        resp = MagicMock()
        resp.headers = {}
        resp.json.return_value = [
            {"error": {"message": "Rate limit exceeded. Try again in 45s."}}
        ]
        assert self.client._parse_retry_after(resp) == 45.0

    def test_groq_body_with_minutes(self):
        resp = MagicMock()
        resp.headers = {}
        resp.json.return_value = {
            "error": {"message": "Rate limited. Please retry in 2m30s."}
        }
        assert self.client._parse_retry_after(resp) == 150.0

    def test_dict_body_retry_in(self):
        resp = MagicMock()
        resp.headers = {}
        resp.json.return_value = {
            "error": {"message": "Please try again in 10s"}
        }
        assert self.client._parse_retry_after(resp) == 10.0


class TestCascadeBehavior:
    """Test provider cascade using mocked requests.post."""

    def _make_ok_response(self, content="test response"):
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [{"message": {"content": content}}]
        }
        resp.raise_for_status = MagicMock()
        return resp

    def _make_error_response(self, status_code, body="error"):
        resp = MagicMock()
        resp.ok = False
        resp.status_code = status_code
        resp.text = body
        resp.headers = {}
        resp.json.return_value = {"error": {"message": body}}

        exc = requests.exceptions.HTTPError(response=resp)
        resp.raise_for_status = MagicMock(side_effect=exc)
        return resp

    @patch("llm_client.time.sleep")
    @patch("llm_client.requests.post")
    def test_single_provider_success(self, mock_post, mock_sleep, mock_config):
        mock_post.return_value = self._make_ok_response("hello")
        client = LLMClient(mock_config)

        result = client.chat(messages=[{"role": "user", "content": "hi"}])
        assert result == "hello"
        assert mock_post.call_count == 1

    @patch("llm_client.time.sleep")
    @patch("llm_client.requests.post")
    def test_cascade_on_auth_error(self, mock_post, mock_sleep, cascade_config):
        mock_post.side_effect = [
            self._make_error_response(401, "Unauthorized"),
            self._make_ok_response("from provider 2"),
        ]
        client = LLMClient(cascade_config)

        result = client.chat(messages=[{"role": "user", "content": "hi"}])
        assert result == "from provider 2"
        assert mock_post.call_count == 2

    @patch("llm_client.time.sleep")
    @patch("llm_client.requests.post")
    def test_cascade_on_429_retries_exhausted(self, mock_post, mock_sleep, cascade_config):
        # Provider 1: 4 consecutive 429s (max_retries=4), then cascade
        error_resps = [self._make_error_response(429, "rate limited")] * 4
        ok_resp = self._make_ok_response("fallback success")

        mock_post.side_effect = error_resps + [ok_resp]
        client = LLMClient(cascade_config)

        result = client.chat(messages=[{"role": "user", "content": "hi"}])
        assert result == "fallback success"
        # 4 retries on provider 1 + 1 success on provider 2
        assert mock_post.call_count == 5

    @patch("llm_client.time.sleep")
    @patch("llm_client.requests.post")
    def test_cascade_on_server_error(self, mock_post, mock_sleep, cascade_config):
        mock_post.side_effect = [
            self._make_error_response(500, "Internal Server Error"),
            self._make_error_response(500, "Internal Server Error"),
            self._make_error_response(500, "Internal Server Error"),
            self._make_error_response(500, "Internal Server Error"),
            self._make_ok_response("recovered"),
        ]
        client = LLMClient(cascade_config)

        result = client.chat(messages=[{"role": "user", "content": "hi"}])
        assert result == "recovered"

    @patch("llm_client.time.sleep")
    @patch("llm_client.requests.post")
    def test_all_providers_exhausted_raises(self, mock_post, mock_sleep, cascade_config):
        # Both providers return 500 for all retries
        mock_post.side_effect = [
            self._make_error_response(500, "error")
        ] * 8  # 4 retries * 2 providers

        client = LLMClient(cascade_config)

        with pytest.raises(requests.exceptions.HTTPError):
            client.chat(messages=[{"role": "user", "content": "hi"}])

    @patch("llm_client.time.sleep")
    @patch("llm_client.requests.post")
    def test_400_does_not_cascade(self, mock_post, mock_sleep, cascade_config):
        """400 Bad Request is fatal — should not cascade."""
        mock_post.return_value = self._make_error_response(400, "Bad Request")
        client = LLMClient(cascade_config)

        with pytest.raises(requests.exceptions.HTTPError):
            client.chat(messages=[{"role": "user", "content": "hi"}])
        # Only tried once — no cascade for 400
        assert mock_post.call_count == 1

    @patch("llm_client.time.sleep")
    @patch("llm_client.requests.post")
    def test_long_retry_after_cascades_immediately(self, mock_post, mock_sleep, cascade_config):
        """If Retry-After > 120s, cascade immediately without retrying."""
        resp_429 = self._make_error_response(429, "rate limited")
        resp_429.return_value = None
        # Override the headers on the response object inside the exception
        error_resp_mock = resp_429.raise_for_status.side_effect.response
        error_resp_mock.headers = {"Retry-After": "300"}
        error_resp_mock.json.return_value = {"error": {"message": "rate limited"}}

        mock_post.side_effect = [
            resp_429,
            self._make_ok_response("quick fallback"),
        ]
        client = LLMClient(cascade_config)

        result = client.chat(messages=[{"role": "user", "content": "hi"}])
        assert result == "quick fallback"
        # Only 1 attempt on provider 1 (immediate cascade), then 1 on provider 2
        assert mock_post.call_count == 2
