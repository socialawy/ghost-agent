"""Ghost Bridge — local HTTP API for the shared memory filesystem.

Exposes Ghost's memory, dream engine, and chat as a REST-like API
on localhost. Any tool that can curl can feed Ghost.

Usage:
    python bridge.py                    # standalone, default port 7701
    python bridge.py --port 8080        # custom port
    # Or via ghost CLI:
    python ghost.py bridge
"""

import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

from llm_client import LLMClient
from memory import Memory
from dream import DreamEngine

logger = logging.getLogger("ghost.bridge")

VERSION = "1.4.0"


class GhostBridge:
    """Manages shared state for the HTTP handler."""

    def __init__(self, config: dict):
        self.config = config
        self.mem = Memory(Path(config.get("state_dir", ".ghost")))
        self.llm = LLMClient(config["llm"])

        dream_llm = None
        if "dream_llm" in config:
            dream_llm = LLMClient(config["dream_llm"])

        workspace = Path(config["workspace_root"]) if config.get("workspace_root") else None
        self.dream_engine = DreamEngine(self.mem, self.llm, workspace, dream_llm=dream_llm)
        self._dream_lock = threading.Lock()

    def inject(self, content: str, source: str = "bridge", confidence: str = "verified") -> dict:
        self.mem.transcript.append(
            role="user",
            content=content,
            event="inject",
            source=source,
            confidence=confidence,
        )
        return {"status": "ok", "chars": len(content), "source": source}

    def chat(self, message: str) -> dict:
        from datetime import datetime, timezone

        memory_context = self.mem.build_context()
        system_prompt = (
            "You are Ghost, a persistent AI assistant with long-term memory.\n\n"
            f"{memory_context}\n\nCurrent time: {datetime.now(timezone.utc).isoformat()}"
        )

        self.mem.transcript.append(role="user", content=message, session="bridge")
        response = self.llm.chat(
            messages=[{"role": "user", "content": message}],
            system=system_prompt,
        )
        self.mem.transcript.append(role="assistant", content=response, session="bridge", confidence="unverified")
        return {"reply": response, "model": self.llm.model}

    def dream(self) -> dict:
        with self._dream_lock:
            return self.dream_engine.dream()

    def status(self) -> dict:
        s = self.mem.status()
        s["version"] = VERSION
        return s

    def recall(self, topic: str) -> Optional[str]:
        return self.mem.topics.read(topic)

    def memory_index(self) -> str:
        return self.mem.index.read()

    def topics_list(self) -> list[str]:
        return self.mem.topics.list_topics()


def _make_handler(bridge: GhostBridge):
    """Create a request handler class with access to the bridge instance."""

    class Handler(BaseHTTPRequestHandler):

        def log_message(self, format, *args):
            logger.info(format, *args)

        def _send_json(self, data: dict, status: int = 200):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, text: str, status: int = 200):
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def do_GET(self):
            path = self.path.rstrip("/")

            if path == "/health":
                self._send_json({"status": "ok", "version": VERSION})

            elif path == "/status":
                self._send_json(bridge.status())

            elif path == "/memory":
                self._send_text(bridge.memory_index())

            elif path == "/topics":
                self._send_json({"topics": bridge.topics_list()})

            elif path.startswith("/recall/"):
                topic = path[len("/recall/"):]
                content = bridge.recall(topic)
                if content is not None:
                    self._send_text(content)
                else:
                    self._send_json({"error": f"Topic not found: {topic}"}, 404)

            else:
                self._send_json({"error": "Not found", "endpoints": [
                    "GET /health", "GET /status", "GET /memory",
                    "GET /topics", "GET /recall/{topic}",
                    "POST /inject", "POST /chat", "POST /dream",
                ]}, 404)

        def do_POST(self):
            path = self.path.rstrip("/")

            try:
                body = self._read_body()
            except (json.JSONDecodeError, ValueError) as exc:
                self._send_json({"error": f"Invalid JSON: {exc}"}, 400)
                return

            if path == "/inject":
                content = body.get("content", "")
                if not content:
                    self._send_json({"error": "Missing 'content' field"}, 400)
                    return
                result = bridge.inject(
                    content=content,
                    source=body.get("source", "bridge"),
                    confidence=body.get("confidence", "verified"),
                )
                self._send_json(result)

            elif path == "/chat":
                message = body.get("message", "")
                if not message:
                    self._send_json({"error": "Missing 'message' field"}, 400)
                    return
                try:
                    result = bridge.chat(message)
                    self._send_json(result)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, 500)

            elif path == "/dream":
                try:
                    result = bridge.dream()
                    self._send_json(result)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, 500)

            else:
                self._send_json({"error": "Not found"}, 404)

    return Handler


def start_bridge(config: dict, port: int = 7701, blocking: bool = True) -> Optional[HTTPServer]:
    """Start the Ghost Bridge HTTP server.

    If blocking=True, runs until interrupted.
    If blocking=False, runs in a daemon thread and returns the server.
    """
    bridge = GhostBridge(config)
    handler_class = _make_handler(bridge)
    server = HTTPServer(("127.0.0.1", port), handler_class)

    if blocking:
        logger.info("Ghost Bridge listening on http://127.0.0.1:%d", port)
        print(f"Ghost Bridge listening on http://127.0.0.1:{port}")
        print("Endpoints: /health /status /memory /topics /recall/{{topic}} /inject /chat /dream")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nBridge stopped.")
        finally:
            server.server_close()
        return None
    else:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info("Ghost Bridge started in background on http://127.0.0.1:%d", port)
        return server


if __name__ == "__main__":
    import argparse
    import yaml
    from ghost import load_config

    parser = argparse.ArgumentParser(description="Ghost Bridge HTTP server")
    parser.add_argument("-c", "--config", default="config.yaml")
    parser.add_argument("-p", "--port", type=int, default=7701)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    config = load_config(args.config)
    start_bridge(config, port=args.port, blocking=True)
