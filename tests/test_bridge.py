"""Tests for the Ghost Bridge HTTP server (bridge.py)."""

import json
import threading
import time
import urllib.request
import urllib.error

import pytest

from bridge import GhostBridge, start_bridge


@pytest.fixture
def bridge_config(tmp_path):
    """Config for a test bridge with temp state dir."""
    return {
        "state_dir": str(tmp_path / ".ghost"),
        "llm": {
            "provider": "openai",
            "api_key": "test",
            "base_url": "https://test.example.com/v1",
            "model": "test-model",
            "min_interval": 0,
        },
    }


@pytest.fixture
def bridge(bridge_config):
    return GhostBridge(bridge_config)


class TestGhostBridge:
    def test_inject(self, bridge):
        result = bridge.inject("test observation", source="unit-test")
        assert result["status"] == "ok"
        assert result["chars"] == 16

        entries = bridge.mem.transcript.read_all()
        assert len(entries) == 1
        assert entries[0]["content"] == "test observation"
        assert entries[0]["source"] == "unit-test"

    def test_status(self, bridge):
        s = bridge.status()
        assert "topic_count" in s
        assert "version" in s

    def test_memory_index(self, bridge):
        content = bridge.memory_index()
        assert "Ghost Agent Memory Index" in content

    def test_topics_list_empty(self, bridge):
        assert bridge.topics_list() == []

    def test_recall_nonexistent(self, bridge):
        assert bridge.recall("missing") is None

    def test_recall_existing(self, bridge):
        bridge.mem.topics.write("test-topic", "# Test\nContent")
        content = bridge.recall("test-topic")
        assert content == "# Test\nContent"


class TestBridgeHTTP:
    """Integration tests that start a real HTTP server."""

    @pytest.fixture(autouse=True)
    def setup_server(self, bridge_config):
        """Start bridge on a random port for each test."""
        # Use port 0 to let the OS pick a free port
        from bridge import GhostBridge, _make_handler
        from http.server import HTTPServer

        bridge = GhostBridge(bridge_config)
        handler = _make_handler(bridge)
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.bridge = bridge

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        yield
        self.server.shutdown()

    def _get(self, path):
        req = urllib.request.Request(f"{self.base}{path}")
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")

    def _post(self, path, data):
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_health(self):
        status, body = self._get("/health")
        data = json.loads(body)
        assert status == 200
        assert data["status"] == "ok"

    def test_status(self):
        status, body = self._get("/status")
        data = json.loads(body)
        assert status == 200
        assert "topic_count" in data

    def test_memory(self):
        status, body = self._get("/memory")
        assert status == 200
        assert "Ghost Agent Memory Index" in body

    def test_topics_empty(self):
        status, body = self._get("/topics")
        data = json.loads(body)
        assert data["topics"] == []

    def test_recall_404(self):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            self._get("/recall/nonexistent")
        assert exc_info.value.code == 404

    def test_recall_success(self):
        self.bridge.mem.topics.write("my-topic", "topic content")
        status, body = self._get("/recall/my-topic")
        assert status == 200
        assert body == "topic content"

    def test_inject(self):
        status, data = self._post("/inject", {
            "content": "test from HTTP",
            "source": "curl",
        })
        assert status == 200
        assert data["status"] == "ok"

        entries = self.bridge.mem.transcript.read_all()
        assert any(e["content"] == "test from HTTP" for e in entries)

    def test_inject_missing_content(self):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            self._post("/inject", {"source": "test"})
        assert exc_info.value.code == 400

    def test_not_found(self):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            self._get("/nonexistent")
        assert exc_info.value.code == 404
