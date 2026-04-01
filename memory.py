"""3-layer persistent memory system.

Layer 1 — MEMORY.md        Lightweight index, always loaded into LLM context.
Layer 2 — topics/*.md      Deep per-topic knowledge files.
Layer 3 — transcript.jsonl  Append-only interaction log (hidden from main context
                            unless explicitly recalled).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ghost.memory")


# ── Layer 3: Append-only transcript ──────────────────────

class Transcript:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, role: str, content: str, session: str = "default", **meta):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "content": content,
            "session": session,
            **meta,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_since(self, cursor: int = 0) -> tuple[list[dict], int]:
        """Read entries from byte-offset *cursor*.  Returns (entries, new_cursor)."""
        entries = []
        with open(self.path, "r", encoding="utf-8") as f:
            f.seek(cursor)
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning("Skipping corrupt transcript line at offset ~%d", cursor)
            new_cursor = f.tell()
        return entries, new_cursor

    def read_all(self) -> list[dict]:
        entries, _ = self.read_since(0)
        return entries

    def entry_count(self) -> int:
        if not self.path.exists():
            return 0
        with open(self.path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())

    def byte_size(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0


# ── Layer 2: Topic knowledge store ───────────────────────

class TopicStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def list_topics(self) -> list[str]:
        return sorted(f.stem for f in self.directory.glob("*.md"))

    def read(self, topic: str) -> Optional[str]:
        path = self.directory / f"{topic}.md"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def write(self, topic: str, content: str):
        path = self.directory / f"{topic}.md"
        path.write_text(content, encoding="utf-8")
        logger.info("Wrote topic: %s (%d chars)", topic, len(content))

    def read_all(self) -> dict[str, str]:
        return {t: self.read(t) for t in self.list_topics()}


# ── Layer 1: Memory index ────────────────────────────────

class MemoryIndex:
    def __init__(self, path: Path):
        self.path = path
        if not self.path.exists():
            self._init()

    def _init(self):
        self.write(
            "# Ghost Agent Memory Index\n"
            f"Last updated: {datetime.now(timezone.utc).isoformat()}\n"
            "Dream cycle: 0\n\n"
            "## Active Context\n"
            "- Status: freshly initialized\n\n"
            "## Topic Files\n"
            "(none yet)\n\n"
            "## Pending Observations\n"
            "(none yet)\n"
        )

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def write(self, content: str):
        self.path.write_text(content, encoding="utf-8")


# ── Unified Memory facade ────────────────────────────────

class Memory:
    """Combined 3-layer memory with cursor tracking."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.index = MemoryIndex(base_dir / "MEMORY.md")
        self.topics = TopicStore(base_dir / "topics")
        self.transcript = Transcript(base_dir / "transcript.jsonl")
        self._cursor_path = base_dir / ".dream_cursor"

    # dream cursor ─────────────────────────────────────────

    def get_dream_cursor(self) -> int:
        if self._cursor_path.exists():
            try:
                return int(self._cursor_path.read_text().strip())
            except ValueError:
                return 0
        return 0

    def set_dream_cursor(self, cursor: int):
        self._cursor_path.write_text(str(cursor))

    # context builder ──────────────────────────────────────

    def build_context(self, include_recent: int = 15) -> str:
        """Assemble a context string from all three layers for injection into
        the LLM system prompt."""
        parts = ["=== MEMORY INDEX ===", self.index.read()]

        topics = self.topics.read_all()
        if topics:
            parts.append("\n=== TOPIC KNOWLEDGE ===")
            for name, content in topics.items():
                parts.append(f"\n--- {name} ---")
                parts.append(content)

        # Only the tail of the transcript — the rest is for dreaming
        entries = self.transcript.read_all()
        recent = entries[-include_recent:]
        if recent:
            parts.append("\n=== RECENT INTERACTIONS (last %d) ===" % len(recent))
            for e in recent:
                role = e.get("role", "?")
                text = e.get("content", "")
                if len(text) > 600:
                    text = text[:600] + "…"
                parts.append(f"[{role}] {text}")

        return "\n".join(parts)

    # status ───────────────────────────────────────────────

    def status(self) -> dict:
        cursor = self.get_dream_cursor()
        undreamed, _ = self.transcript.read_since(cursor)
        return {
            "topics": self.topics.list_topics(),
            "topic_count": len(self.topics.list_topics()),
            "transcript_entries": self.transcript.entry_count(),
            "transcript_bytes": self.transcript.byte_size(),
            "dream_cursor": cursor,
            "undreamed_entries": len(undreamed),
        }